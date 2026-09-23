"""Tests de scripts/prepare_dataset.py — limpieza reproducible del dataset.

Ninguna aserción de este archivo imprime ni inspecciona la columna `Name`.
"""

import filecmp
import hashlib
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import prepare_dataset  # noqa: E402

from conftest import CLEANING_REPORT, COMMITTED_OUTPUTS, RAW_CSV, RAW_README  # noqa: E402

EXPECTED_COLUMNS = [
    "age_years",
    "temperature_f",
    "heart_rate_bpm",
    "systolic_bp_mmhg",
    "diastolic_bp_mmhg",
    "bmi_kg_m2",
    "hba1c_mmol_mol",
    "fasting_glucose_mmol_l",
    "risk_level",
]
CLINICAL_COLUMNS = EXPECTED_COLUMNS[:-1]
RISK_LABELS = {"low risk", "mid risk", "high risk"}

# Cifras derivadas del RAW (6103 filas) y del profiling:
#   - principal: deduplica (-1 fila, el grupo `low risk`) y elimina edad 250,
#     temperatura 39.6 °F y diastólica 9 (-3 filas) → 6099
#   - paper: reproduce la cifra publicada aplicando edad>100, temperatura fuera
#     de 95–105 °F y diastólica<50 (-45 filas) SIN deduplicar → 6058
EXPECTED_CLEAN_ROWS = 6099
EXPECTED_CLEAN_DISTRIBUTION = {"high risk": 2058, "mid risk": 2043, "low risk": 1998}
EXPECTED_PAPER_ROWS = 6058
EXPECTED_PAPER_DISTRIBUTION = {"high risk": 2016, "mid risk": 2043, "low risk": 1999}
EXPECTED_HYPOTHERMIA_ROWS = 42


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _recorded_raw_sha256() -> str:
    text = RAW_README.read_text(encoding="utf-8")
    match = re.search(r"SHA-256:\*\*\s*`([0-9a-f]{64})`", text)
    assert match, "No se encontró el SHA-256 registrado en data/raw/README.md"
    return match.group(1)


def _reported_sha256(csv_name: str) -> str:
    """SHA-256 de una variante tal como lo publica la Sección 3 del reporte.

    Se lee del documento en lugar de fijarlo como constante: si el reporte y
    los datos se separan, el test falla en vez de quedarse mudo.
    """
    text = CLEANING_REPORT.read_text(encoding="utf-8")
    patron = rf"`data/processed/{re.escape(csv_name)}`\s*\|\s*\d+\s*\|\s*`([0-9a-f]{{64}})`"
    match = re.search(patron, text)
    assert match, f"No se encontró el SHA-256 de {csv_name} en {CLEANING_REPORT.name}"
    return match.group(1)


@pytest.fixture(scope="session")
def clean_df(outputs: dict[str, Path]) -> pd.DataFrame:
    return pd.read_csv(outputs["clean"])


@pytest.fixture(scope="session")
def paper_df(outputs: dict[str, Path]) -> pd.DataFrame:
    return pd.read_csv(outputs["paper"])


# --- Inmutabilidad del RAW -------------------------------------------------


def test_raw_sha256_no_cambia_tras_ejecutar_el_pipeline(tmp_path):
    sha_antes = _sha256_of_file(RAW_CSV)
    assert sha_antes == _recorded_raw_sha256()

    prepare_dataset.main(out_dir=tmp_path)

    assert _sha256_of_file(RAW_CSV) == sha_antes


# --- Los SHA-256 publicados ------------------------------------------------


@pytest.mark.parametrize("variant", ["clean", "paper"])
def test_regenerar_reproduce_el_sha256_publicado_en_el_reporte(variant, outputs):
    """Regenerar desde el RAW actual debe dar el hash que publica el reporte.

    Este es el candado que faltaba: sin él, un cambio de umbral reescribía los
    CSV y ningún test lo notaba, dejando reporte y datos en desacuerdo.
    """
    esperado = _reported_sha256(COMMITTED_OUTPUTS[variant].name)
    assert _sha256_of_file(outputs[variant]) == esperado


@pytest.mark.parametrize("variant", ["clean", "paper"])
def test_el_artefacto_commiteado_coincide_con_el_reporte(variant):
    """El archivo versionado en `data/processed/` no se ha desincronizado."""
    commiteado = COMMITTED_OUTPUTS[variant]
    assert _sha256_of_file(commiteado) == _reported_sha256(commiteado.name)


@pytest.mark.parametrize("variant", ["clean", "paper"])
def test_la_suite_no_reescribe_los_artefactos_commiteados(variant, outputs):
    """La salida del pipeline en los tests vive fuera de `data/processed/`."""
    assert outputs[variant] != COMMITTED_OUTPUTS[variant]
    assert COMMITTED_OUTPUTS[variant].parent not in outputs[variant].parents


# --- Esquema de salida -----------------------------------------------------


@pytest.mark.parametrize("variant", ["clean", "paper"])
def test_salida_tiene_las_nueve_columnas_en_orden(variant, outputs):
    df = pd.read_csv(outputs[variant])
    assert list(df.columns) == EXPECTED_COLUMNS


@pytest.mark.parametrize("variant", ["clean", "paper"])
def test_salida_no_contiene_name_ni_patient_id(variant, outputs):
    encabezado = outputs[variant].read_text(encoding="utf-8").splitlines()[0]
    normalizadas = {c.strip().lower() for c in encabezado.split(",")}
    assert "name" not in normalizadas
    assert "patient id" not in normalizadas
    assert "patient_id" not in normalizadas


@pytest.mark.parametrize("variant", ["clean", "paper"])
def test_las_ocho_variables_clinicas_son_numericas(variant, outputs):
    """Blinda contra la fuga de texto libre (p. ej. `Name`) en las features."""
    df = pd.read_csv(outputs[variant])
    no_numericas = [c for c in CLINICAL_COLUMNS if not pd.api.types.is_numeric_dtype(df[c])]
    assert no_numericas == []


@pytest.mark.parametrize("variant", ["clean", "paper"])
def test_risk_level_solo_tiene_las_tres_etiquetas(variant, outputs):
    df = pd.read_csv(outputs[variant])
    assert set(df["risk_level"].unique()) == RISK_LABELS


# --- Calidad de datos ------------------------------------------------------


@pytest.mark.parametrize("variant", ["clean", "paper"])
def test_salida_sin_nulos(variant, outputs):
    df = pd.read_csv(outputs[variant])
    assert df.isna().sum().sum() == 0


def test_variante_principal_sin_duplicados_de_las_ocho_variables(clean_df):
    assert int(clean_df.duplicated(subset=CLINICAL_COLUMNS).sum()) == 0


# --- Variante principal ----------------------------------------------------


def test_variante_principal_tiene_las_filas_y_distribucion_esperadas(clean_df):
    assert len(clean_df) == EXPECTED_CLEAN_ROWS
    assert clean_df["risk_level"].value_counts().to_dict() == EXPECTED_CLEAN_DISTRIBUTION


def test_variante_principal_conserva_la_hipotermia_de_93_a_94_9_f(clean_df):
    hipotermia = clean_df[clean_df["temperature_f"].between(93.0, 94.9)]
    assert len(hipotermia) == EXPECTED_HYPOTHERMIA_ROWS
    assert set(hipotermia["risk_level"].unique()) == {"high risk"}


def test_variante_principal_elimina_los_valores_fisiologicamente_imposibles(clean_df):
    assert clean_df["age_years"].max() <= 100
    assert clean_df["temperature_f"].min() >= 70.0
    assert clean_df["diastolic_bp_mmhg"].min() >= 50


# --- Variante paper --------------------------------------------------------


def test_variante_paper_tiene_las_filas_y_distribucion_esperadas(paper_df):
    assert len(paper_df) == EXPECTED_PAPER_ROWS
    assert paper_df["risk_level"].value_counts().to_dict() == EXPECTED_PAPER_DISTRIBUTION


def test_variante_paper_aplica_las_tres_reglas_del_paper(paper_df):
    assert paper_df["age_years"].max() <= 100
    assert paper_df["temperature_f"].between(95.0, 105.0).all()
    assert paper_df["diastolic_bp_mmhg"].min() >= 50


def test_variante_paper_no_deduplica_y_conserva_el_grupo_duplicado(paper_df):
    """El paper no dedupica: ninguna de sus reglas alcanza al grupo duplicado.

    Conservarlo es lo que permite reproducir exactamente las 6058 filas
    publicadas. La deduplicación vive solo en la variante principal.
    """
    assert int(paper_df.duplicated(subset=CLINICAL_COLUMNS).sum()) == 1


# --- Reproducibilidad ------------------------------------------------------


@pytest.mark.parametrize("variant", ["clean", "paper"])
def test_salida_usa_solo_lf(variant, outputs):
    """`to_csv` usaría os.linesep, lo que haría los bytes dependientes del SO."""
    assert b"\r\n" not in outputs[variant].read_bytes()


@pytest.mark.parametrize("variant", ["clean", "paper"])
def test_gitattributes_protege_los_csv_generados_de_la_conversion_de_eol(variant, outputs):
    """Con core.autocrlf=true, git reescribiría los CSV a CRLF al hacer checkout.

    Eso cambiaría su SHA-256 respecto al documentado en el reporte y ensuciaría
    `git status` en cuanto alguien regenerara los datasets. Igual que
    `data/raw/*.csv`, las salidas deben estar marcadas como binarias.
    """
    nombre = outputs[variant].name
    gitattributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    patrones = {
        linea.split()[0]
        for linea in gitattributes.splitlines()
        if linea.strip() and not linea.startswith("#") and "binary" in linea
    }
    assert "data/processed/*.csv" in patrones, (
        f"{nombre} no está protegido contra la conversión de fin de línea"
    )


def test_dos_ejecuciones_producen_archivos_byte_identicos(tmp_path):
    primera = tmp_path / "primera"
    segunda = tmp_path / "segunda"

    prepare_dataset.main(out_dir=primera)
    prepare_dataset.main(out_dir=segunda)

    for nombre, commiteado in COMMITTED_OUTPUTS.items():
        assert filecmp.cmp(primera / commiteado.name, segunda / commiteado.name, shallow=False), (
            f"La variante '{nombre}' no es byte-idéntica entre ejecuciones"
        )
