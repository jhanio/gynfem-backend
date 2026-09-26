"""Mediciones clínicas con predicción persistida (HU005) y consulta de predicciones.

- `POST /patients/{id}/measurements`: registra las 8 variables, predice y
  guarda medición, predicción y auditoría en una transacción (decisión B).
- `GET /patients/{id}/measurements`: mediciones vigentes, paginadas.
- `POST /measurements/{id}/corrections`: «actualizar» es crear una corrección;
  la original queda dada de baja y su predicción, intacta (decisión C).
- `GET /predictions/{id}`: la predicción persistida con su trazabilidad.

`/predict` (Fase 8) no cambia: sigue sin estado y sin paciente.
**Sin autenticación en esta fase, por diseño** (Fase 11, PR #10).
"""

import time
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.deps import Actor, get_actor
from app.api.v1.patients import ERRORES, registrar
from app.core.logging import request_id_var
from app.schemas.clinical import EvaluationOut, MeasurementCreate, MeasurementListItem, StoredPredictionDetail
from app.schemas.pagination import LIMITE_POR_DEFECTO, Limit, Offset, Page
from app.services.clinical_records import ClinicalRecordService

router = APIRouter(tags=["clinical"], dependencies=[Depends(get_actor)])


def _servicio(request: Request) -> ClinicalRecordService:
    return request.app.state.clinical_record_service


def _valores(datos: MeasurementCreate) -> dict[str, float]:
    return datos.model_dump(exclude={"measured_at"})


@router.post("/patients/{patient_id}/measurements", status_code=201, response_model=EvaluationOut, responses=ERRORES)
def create_measurement(
    patient_id: UUID, datos: MeasurementCreate, request: Request, actor: Actor = Depends(get_actor)
) -> EvaluationOut:
    inicio = time.perf_counter()
    resultado = _servicio(request).evaluate(patient_id, _valores(datos), datos.measured_at, actor, request_id_var.get())
    registrar("clinical_measurement.create", inicio)
    return EvaluationOut.model_validate(resultado)


@router.get("/patients/{patient_id}/measurements", response_model=Page[MeasurementListItem], responses=ERRORES)
def list_measurements(
    patient_id: UUID, request: Request, limit: Limit = LIMITE_POR_DEFECTO, offset: Offset = 0
) -> Page[MeasurementListItem]:
    items, mas = _servicio(request).list_measurements(patient_id, limit, offset)
    return Page[MeasurementListItem](items=items, limit=limit, offset=offset, has_more=mas)


@router.post("/measurements/{measurement_id}/corrections", status_code=201, response_model=EvaluationOut, responses=ERRORES)
def correct_measurement(
    measurement_id: UUID, datos: MeasurementCreate, request: Request, actor: Actor = Depends(get_actor)
) -> EvaluationOut:
    inicio = time.perf_counter()
    resultado = _servicio(request).correct(measurement_id, _valores(datos), datos.measured_at, actor, request_id_var.get())
    registrar("clinical_measurement.correct", inicio)
    return EvaluationOut.model_validate(resultado)


@router.get("/predictions/{prediction_id}", response_model=StoredPredictionDetail, responses=ERRORES)
def get_prediction(prediction_id: UUID, request: Request) -> StoredPredictionDetail:
    return StoredPredictionDetail.model_validate(_servicio(request).get_prediction(prediction_id))
