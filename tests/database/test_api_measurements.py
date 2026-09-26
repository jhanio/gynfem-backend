"""HU005 (registrar y actualizar variables clínicas) y la predicción persistida.

La medición, su predicción y la auditoría se escriben en una sola transacción.
El vector que se guarda es exactamente el que recibió el modelo (lo captura
`EspiaDelModelo`), y lo guardado basta para reproducir la predicción.
"""

import json
import math
import uuid
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from api.api_constantes import CAMPOS_CLINICOS, ENTRADA_EXTRAPOLADA, ENTRADA_NORMAL, METADATA_JSON

from .conftest import filas
from .datos_sinteticos import (
    CAMPOS_INTERNOS,
    CLAVES_MEDICION,
    CLAVES_PAGINA,
    CLAVES_PREDICCION,
    CLAVES_PREDICCION_DETALLE,
    PACIENTE,
)

PACIENTES = "/api/v1/patients"
UUID_INEXISTENTE = "00000000-0000-4000-8000-000000000000"


def features() -> list[str]:
    metadata = json.loads(METADATA_JSON.read_text(encoding="utf-8"))
    return [f["name"] for f in sorted(metadata["features"], key=lambda f: f["position"])]


def paciente(cliente) -> str:
    return cliente.post(PACIENTES, json=PACIENTE).json()["id"]


def medir(cliente, pid: str, entrada=ENTRADA_NORMAL, **extra) -> dict:
    respuesta = cliente.post(f"{PACIENTES}/{pid}/measurements", json={**entrada, **extra})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def contar(url: str) -> dict[str, int]:
    return {
        tabla: filas(url, f"SELECT count(*) FROM gynfem.{tabla}")[0][0]
        for tabla in ("patients", "clinical_measurements", "predictions", "audit_log")
    }


def fila_prediccion(url: str, pid: str) -> dict:
    import psycopg

    with psycopg.connect(url) as c:
        cursor = c.execute("SELECT * FROM gynfem.predictions WHERE id = %s", [pid])
        return dict(zip([d.name for d in cursor.description], cursor.fetchone(), strict=True))


# --- Registrar ----------------------------------------------------------------------


def test_registrar_medicion_201_con_prediccion(cliente_bd):
    cliente = cliente_bd()
    pid = paciente(cliente)
    cuerpo = medir(cliente, pid)

    assert set(cuerpo) == {"measurement", "prediction"}
    assert set(cuerpo["measurement"]) == CLAVES_MEDICION
    assert set(cuerpo["prediction"]) == CLAVES_PREDICCION
    assert cuerpo["measurement"]["patient_id"] == pid
    assert {c: cuerpo["measurement"][c] for c in CAMPOS_CLINICOS} == {c: float(v) for c, v in ENTRADA_NORMAL.items()}
    assert cuerpo["prediction"]["risk_level"] in {"high", "mid", "low"}
    assert math.isclose(sum(cuerpo["prediction"]["probabilities"].values()), 1.0)


def test_la_respuesta_persistida_coincide_con_predict(cliente_bd):
    """Misma entrada, misma predicción que el endpoint sin estado de la Fase 8."""
    cliente = cliente_bd()
    pid = paciente(cliente)
    persistida = medir(cliente, pid, ENTRADA_EXTRAPOLADA)["prediction"]
    sin_estado = cliente.post("/api/v1/predict", json=ENTRADA_EXTRAPOLADA).json()

    for campo in ("risk_level", "probabilities", "extrapolation_warnings", "clinical_disclaimer",
                  "model_version", "conversion_schema_version"):
        assert persistida[campo] == sin_estado[campo], campo


def test_medicion_para_paciente_inexistente_404_sin_escribir(cliente_bd, base_migrada):
    respuesta = cliente_bd().post(f"{PACIENTES}/{UUID_INEXISTENTE}/measurements", json=ENTRADA_NORMAL)

    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "patient_not_found"
    assert contar(base_migrada) == {"patients": 0, "clinical_measurements": 0, "predictions": 0, "audit_log": 0}


def test_medicion_para_paciente_desactivada_404(cliente_bd, base_migrada):
    cliente = cliente_bd()
    pid = paciente(cliente)
    cliente.delete(f"{PACIENTES}/{pid}")
    assert cliente.post(f"{PACIENTES}/{pid}/measurements", json=ENTRADA_NORMAL).status_code == 404
    assert contar(base_migrada)["clinical_measurements"] == 0


@pytest.mark.parametrize(
    "cambios",
    [{"temperature_c": 98.6}, {"diastolic_bp_mmhg": 140}, {"bmi_kg_m2": "32"}, {"extra": 1}],
)
def test_medicion_invalida_422_sin_escribir_ni_predecir(cambios, cliente_bd, espia, modelo_espiado, base_migrada):
    cliente = cliente_bd(modelo=modelo_espiado)
    pid = paciente(cliente)
    antes = contar(base_migrada)

    respuesta = cliente.post(f"{PACIENTES}/{pid}/measurements", json={**ENTRADA_NORMAL, **cambios})

    assert respuesta.status_code == 422
    assert espia.llamadas == []
    assert contar(base_migrada) == antes


def test_measured_at_futuro_422(cliente_bd, base_migrada):
    cliente = cliente_bd()
    pid = paciente(cliente)
    futuro = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    respuesta = cliente.post(f"{PACIENTES}/{pid}/measurements", json={**ENTRADA_NORMAL, "measured_at": futuro})
    assert respuesta.status_code == 422
    assert contar(base_migrada)["clinical_measurements"] == 0


def test_measured_at_sin_zona_horaria_422(cliente_bd):
    cliente = cliente_bd()
    pid = paciente(cliente)
    respuesta = cliente.post(f"{PACIENTES}/{pid}/measurements", json={**ENTRADA_NORMAL, "measured_at": "2026-09-20T10:00:00"})
    assert respuesta.status_code == 422


def test_measured_at_pasado_se_respeta(cliente_bd):
    cliente = cliente_bd()
    pid = paciente(cliente)
    cuerpo = medir(cliente, pid, measured_at="2026-09-20T10:00:00+00:00")
    assert datetime.fromisoformat(cuerpo["measurement"]["measured_at"]) == datetime(2026, 9, 20, 10, tzinfo=UTC)


# --- Trazabilidad -------------------------------------------------------------------


def test_vector_almacenado_es_exactamente_el_enviado_al_modelo(cliente_bd, espia, modelo_espiado, base_migrada):
    cliente = cliente_bd(modelo=modelo_espiado)
    pid = paciente(cliente)
    prediccion = medir(cliente, pid, ENTRADA_EXTRAPOLADA)["prediction"]

    assert len(espia.llamadas) == 1
    enviado = espia.llamadas[0]
    guardada = fila_prediccion(base_migrada, prediccion["id"])

    assert list(enviado.columns) == features()
    columnas_modelo = [c for c in guardada if c.startswith("model_") and c != "model_version"]
    assert columnas_modelo == [f"model_{f}" for f in features()]
    assert [guardada[f"model_{f}"] for f in features()] == [float(v) for v in enviado.iloc[0]], "mismo orden, bit a bit"


def test_prediccion_guardada_se_reproduce(cliente_bd, modelo_real, base_migrada):
    from app.services.prediction import RISK_LEVELS

    cliente = cliente_bd()
    pid = paciente(cliente)
    prediccion = medir(cliente, pid, ENTRADA_EXTRAPOLADA)["prediction"]
    guardada = fila_prediccion(base_migrada, prediccion["id"])

    X = pd.DataFrame([[guardada[f"model_{f}"] for f in features()]], columns=features())
    reproducidas = dict(zip(modelo_real.classes, modelo_real.pipeline.predict_proba(X)[0], strict=True))
    for clase, p in reproducidas.items():
        assert guardada[f"prob_{RISK_LEVELS[clase]}"] == float(p)
    assert guardada["risk_level"] == RISK_LEVELS[max(reproducidas, key=reproducidas.get)]


def test_avisos_de_extrapolacion_se_persisten(cliente_bd, base_migrada):
    cliente = cliente_bd()
    pid = paciente(cliente)
    prediccion = medir(cliente, pid, ENTRADA_EXTRAPOLADA)["prediction"]
    guardada = fila_prediccion(base_migrada, prediccion["id"])

    assert len(guardada["extrapolation_warnings"]) == 2
    assert guardada["extrapolation_warnings"] == prediccion["extrapolation_warnings"]


def test_se_persisten_versiones_y_marca_de_tiempo(cliente_bd, modelo_real, base_migrada):
    from app.services.unit_conversion import CONVERSION_SCHEMA_VERSION

    cliente = cliente_bd()
    pid = paciente(cliente)
    prediccion = medir(cliente, pid)["prediction"]
    guardada = fila_prediccion(base_migrada, prediccion["id"])

    assert guardada["model_version"] == modelo_real.version
    assert guardada["conversion_schema_version"] == CONVERSION_SCHEMA_VERSION
    assert guardada["predicted_at"] == datetime.fromisoformat(prediccion["predicted_at"])
    assert {c: guardada[f"input_{c}"] for c in CAMPOS_CLINICOS} == {c: float(v) for c, v in ENTRADA_NORMAL.items()}


def test_mediciones_se_guardan_en_unidades_clinicas(cliente_bd, base_migrada):
    cliente = cliente_bd()
    pid = paciente(cliente)
    medicion = medir(cliente, pid)["measurement"]

    guardada = filas(
        base_migrada,
        f"SELECT {', '.join(CAMPOS_CLINICOS)} FROM gynfem.clinical_measurements WHERE id = %s",
        [medicion["id"]],
    )[0]
    assert dict(zip(CAMPOS_CLINICOS, guardada, strict=True)) == {c: float(v) for c, v in ENTRADA_NORMAL.items()}


def test_consultar_prediccion_persistida(cliente_bd, espia, modelo_espiado):
    cliente = cliente_bd(modelo=modelo_espiado)
    pid = paciente(cliente)
    creada = medir(cliente, pid, ENTRADA_EXTRAPOLADA)

    respuesta = cliente.get(f"/api/v1/predictions/{creada['prediction']['id']}")

    assert respuesta.status_code == 200
    detalle = respuesta.json()
    assert set(detalle) == CLAVES_PREDICCION_DETALLE
    assert detalle["measurement_id"] == creada["measurement"]["id"]
    assert list(detalle["model_input"]) == features()
    assert list(detalle["model_input"].values()) == [float(v) for v in espia.llamadas[0].iloc[0]]
    assert detalle["input"] == {c: float(v) for c, v in ENTRADA_EXTRAPOLADA.items()}
    for campo in CLAVES_PREDICCION:
        assert detalle[campo] == creada["prediction"][campo], campo


def test_prediccion_inexistente_404(cliente_bd):
    respuesta = cliente_bd().get(f"/api/v1/predictions/{UUID_INEXISTENTE}")
    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "prediction_not_found"


# --- Atomicidad -----------------------------------------------------------------------


class _ModeloQueFalla:
    def __init__(self, pipeline):
        self._pipeline = pipeline

    def predict_proba(self, X):
        raise RuntimeError("fallo del modelo")

    def __getattr__(self, nombre):
        return getattr(self._pipeline, nombre)


def test_fallo_de_la_prediccion_no_deja_escrito_nada(cliente_bd, modelo_real, base_migrada):
    import dataclasses

    cliente = cliente_bd(modelo=dataclasses.replace(modelo_real, pipeline=_ModeloQueFalla(modelo_real.pipeline)))
    pid = paciente(cliente)
    antes = contar(base_migrada)

    respuesta = cliente.post(f"{PACIENTES}/{pid}/measurements", json=ENTRADA_NORMAL)

    assert respuesta.status_code == 500
    assert respuesta.json()["error"]["code"] == "internal_error"
    assert contar(base_migrada) == antes


def test_fallo_a_mitad_de_la_transaccion_revierte_todo(cliente_bd, base_migrada, monkeypatch):
    import app.repositories.predictions as repositorio

    cliente = cliente_bd()
    pid = paciente(cliente)
    antes = contar(base_migrada)

    def fallar(*args, **kwargs):
        raise RuntimeError("fallo al guardar la predicción")

    monkeypatch.setattr(repositorio, "insert_prediction", fallar)
    respuesta = cliente.post(f"{PACIENTES}/{pid}/measurements", json=ENTRADA_NORMAL)

    assert respuesta.status_code == 500
    assert contar(base_migrada) == antes, "la medición ya insertada se deshace con la transacción"


def test_registrar_medicion_audita_medicion_y_prediccion(cliente_bd, base_migrada):
    cliente = cliente_bd()
    pid = paciente(cliente)
    creada = medir(cliente, pid)

    ultimas = filas(base_migrada, "SELECT action, entity_type, entity_id FROM gynfem.audit_log ORDER BY id")[-2:]
    assert ultimas == [
        ("clinical_measurement.create", "clinical_measurement", uuid.UUID(creada["measurement"]["id"])),
        ("prediction.create", "prediction", uuid.UUID(creada["prediction"]["id"])),
    ]


# --- Consultar mediciones -------------------------------------------------------------


def test_consultar_mediciones_paginado(cliente_bd):
    cliente = cliente_bd()
    pid = paciente(cliente)
    creadas = [medir(cliente, pid, measured_at=f"2026-09-{10 + n:02d}T08:00:00+00:00") for n in range(3)]

    pagina = cliente.get(f"{PACIENTES}/{pid}/measurements", params={"limit": 2}).json()
    resto = cliente.get(f"{PACIENTES}/{pid}/measurements", params={"limit": 2, "offset": 2}).json()

    assert set(pagina) == CLAVES_PAGINA
    assert (len(pagina["items"]), pagina["has_more"], len(resto["items"]), resto["has_more"]) == (2, True, 1, False)
    item = pagina["items"][0]
    assert set(item) == CLAVES_MEDICION | {"prediction_id"}
    assert item["id"] == creadas[-1]["measurement"]["id"], "la más reciente primero"
    assert item["prediction_id"] == creadas[-1]["prediction"]["id"]


@pytest.mark.parametrize("params", [{"limit": 51}, {"limit": 0}, {"offset": -1}])
def test_consultar_mediciones_paginacion_invalida_422(params, cliente_bd):
    cliente = cliente_bd()
    pid = paciente(cliente)
    assert cliente.get(f"{PACIENTES}/{pid}/measurements", params=params).status_code == 422


def test_consultar_mediciones_de_paciente_inexistente_404(cliente_bd):
    respuesta = cliente_bd().get(f"{PACIENTES}/{UUID_INEXISTENTE}/measurements")
    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "patient_not_found"


# --- Corrección (HU005, «actualizar») ---------------------------------------------------


def corregir(cliente, mid: str, entrada=ENTRADA_EXTRAPOLADA, **extra):
    return cliente.post(f"/api/v1/measurements/{mid}/corrections", json={**entrada, **extra})


def test_corregir_crea_una_nueva_y_da_de_baja_la_original(cliente_bd, base_migrada):
    cliente = cliente_bd()
    pid = paciente(cliente)
    original = medir(cliente, pid, measured_at="2026-09-20T10:00:00+00:00")

    respuesta = corregir(cliente, original["measurement"]["id"])

    assert respuesta.status_code == 201
    nueva = respuesta.json()
    assert set(nueva) == {"measurement", "prediction"}
    assert nueva["measurement"]["id"] != original["measurement"]["id"]
    assert nueva["measurement"]["measured_at"] == original["measurement"]["measured_at"], "hereda la hora de la original"
    assert filas(
        base_migrada,
        "SELECT replaces_measurement_id FROM gynfem.clinical_measurements WHERE id = %s",
        [nueva["measurement"]["id"]],
    ) == [(uuid.UUID(original["measurement"]["id"]),)]
    assert filas(
        base_migrada,
        "SELECT deleted_at IS NOT NULL FROM gynfem.clinical_measurements WHERE id = %s",
        [original["measurement"]["id"]],
    ) == [(True,)]
    vigentes = cliente.get(f"{PACIENTES}/{pid}/measurements").json()["items"]
    assert [m["id"] for m in vigentes] == [nueva["measurement"]["id"]]


def test_la_prediccion_original_se_conserva_intacta(cliente_bd, base_migrada):
    cliente = cliente_bd()
    pid = paciente(cliente)
    original = medir(cliente, pid)
    antes = fila_prediccion(base_migrada, original["prediction"]["id"])

    corregir(cliente, original["measurement"]["id"])

    despues = fila_prediccion(base_migrada, original["prediction"]["id"])
    assert despues == antes
    assert cliente.get(f"/api/v1/predictions/{original['prediction']['id']}").status_code == 200


def test_corregir_dos_veces_la_misma_409(cliente_bd):
    cliente = cliente_bd()
    pid = paciente(cliente)
    original = medir(cliente, pid)
    assert corregir(cliente, original["measurement"]["id"]).status_code == 201

    respuesta = corregir(cliente, original["measurement"]["id"])
    assert respuesta.status_code in (404, 409)


def test_corregir_medicion_inexistente_404(cliente_bd):
    respuesta = corregir(cliente_bd(), UUID_INEXISTENTE)
    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "measurement_not_found"


def test_corregir_medicion_de_paciente_desactivada_404(cliente_bd):
    cliente = cliente_bd()
    pid = paciente(cliente)
    original = medir(cliente, pid)
    cliente.delete(f"{PACIENTES}/{pid}")
    assert corregir(cliente, original["measurement"]["id"]).status_code == 404


def test_correccion_invalida_422_sin_escribir(cliente_bd, base_migrada):
    cliente = cliente_bd()
    pid = paciente(cliente)
    original = medir(cliente, pid)
    antes = contar(base_migrada)
    assert corregir(cliente, original["measurement"]["id"], {**ENTRADA_NORMAL, "temperature_c": 98.6}).status_code == 422
    assert contar(base_migrada) == antes


def test_corregir_audita_correccion_y_prediccion(cliente_bd, base_migrada):
    cliente = cliente_bd()
    pid = paciente(cliente)
    original = medir(cliente, pid)
    nueva = corregir(cliente, original["measurement"]["id"]).json()

    ultimas = filas(base_migrada, "SELECT action, entity_id FROM gynfem.audit_log ORDER BY id")[-2:]
    assert ultimas == [
        ("clinical_measurement.correct", uuid.UUID(nueva["measurement"]["id"])),
        ("prediction.create", uuid.UUID(nueva["prediction"]["id"])),
    ]


def test_respuestas_de_mediciones_sin_campos_internos(cliente_bd):
    cliente = cliente_bd()
    pid = paciente(cliente)
    creada = medir(cliente, pid)
    corregida = corregir(cliente, creada["measurement"]["id"])
    textos = [
        json.dumps(creada),
        corregida.text,
        cliente.get(f"{PACIENTES}/{pid}/measurements").text,
        cliente.get(f"/api/v1/predictions/{creada['prediction']['id']}").text,
    ]
    for texto in textos:
        for campo in CAMPOS_INTERNOS:
            assert campo not in texto, campo


def test_la_trazabilidad_se_relee_exacta_con_extra_float_digits_de_supabase(cliente_bd, espia, modelo_espiado, base_migrada, servidor_pg):
    """Supabase fija `extra_float_digits = 0`: sin corregirlo, un `float8` se lee con
    15 dígitos (6.11111111111111 en vez de 6.111111111111111). Hallazgo de la
    verificación contra la base real de la Fase 10."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict

    base = conninfo_to_dict(base_migrada)["dbname"]
    with psycopg.connect(servidor_pg, autocommit=True) as admin:
        admin.execute(sql.SQL("ALTER DATABASE {} SET extra_float_digits = 0").format(sql.Identifier(base)))

    cliente = cliente_bd(modelo=modelo_espiado)
    pid = paciente(cliente)
    creada = medir(cliente, pid, ENTRADA_EXTRAPOLADA)
    detalle = cliente.get(f"/api/v1/predictions/{creada['prediction']['id']}").json()
    listado = cliente.get(f"{PACIENTES}/{pid}/measurements").json()["items"][0]

    with psycopg.connect(base_migrada) as c:
        assert c.execute("SHOW extra_float_digits").fetchone() == ("0",), "control: la base imita a Supabase"
    assert list(detalle["model_input"].values()) == [float(v) for v in espia.llamadas[0].iloc[0]]
    assert detalle["input"] == {c: float(v) for c, v in ENTRADA_EXTRAPOLADA.items()}
    assert detalle["model_input"]["fasting_glucose_mmol_l"] == 110 / 18
    assert {c: listado[c] for c in CAMPOS_CLINICOS} == {c: float(v) for c, v in ENTRADA_EXTRAPOLADA.items()}
