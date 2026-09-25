"""Petición y respuestas de la predicción (`docs/API_SPEC.md`, Sección 3).

La petición aplica el nivel a de la validación: los límites fisiológicos se
leen de `app/services/clinical_limits.py`, su única fuente. Además:

- solo números (`strict`): ni texto, ni booleanos, ni nulos;
- sin `NaN` ni infinito;
- sin campos extra: un dato que no sea una de las 8 variables no entra;
- la diastólica debe ser menor que la sistólica.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from app.services.clinical_limits import PHYSIOLOGICAL_LIMITS


def _medida(campo: str, descripcion: str) -> object:
    limite = PHYSIOLOGICAL_LIMITS[campo]
    return Annotated[float, Field(ge=limite.min, le=limite.max, description=descripcion)]


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    age_years: _medida("age_years", "Edad en años")
    temperature_c: _medida("temperature_c", "Temperatura en °C")
    heart_rate_bpm: _medida("heart_rate_bpm", "Frecuencia cardiaca en lpm")
    systolic_bp_mmhg: _medida("systolic_bp_mmhg", "Presión sistólica en mmHg")
    diastolic_bp_mmhg: _medida("diastolic_bp_mmhg", "Presión diastólica en mmHg")
    bmi_kg_m2: _medida("bmi_kg_m2", "IMC en kg/m²")
    hba1c_percent: _medida("hba1c_percent", "HbA1c en % (NGSP)")
    fasting_glucose_mg_dl: _medida("fasting_glucose_mg_dl", "Glucosa en ayunas en mg/dl")

    @model_validator(mode="after")
    def _diastolica_menor_que_sistolica(self) -> "PredictionRequest":
        if self.diastolic_bp_mmhg >= self.systolic_bp_mmhg:
            raise PydanticCustomError(
                "diastolic_not_below_systolic", "La diastólica debe ser menor que la sistólica."
            )
        return self


class ExtrapolationWarningOut(BaseModel):
    field: str
    direction: Literal["below", "above"]
    unit: str
    training_min: float
    training_max: float
    message: str


class Probabilities(BaseModel):
    high: float
    mid: float
    low: float


class PredictionResponse(BaseModel):
    risk_level: Literal["high", "mid", "low"]
    probabilities: Probabilities
    extrapolation_warnings: list[ExtrapolationWarningOut]
    clinical_disclaimer: str
    #: Las 8 variables recibidas, en unidad clínica.
    input: dict[str, float]
    #: El vector que entró al modelo, en unidades del dataset y en su orden.
    model_input: dict[str, float]
    model_version: str
    conversion_schema_version: str
    predicted_at: datetime


class Range(BaseModel):
    min: float
    max: float


class PhysiologicalLimitsOut(Range):
    status: Literal["provisional", "validated"]
    rationale: str


class FieldSchema(BaseModel):
    name: str
    unit: str
    model_feature: str
    model_unit: str
    physiological_limits: PhysiologicalLimitsOut
    training_range: Range
    training_range_model_units: Range


class PredictionSchemaResponse(BaseModel):
    model_version: str
    conversion_schema_version: str
    fields: list[FieldSchema]
