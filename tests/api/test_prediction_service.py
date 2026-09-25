"""Servicio de predicción, sin HTTP: vector, rangos de entrenamiento y determinismo."""

import json
import math

import pandas as pd
import pytest

from .api_constantes import DATASET_CLEAN, ENTRADA_EXTRAPOLADA, ENTRADA_NORMAL, METADATA_JSON


def _servicio(modelo):
    from app.services.prediction import PredictionService

    return PredictionService(modelo)


def _orden_del_metadata() -> list[str]:
    metadata = json.loads(METADATA_JSON.read_text(encoding="utf-8"))
    return [f["name"] for f in sorted(metadata["features"], key=lambda f: f["position"])]


def test_el_vector_sigue_el_orden_y_las_unidades_del_contrato(modelo_espiado, espia):
    # Ocho valores distintos entre sí: cualquier intercambio cambia el vector.
    entrada = {
        "age_years": 31,
        "temperature_c": 37.5,
        "heart_rate_bpm": 92,
        "systolic_bp_mmhg": 141,
        "diastolic_bp_mmhg": 95,
        "bmi_kg_m2": 24.3,
        "hba1c_percent": 5.9,
        "fasting_glucose_mg_dl": 99,
    }
    esperado = [31, 99.5, 92, 141, 95, 24.3, (5.9 - 2.152) * 10.929, 99 / 18]

    _servicio(modelo_espiado).predict(entrada)

    assert len(espia.llamadas) == 1
    X = espia.llamadas[0]
    assert list(X.columns) == _orden_del_metadata()
    assert X.iloc[0].tolist() == pytest.approx(esperado, abs=1e-9)


def test_equivale_al_modelo_sobre_filas_reales(modelo_real):
    """Filas del dataset llevadas a unidad clínica: el servicio debe dar lo mismo que el modelo."""
    from app.services.unit_conversion import CLINICAL_FIELDS, model_to_clinical

    filas = pd.read_csv(DATASET_CLEAN).drop(columns="risk_level").sample(40, random_state=7)
    servicio = _servicio(modelo_real)
    niveles = {"high risk": "high", "mid risk": "mid", "low risk": "low"}

    for _, fila in filas.iterrows():
        entrada = {c.name: model_to_clinical(c.model_feature, fila[c.model_feature]) for c in CLINICAL_FIELDS}
        esperadas = modelo_real.pipeline.predict_proba(fila.to_frame().T)[0]
        esperada_por_clase = dict(zip(modelo_real.pipeline.classes_, esperadas))

        resultado = servicio.predict(entrada)

        for clase, nivel in niveles.items():
            assert resultado.probabilities[nivel] == pytest.approx(esperada_por_clase[clase], abs=1e-12)
        assert resultado.risk_level == niveles[modelo_real.pipeline.predict(fila.to_frame().T)[0]]


def _rangos_clinicos(servicio) -> dict:
    return {c["name"]: c["training_range"] for c in servicio.schema()["fields"]}


def test_en_los_extremos_publicados_no_hay_aviso(modelo_real):
    servicio = _servicio(modelo_real)
    rangos = _rangos_clinicos(servicio)

    for extremo in ("min", "max"):
        entrada = {campo: rango[extremo] for campo, rango in rangos.items()}
        assert servicio.predict(entrada).extrapolation_warnings == [], extremo


@pytest.mark.parametrize("extremo, direccion", [("min", "below"), ("max", "above")])
def test_justo_fuera_del_rango_publicado_hay_aviso(extremo, direccion, modelo_real):
    servicio = _servicio(modelo_real)
    rangos = _rangos_clinicos(servicio)
    hacia = -math.inf if extremo == "min" else math.inf

    for campo, rango in rangos.items():
        entrada = {**ENTRADA_NORMAL, campo: math.nextafter(rango[extremo], hacia)}
        avisos = servicio.predict(entrada).extrapolation_warnings
        assert [(a.field, a.direction) for a in avisos] == [(campo, direccion)]


def test_fuera_del_rango_el_modelo_no_distingue_el_alejamiento(modelo_real):
    """Decisión C: todo valor por encima del máximo entrenado se trata como el máximo."""
    servicio = _servicio(modelo_real)
    en_el_maximo = servicio.predict({**ENTRADA_EXTRAPOLADA, "bmi_kg_m2": 27.9})
    muy_lejos = servicio.predict({**ENTRADA_EXTRAPOLADA, "bmi_kg_m2": 45.0})

    assert muy_lejos.probabilities == en_el_maximo.probabilities
    assert [a.field for a in muy_lejos.extrapolation_warnings] == ["bmi_kg_m2", "hba1c_percent"]


def test_los_rangos_salen_de_feature_ranges_json(copiar_modelo, modelo_real):
    """Con un archivo alterado, el aviso sigue al archivo: nada está escrito a mano."""
    from app.services.model_loader import load_model

    def imc_hasta_30(rangos):
        rangos["features"]["bmi_kg_m2"]["max"] = 30.0

    alterado = _servicio(load_model(copiar_modelo(rangos=imc_hasta_30)))
    real = _servicio(modelo_real)
    entrada = {**ENTRADA_NORMAL, "bmi_kg_m2": 29.0}

    assert alterado.predict(entrada).extrapolation_warnings == []
    assert [a.field for a in real.predict(entrada).extrapolation_warnings] == ["bmi_kg_m2"]
    assert _rangos_clinicos(alterado)["bmi_kg_m2"]["max"] == 30.0


def test_misma_entrada_misma_salida(modelo_real):
    from app.services.model_loader import load_model

    primero = _servicio(modelo_real).predict(ENTRADA_EXTRAPOLADA)
    segundo = _servicio(modelo_real).predict(ENTRADA_EXTRAPOLADA)
    recargado = _servicio(load_model(modelo_real.directory)).predict(ENTRADA_EXTRAPOLADA)

    for otro in (segundo, recargado):
        assert otro.probabilities == primero.probabilities
        assert otro.risk_level == primero.risk_level
        assert otro.model_input == primero.model_input
        assert otro.extrapolation_warnings == primero.extrapolation_warnings
