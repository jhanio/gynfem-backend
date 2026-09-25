"""Conversión de unidades clínicas peruanas a las del dataset (`docs/ML_SPEC.md`, Sección 4).

El módulo es dominio puro: sin FastAPI. Los valores esperados son los casos
conocidos de ML_SPEC, no un recálculo con las mismas fórmulas.
"""

import re
import subprocess
import sys

import pytest

from .api_constantes import CAMPOS_CLINICOS, ENTRADA_NORMAL, REPO_ROOT

FEATURES_DEL_DATASET = [
    "age_years",
    "temperature_f",
    "heart_rate_bpm",
    "systolic_bp_mmhg",
    "diastolic_bp_mmhg",
    "bmi_kg_m2",
    "hba1c_mmol_mol",
    "fasting_glucose_mmol_l",
]


def _convertir(**cambios) -> dict:
    from app.services.unit_conversion import to_model_units

    return to_model_units({**ENTRADA_NORMAL, **cambios})


def test_37_c_son_98_6_f():
    assert _convertir(temperature_c=37)["temperature_f"] == pytest.approx(98.6, abs=1e-9)


def test_90_mg_dl_son_5_mmol_l():
    assert _convertir(fasting_glucose_mg_dl=90)["fasting_glucose_mmol_l"] == pytest.approx(
        5.0, abs=1e-9
    )


def test_5_7_por_ciento_son_38_78_mmol_mol_sin_redondear():
    hba1c = _convertir(hba1c_percent=5.7)["hba1c_mmol_mol"]

    assert hba1c == pytest.approx(38.776092, abs=1e-9)
    assert round(hba1c, 2) == 38.78


@pytest.mark.parametrize(
    "campo, valores",
    [
        ("temperature_c", [30.0, 33.888888888888886, 36.8, 37.0, 40.0, 43.0]),
        ("hba1c_percent", [3.0, 4.9, 5.7, 6.5, 20.0]),
        ("fasting_glucose_mg_dl", [20.0, 63.0, 90.0, 147.6, 600.0]),
    ],
)
def test_ida_y_vuelta(campo, valores):
    from app.services.unit_conversion import CLINICAL_FIELDS, model_to_clinical, to_model_units

    feature = {c.name: c.model_feature for c in CLINICAL_FIELDS}[campo]
    for valor in valores:
        convertida = to_model_units({**ENTRADA_NORMAL, campo: valor})
        assert model_to_clinical(feature, convertida[feature]) == pytest.approx(valor, abs=1e-6)


def test_variables_sin_conversion_pasan_intactas():
    convertida = _convertir()

    for campo in ["age_years", "heart_rate_bpm", "systolic_bp_mmhg", "diastolic_bp_mmhg", "bmi_kg_m2"]:
        assert convertida[campo] == ENTRADA_NORMAL[campo]


def test_la_salida_tiene_las_8_features_del_dataset():
    assert list(_convertir()) == FEATURES_DEL_DATASET


def test_los_campos_clinicos_son_los_aprobados():
    from app.services.unit_conversion import CLINICAL_FIELDS

    assert [c.name for c in CLINICAL_FIELDS] == CAMPOS_CLINICOS
    assert [c.model_feature for c in CLINICAL_FIELDS] == FEATURES_DEL_DATASET


def test_el_modulo_no_depende_de_fastapi():
    codigo = "import sys, app.services.unit_conversion; print('fastapi' in sys.modules)"
    resultado = subprocess.run(
        [sys.executable, "-c", codigo], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60
    )

    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == "False"


def test_la_version_del_esquema_de_conversion_es_semver():
    from app.services.unit_conversion import CONVERSION_SCHEMA_VERSION

    assert re.fullmatch(r"\d+\.\d+\.\d+", CONVERSION_SCHEMA_VERSION)


def test_las_formulas_solo_viven_en_el_modulo_de_conversion():
    """Una fórmula duplicada podría divergir de la que se documenta y se prueba."""
    fragmentos = ["10.929", "2.152", "9 / 5", "5 / 9", "/ 18", "* 18", "9/5", "5/9", "/18", "*18"]
    modulo = REPO_ROOT / "app" / "services" / "unit_conversion.py"
    infractores = []
    for ruta in (REPO_ROOT / "app").rglob("*.py"):
        if ruta == modulo:
            continue
        texto = ruta.read_text(encoding="utf-8")
        infractores += [f"{ruta.name}: {f}" for f in fragmentos if f in texto]

    assert not infractores
