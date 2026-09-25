"""Construcción de la aplicación.

`create_app()` no tiene efectos al importarse: los tests construyen una
aplicación por test. El objeto que arranca uvicorn está en `app/main.py`.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import API_V1_PREFIX, api_router
from app.core.config import Settings, load_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import HEADER_REQUEST_ID, RequestContextMiddleware
from app.schemas.error import ErrorResponse

CORS_METODOS = ["GET", "POST"]
CORS_CABECERAS = ["Authorization", "Content-Type", HEADER_REQUEST_ID]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Lanza `ConfigurationError` si el entorno es inválido, antes de construir nada."""
    settings = settings or load_settings()
    configure_logging(settings.log_level)

    docs = settings.environment != "production"
    app = FastAPI(
        title="GynFem API",
        version=__version__,
        openapi_url=f"{API_V1_PREFIX}/openapi.json" if docs else None,
        docs_url=f"{API_V1_PREFIX}/docs" if docs else None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
        responses={
            404: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    app.state.settings = settings
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
