"""Formato de error uniforme (`docs/API_SPEC.md`) sin detalles internos."""

import re
import uuid

import pytest

from .api_constantes import CENTINELA, ORIGEN_LOCAL, REPO_ROOT, RUTA_SECRETA

CLAVES_ERROR = {"code", "message", "request_id"}


def _assert_error_uniforme(respuesta, estado: int, codigo: str) -> dict:
    assert respuesta.status_code == estado
    assert respuesta.headers["content-type"].startswith("application/json")
    cuerpo = respuesta.json()
    assert set(cuerpo) == {"error"}
    assert cuerpo["error"]["code"] == codigo
    assert isinstance(cuerpo["error"]["message"], str) and cuerpo["error"]["message"]
    assert cuerpo["error"]["request_id"] == respuesta.headers["x-request-id"]
    return cuerpo["error"]


def test_ruta_inexistente_devuelve_error_uniforme(cliente):
    error = _assert_error_uniforme(cliente.get("/api/v1/no-existe"), 404, "not_found")
    assert set(error) == CLAVES_ERROR


def test_metodo_no_permitido_devuelve_error_uniforme(cliente):
    error = _assert_error_uniforme(cliente.delete("/api/v1/health"), 405, "method_not_allowed")
    assert set(error) == CLAVES_ERROR


def test_excepcion_no_controlada_no_filtra_traza(cliente):
    respuesta = cliente.get("/api/v1/_test/boom")

    error = _assert_error_uniforme(respuesta, 500, "internal_error")
    assert set(error) == CLAVES_ERROR
    texto = respuesta.text
    for prohibido in [
        "Traceback",
        'File "',
        ".py",
        "RuntimeError",
        CENTINELA,
        RUTA_SECRETA,
        str(REPO_ROOT),
        REPO_ROOT.as_posix(),
    ]:
        assert prohibido not in texto, prohibido


def test_error_de_validacion_no_refleja_el_valor(cliente):
    respuesta = cliente.post(
        "/api/v1/_test/items/abc", json={"systolic_bp_mmhg": f"no-numero-{CENTINELA}"}
    )

    error = _assert_error_uniforme(respuesta, 422, "validation_error")
    assert set(error) == CLAVES_ERROR | {"details"}
    assert error["details"], "el 422 debe indicar qué campo falló"
    for detalle in error["details"]:
        assert set(detalle) == {"loc", "type"}
    assert ["body", "systolic_bp_mmhg"] in [d["loc"] for d in error["details"]]
    assert CENTINELA not in respuesta.text


def test_error_500_conserva_cabeceras_cors(cliente):
    respuesta = cliente.get("/api/v1/_test/boom", headers={"Origin": ORIGEN_LOCAL})

    assert respuesta.status_code == 500
    assert respuesta.headers.get("access-control-allow-origin") == ORIGEN_LOCAL


def test_request_id_se_genera_si_no_viene(cliente):
    request_id = cliente.get("/api/v1/health").headers["x-request-id"]

    assert uuid.UUID(request_id).version == 4


def test_request_id_valido_se_respeta(cliente):
    propio = "front-3f2a9c1e-0001"
    respuesta = cliente.get("/api/v1/no-existe", headers={"X-Request-ID": propio})

    assert respuesta.headers["x-request-id"] == propio
    assert respuesta.json()["error"]["request_id"] == propio


@pytest.mark.parametrize(
    "malicioso", ["a" * 65, "abc def", "abc\tINYECTADO", "<script>", "abc;rm", f"x{CENTINELA}"]
)
def test_request_id_malicioso_se_reemplaza(malicioso, cliente):
    devuelto = cliente.get("/api/v1/health", headers={"X-Request-ID": malicioso}).headers[
        "x-request-id"
    ]

    assert devuelto != malicioso
    assert re.fullmatch(r"[0-9a-f-]{36}", devuelto)


def test_respuesta_sin_cabeceras_recibe_request_id():
    """ASGI permite un `http.response.start` sin la clave `headers`."""
    from fastapi.testclient import TestClient

    from app.core.middleware import RequestContextMiddleware

    async def app_sin_cabeceras(scope, receive, send):
        await send({"type": "http.response.start", "status": 204})
        await send({"type": "http.response.body", "body": b""})

    respuesta = TestClient(RequestContextMiddleware(app_sin_cabeceras)).get("/")

    assert respuesta.status_code == 204
    assert uuid.UUID(respuesta.headers["x-request-id"]).version == 4
