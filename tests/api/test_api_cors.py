"""CORS: solo los orígenes configurados, nunca el comodín."""

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
