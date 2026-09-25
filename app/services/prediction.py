"""Servicio de predicción: la lógica de negocio de HU006, independiente de HTTP.

Recibe las 8 variables en unidad clínica ya validadas en el nivel a (límites
fisiológicos, `app/schemas/prediction.py`) y hace el resto:

1. convierte a las unidades del dataset (`app/services/unit_conversion.py`);
2. arma el vector en el orden exacto del contrato del modelo;
3. predice con `predict_proba` y asigna cada probabilidad a su clase por
   nombre (el orden de `classes_` no es el de severidad);
4. emite un aviso de extrapolación (nivel b) por cada variable fuera del rango
   de entrenamiento.

El nivel b compara la entrada clínica con el rango de entrenamiento ya
convertido a unidad clínica: son los mismos números que publica
`/prediction/schema`, así que el frontend y el backend nunca discrepan en un
extremo por un error de redondeo de la conversión.

Nada se guarda: el resultado se devuelve y se descarta (la persistencia llega
en la Fase 10).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import pandas as pd

from app.services.clinical_limits import PHYSIOLOGICAL_LIMITS
from app.services.model_loader import LoadedModel
from app.services.unit_conversion import (
    CLINICAL_FIELDS,
    ClinicalField,
    CONVERSION_SCHEMA_VERSION,
    model_to_clinical,
    to_model_units,
)

#: Advertencia clínica obligatoria de toda predicción (HU007). Único lugar del
#: código con este texto.
CLINICAL_DISCLAIMER = (
    "Herramienta de apoyo a la decisión clínica. No es un diagnóstico y no sustituye "
    "el criterio del profesional de salud."
)

#: Clase del modelo → nivel de riesgo publicado.
RISK_LEVELS = {"high risk": "high", "mid risk": "mid", "low risk": "low"}

Direction = Literal["below", "above"]

#: Mensaje fijo por dirección. Sin números: el frontend los toma de los campos
#: del aviso. Fuera del rango, el Random Forest trata cualquier valor como el
#: extremo más cercano (decisión C), así que el aviso no gradúa el alejamiento.
EXTRAPOLATION_MESSAGES: dict[Direction, str] = {
    "below": (
        "Valor por debajo del rango de entrenamiento. Para el modelo, cualquier valor por "
        "debajo del mínimo equivale al mínimo: la predicción no refleja cuánto se aleja."
    ),
    "above": (
        "Valor por encima del rango de entrenamiento. Para el modelo, cualquier valor por "
        "encima del máximo equivale al máximo: la predicción no refleja cuánto se aleja."
    ),
}


@dataclass(frozen=True)
class ExtrapolationWarning:
    field: str
    direction: Direction
    unit: str
    training_min: float
    training_max: float
    message: str


@dataclass(frozen=True)
class PredictionResult:
    risk_level: str
    probabilities: dict[str, float]
    extrapolation_warnings: list[ExtrapolationWarning]
    input: dict[str, float]
    model_input: dict[str, float]
    model_version: str
    conversion_schema_version: str
    predicted_at: datetime
    clinical_disclaimer: str = CLINICAL_DISCLAIMER


class PredictionService:
    def __init__(self, model: LoadedModel) -> None:
        self._model = model
        #: Rango de entrenamiento por campo clínico, en unidad clínica.
        self._rangos_clinicos = {
            campo.name: tuple(
                model_to_clinical(campo.model_feature, v)
                for v in model.training_ranges[campo.model_feature]
            )
            for campo in CLINICAL_FIELDS
        }

    def predict(self, clinical: Mapping[str, float]) -> PredictionResult:
        entrada = {campo.name: clinical[campo.name] for campo in CLINICAL_FIELDS}
        convertida = to_model_units(entrada)
        vector = {feature: convertida[feature] for feature in self._model.feature_order}
        X = pd.DataFrame([vector], columns=list(self._model.feature_order))

        fila = self._model.pipeline.predict_proba(X)[0]
        probabilidades = {
            RISK_LEVELS[clase]: float(p) for clase, p in zip(self._model.classes, fila, strict=True)
        }
        # Argmax en el orden de `classes_`, igual que `predict`: un empate se
        # resuelve a favor de la clase que aparece antes en ese orden.
        clase_predicha = self._model.classes[int(fila.argmax())]

        return PredictionResult(
            risk_level=RISK_LEVELS[clase_predicha],
            probabilities=probabilidades,
            extrapolation_warnings=self._avisos(entrada),
            input=entrada,
            model_input=vector,
            model_version=self._model.version,
            conversion_schema_version=CONVERSION_SCHEMA_VERSION,
            predicted_at=datetime.now(UTC),
        )

    def _avisos(self, entrada: Mapping[str, float]) -> list[ExtrapolationWarning]:
        avisos = []
        for campo in sorted(CLINICAL_FIELDS, key=self._posicion):
            minimo, maximo = self._rangos_clinicos[campo.name]
            valor = entrada[campo.name]
            if minimo <= valor <= maximo:
                continue
            direccion: Direction = "below" if valor < minimo else "above"
            avisos.append(
                ExtrapolationWarning(
                    field=campo.name,
                    direction=direccion,
                    unit=campo.unit,
                    training_min=minimo,
                    training_max=maximo,
                    message=EXTRAPOLATION_MESSAGES[direccion],
                )
            )
        return avisos

    def _posicion(self, campo: ClinicalField) -> int:
        return self._model.feature_order.index(campo.model_feature)

    def schema(self) -> dict:
        """Por campo: unidad, límites fisiológicos y rango de entrenamiento en ambas unidades."""
        campos = []
        for campo in sorted(CLINICAL_FIELDS, key=self._posicion):
            limite = PHYSIOLOGICAL_LIMITS[campo.name]
            minimo, maximo = self._model.training_ranges[campo.model_feature]
            clinico_min, clinico_max = self._rangos_clinicos[campo.name]
            campos.append(
                {
                    "name": campo.name,
                    "unit": campo.unit,
                    "model_feature": campo.model_feature,
                    "model_unit": campo.model_unit,
                    "physiological_limits": {
                        "min": limite.min,
                        "max": limite.max,
                        "status": limite.status,
                        "rationale": limite.rationale,
                    },
                    "training_range": {"min": clinico_min, "max": clinico_max},
                    "training_range_model_units": {"min": minimo, "max": maximo},
                }
            )
        return {
            "model_version": self._model.version,
            "conversion_schema_version": CONVERSION_SCHEMA_VERSION,
            "fields": campos,
        }
