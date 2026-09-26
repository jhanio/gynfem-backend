"""Piezas compartidas por los routers clínicos (`patients.py`, `measurements.py`)."""

import logging
import time

from app.core.logging import LOGGER_RAIZ
from app.schemas.error import ErrorResponse

#: Respuestas de error documentadas en OpenAPI para las rutas clínicas.
ERRORES = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}

logger = logging.getLogger(f"{LOGGER_RAIZ}.clinical")


def registrar(accion: str, inicio: float) -> None:
    """Solo la acción y la latencia: nunca ids, nombres, documentos ni valores."""
    logger.info(
        "escritura clínica",
        extra={"action": accion, "duration_ms": round((time.perf_counter() - inicio) * 1000, 2)},
    )
