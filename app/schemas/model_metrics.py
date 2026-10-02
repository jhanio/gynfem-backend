"""Salida de las métricas del modelo (HU010).

Las cifras del resumen son opcionales a propósito: una que no exista en los
artefactos **no se publica** (la ruta serializa con `exclude_unset`), en lugar
de ir como `null` o cero. `detail` sí va siempre: `null`, con su motivo, cuando
el detalle no está disponible. Las limitaciones son obligatorias.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ModelInfo(BaseModel):
    model_version: str | None = None
    algorithm: str | None = None
    trained_at: datetime | None = None
    variant: str | None = None


class EvaluationInfo(BaseModel):
    #: `held_out_test`: el conjunto de prueba apartado antes de entrenar.
    source: str | None = None
    dataset_rows: int | None = None
    training_rows: int | None = None
    test_size: float | None = None
    stratified: bool | None = None


class SummaryMetrics(BaseModel):
    accuracy: float | None = None
    f1_macro: float | None = None
    precision_macro: float | None = None
    recall_macro: float | None = None
    #: Casos de riesgo alto clasificados como riesgo bajo: el error clínicamente grave.
    high_to_low_errors: int | None = None


class TrainingRange(BaseModel):
    feature: str
    unit: str
    min: float
    max: float
    clinical_field: str
    clinical_unit: str
    clinical_min: float
    clinical_max: float


class ClassMetrics(BaseModel):
    precision: float
    recall: float
    f1: float
    support: int


class ProcedureEstimate(BaseModel):
    """Validación cruzada anidada: estima el procedimiento, **no** el rendimiento del modelo."""

    label: str
    metric: str
    mean: float
    std: float
    outer_folds: int
    inner_folds: int
    description: str


class MetricsDetail(BaseModel):
    test_rows: int
    #: Orden de filas y columnas de `confusion_matrix`. No es el de severidad.
    labels: list[str]
    #: Filas: clase real. Columnas: clase predicha.
    confusion_matrix: list[list[int]]
    per_class: dict[str, ClassMetrics]
    procedure_estimate: ProcedureEstimate


class Limitation(BaseModel):
    code: str
    title: str
    message: str
    #: Artefacto y sección de los que sale la limitación.
    sources: list[str] = Field(min_length=1)


class ModelMetricsResponse(BaseModel):
    model: ModelInfo
    evaluation: EvaluationInfo
    metrics: SummaryMetrics
    training_ranges: list[TrainingRange]
    detail: MetricsDetail | None
    detail_unavailable_reason: (
        Literal["training_metrics_missing", "training_metrics_invalid", "training_metrics_mismatch"] | None
    )
    #: Siempre presentes: una exactitud sin su contexto es engañosa para un usuario clínico.
    limitations: list[Limitation] = Field(min_length=1)
