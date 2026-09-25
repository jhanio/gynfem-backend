"""`GET /api/v1/health` (liveness) y `GET /api/v1/health/ready` (readiness).

`/health` no consulta dependencias externas: Render lo usa para decidir si
reinicia la instancia, y reiniciar no arregla una caída de un servicio externo
(`docs/API_SPEC.md`). Tampoco expone versiones de dependencias, rutas ni
entorno: solo estado, versión de la aplicación y hora.

`/health/ready` sí consulta la base y el estado de sus migraciones. Es para
diagnóstico y monitorización, no para el health check de Render. Responde 200
o 503 con el formato de error uniforme, sin detalles de la conexión.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.core.errors import error_response
from app.schemas.error import ErrorResponse
from app.schemas.health import HealthResponse, ReadyChecks, ReadyResponse
from app.services.readiness import ReadinessService, ReadinessStatus

#: Mensaje para el cliente por cada estado no disponible. Sin detalles internos.
MENSAJES_NO_DISPONIBLE = {
    ReadinessStatus.DATABASE_UNAVAILABLE: "La base de datos no está disponible.",
    ReadinessStatus.SCHEMA_OUTDATED: "El esquema de la base de datos no está al día.",
}

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__, timestamp=datetime.now(UTC))


@router.get(
    "/health/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ErrorResponse}},
)
def ready(request: Request) -> ReadyResponse | JSONResponse:
    servicio: ReadinessService = request.app.state.readiness_service
    estado = servicio.check()
    if estado is not ReadinessStatus.READY:
        return error_response(503, estado.value, MENSAJES_NO_DISPONIBLE[estado])
    return ReadyResponse(status="ready", checks=ReadyChecks(database="ok", schema="ok"))
