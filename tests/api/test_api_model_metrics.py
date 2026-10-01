"""HU010: métricas reales del modelo, publicadas desde los artefactos de la Fase 6.

Nada se recalcula ni se entrena: el resumen sale de `models/model_metadata.json`,
los rangos de `models/feature_ranges.json` y el detalle de
`reports/ml/training_metrics.json`. Los tests leen esos mismos archivos y
comparan con igualdad exacta. Las limitaciones van siempre en la respuesta: una
exactitud sin su contexto es engañosa para un usuario clínico.

`reports/ml/training_report.md` solo se lee aquí, nunca en ejecución.
"""

import ast
import copy
import json
import re

import pytest

from .api_constantes import FEATURE_RANGES_JSON, METADATA_JSON, REPO_ROOT

METRICAS = "/api/v1/model/metrics"
TRAINING_METRICS_JSON = REPO_ROOT / "reports" / "ml" / "training_metrics.json"
TRAINING_REPORT_MD = REPO_ROOT / "reports" / "ml" / "training_report.md"

CLAVES_RAIZ = {"model", "evaluation", "metrics", "training_ranges", "detail", "detail_unavailable_reason", "limitations"}
CLAVES_DETALLE = {"test_rows", "labels", "confusion_matrix", "per_class", "procedure_estimate"}
CLAVES_LIMITACION = {"code", "title", "message", "sources"}
CODIGOS = [
    "metrics_scope", "accuracy_meaning", "high_risk_errors", "narrow_training_range", "dataset_not_local",
    "labels_not_verified", "variant_selection", "low_temperature_band", "clinical_disclaimer",
]
RESUMEN = ("accuracy", "f1_macro", "precision_macro", "recall_macro")


def metadata() -> dict:
    return json.loads(METADATA_JSON.read_text(encoding="utf-8"))


def entrenamiento() -> dict:
    return json.loads(TRAINING_METRICS_JSON.read_text(encoding="utf-8"))


def variante() -> dict:
    return entrenamiento()["variants"][metadata()["variant"]]


def mensajes(cuerpo: dict) -> dict[str, str]:
    return {limitacion["code"]: limitacion["message"] for limitacion in cuerpo["limitations"]}


@pytest.fixture
def con_metricas(tmp_path, configurar, crear_cliente):
    """Cliente cuya aplicación lee una copia alterada de `training_metrics.json`.

    `alterar` recibe el dict y lo modifica en sitio; `contenido` escribe ese texto
    tal cual; sin ninguno, la ruta apunta a un archivo que no existe.
    """

    def _crear(alterar=None, contenido: str | None = None, **kwargs):
        ruta = tmp_path / "training_metrics.json"
        if alterar is not None:
            datos = entrenamiento()
            alterar(datos)
            contenido = json.dumps(datos, ensure_ascii=False)
        if contenido is not None:
            ruta.write_text(contenido, encoding="utf-8")
        configurar(training_metrics_file=str(ruta))
        return crear_cliente(**kwargs)

    return _crear


@pytest.fixture
def con_metadata(copiar_modelo, crear_cliente):
    """Cliente cuyo modelo se cargó de una copia de `models/` con el metadata alterado."""

    def _crear(alterar, **kwargs):
        from app.services.model_loader import load_model

        return crear_cliente(modelo=load_model(copiar_modelo(metadata=alterar)), **kwargs)

    return _crear


# --- Acceso --------------------------------------------------------------------------------


@pytest.mark.parametrize("rol", ["medico", "administrador"])
def test_medico_y_administrador_ven_las_metricas(rol, crear_cliente):
    respuesta = crear_cliente(rol=rol).get(METRICAS)

    assert respuesta.status_code == 200, respuesta.text
    assert set(respuesta.json()) == CLAVES_RAIZ


def test_sin_token_401(crear_cliente):
    respuesta = crear_cliente(rol=None).get(METRICAS)

    assert respuesta.status_code == 401
    assert "accuracy" not in respuesta.text


# --- El resumen sale de model_metadata.json -----------------------------------------------------


def test_las_metricas_son_exactamente_las_del_metadata(cliente):
    cuerpo = cliente.get(METRICAS).json()
    resumen = metadata()["metrics_summary"]

    # Igualdad exacta de floats: el mismo número que el artefacto, sin redondear.
    assert cuerpo["metrics"] == {
        "accuracy": resumen["accuracy"],
        "f1_macro": resumen["f1_macro"],
        "precision_macro": resumen["precision_macro"],
        "recall_macro": resumen["recall_macro"],
        "high_to_low_errors": resumen["high_to_low_errors"],
    }
    assert cuerpo["metrics"]["accuracy"] == 0.9877049180327869, "control: el test lee el artefacto versionado"


def test_el_modelo_y_la_evaluacion_son_los_del_metadata(cliente):
    cuerpo = cliente.get(METRICAS).json()
    m = metadata()

    assert cuerpo["model"] == {
        "model_version": m["model_version"], "algorithm": m["algorithm"],
        "trained_at": m["created_at"], "variant": m["variant"],
    }
    assert cuerpo["evaluation"] == {
        "source": m["metrics_summary"]["source"], "dataset_rows": m["dataset"]["rows"],
        "training_rows": m["training_rows"], "test_size": m["split"]["test_size"],
        "stratified": m["split"]["stratified"],
    }


def test_las_metricas_siguen_al_artefacto_y_no_a_una_constante(con_metadata):
    def alterar(m):
        m["metrics_summary"]["accuracy"] = 0.5
        m["metrics_summary"]["high_to_low_errors"] = 3
        m["training_rows"] = 1234

    cuerpo = con_metadata(alterar).get(METRICAS).json()

    assert cuerpo["metrics"]["accuracy"] == 0.5
    assert cuerpo["metrics"]["high_to_low_errors"] == 3
    assert cuerpo["evaluation"]["training_rows"] == 1234
    assert "Una exactitud de 50,0 %" in mensajes(cuerpo)["accuracy_meaning"]
    assert "98,8" not in json.dumps(cuerpo, ensure_ascii=False)


@pytest.mark.parametrize("clave", ["recall_macro", "accuracy", "high_to_low_errors"])
def test_una_cifra_ausente_del_artefacto_se_omite(clave, con_metadata):
    cuerpo = con_metadata(lambda m: m["metrics_summary"].pop(clave)).get(METRICAS).json()

    assert clave not in cuerpo["metrics"], "ni null ni cero: la clave no aparece"
    assert set(cuerpo["metrics"]) == {*RESUMEN, "high_to_low_errors"} - {clave}
    assert None not in cuerpo["metrics"].values()


def test_un_dato_del_modelo_ausente_se_omite(con_metadata):
    def alterar(m):
        del m["algorithm"]
        del m["split"]["stratified"]
        del m["dataset"]

    cuerpo = con_metadata(alterar).get(METRICAS).json()

    assert set(cuerpo["model"]) == {"model_version", "trained_at", "variant"}
    assert set(cuerpo["evaluation"]) == {"source", "training_rows", "test_size"}


# --- Los rangos salen de feature_ranges.json -----------------------------------------------------


def test_los_rangos_de_entrenamiento_son_los_de_feature_ranges(cliente):
    cuerpo = cliente.get(METRICAS).json()
    rangos = json.loads(FEATURE_RANGES_JSON.read_text(encoding="utf-8"))["features"]
    esquema = {campo["model_feature"]: campo for campo in cliente.get("/api/v1/prediction/schema").json()["fields"]}

    assert [r["feature"] for r in cuerpo["training_ranges"]] == [
        f["name"] for f in sorted(metadata()["features"], key=lambda f: f["position"])
    ]
    for rango in cuerpo["training_ranges"]:
        assert set(rango) == {
            "feature", "unit", "min", "max", "clinical_field", "clinical_unit", "clinical_min", "clinical_max",
        }
        del_artefacto, del_esquema = rangos[rango["feature"]], esquema[rango["feature"]]
        assert (rango["min"], rango["max"], rango["unit"]) == (
            del_artefacto["min"], del_artefacto["max"], del_artefacto["unit"]
        )
        # En unidad clínica, los mismos extremos que publica /prediction/schema y aplica /predict.
        assert (rango["clinical_field"], rango["clinical_unit"]) == (del_esquema["name"], del_esquema["unit"])
        assert (rango["clinical_min"], rango["clinical_max"]) == (
            del_esquema["training_range"]["min"], del_esquema["training_range"]["max"]
        )


def test_los_rangos_siguen_a_feature_ranges(copiar_modelo, crear_cliente):
    from app.services.model_loader import load_model

    modelo = load_model(copiar_modelo(rangos=lambda r: r["features"]["bmi_kg_m2"].update(max=26.5)))
    cuerpo = crear_cliente(modelo=modelo).get(METRICAS).json()

    imc = next(r for r in cuerpo["training_ranges"] if r["feature"] == "bmi_kg_m2")
    assert imc["max"] == imc["clinical_max"] == 26.5
    assert "el IMC máximo que vio fue 26,5 kg/m²" in mensajes(cuerpo)["narrow_training_range"]


# --- El detalle sale de training_metrics.json ----------------------------------------------------


def test_el_detalle_coincide_con_training_metrics(cliente):
    cuerpo = cliente.get(METRICAS).json()
    v = variante()

    assert cuerpo["detail_unavailable_reason"] is None
    detalle = cuerpo["detail"]
    assert set(detalle) == CLAVES_DETALLE
    assert detalle["test_rows"] == v["split"]["test_rows"] == 1220
    assert detalle["labels"] == v["held_out_test"]["labels"]
    assert detalle["confusion_matrix"] == v["held_out_test"]["confusion_matrix"]
    assert detalle["per_class"] == v["held_out_test"]["per_class"]


def test_la_cv_anidada_va_rotulada_como_estimacion_del_procedimiento(cliente):
    cuerpo = cliente.get(METRICAS).json()
    anidada = variante()["nested_cv"]

    estimacion = cuerpo["detail"]["procedure_estimate"]
    assert set(estimacion) == {"label", "metric", "mean", "std", "outer_folds", "inner_folds", "description"}
    assert (estimacion["metric"], estimacion["mean"], estimacion["std"]) == (
        anidada["metric"], anidada["mean"], anidada["std"]
    )
    assert (estimacion["outer_folds"], estimacion["inner_folds"]) == (anidada["outer_folds"], anidada["inner_folds"])
    assert estimacion["label"] == "Estimación del procedimiento (validación cruzada anidada)"
    assert estimacion["description"] == (
        "Estimación del procedimiento (validación cruzada anidada): 0,991 ± 0,004 de F1 macro. Estima cómo rinde "
        "el método completo de entrenamiento al repetirlo sobre distintas particiones de los datos de "
        "entrenamiento. No es el rendimiento del modelo entregado ni el que cabe esperar con pacientes reales."
    )
    # No se mezcla con las métricas de rendimiento.
    assert anidada["mean"] not in cuerpo["metrics"].values()


def test_sin_la_variable_el_endpoint_usa_la_ruta_del_repositorio(configurar, cliente, monkeypatch):
    """Render no necesita una variable nueva: el valor por defecto es la ruta dentro del repositorio."""
    import os

    from app.core.config import load_settings

    assert "GYNFEM_TRAINING_METRICS_FILE" not in os.environ
    assert load_settings().training_metrics_file == TRAINING_METRICS_JSON

    cuerpo = cliente.get(METRICAS).json()

    assert cuerpo["detail"] is not None
    assert cuerpo["detail"]["confusion_matrix"] == variante()["held_out_test"]["confusion_matrix"]


def test_una_ruta_relativa_se_resuelve_desde_la_raiz_del_repositorio(configurar):
    from app.core.config import load_settings

    configurar(environment="development", cors_origins="http://localhost:5173",
               training_metrics_file="reports/ml/training_metrics.json")

    assert load_settings().training_metrics_file == TRAINING_METRICS_JSON


def test_si_falta_el_archivo_del_detalle_la_api_arranca_y_detail_es_null(con_metricas):
    respuesta = con_metricas().get(METRICAS)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert "detail" in cuerpo and cuerpo["detail"] is None
    assert cuerpo["detail_unavailable_reason"] == "training_metrics_missing"
    # El resumen no depende del detalle.
    assert cuerpo["metrics"]["accuracy"] == metadata()["metrics_summary"]["accuracy"]


def _otra_exactitud(d):
    d["variants"]["clean"]["held_out_test"]["accuracy"] = 0.99


def _otra_version(d):
    d["model_version"] = "9.9.9"


def _otro_error_grave(d):
    d["variants"]["clean"]["held_out_test"]["high_to_low"] = 2


def _matriz_que_no_cuadra_con_el_metadata(d):
    # Con las etiquetas cambiadas de sitio, la fila de alto riesgo es otra: 1 caso a bajo riesgo.
    d["variants"]["clean"]["held_out_test"]["labels"] = ["low risk", "high risk", "mid risk"]


@pytest.mark.parametrize(
    "alterar", [_otra_exactitud, _otra_version, _otro_error_grave, _matriz_que_no_cuadra_con_el_metadata],
    ids=["otra exactitud", "otra versión del modelo", "otro número de errores graves", "matriz con otras etiquetas"],
)
def test_si_el_detalle_no_coincide_con_el_metadata_detail_es_null(alterar, con_metricas):
    respuesta = con_metricas(alterar).get(METRICAS)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["detail"] is None
    assert cuerpo["detail_unavailable_reason"] == "training_metrics_mismatch"
    assert '"confusion_matrix":' not in respuesta.text, "la matriz no se publica; solo la cita su fuente"


def test_si_al_metadata_le_falta_una_cifra_el_detalle_no_se_puede_contrastar(con_metadata):
    cuerpo = con_metadata(lambda m: m["metrics_summary"].pop("f1_macro")).get(METRICAS).json()

    assert cuerpo["detail"] is None
    assert cuerpo["detail_unavailable_reason"] == "training_metrics_mismatch"


@pytest.mark.parametrize(
    "contenido",
    ["{esto no es json", "[1, 2, 3]", '{"model_version": "1.0.0"}', ""],
    ids=["no es JSON", "no es un objeto", "sin la variante de producción", "vacío"],
)
def test_si_el_detalle_es_ilegible_detail_es_null(contenido, con_metricas):
    respuesta = con_metricas(contenido=contenido).get(METRICAS)

    assert respuesta.status_code == 200
    assert respuesta.json()["detail"] is None
    assert respuesta.json()["detail_unavailable_reason"] == "training_metrics_invalid"


def test_un_detalle_con_estructura_rota_no_impide_arrancar(con_metricas):
    def alterar(d):
        d["variants"]["clean"]["held_out_test"]["confusion_matrix"] = [[1, 2], [3]]

    respuesta = con_metricas(alterar).get(METRICAS)

    assert respuesta.status_code == 200
    assert respuesta.json()["detail_unavailable_reason"] == "training_metrics_invalid"


# --- Las limitaciones van siempre ------------------------------------------------------------------


def test_las_limitaciones_van_siempre_y_completas(cliente):
    cuerpo = cliente.get(METRICAS).json()

    assert [limitacion["code"] for limitacion in cuerpo["limitations"]] == CODIGOS
    for limitacion in cuerpo["limitations"]:
        assert set(limitacion) == CLAVES_LIMITACION
        assert limitacion["title"].strip() and limitacion["message"].strip(), limitacion["code"]
        assert limitacion["sources"] and all(fuente.strip() for fuente in limitacion["sources"]), limitacion["code"]


def test_las_limitaciones_van_tambien_sin_detalle(con_metricas):
    cuerpo = con_metricas().get(METRICAS).json()

    assert cuerpo["detail"] is None
    assert [limitacion["code"] for limitacion in cuerpo["limitations"]] == CODIGOS
    assert all(limitacion["message"].strip() for limitacion in cuerpo["limitations"])


def test_no_hay_modo_de_pedir_solo_las_cifras(cliente, crear_cliente):
    completa = cliente.get(METRICAS).json()

    for parametros in ({"limitations": "false"}, {"fields": "metrics"}, {"only": "metrics"}, {"detail": "false"}):
        assert cliente.get(METRICAS, params=parametros).json() == completa, parametros
    from .test_auth_rbac import rutas_de

    [ruta] = [r for r in rutas_de(cliente.app) if getattr(r, "path", "") == METRICAS]
    assert ruta.dependant.query_params == [] and ruta.dependant.body_params == []
    assert ruta.methods == {"GET"}


def test_la_advertencia_clinica_es_la_de_toda_prediccion(cliente):
    from app.services.prediction import CLINICAL_DISCLAIMER

    assert mensajes(cliente.get(METRICAS).json())["clinical_disclaimer"] == CLINICAL_DISCLAIMER


# --- El texto aprobado, con las cifras de los artefactos versionados -------------------------------------

TEXTO_APROBADO = {
    "metrics_scope": (
        "Estas métricas se calcularon una sola vez, sobre 1220 casos apartados del mismo conjunto de datos "
        "público con el que se entrenó el modelo. Indican qué tan bien reproduce el modelo las etiquetas de ese "
        "conjunto. No indican qué tan bien acierta con las pacientes de GynFem: eso no se ha medido."
    ),
    "accuracy_meaning": (
        "Una exactitud de 98,8 % significa que, en esos casos de prueba, el modelo coincidió con la etiqueta del "
        "conjunto de datos en esa proporción. No significa que 98,8 de cada 100 pacientes suyas recibirán la "
        "clasificación correcta, ni es la probabilidad de que una predicción concreta sea acertada."
    ),
    "high_risk_errors": (
        "De los 412 casos de prueba etiquetados como riesgo alto, el modelo identificó 405; los otros 7 los "
        "clasificó como riesgo medio y 0 como riesgo bajo. Clasificar un riesgo alto como bajo es el error más "
        "grave posible: que no apareciera en esta prueba no garantiza que no ocurra en la práctica."
    ),
    "narrow_training_range": (
        "El modelo solo vio valores dentro de los rangos de la tabla que acompaña a este texto. Fuera de ellos, "
        "la predicción no tiene respaldo en los datos. En particular: nunca vio una gestante con obesidad (el "
        "IMC máximo que vio fue 27,9 kg/m²; la obesidad empieza en 30); la HbA1c máxima que vio fue 50,0 "
        "mmol/mol (≈6,7 %), apenas por encima del umbral diagnóstico de diabetes (48 mmol/mol); y solo vio "
        "edades entre 15 y 47 años. El sistema avisa cuando un valor queda fuera de rango, pero igual entrega "
        "una predicción: en ese caso debe leerse con especial cautela."
    ),
    "dataset_not_local": (
        "El modelo se entrenó con un conjunto de datos público de otra población, con otros instrumentos y "
        "otros criterios de etiquetado. No se entrenó ni se validó con pacientes de GynFem ni de ninguna otra "
        "institución."
    ),
    "labels_not_verified": (
        "El modelo aprendió a reproducir la categoría de riesgo que traía el conjunto de datos original, que no "
        "es un diagnóstico confirmado de forma independiente. Si ese criterio tenía sesgos, el modelo los "
        "reproduce."
    ),
    "variant_selection": (
        "Antes de entrenar el modelo final se prepararon dos versiones de los datos y se eligió una. La elección "
        "se hizo con los datos de entrenamiento, sin consultar los casos de prueba, pero escoger la mejor de dos "
        "opciones tiende a favorecer ligeramente a la elegida. Por eso estas cifras pueden ser algo optimistas."
    ),
    "low_temperature_band": (
        "En el conjunto de datos, todos los casos con temperatura entre 33,9 y 34,9 °C (93,0–94,9 °F) estaban "
        "etiquetados como riesgo alto; 36 de ellos se usaron para entrenar. No se ha comprobado si el modelo "
        "aprendió esa asociación como una regla. Una temperatura en ese rango no genera aviso, porque está "
        "dentro de lo que el modelo vio."
    ),
    "clinical_disclaimer": (
        "Herramienta de apoyo a la decisión clínica. No es un diagnóstico y no sustituye el criterio del "
        "profesional de salud."
    ),
}

TEXTO_SIN_DETALLE = {
    "metrics_scope": (
        "Estas métricas se calcularon una sola vez, sobre el 20 % de los casos del mismo conjunto de datos "
        "público con el que se entrenó el modelo. Indican qué tan bien reproduce el modelo las etiquetas de ese "
        "conjunto. No indican qué tan bien acierta con las pacientes de GynFem: eso no se ha medido."
    ),
    "high_risk_errors": (
        "En los casos de prueba, el modelo clasificó como riesgo bajo 0 casos etiquetados como riesgo alto. Es "
        "el error más grave posible: que no apareciera en esta prueba no garantiza que no ocurra en la práctica."
    ),
    "low_temperature_band": (
        "En el conjunto de datos, todos los casos con temperatura muy baja estaban etiquetados como riesgo alto. "
        "No se ha comprobado si el modelo aprendió esa asociación como una regla. Una temperatura en ese rango "
        "no genera aviso, porque está dentro de lo que el modelo vio."
    ),
}


def test_el_texto_de_cada_limitacion_es_el_aprobado(cliente):
    assert mensajes(cliente.get(METRICAS).json()) == TEXTO_APROBADO


def test_sin_detalle_las_limitaciones_usan_su_variante_sin_esas_cifras(con_metricas):
    assert mensajes(con_metricas().get(METRICAS).json()) == {**TEXTO_APROBADO, **TEXTO_SIN_DETALLE}


def test_las_cifras_en_prosa_usan_coma_decimal(cliente, con_metricas):
    for cuerpo in (cliente.get(METRICAS).json(), con_metricas().get(METRICAS).json()):
        textos = [limitacion["message"] for limitacion in cuerpo["limitations"]]
        if cuerpo["detail"] is not None:
            textos.append(cuerpo["detail"]["procedure_estimate"]["description"])
        for texto in textos:
            assert not re.search(r"\d\.\d", texto), f"punto decimal en la prosa: {texto!r}"
    con_detalle = mensajes(cliente.get(METRICAS).json())
    assert "98,8 %" in con_detalle["accuracy_meaning"]
    assert "27,9 kg/m²" in con_detalle["narrow_training_range"]
    assert "33,9 y 34,9 °C (93,0–94,9 °F)" in con_detalle["low_temperature_band"]


def test_la_coma_decimal_redondea_y_conserva_los_ceros():
    from app.services.model_limitations import decimal

    assert decimal(98.77049180327869, 1) == "98,8"
    assert decimal(50.0, 1) == "50,0"
    assert decimal(15.0, 0) == "15"
    assert decimal(0.9906143060396209, 3) == "0,991"


# --- La matriz de confusión se lee con sus etiquetas, sin suponer el orden -----------------------------------


def test_los_conteos_de_alto_riesgo_salen_de_la_fila_que_indican_las_etiquetas():
    from app.services.model_limitations import conteos_de_alto_riesgo

    prueba = variante()["held_out_test"]
    assert prueba["labels"] == ["high risk", "low risk", "mid risk"], "control: el orden del artefacto no es el de severidad"

    assert conteos_de_alto_riesgo(prueba["labels"], prueba["confusion_matrix"]) == {
        "total": 412, "identificados": 405, "como_medio": 7, "como_bajo": 0,
    }
    # La misma matriz con otras etiquetas: la fila de «alto» es otra, y los conteos, otros.
    assert conteos_de_alto_riesgo(["mid risk", "high risk", "low risk"], prueba["confusion_matrix"]) == {
        "total": 399, "identificados": 394, "como_medio": 1, "como_bajo": 4,
    }


def test_un_artefacto_con_las_clases_en_otro_orden_da_la_misma_limitacion(con_metricas):
    """Se reordenan a la vez las etiquetas y la matriz: describen la misma prueba."""

    def reordenar(d):
        prueba = d["variants"]["clean"]["held_out_test"]
        original = copy.deepcopy(prueba["confusion_matrix"])
        orden = [2, 0, 1]  # mid, high, low
        prueba["labels"] = [prueba["labels"][i] for i in orden]
        prueba["confusion_matrix"] = [[original[i][j] for j in orden] for i in orden]

    cuerpo = con_metricas(reordenar).get(METRICAS).json()

    assert cuerpo["detail"]["labels"] == ["mid risk", "high risk", "low risk"]
    assert cuerpo["detail"]["confusion_matrix"][1] == [7, 405, 0]
    assert mensajes(cuerpo)["high_risk_errors"] == TEXTO_APROBADO["high_risk_errors"]


# --- Las cifras citadas constan en su fuente (el Markdown solo se lee en tests) ---------------------------------


def seccion(titulo: str) -> str:
    texto = TRAINING_REPORT_MD.read_text(encoding="utf-8")
    inicio = texto.index(titulo)
    siguiente = re.search(r"^#{2,3} ", texto[inicio + len(titulo):], flags=re.MULTILINE)
    return texto[inicio: inicio + len(titulo) + siguiente.start()] if siguiente else texto[inicio:]


def test_los_umbrales_clinicos_citados_constan_en_el_reporte_de_entrenamiento():
    from app.services.model_limitations import UMBRAL_DIABETES_MMOL_MOL, UMBRAL_OBESIDAD_IMC

    rango_estrecho = " ".join(seccion("### 11.1 El rango de entrenamiento es estrecho").split())

    assert (UMBRAL_OBESIDAD_IMC, UMBRAL_DIABETES_MMOL_MOL) == (30, 48)
    assert "El umbral de obesidad es 30." in rango_estrecho
    assert "El umbral diagnóstico de diabetes es 48 mmol/mol" in rango_estrecho


def test_la_banda_de_temperatura_baja_consta_en_sus_fuentes(cliente):
    ablacion = variante()["checks"]["hypothermia_ablation"]
    hipotermia = " ".join(seccion("### 7.5 Ablación de las filas de hipotermia (C6)").split())

    assert (ablacion["band_f"], ablacion["rows_removed"]) == ([93.0, 94.9], 36)
    # «Todos los casos»: el reporte dice que las filas de la banda son todas de alto riesgo.
    assert "93.0–94.9 °F son todas `high risk`" in hipotermia
    assert "No** mide si el modelo aprendió la regla" in hipotermia


def test_las_demas_limitaciones_constan_en_el_reporte_de_entrenamiento():
    otras = " ".join(seccion("### 11.2 Otras limitaciones").split())

    for frase in (
        "El dataset no es de GynFem.",
        "no un diagnóstico verificado de forma independiente",
        "La elección de variante es una selección entre dos opciones.",
        "el `delta` se mide sobre la CV anidada y no sobre el test",
        "No hay validación externa",
    ):
        assert frase in otras, frase
    assert entrenamiento()["production"]["basis"] == "nested_cv"
    estimaciones = " ".join(seccion("## 4. Las tres estimaciones, y cuál es cuál").split())
    assert "Estimación insesgada del **procedimiento** completo" in estimaciones
    assert "No es el rendimiento del modelo final concreto" in estimaciones


# --- Nada se recalcula, ni se carga el modelo, ni se lee Markdown ----------------------------------------------


def test_las_metricas_no_usan_el_modelo(cliente_espiado, espia):
    assert cliente_espiado.get(METRICAS).status_code == 200
    assert espia.llamadas == []


MODULOS_DE_METRICAS = ("app/services/model_metrics.py", "app/services/model_limitations.py",
                       "app/api/v1/model_metrics.py", "app/schemas/model_metrics.py")


@pytest.mark.parametrize("modulo", MODULOS_DE_METRICAS)
def test_los_modulos_de_metricas_no_importan_nada_que_calcule(modulo):
    arbol = ast.parse((REPO_ROOT / modulo).read_text(encoding="utf-8"))
    importados = [n.module for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom) and n.module] + [
        alias.name for n in ast.walk(arbol) if isinstance(n, ast.Import) for alias in n.names
    ]

    for prohibido in ("joblib", "sklearn", "pandas", "numpy", "scripts"):
        assert not any(i == prohibido or i.startswith(prohibido + ".") for i in importados), f"{modulo} importa {prohibido}"


def test_la_aplicacion_no_lee_markdown_en_ejecucion(crear_cliente, monkeypatch):
    """Al arrancar y al responder solo se leen los JSON: las citas a `training_report.md`
    son texto, y ese archivo no se abre nunca."""
    from pathlib import Path

    leidos: list[Path] = []
    leer, abrir = Path.read_text, Path.open

    def espiar(original):
        def envoltura(self, *args, **kwargs):
            leidos.append(Path(self))
            return original(self, *args, **kwargs)

        return envoltura

    monkeypatch.setattr(Path, "read_text", espiar(leer))
    monkeypatch.setattr(Path, "open", espiar(abrir))

    assert crear_cliente().get(METRICAS).status_code == 200

    assert METADATA_JSON in leidos and TRAINING_METRICS_JSON in leidos, "control: el espía ve las lecturas"
    assert [ruta for ruta in leidos if ruta.suffix.lower() == ".md"] == []


def test_los_artefactos_no_se_modifican_al_consultar(cliente):
    antes = [ruta.read_bytes() for ruta in (METADATA_JSON, FEATURE_RANGES_JSON, TRAINING_METRICS_JSON)]

    assert cliente.get(METRICAS).status_code == 200

    assert [ruta.read_bytes() for ruta in (METADATA_JSON, FEATURE_RANGES_JSON, TRAINING_METRICS_JSON)] == antes
