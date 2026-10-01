"""Limitaciones que acompañan siempre a las métricas del modelo (HU010).

Una exactitud sin su contexto es engañosa para un usuario clínico: cada
limitación dice qué significa una cifra y qué **no** significa, en lenguaje
para un médico. El texto fue aprobado en la Fase 16 y un test lo fija palabra
por palabra (`tests/api/test_api_model_metrics.py`).

- **Ninguna cifra se escribe a mano**: salen de `model_metadata.json`,
  `feature_ranges.json` y `training_metrics.json`, y se pasan aquí ya leídas.
  Las únicas constantes son dos umbrales clínicos externos, citados en
  `training_report.md`, Sección 11.1; un test comprueba que constan allí.
- En la prosa, las cifras van redondeadas y con **coma decimal**; los valores
  exactos viajan en los campos estructurados de la misma respuesta.
- Cada limitación cita la sección del artefacto de la que sale (`sources`).
  Las citas son texto: la aplicación nunca lee un Markdown.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from app.services.prediction import CLINICAL_DISCLAIMER
from app.services.unit_conversion import model_to_clinical

#: Umbrales clínicos externos citados en `training_report.md`, Sección 11.1.
UMBRAL_OBESIDAD_IMC = 30
UMBRAL_DIABETES_MMOL_MOL = 48

#: Etiquetas de clase del dataset (`ML_SPEC.md`, Sección 9.6).
ALTO, MEDIO, BAJO = "high risk", "mid risk", "low risk"

_REPORTE = "reports/ml/training_report.md"
_METADATA = "models/model_metadata.json"
_RANGOS = "models/feature_ranges.json"
_METRICAS = "reports/ml/training_metrics.json"

_FINAL_DEL_ERROR_GRAVE = "que no apareciera en esta prueba no garantiza que no ocurra en la práctica."
_FINAL_DE_LA_BANDA = (
    "No se ha comprobado si el modelo aprendió esa asociación como una regla. Una temperatura en ese rango "
    "no genera aviso, porque está dentro de lo que el modelo vio."
)


def decimal(valor: float, decimales: int) -> str:
    """Una cifra para la prosa: redondeada y con coma decimal (98,8)."""
    return f"{valor:.{decimales}f}".replace(".", ",")


def conteos_de_alto_riesgo(labels: Sequence[str], matriz: Sequence[Sequence[int]]) -> dict[str, int]:
    """Qué predijo el modelo para los casos reales de riesgo alto.

    La fila y las columnas se localizan por las etiquetas del artefacto: su
    orden no es el de severidad y nunca se supone (`ML_SPEC.md`, Sección 9.6).
    """
    fila = matriz[labels.index(ALTO)]
    return {
        "total": sum(fila),
        "identificados": fila[labels.index(ALTO)],
        "como_medio": fila[labels.index(MEDIO)],
        "como_bajo": fila[labels.index(BAJO)],
    }


def _limitacion(code: str, title: str, message: str, *sources: str) -> dict[str, Any]:
    return {"code": code, "title": title, "message": message, "sources": list(sources)}


def _alcance(evaluacion: Mapping[str, Any], detalle: Mapping[str, Any] | None) -> dict[str, Any]:
    if detalle is not None:
        sobre = f"sobre {detalle['test_rows']} casos apartados del mismo conjunto de datos público"
    elif "test_size" in evaluacion:
        sobre = f"sobre el {decimal(evaluacion['test_size'] * 100, 0)} % de los casos del mismo conjunto de datos público"
    else:
        sobre = "sobre casos apartados del mismo conjunto de datos público"
    return _limitacion(
        "metrics_scope", "Qué miden estas cifras",
        f"Estas métricas se calcularon una sola vez, {sobre} con el que se entrenó el modelo. Indican qué tan "
        "bien reproduce el modelo las etiquetas de ese conjunto. No indican qué tan bien acierta con las "
        "pacientes de GynFem: eso no se ha medido.",
        f"{_METADATA}: metrics_summary.source, split.test_size",
        f"{_METRICAS}: variants.<variante>.split.test_rows",
        f"{_REPORTE}, Sección 4",
    )


def _exactitud(metricas: Mapping[str, Any]) -> dict[str, Any] | None:
    if "accuracy" not in metricas:
        return None
    porcentaje = decimal(metricas["accuracy"] * 100, 1)
    return _limitacion(
        "accuracy_meaning", "Qué significa la exactitud",
        f"Una exactitud de {porcentaje} % significa que, en esos casos de prueba, el modelo coincidió con la "
        f"etiqueta del conjunto de datos en esa proporción. No significa que {porcentaje} de cada 100 pacientes "
        "suyas recibirán la clasificación correcta, ni es la probabilidad de que una predicción concreta sea "
        "acertada.",
        f"{_METADATA}: metrics_summary.accuracy",
        f"{_REPORTE}, Sección 5",
    )


def _errores_de_alto_riesgo(metricas: Mapping[str, Any], detalle: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if detalle is not None:
        conteos = conteos_de_alto_riesgo(detalle["labels"], detalle["confusion_matrix"])
        mensaje = (
            f"De los {conteos['total']} casos de prueba etiquetados como riesgo alto, el modelo identificó "
            f"{conteos['identificados']}; los otros {conteos['como_medio']} los clasificó como riesgo medio y "
            f"{conteos['como_bajo']} como riesgo bajo. Clasificar un riesgo alto como bajo es el error más grave "
            f"posible: {_FINAL_DEL_ERROR_GRAVE}"
        )
    elif "high_to_low_errors" in metricas:
        mensaje = (
            f"En los casos de prueba, el modelo clasificó como riesgo bajo {metricas['high_to_low_errors']} casos "
            f"etiquetados como riesgo alto. Es el error más grave posible: {_FINAL_DEL_ERROR_GRAVE}"
        )
    else:
        return None
    return _limitacion(
        "high_risk_errors", "Errores en los casos de alto riesgo", mensaje,
        f"{_METADATA}: metrics_summary.high_to_low_errors",
        f"{_METRICAS}: variants.<variante>.held_out_test.labels, confusion_matrix",
        f"{_REPORTE}, Secciones 5 y 5.1",
    )


def _rango_estrecho(rangos: Mapping[str, tuple[float, float]]) -> dict[str, Any]:
    imc_max = rangos["bmi_kg_m2"][1]
    hba1c_max = rangos["hba1c_mmol_mol"][1]
    edad_min, edad_max = rangos["age_years"]
    return _limitacion(
        "narrow_training_range", "El modelo solo conoce un rango estrecho de valores",
        "El modelo solo vio valores dentro de los rangos de la tabla que acompaña a este texto. Fuera de ellos, "
        "la predicción no tiene respaldo en los datos. En particular: nunca vio una gestante con obesidad (el "
        f"IMC máximo que vio fue {decimal(imc_max, 1)} kg/m²; la obesidad empieza en {UMBRAL_OBESIDAD_IMC}); la "
        f"HbA1c máxima que vio fue {decimal(hba1c_max, 1)} mmol/mol "
        f"(≈{decimal(model_to_clinical('hba1c_mmol_mol', hba1c_max), 1)} %), apenas por encima del umbral "
        f"diagnóstico de diabetes ({UMBRAL_DIABETES_MMOL_MOL} mmol/mol); y solo vio edades entre "
        f"{decimal(edad_min, 0)} y {decimal(edad_max, 0)} años. El sistema avisa cuando un valor queda fuera de "
        "rango, pero igual entrega una predicción: en ese caso debe leerse con especial cautela.",
        f"{_RANGOS}: features",
        f"{_REPORTE}, Sección 11.1",
    )


def _banda_de_temperatura_baja(ablacion: Mapping[str, Any] | None) -> dict[str, Any]:
    if ablacion is not None:
        minimo_f, maximo_f = ablacion["band_f"]
        minimo_c, maximo_c = (model_to_clinical("temperature_f", extremo) for extremo in (minimo_f, maximo_f))
        inicio = (
            f"En el conjunto de datos, todos los casos con temperatura entre {decimal(minimo_c, 1)} y "
            f"{decimal(maximo_c, 1)} °C ({decimal(minimo_f, 1)}–{decimal(maximo_f, 1)} °F) estaban etiquetados "
            f"como riesgo alto; {ablacion['rows_removed']} de ellos se usaron para entrenar."
        )
    else:
        inicio = (
            "En el conjunto de datos, todos los casos con temperatura muy baja estaban etiquetados como riesgo alto."
        )
    return _limitacion(
        "low_temperature_band", "Temperaturas muy bajas", f"{inicio} {_FINAL_DE_LA_BANDA}",
        f"{_METRICAS}: variants.<variante>.checks.hypothermia_ablation.band_f, rows_removed",
        f"{_REPORTE}, Sección 7.5",
    )


def build_limitations(
    *,
    evaluacion: Mapping[str, Any],
    metricas: Mapping[str, Any],
    rangos: Mapping[str, tuple[float, float]],
    detalle: Mapping[str, Any] | None,
    ablacion: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Las limitaciones, en orden. Van siempre, haya o no detalle.

    Una limitación que explica una cifra solo se omite si esa cifra no existe en
    los artefactos y, por tanto, tampoco se publica.
    """
    limitaciones = [
        _alcance(evaluacion, detalle),
        _exactitud(metricas),
        _errores_de_alto_riesgo(metricas, detalle),
        _rango_estrecho(rangos),
        _limitacion(
            "dataset_not_local", "Los datos no son de GynFem",
            "El modelo se entrenó con un conjunto de datos público de otra población, con otros instrumentos y "
            "otros criterios de etiquetado. No se entrenó ni se validó con pacientes de GynFem ni de ninguna otra "
            "institución.",
            f"{_REPORTE}, Sección 11.2",
        ),
        _limitacion(
            "labels_not_verified", "Las etiquetas no son diagnósticos verificados",
            "El modelo aprendió a reproducir la categoría de riesgo que traía el conjunto de datos original, que "
            "no es un diagnóstico confirmado de forma independiente. Si ese criterio tenía sesgos, el modelo los "
            "reproduce.",
            f"{_REPORTE}, Sección 11.2",
        ),
        _limitacion(
            "variant_selection", "Las cifras pueden ser algo optimistas",
            "Antes de entrenar el modelo final se prepararon dos versiones de los datos y se eligió una. La "
            "elección se hizo con los datos de entrenamiento, sin consultar los casos de prueba, pero escoger la "
            "mejor de dos opciones tiende a favorecer ligeramente a la elegida. Por eso estas cifras pueden ser "
            "algo optimistas.",
            f"{_REPORTE}, Secciones 9 y 11.2",
            f"{_METRICAS}: production.basis",
        ),
        _banda_de_temperatura_baja(ablacion),
        _limitacion(
            "clinical_disclaimer", "Apoyo, no diagnóstico", CLINICAL_DISCLAIMER,
            "docs/SECURITY.md, Sección 4, advertencia 1",
        ),
    ]
    return [limitacion for limitacion in limitaciones if limitacion is not None]
