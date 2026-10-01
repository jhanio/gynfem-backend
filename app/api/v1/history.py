"""Historial de evaluaciones de una paciente (HU008): solo el médico.

`GET /patients/{id}/evaluations`: las evaluaciones de la paciente, de la
medición más reciente a la más antigua, paginadas y sin total. Incluye las
corregidas, con `status: "corrected"`. Sin `limit`, rige el parámetro
`history_default_page_size` (HU011).

Solo lectura: no escribe en la base ni añade una línea de log propia.
"""

from uuid import UUID

from fastapi import APIRouter, Request

from app.api.access import requiere
from app.api.v1.comun import ERRORES
from app.auth.roles import Role
from app.schemas.history import EvaluationHistoryPage
from app.schemas.pagination import Limit, Offset
from app.services.history import EvaluationHistoryService
from app.services.prediction import CLINICAL_DISCLAIMER

router = APIRouter(tags=["clinical"], dependencies=[requiere(Role.MEDICO)])


def _servicio(request: Request) -> EvaluationHistoryService:
    return request.app.state.evaluation_history_service


@router.get("/patients/{patient_id}/evaluations", response_model=EvaluationHistoryPage, responses=ERRORES)
def list_evaluations(
    patient_id: UUID, request: Request, limit: Limit | None = None, offset: Offset = 0
) -> EvaluationHistoryPage:
    items, aplicado, mas = _servicio(request).list_page(patient_id, limit, offset)
    return EvaluationHistoryPage(
        items=items, limit=aplicado, offset=offset, has_more=mas, clinical_disclaimer=CLINICAL_DISCLAIMER
    )
