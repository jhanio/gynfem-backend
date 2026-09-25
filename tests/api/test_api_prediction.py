"""POST /api/v1/predict y GET /api/v1/prediction/schema (HU006, HU007).

Validación en tres niveles (`docs/API_SPEC.md`, Sección 2.3):

- imposible fisiológicamente → 422 y no se predice;
- fuera del rango de entrenamiento → 200 con un aviso por variable;
- dentro del rango → 200 sin avisos.

Los límites se leen de su única fuente (`clinical_limits`, `feature_ranges.json`),
nunca se repiten aquí.
"""

import json
import math
from datetime import UTC, datetime, timedelta

import pytest

from .api_constantes import (
    CAMPOS_CLINICOS,
    CENTINELA,
    ENTRADA_EXTRAPOLADA,
    ENTRADA_NORMAL,
    FEATURE_RANGES_JSON,
    METADATA_JSON,
)

PREDICT = "/api/v1/predict"
SCHEMA = "/api/v1/prediction/schema"
NIVELES = {"high", "mid", "low"}
CLAVES_RESPUESTA = {
    "risk_level",
    "probabilities",
    "extrapolation_warnings",
    "clinical_disclaimer",
    "input",
    "model_input",
    "model_version",
    "conversion_schema_version",
    "predicted_at",
}


def _metadata() -> dict:
    return json.loads(METADATA_JSON.read_text(encoding="utf-8"))


def _rangos_json() -> dict:
    return json.loads(FEATURE_RANGES_JSON.read_text(encoding="utf-8"))["features"]


# --- Nivel c: dentro del rango ------------------------------------------------


def test_dentro_del_rango_200_sin_avisos(cliente):
    respuesta = cliente.post(PREDICT, json=ENTRADA_NORMAL)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert set(cuerpo) == CLAVES_RESPUESTA
    assert cuerpo["extrapolation_warnings"] == []


# --- Nivel b: fuera del rango de entrenamiento --------------------------------


def test_fuera_del_rango_200_con_aviso(cliente):
    from app.services.unit_conversion import model_to_clinical

    respuesta = cliente.post(PREDICT, json={**ENTRADA_NORMAL, "bmi_kg_m2": 32.0})

    assert respuesta.status_code == 200
    avisos = respuesta.json()["extrapolation_warnings"]
    assert len(avisos) == 1
    aviso = avisos[0]
    assert aviso["field"] == "bmi_kg_m2"
    assert aviso["direction"] == "above"
    assert aviso["unit"] == "kg/m²"
    assert aviso["training_max"] == model_to_clinical("bmi_kg_m2", _rangos_json()["bmi_kg_m2"]["max"])
    assert aviso["training_min"] == model_to_clinical("bmi_kg_m2", _rangos_json()["bmi_kg_m2"]["min"])
    assert aviso["message"]


def test_un_aviso_por_cada_variable_fuera_en_el_orden_del_contrato(cliente):
    entrada = {**ENTRADA_NORMAL, "bmi_kg_m2": 32.0, "age_years": 50}

    avisos = cliente.post(PREDICT, json=entrada).json()["extrapolation_warnings"]

    assert [(a["field"], a["direction"]) for a in avisos] == [
        ("age_years", "above"),
        ("bmi_kg_m2", "above"),
    ]


def test_aviso_por_debajo_del_minimo(cliente):
    avisos = cliente.post(PREDICT, json={**ENTRADA_NORMAL, "temperature_c": 32.0}).json()[
        "extrapolation_warnings"
    ]

    assert [(a["field"], a["direction"]) for a in avisos] == [("temperature_c", "below")]


# --- Nivel a: imposible fisiológicamente --------------------------------------


@pytest.mark.parametrize("extremo", ["min", "max"])
@pytest.mark.parametrize("campo", CAMPOS_CLINICOS)
def test_valor_imposible_422_sin_predecir(campo, extremo, cliente_espiado, espia):
    from app.services.clinical_limits import PHYSIOLOGICAL_LIMITS

    limite = getattr(PHYSIOLOGICAL_LIMITS[campo], extremo)
    valor = math.nextafter(limite, -math.inf if extremo == "min" else math.inf)
    tipo = "greater_than_equal" if extremo == "min" else "less_than_equal"

    respuesta = cliente_espiado.post(PREDICT, json={**ENTRADA_NORMAL, campo: valor})

    assert respuesta.status_code == 422
    error = respuesta.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"] == [{"loc": ["body", campo], "type": tipo}]
    assert espia.llamadas == [], "un valor imposible no debe llegar al modelo"


def test_los_limites_fisiologicos_se_admiten_inclusive(cliente):
    from app.services.clinical_limits import PHYSIOLOGICAL_LIMITS

    for extremo in ("min", "max"):
        entrada = {campo: getattr(limite, extremo) for campo, limite in PHYSIOLOGICAL_LIMITS.items()}
        assert entrada["diastolic_bp_mmhg"] < entrada["systolic_bp_mmhg"]
        assert cliente.post(PREDICT, json=entrada).status_code == 200, extremo


@pytest.mark.parametrize("diastolica", [118, 130])
def test_diastolica_no_menor_que_sistolica_422(diastolica, cliente_espiado, espia):
    entrada = {**ENTRADA_NORMAL, "systolic_bp_mmhg": 118, "diastolic_bp_mmhg": diastolica}

    respuesta = cliente_espiado.post(PREDICT, json=entrada)

    assert respuesta.status_code == 422
    assert [d["type"] for d in respuesta.json()["error"]["details"]] == [
        "diastolic_not_below_systolic"
    ]
    assert espia.llamadas == []


@pytest.mark.parametrize(
    "cuerpo",
    [
        {k: v for k, v in ENTRADA_NORMAL.items() if k != "bmi_kg_m2"},
        {**ENTRADA_NORMAL, "patient_name": "x"},
        {**ENTRADA_NORMAL, "age_years": True},
        {**ENTRADA_NORMAL, "age_years": "28"},
        {**ENTRADA_NORMAL, "age_years": None},
    ],
    ids=["falta_un_campo", "campo_extra", "booleano", "texto", "nulo"],
)
def test_entrada_malformada_422(cuerpo, cliente_espiado, espia):
    respuesta = cliente_espiado.post(PREDICT, json=cuerpo)

    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["code"] == "validation_error"
    assert espia.llamadas == []


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_nan_e_infinito_422(literal, cliente_espiado, espia):
    texto = json.dumps(ENTRADA_NORMAL).replace('"bmi_kg_m2": 22.5', f'"bmi_kg_m2": {literal}')

    respuesta = cliente_espiado.post(
        PREDICT, content=texto, headers={"Content-Type": "application/json"}
    )

    assert respuesta.status_code == 422
    assert espia.llamadas == []


def test_el_422_no_repite_el_valor(cliente):
    respuesta = cliente.post(PREDICT, json={**ENTRADA_NORMAL, "temperature_c": float(CENTINELA)})

    assert respuesta.status_code == 422
    assert CENTINELA not in respuesta.text


# --- Contenido de la respuesta ------------------------------------------------


@pytest.mark.parametrize("entrada", [ENTRADA_NORMAL, ENTRADA_EXTRAPOLADA])
def test_clase_y_probabilidades_validas(entrada, cliente):
    cuerpo = cliente.post(PREDICT, json=entrada).json()

    assert cuerpo["risk_level"] in NIVELES
    assert set(cuerpo["probabilities"]) == NIVELES
    assert sum(cuerpo["probabilities"].values()) == pytest.approx(1.0, abs=1e-9)
    assert all(0.0 <= p <= 1.0 for p in cuerpo["probabilities"].values())
    assert cuerpo["risk_level"] == max(cuerpo["probabilities"], key=cuerpo["probabilities"].get)


def test_probabilidades_por_clase_coinciden_con_el_modelo(cliente, modelo_real):
    """El orden de `classes_` no es el de severidad: la asignación debe ser por nombre."""
    import pandas as pd

    from app.services.unit_conversion import to_model_units

    cuerpo = cliente.post(PREDICT, json=ENTRADA_EXTRAPOLADA).json()
    X = pd.DataFrame([to_model_units(ENTRADA_EXTRAPOLADA)])
    esperadas = dict(zip(modelo_real.pipeline.classes_, modelo_real.pipeline.predict_proba(X)[0]))

    assert cuerpo["probabilities"] == {
        "high": pytest.approx(esperadas["high risk"], abs=1e-12),
        "mid": pytest.approx(esperadas["mid risk"], abs=1e-12),
        "low": pytest.approx(esperadas["low risk"], abs=1e-12),
    }


@pytest.mark.parametrize("entrada", [ENTRADA_NORMAL, ENTRADA_EXTRAPOLADA])
def test_siempre_incluye_la_advertencia_clinica(entrada, cliente):
    from app.services.prediction import CLINICAL_DISCLAIMER

    assert "no es un diagnóstico" in CLINICAL_DISCLAIMER.lower()
    assert "no sustituye" in CLINICAL_DISCLAIMER.lower()
    assert cliente.post(PREDICT, json=entrada).json()["clinical_disclaimer"] == CLINICAL_DISCLAIMER


@pytest.mark.parametrize("entrada", [ENTRADA_NORMAL, ENTRADA_EXTRAPOLADA])
def test_siempre_incluye_las_versiones(entrada, cliente):
    from app.services.unit_conversion import CONVERSION_SCHEMA_VERSION

    cuerpo = cliente.post(PREDICT, json=entrada).json()

    assert cuerpo["model_version"] == _metadata()["model_version"]
    assert cuerpo["conversion_schema_version"] == CONVERSION_SCHEMA_VERSION


def test_incluye_la_entrada_y_el_vector_del_modelo(cliente):
    from app.services.unit_conversion import to_model_units

    cuerpo = cliente.post(PREDICT, json=ENTRADA_NORMAL).json()
    orden = [f["name"] for f in sorted(_metadata()["features"], key=lambda f: f["position"])]

    assert cuerpo["input"] == ENTRADA_NORMAL
    assert list(cuerpo["input"]) == CAMPOS_CLINICOS
    assert list(cuerpo["model_input"]) == orden
    assert cuerpo["model_input"] == pytest.approx(to_model_units(ENTRADA_NORMAL), abs=1e-12)


def test_predicted_at_es_utc_actual(cliente):
    predicted_at = datetime.fromisoformat(cliente.post(PREDICT, json=ENTRADA_NORMAL).json()["predicted_at"])

    assert predicted_at.utcoffset() == timedelta(0)
    assert abs(datetime.now(UTC) - predicted_at) < timedelta(minutes=1)


def test_misma_entrada_misma_salida(cliente):
    primera = cliente.post(PREDICT, json=ENTRADA_EXTRAPOLADA).json()
    segunda = cliente.post(PREDICT, json=ENTRADA_EXTRAPOLADA).json()

    primera.pop("predicted_at")
    segunda.pop("predicted_at")
    assert primera == segunda


# --- /prediction/schema -------------------------------------------------------


def test_schema_expone_los_rangos_de_feature_ranges(cliente):
    from app.services.unit_conversion import CLINICAL_FIELDS, model_to_clinical

    cuerpo = cliente.get(SCHEMA).json()
    rangos = _rangos_json()

    assert [c["name"] for c in cuerpo["fields"]] == CAMPOS_CLINICOS
    for campo, publicado in zip(CLINICAL_FIELDS, cuerpo["fields"]):
        del_archivo = rangos[campo.model_feature]
        assert publicado["model_feature"] == campo.model_feature
        assert publicado["unit"] == campo.unit
        assert publicado["model_unit"] == del_archivo["unit"]
        assert publicado["training_range_model_units"] == {
            "min": del_archivo["min"],
            "max": del_archivo["max"],
        }
        assert publicado["training_range"] == {
            "min": model_to_clinical(campo.model_feature, del_archivo["min"]),
            "max": model_to_clinical(campo.model_feature, del_archivo["max"]),
        }


def test_schema_expone_los_limites_fisiologicos(cliente):
    from app.services.clinical_limits import PHYSIOLOGICAL_LIMITS

    for campo in cliente.get(SCHEMA).json()["fields"]:
        limite = PHYSIOLOGICAL_LIMITS[campo["name"]]
        assert campo["physiological_limits"] == {
            "min": limite.min,
            "max": limite.max,
            "status": limite.status,
            "rationale": limite.rationale,
        }
        assert campo["physiological_limits"]["status"] == "provisional"


def test_schema_y_validacion_comparten_los_limites(cliente):
    """Lo que publica el esquema es exactamente lo que aplica la validación."""
    # Sistólica alta como base: así la diastólica máxima no choca con la regla cruzada.
    base = {**ENTRADA_NORMAL, "systolic_bp_mmhg": 250}
    for campo in cliente.get(SCHEMA).json()["fields"]:
        nombre, maximo = campo["name"], campo["physiological_limits"]["max"]
        assert cliente.post(PREDICT, json={**base, nombre: maximo}).status_code == 200, nombre
        fuera = math.nextafter(maximo, math.inf)
        assert cliente.post(PREDICT, json={**base, nombre: fuera}).status_code == 422, nombre


def test_schema_incluye_las_versiones(cliente):
    from app.services.unit_conversion import CONVERSION_SCHEMA_VERSION

    cuerpo = cliente.get(SCHEMA).json()

    assert cuerpo["model_version"] == _metadata()["model_version"]
    assert cuerpo["conversion_schema_version"] == CONVERSION_SCHEMA_VERSION


# --- Logs ---------------------------------------------------------------------


def _lineas_json(capsys) -> list[dict]:
    salida = capsys.readouterr()
    return [
        json.loads(linea)
        for linea in (salida.out + salida.err).splitlines()
        if linea.strip().startswith("{")
    ]


#: Valores reconocibles, dentro del rango de entrenamiento. Todos tienen tres o
#: más decimales, así que no pueden confundirse con `duration_ms` (dos decimales).
ENTRADA_RECONOCIBLE = {
    "age_years": 33.125,
    "temperature_c": 36.9375,
    "heart_rate_bpm": 83.375,
    "systolic_bp_mmhg": 121.625,
    "diastolic_bp_mmhg": 77.875,
    "bmi_kg_m2": 23.4375,
    "hba1c_percent": 5.3125,
    "fasting_glucose_mg_dl": 87.625,
}


def test_los_logs_de_prediccion_no_contienen_valores_clinicos(cliente, capsys):
    from app.services.unit_conversion import to_model_units

    imposible = 98.6125  # °F escrito en el campo en °C: rechazado con 422
    capsys.readouterr()
    assert cliente.post(PREDICT, json=ENTRADA_RECONOCIBLE).status_code == 200
    assert cliente.post(PREDICT, json={**ENTRADA_RECONOCIBLE, "temperature_c": imposible}).status_code == 422
    lineas = _lineas_json(capsys)
    assert lineas, "no se capturó ningún log"
    # `timestamp` lleva segundos y microsegundos: podría contener «33.125» por azar.
    texto = json.dumps([{k: v for k, v in linea.items() if k != "timestamp"} for linea in lineas])

    convertidos = to_model_units(ENTRADA_RECONOCIBLE).values()
    for valor in [*ENTRADA_RECONOCIBLE.values(), *convertidos, imposible]:
        for forma in {str(valor), repr(valor), f"{valor:.3f}"}:
            assert forma not in texto, "un valor clínico llegó a los logs"


def test_el_log_de_prediccion_solo_lleva_el_resultado_agregado(cliente, capsys):
    capsys.readouterr()
    respuesta = cliente.post(PREDICT, json=ENTRADA_EXTRAPOLADA)

    lineas = [r for r in _lineas_json(capsys) if r.get("logger") == "gynfem.prediction"]
    assert len(lineas) == 1
    linea = lineas[0]
    assert set(linea) == {
        "timestamp",
        "level",
        "logger",
        "message",
        "request_id",
        "risk_level",
        "warning_count",
        "duration_ms",
    }
    assert linea["request_id"] == respuesta.headers["x-request-id"]
    assert linea["risk_level"] == respuesta.json()["risk_level"]
    assert linea["warning_count"] == 2
