"""Construcción de la aplicación.

`create_app()` no tiene efectos al importarse: los tests construyen una
aplicación por test. El objeto que arranca uvicorn está en `app/main.py`.

El modelo se carga aquí, **una sola vez**, y se valida su contrato: si no
coincide, `create_app()` lanza `ModelContractError` y la aplicación no
arranca. Los tests pueden inyectar un modelo ya cargado.

El pool de la base se **crea** aquí, cerrado, y se abre en el ciclo de vida
(`_lifespan`) sin esperar a la base: crear o importar la aplicación nunca
conecta, y una base caída no impide arrancar (`app/db/pool.py`).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import API_V1_PREFIX, api_router
from app.core.config import Settings, load_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import HEADER_REQUEST_ID, RequestContextMiddleware
from app.db.migrate import discover
from app.db.pool import close_pool, create_pool, open_pool
from app.schemas.error import ErrorResponse
from app.services.model_loader import LoadedModel, load_model
from app.services.prediction import PredictionService
from app.services.readiness import ReadinessService

CORS_METODOS = ["GET", "POST"]
CORS_CABECERAS = ["Authorization", "Content-Type", HEADER_REQUEST_ID]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    open_pool(app.state.db_pool)
    try:
        yield
    finally:
        close_pool(app.state.db_pool)


def create_app(settings: Settings | None = None, model: LoadedModel | None = None) -> FastAPI:
    """Lanza `ConfigurationError` si el entorno es inválido, antes de construir nada;
    `ModelContractError` si el contrato del modelo no se puede verificar, y
    `MigrationError` si la serie de migraciones del repositorio no es válida."""
    settings = settings or load_settings()
    configure_logging(settings.log_level)
    model = model or load_model(settings.model_dir)
    migraciones_esperadas = frozenset(m.version for m in discover())

    docs = settings.environment != "production"
    app = FastAPI(
        title="GynFem API",
        version=__version__,
        openapi_url=f"{API_V1_PREFIX}/openapi.json" if docs else None,
        docs_url=f"{API_V1_PREFIX}/docs" if docs else None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
        lifespan=_lifespan,
        responses={
            404: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    app.state.settings = settings
    app.state.prediction_service = PredictionService(model)
    app.state.db_pool = create_pool(settings)
    app.state.readiness_service = ReadinessService(
        app.state.db_pool, settings, migraciones_esperadas
    )
    register_exception_handlers(app)
    app.include_router(api_router)

    # El último añadido es el más externo: CORS envuelve al de contexto.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=CORS_METODOS,
        allow_headers=CORS_CABECERAS,
        expose_headers=[HEADER_REQUEST_ID],
    )
    return app
