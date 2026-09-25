"""Fixtures de la suite de la API.

Aislamiento respecto de la suite de ML y del entorno del desarrollador:

- Ninguna fixture de aquí pide las de `tests/conftest.py`, así que esta suite
  nunca ejecuta el pipeline ni el entrenamiento.
- Toda variable `GYNFEM_*` del shell se borra antes de cada test: la
  configuración de cada test es solo la que el propio test declara.
- Cada test construye su propia aplicación con `create_app()`. No hay una
  aplicación global compartida entre tests.
- Las rutas que provocan errores a propósito se añaden aquí, sobre la
  aplicación del test; no existen en el código de la aplicación.
"""

import logging
import os
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from .api_constantes import CENTINELA, ORIGEN_LOCAL, REPO_ROOT, RUTA_SECRETA

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class CuerpoDePrueba(BaseModel):
    systolic_bp_mmhg: float


def _anadir_rutas_de_prueba(app) -> None:
    @app.get("/api/v1/_test/boom")
    def boom():
        raise RuntimeError(f"fallo con {CENTINELA} en {RUTA_SECRETA}")

    @app.post("/api/v1/_test/items/{item_id}")
    def item(item_id: str, cuerpo: CuerpoDePrueba, q: str | None = None):
        return {"ok": True}


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Borra toda variable `GYNFEM_*` heredada del shell."""
    for clave in list(os.environ):
        if clave.startswith("GYNFEM_"):
            monkeypatch.delenv(clave)


@pytest.fixture
def configurar(monkeypatch: pytest.MonkeyPatch):
    """Declara variables de entorno: `configurar(cors_origins="…")` → `GYNFEM_CORS_ORIGINS`."""

    def _configurar(**variables: str) -> None:
        for nombre, valor in variables.items():
            monkeypatch.setenv(f"GYNFEM_{nombre.upper()}", valor)

    return _configurar


@pytest.fixture
def crear_cliente(configurar):
    """Construye la aplicación desde el entorno, como en el arranque real."""
    from app.factory import create_app

    def _crear(environment: str = "development", cors_origins: str = ORIGEN_LOCAL) -> TestClient:
        configurar(environment=environment, cors_origins=cors_origins)
        app = create_app()
        _anadir_rutas_de_prueba(app)
        return TestClient(app, raise_server_exceptions=False)

    yield _crear
    logging.getLogger("gynfem").handlers.clear()


@pytest.fixture
def cliente(crear_cliente) -> TestClient:
    return crear_cliente()
