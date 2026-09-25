"""Logs estructurados con correlación y sin valores clínicos.

Se captura todo lo que el proceso escribe (stdout y stderr), no solo el logger
de la aplicación: un valor clínico filtrado por cualquier otro camino también
debe hacer fallar el test.
"""

import json
import logging

import pytest
from fastapi import APIRouter

from .api_constantes import CENTINELA, RUTA_SECRETA

CLAVES_ACCESO = {
    "timestamp",
    "level",
    "logger",
    "message",
    "request_id",
    "method",
    "route",
    "status_code",
    "duration_ms",
}


def _lineas_json(texto: str) -> list[dict]:
    lineas = []
    for linea in texto.splitlines():
        linea = linea.strip()
        if linea.startswith("{"):
            lineas.append(json.loads(linea))
    return lineas


def _accesos(capsys) -> list[dict]:
    salida = capsys.readouterr()
    return [r for r in _lineas_json(salida.out + salida.err) if r.get("logger") == "gynfem.access"]


def test_cada_peticion_emite_una_linea_json_de_acceso(cliente, capsys):
    capsys.readouterr()
    cliente.get("/api/v1/health")

    accesos = _accesos(capsys)
    assert len(accesos) == 1
    acceso = accesos[0]
    assert set(acceso) == CLAVES_ACCESO
    assert acceso["method"] == "GET"
    assert acceso["route"] == "/api/v1/health"
    assert acceso["status_code"] == 200


def test_request_id_del_log_coincide_con_el_header(cliente, capsys):
    capsys.readouterr()
    respuesta = cliente.get("/api/v1/health")

    assert _accesos(capsys)[0]["request_id"] == respuesta.headers["x-request-id"]


def test_el_500_queda_registrado_con_su_estado(cliente, capsys):
    capsys.readouterr()
    cliente.get("/api/v1/_test/boom")

    assert _accesos(capsys)[0]["status_code"] == 500


def test_logs_no_contienen_valores_clinicos(cliente, capsys):
    capsys.readouterr()
    cliente.post(
        f"/api/v1/_test/items/{CENTINELA}",
        params={"q": CENTINELA},
        headers={"X-Clinico": CENTINELA},
        json={"systolic_bp_mmhg": float(CENTINELA)},
    )
    cliente.post("/api/v1/_test/items/x", json={"systolic_bp_mmhg": f"no-numero-{CENTINELA}"})
    cliente.get("/api/v1/_test/boom")
    cliente.get(f"/api/v1/no-existe/{CENTINELA}", params={"q": CENTINELA})

    salida = capsys.readouterr()
    todo = salida.out + salida.err
    assert _lineas_json(salida.out), "no se capturó ningún log: el test no estaría verificando nada"
    assert CENTINELA not in todo
    assert RUTA_SECRETA not in todo


def test_log_registra_la_plantilla_de_ruta(cliente, capsys):
    capsys.readouterr()
    cliente.post("/api/v1/_test/items/paciente-123", json={"systolic_bp_mmhg": 120.0})

    acceso = _accesos(capsys)[0]
    assert acceso["route"] == "/api/v1/_test/items/{item_id}"


def test_ruta_sin_coincidencia_no_registra_el_path(cliente, capsys):
    capsys.readouterr()
    cliente.get("/api/v1/pacientes-inexistentes/abc-999")

    acceso = _accesos(capsys)[0]
    assert "abc-999" not in json.dumps(acceso)
    assert acceso["status_code"] == 404


def test_el_error_no_controlado_se_registra_sin_su_mensaje(cliente, capsys):
    capsys.readouterr()
    cliente.get("/api/v1/_test/boom")

    registros = _lineas_json(capsys.readouterr().out)
    errores = [r for r in registros if r.get("level") == "ERROR"]
    assert len(errores) == 1
    assert errores[0]["error_type"] == "RuntimeError"
    assert CENTINELA not in json.dumps(errores[0])


def test_parametro_en_el_prefijo_de_un_router_padre_no_se_registra(cliente, capsys):
    """Recursos anidados (pacientes → evaluaciones), previsibles desde la Fase 10.

    `scope["route"].path` es relativo al router que declara la ruta, así que un
    parámetro del prefijo del router padre no está en la plantilla.
    """
    padre = APIRouter(prefix="/api/v1/_test/pacientes/{pid}")
    hijo = APIRouter()

    @hijo.get("/evaluaciones")
    def evaluaciones(pid: str):
        return {}

    @hijo.get("/evaluaciones/{eid}")
    def evaluacion(pid: str, eid: str):
        return {}

    padre.include_router(hijo)
    cliente.app.include_router(padre)

    capsys.readouterr()
    assert cliente.get(f"/api/v1/_test/pacientes/{CENTINELA}/evaluaciones").status_code == 200
    assert cliente.get(f"/api/v1/_test/pacientes/{CENTINELA}/evaluaciones/e-1").status_code == 200

    accesos = _accesos(capsys)
    assert len(accesos) == 2
    assert CENTINELA not in json.dumps(accesos)


def test_create_app_repetido_no_duplica_las_lineas_de_log(crear_cliente, capsys):
    crear_cliente()
    cliente = crear_cliente()
    capsys.readouterr()
    cliente.get("/api/v1/health")

    assert len(_accesos(capsys)) == 1


class _Coleccion(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.registros: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.registros.append(logging.Formatter("%(message)s").format(record))


@pytest.fixture
def loggers_de_uvicorn():
    """Simula la configuración de uvicorn, que añade sus handlers antes de importar la app."""
    coleccion = _Coleccion()
    nombres = ("uvicorn.access", "uvicorn.error")
    for nombre in nombres:
        logger = logging.getLogger(nombre)
        logger.addHandler(coleccion)
        logger.setLevel(logging.INFO)
    yield coleccion
    for nombre in nombres:
        logger = logging.getLogger(nombre)
        logger.removeHandler(coleccion)
        logger.setLevel(logging.NOTSET)
        logger.disabled = False
        logger.filters.clear()


def test_el_log_de_acceso_de_uvicorn_queda_desactivado_sin_depender_del_flag(
    loggers_de_uvicorn, crear_cliente
):
    crear_cliente()
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/1.1" %d', "127.0.0.1:5000", "GET", f"/api/v1/x?q={CENTINELA}", 404
    )

    assert loggers_de_uvicorn.registros == []


def test_uvicorn_error_no_registra_el_mensaje_de_la_excepcion(loggers_de_uvicorn, crear_cliente):
    """uvicorn registra así la excepción que el middleware relanza si la respuesta ya empezó."""
    crear_cliente()
    try:
        raise RuntimeError(f"fallo con {CENTINELA} en {RUTA_SECRETA}")
    except RuntimeError as exc:
        logging.getLogger("uvicorn.error").error("Exception in ASGI application\n", exc_info=exc)

    texto = "\n".join(loggers_de_uvicorn.registros)
    assert "Exception in ASGI application" in texto
    assert "RuntimeError" in texto
    assert CENTINELA not in texto
    assert RUTA_SECRETA not in texto
