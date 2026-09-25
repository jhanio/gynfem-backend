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
- El modelo se carga **una vez por sesión** (`modelo_real`) y se inyecta en
  cada aplicación: cargar el `.joblib` cuesta alrededor de un segundo. Los
  tests que prueban la carga misma usan `create_app()` sin inyectar nada.
- Los contratos alterados se construyen sobre una copia en `tmp_path`
  (`copiar_modelo`): `models/` nunca se escribe.
"""

import dataclasses
import json
import logging
import os
import shutil
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from .api_constantes import (
    CENTINELA,
    MODELS_DIR,
    ORIGEN_LOCAL,
    REPO_ROOT,
    RUTA_SECRETA,
    URL_BD_FICTICIA,
)

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
    """Declara variables de entorno: `configurar(cors_origins="…")` → `GYNFEM_CORS_ORIGINS`.

    `GYNFEM_DATABASE_URL` es obligatoria desde la Fase 9: si el test no la
    declara, se usa `URL_BD_FICTICIA`. Los tests que la quieren ausente
    configuran el entorno con `monkeypatch` directamente.
    """

    def _configurar(**variables: str) -> None:
        variables.setdefault("database_url", URL_BD_FICTICIA)
        for nombre, valor in variables.items():
            monkeypatch.setenv(f"GYNFEM_{nombre.upper()}", valor)

    return _configurar


@pytest.fixture(scope="session")
def modelo_real():
    """El modelo commiteado, cargado y validado una sola vez por sesión."""
    from app.services.model_loader import load_model

    return load_model(MODELS_DIR)


class EspiaDelModelo:
    """Envuelve el pipeline real: registra cada `X` que recibe y delega."""

    def __init__(self, pipeline) -> None:
        self._pipeline = pipeline
        self.llamadas: list = []

    def predict_proba(self, X):
        self.llamadas.append(X.copy())
        return self._pipeline.predict_proba(X)

    def __getattr__(self, nombre):
        return getattr(self._pipeline, nombre)


@pytest.fixture
def espia(modelo_real) -> EspiaDelModelo:
    return EspiaDelModelo(modelo_real.pipeline)


@pytest.fixture
def modelo_espiado(modelo_real, espia):
    return dataclasses.replace(modelo_real, pipeline=espia)


@pytest.fixture
def copiar_modelo(tmp_path):
    """Copia `models/` a `tmp_path` y aplica alteraciones a sus JSON.

    `copiar_modelo(metadata=f, rangos=g)`: `f` y `g` reciben el dict leído y lo
    modifican en sitio. Devuelve el directorio de la copia.
    """

    def _copiar(metadata=None, rangos=None, nombre: str = "modelo") -> "os.PathLike":
        destino = tmp_path / nombre
        shutil.copytree(MODELS_DIR, destino)
        for archivo, alterar in (("model_metadata.json", metadata), ("feature_ranges.json", rangos)):
            if alterar is None:
                continue
            ruta = destino / archivo
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            alterar(datos)
            ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        return destino

    return _copiar


@pytest.fixture
def crear_cliente(configurar, modelo_real):
    """Construye la aplicación desde el entorno, como en el arranque real.

    Con `modelo=None` se inyecta el modelo de la sesión; se puede pasar otro
    (por ejemplo, uno espiado).
    """
    from app.factory import create_app

    def _crear(
        environment: str = "development", cors_origins: str = ORIGEN_LOCAL, modelo=None
    ) -> TestClient:
        configurar(environment=environment, cors_origins=cors_origins)
        app = create_app(model=modelo or modelo_real)
        _anadir_rutas_de_prueba(app)
        return TestClient(app, raise_server_exceptions=False)

    yield _crear
    logging.getLogger("gynfem").handlers.clear()


@pytest.fixture
def cliente(crear_cliente) -> TestClient:
    return crear_cliente()


@pytest.fixture
def cliente_espiado(crear_cliente, modelo_espiado) -> TestClient:
    return crear_cliente(modelo=modelo_espiado)
