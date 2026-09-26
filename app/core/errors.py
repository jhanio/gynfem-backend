"""Manejo centralizado de errores con el formato uniforme de `docs/API_SPEC.md`.

Los errores HTTP (404, 405, …) y de validación (422) se resuelven aquí. Las
excepciones no controladas las convierte en 500 `RequestContextMiddleware`,
que está dentro de CORS a fin de que el 500 conserve las cabeceras CORS.

Desde la Fase 10, también los errores del dominio (`app/services/errors.py`:
404 y 409 con su código estable) y la caída de la base en una operación
clínica (503 `database_unavailable`). De un error de base se registra el tipo,
nunca el mensaje: el de libpq nombra host, puerto y usuario.
"""

import logging


from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import psycopg
from psycopg_pool import PoolTimeout

from app.core.logging import LOGGER_RAIZ, request_id_var
from app.schemas.error import ErrorBody, ErrorDetail, ErrorResponse
from app.services.errors import Conflict, DomainError, NotFound

#: Estado HTTP -> (código estable, mensaje para el cliente).
ERRORES_HTTP = {
    404: ("not_found", "Recurso no encontrado."),
    405: ("method_not_allowed", "Método no permitido."),
}
ERROR_HTTP_GENERICO = ("http_error", "La solicitud no se pudo procesar.")
ERROR_VALIDACION = ("validation_error", "La solicitud no es válida.")
ERROR_INTERNO = ("internal_error", "Error interno del servidor.")
ERROR_BASE = ("database_unavailable", "La base de datos no está disponible.")

logger = logging.getLogger(f"{LOGGER_RAIZ}.errors")


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    cuerpo = ErrorResponse(
        error=ErrorBody(
            code=code, message=message, request_id=request_id_var.get(), details=details
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=cuerpo.model_dump(exclude_none=True),
        headers=headers,
    )


async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code, message = ERRORES_HTTP.get(exc.status_code, ERROR_HTTP_GENERICO)
    return error_response(exc.status_code, code, message, headers=exc.headers)


async def _validation_exception(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Solo `loc` y `type`: el `input` y el `msg` de Pydantic pueden repetir el valor enviado."""
    detalles = [ErrorDetail(loc=list(e["loc"]), type=e["type"]) for e in exc.errors()]
    code, message = ERROR_VALIDACION
    return error_response(422, code, message, details=detalles)


async def _domain_exception(request: Request, exc: DomainError) -> JSONResponse:
    estado = 404 if isinstance(exc, NotFound) else 409 if isinstance(exc, Conflict) else 400
    return error_response(estado, exc.code, exc.message)


async def _database_exception(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("base de datos no disponible", extra={"error_type": type(exc).__name__})
    code, message = ERROR_BASE
    return error_response(503, code, message)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_exception)
    app.add_exception_handler(RequestValidationError, _validation_exception)
    app.add_exception_handler(DomainError, _domain_exception)
    app.add_exception_handler(PoolTimeout, _database_exception)
    app.add_exception_handler(psycopg.OperationalError, _database_exception)
