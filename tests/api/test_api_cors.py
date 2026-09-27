"""CORS: solo los orígenes configurados, nunca el comodín."""

import pytest

from .api_constantes import ORIGEN_LOCAL, ORIGEN_NO_CONFIGURADO


def _preflight(cliente, origen: str):
    return cliente.options(
        "/api/v1/health",
        headers={"Origin": origen, "Access-Control-Request-Method": "GET"},
    )


def test_preflight_origen_configurado_se_acepta(cliente):
    respuesta = _preflight(cliente, ORIGEN_LOCAL)

    assert respuesta.status_code == 200
    assert respuesta.headers["access-control-allow-origin"] == ORIGEN_LOCAL


def test_preflight_origen_no_configurado_se_rechaza(cliente):
    respuesta = _preflight(cliente, ORIGEN_NO_CONFIGURADO)

    assert respuesta.status_code != 200
    assert "access-control-allow-origin" not in respuesta.headers


def test_get_origen_no_configurado_sin_cabecera_cors(cliente):
    respuesta = cliente.get("/api/v1/health", headers={"Origin": ORIGEN_NO_CONFIGURADO})

    assert respuesta.status_code == 200
    assert "access-control-allow-origin" not in respuesta.headers


def test_get_origen_configurado_recibe_su_origen_exacto(cliente):
    respuesta = cliente.get("/api/v1/health", headers={"Origin": ORIGEN_LOCAL})

    assert respuesta.headers["access-control-allow-origin"] == ORIGEN_LOCAL
    assert "x-request-id" in respuesta.headers.get("access-control-expose-headers", "").lower()


def test_no_se_permiten_credenciales(cliente):
    respuesta = _preflight(cliente, ORIGEN_LOCAL)

    assert "access-control-allow-credentials" not in respuesta.headers


@pytest.mark.parametrize("metodo", ["GET", "POST", "PATCH", "DELETE"])
def test_preflight_admite_los_metodos_de_la_api(metodo, cliente):
    """`PATCH /patients/{id}`, `DELETE /patients/{id}` y `PATCH /users/{id}` también desde el navegador."""
    respuesta = cliente.options(
        "/api/v1/patients/00000000-0000-4000-8000-000000000000",
        headers={"Origin": ORIGEN_LOCAL, "Access-Control-Request-Method": metodo,
                 "Access-Control-Request-Headers": "authorization, content-type"},
    )

    assert respuesta.status_code == 200
    assert metodo in respuesta.headers["access-control-allow-methods"]
    assert "authorization" in respuesta.headers["access-control-allow-headers"].lower()


def test_preflight_no_admite_metodos_que_la_api_no_usa(cliente):
    respuesta = cliente.options(
        "/api/v1/health", headers={"Origin": ORIGEN_LOCAL, "Access-Control-Request-Method": "PUT"}
    )

    assert respuesta.status_code != 200
