"""Salida del reporte de una evaluación (HU009).

Datos estructurados: el frontend compone la vista de impresión. Contiene solo lo
ya almacenado más la advertencia clínica. El documento de la paciente va
completo, sin enmascarar: el médico necesita entregar o archivar el reporte.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.history import HistoryPredictionOut
from app.schemas.patients import DocumentType


class ReportPatient(BaseModel):
    id: UUID
    document_type: DocumentType
    document_number: str
    given_names: str
    family_names: str


class ReportMeasurement(BaseModel):
    """Las 8 variables en unidad clínica; la unidad va en el nombre del campo."""

    id: UUID
    measured_at: datetime
    age_years: float
    temperature_c: float
    heart_rate_bpm: float
    systolic_bp_mmhg: float
    diastolic_bp_mmhg: float
    bmi_kg_m2: float
    hba1c_percent: float
    fasting_glucose_mg_dl: float


class ReportPrediction(HistoryPredictionOut):
    #: `corrected`: una corrección posterior sustituyó esta evaluación.
    status: Literal["current", "corrected"]


class EvaluationReport(BaseModel):
    institution_name: str
    generated_at: datetime
    patient: ReportPatient
    measurement: ReportMeasurement
    prediction: ReportPrediction
    #: Advertencia clínica obligatoria (HU007, HU009).
    clinical_disclaimer: str
