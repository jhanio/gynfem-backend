"""Salida del historial de evaluaciones de una paciente (HU008).

Cada ítem lleva la medición (las 8 variables en unidad clínica), su predicción y
si la evaluación está vigente o fue corregida. La advertencia clínica va una
vez, en la página. Sin `input` ni `model_input` (los da `GET /predictions/{id}`)
y sin ningún campo interno.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.clinical import MeasurementOut
from app.schemas.pagination import Page
from app.schemas.prediction import ExtrapolationWarningOut, Probabilities


class HistoryPredictionOut(BaseModel):
    id: UUID
    risk_level: Literal["high", "mid", "low"]
    probabilities: Probabilities
    extrapolation_warnings: list[ExtrapolationWarningOut]
    model_version: str
    conversion_schema_version: str
    predicted_at: datetime


class EvaluationHistoryItem(BaseModel):
    measurement: MeasurementOut
    prediction: HistoryPredictionOut
    #: `corrected`: una corrección posterior la sustituyó; su predicción se conserva intacta.
    status: Literal["current", "corrected"]


class EvaluationHistoryPage(Page[EvaluationHistoryItem]):
    #: Advertencia clínica obligatoria (HU007): toda vista que muestre un riesgo la lleva.
    clinical_disclaimer: str
