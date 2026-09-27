"""Claves, tokens y dobles de prueba de la autenticación (Fase 11).

Todo token de la suite se **genera aquí**, con un par EC P-256 creado en la
propia sesión de pytest: nunca se copia uno de una sesión real de Supabase
(`CLAUDE.md`, regla 15). La URL de Supabase es un puerto cerrado de loopback:
ningún test sale a la red.
"""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

#: `https` para que también sea válida en production; puerto 1, cerrado.
URL_SUPABASE_FICTICIA = "https://127.0.0.1:1"
EMISOR_FICTICIO = f"{URL_SUPABASE_FICTICIA}/auth/v1"
AUDIENCIA = "authenticated"
KID = "clave-de-prueba"
CLAVE_SECRETA_FICTICIA = "clave-secreta-ficticia-de-prueba"

MEDICO_ID = UUID("10000000-0000-4000-8000-000000000001")
ADMIN_ID = UUID("10000000-0000-4000-8000-000000000002")
MEDICO_INACTIVO_ID = UUID("10000000-0000-4000-8000-000000000003")
ADMIN_INACTIVO_ID = UUID("10000000-0000-4000-8000-000000000004")
SIN_PERFIL_ID = UUID("10000000-0000-4000-8000-000000000005")

MEDICO = "medico"
ADMINISTRADOR = "administrador"
ROLES = (MEDICO, ADMINISTRADOR)

#: Marca un claim que el token no debe llevar.
AUSENTE = object()


def nueva_clave() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


class Emisor:
    """Emite tokens como Supabase Auth (ES256, con `kid`), con los claims que el test elija."""

    def __init__(self, clave: ec.EllipticCurvePrivateKey | None = None, kid: str = KID) -> None:
        self.clave = clave or nueva_clave()
        self.kid = kid

    def claims(self, sujeto, **cambios) -> dict:
        ahora = int(time.time())
        claims = {
            "sub": str(sujeto),
            "iss": EMISOR_FICTICIO,
            "aud": AUDIENCIA,
            "iat": ahora,
            "exp": ahora + 3600,
            "role": "authenticated",
            "is_anonymous": False,
        }
        claims.update(cambios)
        return {k: v for k, v in claims.items() if v is not AUSENTE}

    def token(self, sujeto, *, kid: str | None | object = AUSENTE, **cambios) -> str:
        """`cambios` reemplaza claims; `AUSENTE` los quita (también `sub=AUSENTE`)."""
        cabeceras = {} if kid is None else {"kid": self.kid if kid is AUSENTE else kid}
        return jwt.encode(self.claims(sujeto, **cambios), self.clave, algorithm="ES256", headers=cabeceras)

    def clave_publica(self):
        return self.clave.public_key()

    def jwk(self) -> dict:
        datos = jwt.algorithms.ECAlgorithm.to_jwk(self.clave_publica(), as_dict=True)
        return {**datos, "kid": self.kid, "alg": "ES256", "use": "sig"}

    def pem_publico(self) -> bytes:
        return self.clave_publica().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def token_sin_firma_valida(cabecera: dict, claims: dict, secreto: bytes | None = None) -> str:
    """Token con `alg` arbitrario: HS256 firmado con `secreto`, o `none` sin firma.

    PyJWT se niega a firmar HS256 con una clave pública (ataque de confusión de
    algoritmo), así que se construye a mano.
    """
    base = f"{_b64(json.dumps(cabecera).encode())}.{_b64(json.dumps(claims).encode())}"
    if secreto is None:
        return f"{base}."
    firma = hmac.new(secreto, base.encode(), hashlib.sha256).digest()
    return f"{base}.{_b64(firma)}"


class FuenteDeClavesEnMemoria:
    """Doble de `JwksKeySource`: las claves públicas de los emisores dados, por `kid`."""

    def __init__(self, *emisores: Emisor) -> None:
        self._claves = {e.kid: e.clave_publica() for e in emisores}

    def signing_key(self, kid: str):
        return self._claves.get(kid)


@dataclass
class EstadoDePrueba:
    role: str
    is_active: bool


class DirectorioEnMemoria:
    """Doble de `DatabaseUserDirectory` para la suite de la API, que no tiene base.

    Es mutable a propósito: un test puede desactivar a un usuario entre dos
    peticiones y comprobar que la segunda ya se rechaza.
    """

    def __init__(self) -> None:
        self.usuarios: dict[UUID, EstadoDePrueba] = {
            MEDICO_ID: EstadoDePrueba(MEDICO, True),
            ADMIN_ID: EstadoDePrueba(ADMINISTRADOR, True),
            MEDICO_INACTIVO_ID: EstadoDePrueba(MEDICO, False),
            ADMIN_INACTIVO_ID: EstadoDePrueba(ADMINISTRADOR, False),
        }
        self.consultas: list[UUID] = []

    def status(self, user_id: UUID):
        from app.auth.directory import UserStatus

        self.consultas.append(user_id)
        estado = self.usuarios.get(user_id)
        return None if estado is None else UserStatus(role=estado.role, is_active=estado.is_active)


def cabecera(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


#: Usuario de cada rol en el directorio de prueba.
USUARIO_DE = {MEDICO: MEDICO_ID, ADMINISTRADOR: ADMIN_ID}
