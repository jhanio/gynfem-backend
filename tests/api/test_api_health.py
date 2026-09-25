"""GET /api/v1/health: liveness de la propia aplicación, sin detalles internos.

Las rutas se escriben literales a propósito: si el prefijo cambia en el
código, estos tests deben fallar.
"""

import platform
import re
from datetime import UTC, datetime, timedelta

import fastapi
import pydantic
import pytest
import starlette

from .api_constantes import ORIGEN_LOCAL, REPO_ROOT

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
API_SPEC = REPO_ROOT / "docs" / "API_SPEC.md"


def test_health_responde_200_con_el_esquema(cliente):
    respuesta = cliente.get("/api/v1/health")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert set(cuerpo) == {"status", "version", "timestamp"}
    assert cuerpo["status"] == "ok"


def test_health_version_es_la_de_la_app(cliente):
    from app import __version__

    version = cliente.get("/api/v1/health").json()["version"]

    assert version == __version__
    assert SEMVER.match(version)


def test_health_timestamp_es_utc_actual(cliente):
    marca = cliente.get("/api/v1/health").json()["timestamp"]
    momento = datetime.fromisoformat(marca)

    assert momento.utcoffset() == timedelta(0)
    assert abs(datetime.now(UTC) - momento) < timedelta(seconds=5)


def test_health_no_expone_informacion_interna(cliente):
    texto = cliente.get("/api/v1/health").text

    prohibidos = [
        platform.python_version(),
        fastapi.__version__,
        starlette.__version__,
        pydantic.VERSION,
        str(REPO_ROOT),
        REPO_ROOT.as_posix(),
        "development",
        ORIGEN_LOCAL,
    ]
    for valor in prohibidos:
        assert valor not in texto


@pytest.mark.parametrize("ruta", ["/health", "/api/v2/health", "/v1/health"])
def test_health_fuera_del_prefijo_no_existe(ruta, cliente):
    respuesta = cliente.get(ruta)

    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "not_found"


def test_version_del_ejemplo_de_api_spec_coincide():
    from app import __version__

    versiones = re.findall(r'"version":\s*"([^"]+)"', API_SPEC.read_text(encoding="utf-8"))

    assert versiones, "API_SPEC.md no incluye el ejemplo de /health"
    assert set(versiones) == {__version__}


def test_docs_disponibles_bajo_el_prefijo_en_desarrollo(cliente):
    assert cliente.get("/api/v1/docs").status_code == 200
    assert cliente.get("/api/v1/openapi.json").status_code == 200
    assert cliente.get("/docs").status_code == 404
    assert cliente.get("/openapi.json").status_code == 404
    assert cliente.get("/docs/oauth2-redirect").status_code == 404
    assert cliente.get("/redoc").status_code == 404


def test_docs_deshabilitadas_en_produccion(crear_cliente):
    cliente = crear_cliente(environment="production", cors_origins="https://gynfem.vercel.app")

    for ruta in ["/api/v1/docs", "/api/v1/openapi.json", "/docs", "/openapi.json", "/redoc"]:
        assert cliente.get(ruta).status_code == 404, ruta
    assert cliente.get("/api/v1/health").status_code == 200
