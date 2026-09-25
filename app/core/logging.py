"""Logs estructurados (una línea JSON por evento) con identificador de correlación.

Regla: **ningún dato clínico ni identificador de paciente en los logs**
(`docs/SECURITY.md`). Se garantiza por construcción:

- el formateador solo emite las claves de `CAMPOS_EXTRA`; cualquier otro
  `extra` se descarta;
- de una excepción se registra el tipo y la pila (archivo, línea, función),
  nunca su mensaje, que puede contener valores enviados por el cliente;
- el log de acceso registra la plantilla de la ruta, nunca el path real ni la
  query string (`app/core/middleware.py`).
"""

import json
import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime

LOGGER_RAIZ = "gynfem"

#: Identificador de correlación de la petición en curso.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

#: Únicas claves adicionales que un registro puede llevar.
CAMPOS_EXTRA = ("method", "route", "status_code", "duration_ms", "error_type", "stack")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        datos = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for campo in CAMPOS_EXTRA:
            if hasattr(record, campo):
                datos[campo] = getattr(record, campo)
        return json.dumps(datos)


class _StdoutHandler(logging.StreamHandler):
    """Escribe en el `sys.stdout` vigente en cada emisión, no en el del arranque."""

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stdout
        super().emit(record)


class _SinMensajeDeExcepcion(logging.Filter):
    """Reduce la excepción de un registro a su tipo: sin mensaje ni traza.

    uvicorn registra en `uvicorn.error` la excepción que llega al servidor (la
    que `RequestContextMiddleware` relanza si la respuesta ya había empezado),
    con la traza completa y el mensaje, que puede contener valores enviados por
    el cliente.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and record.exc_info[0] is not None:
            tipo = record.exc_info[0].__name__
            record.msg = f"{record.getMessage().strip()} ({tipo})"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


def configure_logging(level: str) -> None:
    """Configura el logger `gynfem` y neutraliza los de uvicorn. Idempotente.

    No depende de que el comando de arranque lleve `--no-access-log`: uvicorn
    configura sus loggers antes de importar la aplicación, así que lo que se
    fija aquí prevalece.
    """
    logger = logging.getLogger(LOGGER_RAIZ)
    logger.handlers.clear()
    handler = _StdoutHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False

    # Registra el path real y la query string; lo reemplaza el log de acceso propio.
    logging.getLogger("uvicorn.access").disabled = True
    uvicorn_error = logging.getLogger("uvicorn.error")
    if not any(isinstance(f, _SinMensajeDeExcepcion) for f in uvicorn_error.filters):
        uvicorn_error.addFilter(_SinMensajeDeExcepcion())


def pila_sin_mensaje(exc: BaseException) -> list[str]:
    """La pila de `exc` como `archivo:línea en función`, sin el mensaje de la excepción."""
    return [
        f"{frame.filename}:{frame.lineno} en {frame.name}"
        for frame in traceback.extract_tb(exc.__traceback__)
    ]
