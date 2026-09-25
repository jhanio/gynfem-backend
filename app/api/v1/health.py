"""`GET /api/v1/health`: liveness de la propia aplicación.

No consulta dependencias externas: Render usa este endpoint para decidir si
reinicia la instancia, y reiniciar no arregla una caída de un servicio externo
(`docs/API_SPEC.md`). Tampoco expone versiones de dependencias, rutas ni
entorno: solo estado, versión de la aplicación y hora.
"""

from datetime import UTC, datetime

from fastapi import APIRouter

from app import __version__
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__, timestamp=datetime.now(UTC))
