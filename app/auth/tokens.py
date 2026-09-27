"""Verificación del JWT de Supabase Auth (decisiones aprobadas 1 y 2).

Se exige, en cada petición:

- **firma ES256** con una clave del JWKS del proyecto (solo ese algoritmo: ni
  `HS256`, que permitiría firmar con la clave pública, ni `none`);
- `exp`, `iat`, `sub`, `iss` y `aud` presentes; `exp` no vencido e `iat` no
  futuro, con `TOLERANCIA_RELOJ_S` de margen;
- `iss` = `{GYNFEM_SUPABASE_URL}/auth/v1` (tokens de otro proyecto fuera);
- `aud` = `authenticated` (el `anon` o `service_role` de Supabase fuera);
- `sub` con formato UUID y `is_anonymous` distinto de `true`.

El rol **no** sale del token (ni de `role`, ni de `app_metadata`, ni de
`user_metadata`): lo resuelve `app/auth/directory.py` contra la base.
"""

import math
import threading
import time
from typing import Any, Protocol
from uuid import UUID

import jwt

from app.auth.errors import AuthUnavailable, InvalidToken, TokenExpired

AUDIENCIA = "authenticated"
ALGORITMOS = ("ES256",)
CLAIMS_OBLIGATORIOS = ("exp", "iat", "sub", "iss", "aud")
#: Margen para relojes desincronizados entre Supabase y el servidor. Decisión
#: de ingeniería: sin margen, un token recién emitido podría rechazarse por un
#: `iat` unos segundos «en el futuro».
TOLERANCIA_RELOJ_S = 30
#: Tiempo que se reutiliza el JWKS descargado.
CACHE_JWKS_S = 300
#: Un `kid` desconocido obliga a recargar el JWKS (rotación de claves), pero como
#: mucho una vez en este intervalo: un token con `kid` inventado no convierte
#: cada petición en una descarga.
RECARGA_MINIMA_S = 60
RUTA_JWKS = "/auth/v1/.well-known/jwks.json"


def issuer_de(supabase_url: str) -> str:
    return f"{supabase_url}/auth/v1"


def jwks_url_de(supabase_url: str) -> str:
    return f"{supabase_url}{RUTA_JWKS}"


class KeySource(Protocol):
    def signing_key(self, kid: str) -> Any | None:
        """La clave pública de ese `kid`, o `None` si no existe. `AuthUnavailable` si no se puede saber."""


class JwksKeySource:
    """Claves públicas del JWKS de Supabase, con caché y recarga acotada."""

    def __init__(self, supabase_url: str, timeout_s: float) -> None:
        self._cliente = jwt.PyJWKClient(
            jwks_url_de(supabase_url), cache_jwk_set=True, lifespan=CACHE_JWKS_S, timeout=timeout_s
        )
        self._ultima_recarga = -math.inf
        self._cerrojo = threading.Lock()

    def signing_key(self, kid: str) -> Any | None:
        clave = self._buscar(kid, recargar=False)
        if clave is None:
            with self._cerrojo:
                if time.monotonic() - self._ultima_recarga < RECARGA_MINIMA_S:
                    return None
                self._ultima_recarga = time.monotonic()
            clave = self._buscar(kid, recargar=True)
        return clave

    def _buscar(self, kid: str, *, recargar: bool) -> Any | None:
        try:
            claves = self._cliente.get_signing_keys(refresh=recargar)
        except (jwt.PyJWTError, ValueError):
            # Sin conexión, una respuesta que no es JSON (ValueError), o un JWKS sin
            # claves de firma utilizables (PyJWKClientError, PyJWKSetError): nadie
            # puede autenticarse, y es una dependencia caída, no un token inválido.
            raise AuthUnavailable() from None
        encontrada = self._cliente.match_kid(claves, kid)
        return None if encontrada is None else encontrada.key


class TokenVerifier:
    def __init__(self, keys: KeySource, issuer: str) -> None:
        self._claves = keys
        self._emisor = issuer

    def verify(self, token: str) -> UUID:
        """El `sub` del token verificado. `InvalidToken`, `TokenExpired` o `AuthUnavailable` si no."""
        try:
            cabecera = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise InvalidToken() from None
        kid = cabecera.get("kid")
        if cabecera.get("alg") not in ALGORITMOS or not isinstance(kid, str):
            raise InvalidToken()
        clave = self._claves.signing_key(kid)
        if clave is None:
            raise InvalidToken()
        try:
            claims = jwt.decode(
                token,
                clave,
                algorithms=list(ALGORITMOS),
                audience=AUDIENCIA,
                issuer=self._emisor,
                leeway=TOLERANCIA_RELOJ_S,
                options={"require": list(CLAIMS_OBLIGATORIOS)},
            )
        except jwt.ExpiredSignatureError:
            raise TokenExpired() from None
        except jwt.PyJWTError:
            raise InvalidToken() from None
        if claims.get("is_anonymous") is True:
            raise InvalidToken()
        try:
            return UUID(claims["sub"])
        except (ValueError, TypeError, AttributeError):
            raise InvalidToken() from None
