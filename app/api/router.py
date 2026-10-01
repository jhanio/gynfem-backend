"""Router raíz de la API: todo cuelga de `/api/v1` (`docs/API_SPEC.md`, Sección 2.1)."""

from fastapi import APIRouter

from app.api.prefix import API_V1_PREFIX
from app.api.v1 import health, measurements, me, patients, prediction, settings, users

__all__ = ["API_V1_PREFIX", "api_router"]

api_router = APIRouter(prefix=API_V1_PREFIX)
api_router.include_router(health.router)
api_router.include_router(prediction.router)
api_router.include_router(patients.router)
api_router.include_router(measurements.router)
api_router.include_router(me.router)
api_router.include_router(users.router)
api_router.include_router(settings.router)
