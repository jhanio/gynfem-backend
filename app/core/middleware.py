"""Correlación, log de acceso y captura de excepciones no controladas.

ASGI puro (no `BaseHTTPMiddleware`), montado dentro de `CORSMiddleware`:

    ServerErrorMiddleware → CORSMiddleware → RequestContextMiddleware → rutas

Así el 500 que genera aquí pasa por CORS y el frontend recibe el error real en
vez de un fallo de CORS.
"""

import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import ERROR_INTERNO, error_response
from app.core.logging import LOGGER_RAIZ, pila_sin_mensaje, request_id_var

HEADER_REQUEST_ID = "X-Request-ID"

#: Un identificador entrante se respeta solo si es corto y sin caracteres que
#: puedan inyectar líneas o marcado en los logs.
REQUEST_ID_VALIDO = re.compile(r"[A-Za-z0-9-]{1,64}")

#: Valor de `route` en el log cuando la petición no coincide con ninguna ruta:
#: el path real podría contener un identificador.
RUTA_SIN_COINCIDENCIA = "<sin coincidencia>"

#: `{nombre}` o `{nombre:convertidor}` dentro de una plantilla de ruta.
PARAMETRO_DE_RUTA = re.compile(r"\{(\w+)(?::\w+)?\}")

access_logger = logging.getLogger(f"{LOGGER_RAIZ}.access")
error_logger = logging.getLogger(f"{LOGGER_RAIZ}.errors")


def _request_id(scope: Scope) -> str:
    entrante = Headers(scope=scope).get(HEADER_REQUEST_ID)
    if entrante and REQUEST_ID_VALIDO.fullmatch(entrante):
        return entrante
    return str(uuid.uuid4())


def _plantilla_de_ruta(scope: Scope) -> str:
    """La plantilla completa (`/api/v1/items/{item_id}`), nunca el path real.

    Desde FastAPI 0.14x, `scope["route"].path` es relativo al router incluido
    (`/items/{item_id}`), sin su prefijo. El prefijo se recupera restando del
    path real la ruta renderizada con sus parámetros. Si no cuadra, no se
    arriesga a registrar el path real.

    Si algún parámetro no está en la plantilla, vive en el prefijo de un router
    padre (`/pacientes/{pid}` + `/evaluaciones`): el prefijo recuperado
    contendría su valor real, así que tampoco se registra.
    """
    ruta = scope.get("route")
    plantilla = getattr(ruta, "path", None)
    if not plantilla:
        return RUTA_SIN_COINCIDENCIA
    parametros = scope.get("path_params", {})
    if set(parametros) != set(PARAMETRO_DE_RUTA.findall(plantilla)):
        return RUTA_SIN_COINCIDENCIA
    renderizada = PARAMETRO_DE_RUTA.sub(lambda m: str(parametros.get(m[1], m[0])), plantilla)
    path = scope["path"]
    if not path.endswith(renderizada):
        return RUTA_SIN_COINCIDENCIA
    return path[: len(path) - len(renderizada)] + plantilla


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id(scope)
        token = request_id_var.set(request_id)
        inicio = time.perf_counter()
        estado = {"status_code": 500, "iniciada": False}

        async def send_con_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                estado["status_code"] = message["status"]
                estado["iniciada"] = True
                message.setdefault("headers", [])
                MutableHeaders(scope=message)[HEADER_REQUEST_ID] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_con_request_id)
        except Exception as exc:
            error_logger.error(
                "excepción no controlada",
                extra={"error_type": type(exc).__name__, "stack": pila_sin_mensaje(exc)},
            )
            if estado["iniciada"]:
                raise
            code, message = ERROR_INTERNO
            await error_response(500, code, message)(scope, receive, send_con_request_id)
        finally:
            access_logger.info(
                "petición atendida",
                extra={
                    "method": scope["method"],
                    "route": _plantilla_de_ruta(scope),
                    "status_code": estado["status_code"],
                    "duration_ms": round((time.perf_counter() - inicio) * 1000, 2),
                },
            )
            request_id_var.reset(token)
