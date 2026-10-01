"""Métricas del modelo (HU010): se publican las obtenidas en la Fase 6, tal cual.

**Nada se entrena, se recalcula ni se predice.** Este módulo solo lee JSON:

- el **resumen** (`metrics`, `model`, `evaluation`) sale de `model_metadata.json`,
  el archivo que acompaña al modelo desplegado;
- los **rangos de entrenamiento**, de `feature_ranges.json`, ya leído y validado
  al cargar el modelo;
- el **detalle** (matriz de confusión, métricas por clase, tamaño del conjunto
  de prueba y validación cruzada anidada), de `reports/ml/training_metrics.json`.

El detalle solo se publica si **coincide** con el metadata: misma versión del
modelo, las mismas cuatro métricas macro y el mismo número de errores de riesgo
alto a bajo, también el que se lee de la matriz. Si el archivo falta, no se
puede leer o no coincide, `detail` va `null` con su motivo y la aplicación
arranca igual: una métrica de consulta no puede dejar al sistema sin predecir.

Una cifra que no está en los artefactos **se omite**: ni `null` ni cero.
Las limitaciones (`app/services/model_limitations.py`) van siempre.

Los artefactos no cambian mientras la aplicación corre, así que la respuesta se
construye una vez, al arrancar.
"""

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.services.model_limitations import ALTO, BAJO, MEDIO, build_limitations, conteos_de_alto_riesgo, decimal
from app.services.model_loader import METADATA_FILE, LoadedModel
from app.services.unit_conversion import CLINICAL_FIELDS, model_to_clinical

#: Motivos por los que `detail` va `null`.
DETALLE_AUSENTE = "training_metrics_missing"
DETALLE_ILEGIBLE = "training_metrics_invalid"
DETALLE_NO_COINCIDE = "training_metrics_mismatch"

#: Clave publicada → clave del artefacto.
_DEL_MODELO = {"model_version": "model_version", "algorithm": "algorithm", "trained_at": "created_at", "variant": "variant"}
_METRICAS = ("accuracy", "f1_macro", "precision_macro", "recall_macro", "high_to_low_errors")
#: Lo que debe coincidir entre el metadata y el detalle: clave del metadata → clave de `held_out_test`.
_CONTRASTE = {
    "accuracy": "accuracy", "f1_macro": "f1_macro", "precision_macro": "precision_macro",
    "recall_macro": "recall_macro", "high_to_low_errors": "high_to_low",
}
_POR_CLASE = ("precision", "recall", "f1", "support")

ROTULO_CV_ANIDADA = "Estimación del procedimiento (validación cruzada anidada)"
_NOMBRE_DE_METRICA = {"f1_macro": "F1 macro", "accuracy": "exactitud"}


class _NoCoincide(Exception):
    """El detalle es legible, pero no describe el modelo del metadata."""


def _presentes(origen: Any, claves: Mapping[str, str]) -> dict[str, Any]:
    """Solo las cifras que existen en el artefacto: una ausente no se publica."""
    if not isinstance(origen, dict):
        return {}
    return {publicada: origen[clave] for publicada, clave in claves.items() if origen.get(clave) is not None}


def _resumen(metadata: Mapping[str, Any]) -> tuple[dict, dict, dict]:
    resumen = metadata.get("metrics_summary")
    division = metadata.get("split")
    evaluacion = {
        **_presentes(resumen, {"source": "source"}),
        **_presentes(metadata.get("dataset"), {"dataset_rows": "rows"}),
        **_presentes(metadata, {"training_rows": "training_rows"}),
        **_presentes(division, {"test_size": "test_size", "stratified": "stratified"}),
    }
    return _presentes(metadata, _DEL_MODELO), evaluacion, _presentes(resumen, {clave: clave for clave in _METRICAS})


def _rangos(model: LoadedModel) -> list[dict[str, Any]]:
    """Los extremos de `feature_ranges.json`, en unidad del dataset y en unidad clínica."""
    por_feature = {campo.model_feature: campo for campo in CLINICAL_FIELDS}
    rangos = []
    for feature in model.feature_order:
        campo = por_feature[feature]
        minimo, maximo = model.training_ranges[feature]
        rangos.append(
            {
                "feature": feature,
                "unit": campo.model_unit,
                "min": minimo,
                "max": maximo,
                "clinical_field": campo.name,
                "clinical_unit": campo.unit,
                # La misma conversión que `/prediction/schema` y que aplica `/predict`.
                "clinical_min": model_to_clinical(feature, minimo),
                "clinical_max": model_to_clinical(feature, maximo),
            }
        )
    return rangos


def _estimacion_del_procedimiento(anidada: Mapping[str, Any]) -> dict[str, Any]:
    metrica = anidada["metric"]
    media, desviacion = float(anidada["mean"]), float(anidada["std"])
    return {
        "label": ROTULO_CV_ANIDADA,
        "metric": metrica,
        "mean": media,
        "std": desviacion,
        "outer_folds": int(anidada["outer_folds"]),
        "inner_folds": int(anidada["inner_folds"]),
        "description": (
            f"{ROTULO_CV_ANIDADA}: {decimal(media, 3)} ± {decimal(desviacion, 3)} de "
            f"{_NOMBRE_DE_METRICA.get(metrica, metrica)}. Estima cómo rinde el método completo de entrenamiento "
            "al repetirlo sobre distintas particiones de los datos de entrenamiento. No es el rendimiento del "
            "modelo entregado ni el que cabe esperar con pacientes reales."
        ),
    }


def _detalle(datos: Any, metadata: Mapping[str, Any], metricas: Mapping[str, Any]) -> tuple[dict, dict]:
    """El detalle y la ablación de temperatura baja. `_NoCoincide` si no describe este modelo;
    `KeyError`, `TypeError` o `ValueError` si su estructura no es la esperada."""
    if not isinstance(datos, dict):
        raise TypeError("no es un objeto JSON")
    variante = datos["variants"][metadata["variant"]]
    prueba = variante["held_out_test"]
    labels = [str(etiqueta) for etiqueta in prueba["labels"]]
    matriz = [[int(celda) for celda in fila] for fila in prueba["confusion_matrix"]]
    if sorted(labels) != sorted((ALTO, MEDIO, BAJO)) or [len(fila) for fila in matriz] != [len(labels)] * len(labels):
        raise ValueError("la matriz de confusión no corresponde a las tres clases")
    por_clase = {
        etiqueta: {clave: prueba["per_class"][etiqueta][clave] for clave in _POR_CLASE} for etiqueta in labels
    }

    if datos["model_version"] != metadata.get("model_version"):
        raise _NoCoincide()
    for del_metadata, del_detalle in _CONTRASTE.items():
        # Igualdad exacta: son la misma ejecución del entrenamiento o no lo son.
        if del_metadata not in metricas or prueba[del_detalle] != metricas[del_metadata]:
            raise _NoCoincide()
    if conteos_de_alto_riesgo(labels, matriz)["como_bajo"] != metricas["high_to_low_errors"]:
        raise _NoCoincide()

    filas_de_prueba = int(variante["split"]["test_rows"])
    if any(sum(fila) != por_clase[etiqueta]["support"] for etiqueta, fila in zip(labels, matriz, strict=True)):
        raise ValueError("la matriz de confusión no suma el soporte de cada clase")
    if sum(map(sum, matriz)) != filas_de_prueba:
        raise ValueError("la matriz de confusión no suma las filas de prueba")

    ablacion = variante["checks"]["hypothermia_ablation"]
    minimo_f, maximo_f = (float(extremo) for extremo in ablacion["band_f"])
    if not (math.isfinite(minimo_f) and math.isfinite(maximo_f)):
        raise ValueError("banda de temperatura no finita")
    detalle = {
        "test_rows": filas_de_prueba,
        "labels": labels,
        "confusion_matrix": matriz,
        "per_class": por_clase,
        "procedure_estimate": _estimacion_del_procedimiento(variante["nested_cv"]),
    }
    return detalle, {"band_f": (minimo_f, maximo_f), "rows_removed": int(ablacion["rows_removed"])}


def _leer_detalle(
    ruta: Path, metadata: Mapping[str, Any], metricas: Mapping[str, Any]
) -> tuple[dict | None, dict | None, str | None]:
    """`(detalle, ablación, motivo)`. Nunca lanza: sin detalle, la aplicación arranca igual."""
    try:
        texto = Path(ruta).read_text(encoding="utf-8")
    except OSError:
        return None, None, DETALLE_AUSENTE
    try:
        detalle, ablacion = _detalle(json.loads(texto), metadata, metricas)
    except _NoCoincide:
        return None, None, DETALLE_NO_COINCIDE
    except (KeyError, TypeError, ValueError, IndexError):
        return None, None, DETALLE_ILEGIBLE
    return detalle, ablacion, None


class ModelMetricsService:
    def __init__(self, model: LoadedModel, training_metrics_file: Path) -> None:
        # El contrato del metadata ya se verificó al cargar el modelo (`model_loader`).
        metadata = json.loads((model.directory / METADATA_FILE).read_text(encoding="utf-8"))
        modelo, evaluacion, metricas = _resumen(metadata)
        detalle, ablacion, motivo = _leer_detalle(training_metrics_file, metadata, metricas)
        self._respuesta = {
            "model": modelo,
            "evaluation": evaluacion,
            "metrics": metricas,
            "training_ranges": _rangos(model),
            "detail": detalle,
            "detail_unavailable_reason": motivo,
            "limitations": build_limitations(
                evaluacion=evaluacion, metricas=metricas, rangos=model.training_ranges,
                detalle=detalle, ablacion=ablacion,
            ),
        }

    def metrics(self) -> dict[str, Any]:
        return self._respuesta
