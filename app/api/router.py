"""Router raíz de la API: todo cuelga de `/api/v1` (`docs/API_SPEC.md`, Sección 2.1)."""

from fastapi import APIRouter

from app.api.v1 import health

API_V1_PREFIX = "/api/v1"

api_router = APIRouter(prefix=API_V1_PREFIX)
api_router.include_router(health.router)
