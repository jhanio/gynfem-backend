"""Fixtures compartidas de la suite.

El pipeline se ejecuta **una sola vez por sesión** y siempre sobre un
directorio temporal. Los artefactos commiteados en `data/processed/` no se
reescriben nunca al correr los tests: se leen como referencia, pero la suite
no los toca.
"""

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
