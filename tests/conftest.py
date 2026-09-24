"""Fixtures compartidas de la suite.

Cada script se ejecuta **una sola vez por sesión** y siempre sobre un
directorio temporal. Los artefactos commiteados —`data/processed/`, `models/` y
`reports/ml/`— no se reescriben nunca al correr los tests: se leen como
referencia, pero la suite no los toca.

`train_model` se importa **dentro** de las fixtures, no a nivel de módulo: así
un fallo de ese script no impide colectar `test_prepare_dataset.py`.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import prepare_dataset  # noqa: E402

RAW_CSV = REPO_ROOT / "data" / "raw" / "Mathernal_Risk.csv"
RAW_README = REPO_ROOT / "data" / "raw" / "README.md"
CLEANING_REPORT = REPO_ROOT / "reports" / "ml" / "data_cleaning_report.md"

#: Nombre de variante -> archivo commiteado en `data/processed/`.
COMMITTED_OUTPUTS = {
    "clean": prepare_dataset.CLEAN_CSV,
    "paper": prepare_dataset.PAPER_CSV,
}


@pytest.fixture(scope="session")
def pipeline_out_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Ejecuta el pipeline una vez en un directorio temporal de sesión."""
    destino = tmp_path_factory.mktemp("processed")
    prepare_dataset.main(out_dir=destino)
    return destino


@pytest.fixture(scope="session")
def outputs(pipeline_out_dir: Path) -> dict[str, Path]:
    """Rutas de ambas variantes recién generadas, dentro del `tmp_path`."""
    return {
        nombre: pipeline_out_dir / commiteado.name
        for nombre, commiteado in COMMITTED_OUTPUTS.items()
    }


# --- Entrenamiento (PR #4) -------------------------------------------------

MODELS_DIR = REPO_ROOT / "models"
MODEL_METADATA = MODELS_DIR / "model_metadata.json"
FEATURE_RANGES = MODELS_DIR / "feature_ranges.json"
TRAINING_METRICS = REPO_ROOT / "reports" / "ml" / "training_metrics.json"
TRAINING_REPORT = REPO_ROOT / "reports" / "ml" / "training_report.md"
ML_SPEC = REPO_ROOT / "docs" / "ML_SPEC.md"
REQUIREMENTS = REPO_ROOT / "requirements.txt"

#: Rejilla mínima para los tests: una sola configuración, 50 árboles. La
#: rejilla real (72 configuraciones) tarda minutos y no aporta nada a lo que
#: estos tests comprueban, que es el determinismo del procedimiento.
TINY_PARAM_GRID = {
    "n_estimators": [50],
    "max_depth": [None],
    "min_samples_leaf": [1],
    "max_features": ["sqrt"],
    "class_weight": [None],
}

#: Rejilla del test lento de determinismo: dos valores en dos ejes, lo justo
#: para que la busqueda tenga que elegir y el desempate se ejerza.
REDUCED_PARAM_GRID = {
    "n_estimators": [50, 100],
    "max_depth": [None, 10],
    "min_samples_leaf": [1],
    "max_features": ["sqrt"],
    "class_weight": [None],
}


@pytest.fixture(scope="session")
def training_out_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Ejecuta el entrenamiento una vez, con rejilla mínima y sin comprobaciones caras."""
    import train_model

    destino = tmp_path_factory.mktemp("training")
    train_model.main(out_dir=destino, param_grid=TINY_PARAM_GRID, full_checks=False)
    return destino


@pytest.fixture(scope="session")
def committed_metrics() -> dict:
    """`reports/ml/training_metrics.json` tal como está commiteado."""
    return json.loads(TRAINING_METRICS.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def committed_metadata() -> dict:
    """`models/model_metadata.json` tal como está commiteado."""
    return json.loads(MODEL_METADATA.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def committed_ranges() -> dict:
    """`models/feature_ranges.json` tal como está commiteado."""
    return json.loads(FEATURE_RANGES.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def committed_model(committed_metadata: dict):
    """El `.joblib` commiteado, ya deserializado."""
    import joblib

    return joblib.load(MODELS_DIR / committed_metadata["model_file"])


class Artefactos:
    """Los artefactos de un entrenamiento, vengan de donde vengan.

    Existe porque las pruebas de contrato —orden de features, orden de clases,
    hiperparametros, versiones, rangos— compararian si no dos archivos
    commiteados entre si. Eso las volveria ciegas a una mutacion del script:
    seguirian pasando hasta que alguien regenerara los artefactos. Ejecutarlas
    tambien contra una generacion recien hecha en `tmp_path` las ata al codigo.
    """

    def __init__(self, origen: str, raiz: Path):
        import joblib

        self.origen = origen
        self.models_dir = raiz / "models"
        self.metadata = json.loads((self.models_dir / "model_metadata.json").read_text("utf-8"))
        self.ranges = json.loads((self.models_dir / "feature_ranges.json").read_text("utf-8"))
        self.metrics = json.loads(
            (raiz / "reports" / "ml" / "training_metrics.json").read_text("utf-8")
        )
        self.model = joblib.load(self.models_dir / self.metadata["model_file"])

    def __repr__(self) -> str:
        return self.origen


@pytest.fixture(scope="session", params=["commiteado", "recien-generado"])
def artifacts(request, training_out_dir: Path) -> Artefactos:
    """Los mismos contratos, sobre lo commiteado y sobre una generacion nueva."""
    raiz = REPO_ROOT if request.param == "commiteado" else training_out_dir
    return Artefactos(request.param, raiz)
