"""Entrada y salida de mediciones clínicas y predicciones persistidas (HU005).

`MeasurementCreate` **hereda** de `PredictionRequest`: las mismas 8 variables
con los mismos límites fisiológicos, esquema estricto y regla diastólica <
sistólica (una sola fuente, `app/services/clinical_limits.py`). Solo añade la
hora de la medición.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError

from app.schemas.prediction import ExtrapolationWarningOut, PredictionRequest, Probabilities

#: Margen por la diferencia de reloj entre el cliente y el servidor.
TOLERANCIA_FUTURO = timedelta(minutes=5)


class MeasurementCreate(PredictionRequest):
    #: Hora de la medición, con zona horaria. Por defecto, la del servidor.
    measured_at: Annotated[AwareDatetime | None, Field(strict=False)] = None

    @field_validator("measured_at")
    @classmethod
    def _no_futura(cls, valor: datetime | None) -> datetime | None:
        if valor is not None and valor > datetime.now(UTC) + TOLERANCIA_FUTURO:
            raise PydanticCustomError("measured_at_in_future", "La hora de la medición no puede ser futura.")
        return valor


class MeasurementOut(BaseModel):
    id: UUID
    patient_id: UUID
    measured_at: datetime
    age_years: float
    temperature_c: float
    heart_rate_bpm: float
    systolic_bp_mmhg: float
    diastolic_bp_mmhg: float
    bmi_kg_m2: float
    hba1c_percent: float
    fasting_glucose_mg_dl: float


class MeasurementListItem(MeasurementOut):
    #: La predicción vigente de la medición.
    prediction_id: UUID | None


class StoredPredictionOut(BaseModel):
    """Lo que el médico necesita ver (HU007). Sin `input` ni `model_input`."""

    id: UUID
    risk_level: Literal["high", "mid", "low"]
    probabilities: Probabilities
    extrapolation_warnings: list[ExtrapolationWarningOut]
    clinical_disclaimer: str
    model_version: str
    conversion_schema_version: str
    predicted_at: datetime


class StoredPredictionDetail(StoredPredictionOut):
    """La trazabilidad completa (`docs/ML_SPEC.md` §6)."""

    measurement_id: UUID
    input: dict[str, float]
    model_input: dict[str, float]


class EvaluationOut(BaseModel):
    measurement: MeasurementOut
    prediction: StoredPredictionOut
