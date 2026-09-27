"""Decisión de acceso de cada ruta: la matriz rol × endpoint en código (HU001).

Toda ruta declara **exactamente una** de estas dependencias, en su router o en
su decorador:

- `requiere(Role.MEDICO, …)`: exige un token válido de un usuario **activo** con
  uno de esos roles. Resuelve el `Actor` de la petición.
- `publica("motivo")`: no exige ni valida token; el motivo queda escrito.

La documentación interactiva no es una ruta de un router: su decisión está en
`RUTAS_DE_DOCUMENTACION`. `tests/api/test_auth_rbac.py` recorre las rutas reales
y falla si alguna no tiene decisión o no coincide con la matriz de
`docs/API_SPEC.md`.

Orden: la autorización se resuelve **antes** que el cuerpo y que cualquier
consulta del recurso, así que un 401 o un 403 no dicen si el recurso existe.
"""

import logging

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.prefix import API_V1_PREFIX
from app.auth.errors import AccountDisabled, AuthError, Forbidden, NotAuthenticated
from app.auth.roles import Role
from app.core.logging import LOGGER_RAIZ
from app.services.actor import Actor

#: Rutas de FastAPI, fuera de los routers. Solo existen en development y test.
RUTAS_DE_DOCUMENTACION = {
    f"{API_V1_PREFIX}/openapi.json": "Documentación del contrato, sin datos; no existe en production.",
    f"{API_V1_PREFIX}/docs": "Interfaz de la documentación del contrato, sin datos; no existe en production.",
}

#: Lee `Authorization: Bearer …` y declara el esquema en OpenAPI. Sin
#: `auto_error`: la ausencia la convierte `Requiere` en el 401 uniforme.
esquema_bearer = HTTPBearer(auto_error=False, description="Access token de Supabase Auth")

logger = logging.getLogger(f"{LOGGER_RAIZ}.auth")


class Requiere:
    """Dependencia que autentica y autoriza. Deja el `Actor` en `request.state.actor`."""

    def __init__(self, *roles: Role) -> None:
        if not roles:
            raise ValueError("una ruta protegida declara al menos un rol")
        self.roles = frozenset(roles)

    def __call__(
        self,
        request: Request,
        credenciales: HTTPAuthorizationCredentials | None = Depends(esquema_bearer),
    ) -> Actor:
        user_id = None
        try:
            if credenciales is None or not credenciales.credentials:
                raise NotAuthenticated()
            user_id = request.app.state.token_verifier.verify(credenciales.credentials)
            estado = request.app.state.user_directory.status(user_id)
            if estado is None or not estado.is_active:
                raise AccountDisabled()
            if estado.role not in self.roles:
                raise Forbidden()
        except AuthError as exc:
            _registrar(user_id, exc.code)
            raise
        _registrar(user_id, "allowed")
        actor = Actor(user_id=user_id, role=estado.role)
        request.state.actor = actor
        return actor


class Publica:
    """Dependencia que no hace nada: deja escrita la justificación de una ruta pública."""

    def __init__(self, motivo: str) -> None:
        if not motivo.strip():
            raise ValueError("una ruta pública declara su motivo")
        self.motivo = motivo

    def __call__(self) -> None:
        return None


def requiere(*roles: Role):
    return Depends(Requiere(*roles))


def publica(motivo: str):
    return Depends(Publica(motivo))


def _registrar(user_id, resultado: str) -> None:
    extra = {"auth_outcome": resultado}
    if user_id is not None:
        extra["user_id"] = str(user_id)
    logger.info("autorización", extra=extra)
