"""Admin API de Supabase Auth: crear y borrar usuarios (HU002, decisión aprobada 10).

Solo el backend la llama, con la clave de servicio (`GYNFEM_SUPABASE_SECRET_KEY`),
que omite toda la seguridad del proyecto. La clave viaja **solo** en las
cabeceras `apikey` y `Authorization`, como hace el cliente oficial; nunca en una
URL, un log, un error ni una respuesta. Del cuerpo de un error de Supabase solo
se lee su código estable (`email_exists`, `weak_password`), nunca el mensaje.
"""

import http.client
import json
import logging
import urllib.error
import urllib.request
from typing import Protocol
from uuid import UUID

from pydantic import SecretStr

from app.auth.errors import AuthUnavailable
from app.core.logging import LOGGER_RAIZ
from app.services.errors import UserAlreadyExists, UserRejected, WeakPassword

RUTA_USUARIOS = "/auth/v1/admin/users"

logger = logging.getLogger(f"{LOGGER_RAIZ}.auth")
#: Estados con los que Supabase rechaza los datos enviados (no la credencial).
ESTADOS_DE_DATOS_INVALIDOS = frozenset({400, 422})


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    """urllib copiaría `apikey` y `Authorization` al destino de una redirección."""

    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_SinRedirecciones)


class AuthAdmin(Protocol):
    def create_user(self, email: str, password: str) -> UUID: ...

    def delete_user(self, user_id: UUID) -> None: ...


class SupabaseAdminClient:
    def __init__(self, supabase_url: str, secret_key: str | SecretStr, timeout_s: float) -> None:
        self._url = supabase_url
        self._clave = secret_key if isinstance(secret_key, SecretStr) else SecretStr(secret_key)
        self._timeout_s = timeout_s

    def __repr__(self) -> str:
        return "SupabaseAdminClient()"

    def create_user(self, email: str, password: str) -> UUID:
        """El id del usuario creado, ya confirmado (el registro público está cerrado)."""
        estado, datos = self._llamar(
            "POST", RUTA_USUARIOS, {"email": email, "password": password, "email_confirm": True}
        )
        if 400 <= estado < 500 and _codigo(datos) == "email_exists":
            raise UserAlreadyExists()
        if 400 <= estado < 500 and _codigo(datos) == "weak_password":
            raise WeakPassword()
        if estado in ESTADOS_DE_DATOS_INVALIDOS:
            raise UserRejected()
        if estado not in (200, 201):
            logger.warning("la Admin API rechazó el alta", extra={"status_code": estado})
            raise AuthUnavailable()
        try:
            return UUID(datos["id"])
        except (KeyError, TypeError, ValueError):
            raise AuthUnavailable() from None

    def delete_user(self, user_id: UUID) -> None:
        estado, _ = self._llamar("DELETE", f"{RUTA_USUARIOS}/{user_id}", None)
        if estado not in (200, 204):
            logger.warning("la Admin API rechazó el borrado", extra={"status_code": estado})
            raise AuthUnavailable()

    def _llamar(self, metodo: str, ruta: str, cuerpo: dict | None) -> tuple[int, dict]:
        clave = self._clave.get_secret_value()
        peticion = urllib.request.Request(
            f"{self._url}{ruta}",
            method=metodo,
            data=None if cuerpo is None else json.dumps(cuerpo).encode(),
            headers={"apikey": clave, "Authorization": f"Bearer {clave}", "Content-Type": "application/json"},
        )
        try:
            with _opener.open(peticion, timeout=self._timeout_s) as respuesta:
                return respuesta.status, _json(respuesta.read())
        except urllib.error.HTTPError as error:
            return error.code, _json(error.read())
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as error:
            logger.warning("la Admin API no responde", extra={"error_type": type(error).__name__})
            raise AuthUnavailable() from None


def _json(contenido: bytes) -> dict:
    try:
        datos = json.loads(contenido or b"{}")
    except ValueError:
        return {}
    return datos if isinstance(datos, dict) else {}


def _codigo(datos: dict) -> str | None:
    """GoTrue usa `error_code` en las versiones nuevas y `code` en otras."""
    codigo = datos.get("error_code") or datos.get("code")
    return codigo if isinstance(codigo, str) else None
