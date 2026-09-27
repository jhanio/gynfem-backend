"""Errores de autenticación y autorización. `app/core/errors.py` los traduce al
formato uniforme (`docs/API_SPEC.md` §2.5).

401 = no autenticado (sin token, o token inválido o caducado). 403 = autenticado
pero sin permiso (rol insuficiente, o cuenta desactivada o sin perfil). Los
mensajes nunca llevan el token, un claim ni el motivo técnico del rechazo.
"""


class AuthError(Exception):
    status_code: int = 401
    code: str = "not_authenticated"
    message: str = "Se requiere autenticación."


class NotAuthenticated(AuthError):
    pass


class InvalidToken(AuthError):
    code = "invalid_token"
    message = "El token de acceso no es válido."


class TokenExpired(AuthError):
    code = "token_expired"
    message = "El token de acceso ha caducado."


class Forbidden(AuthError):
    status_code = 403
    code = "forbidden"
    message = "No tiene permiso para esta operación."


class AccountDisabled(AuthError):
    status_code = 403
    code = "account_disabled"
    message = "La cuenta no está habilitada para operar."


class SchemaOutdated(AuthError):
    """La base no tiene la tabla de perfiles (falta la migración 0008): no se puede autorizar.

    El mismo 503 que `/health/ready` (`docs/API_SPEC.md` §3.4), nunca un 500.
    """

    status_code = 503
    code = "schema_outdated"
    message = "El esquema de la base de datos no coincide con el que espera la aplicación."


class AuthUnavailable(AuthError):
    """Supabase (JWKS o Admin API) no responde: es una dependencia caída, no un 401."""

    status_code = 503
    code = "auth_unavailable"
    message = "El servicio de autenticación no está disponible."
