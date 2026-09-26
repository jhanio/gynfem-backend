"""Pacientes: `/api/v1/patients` (HU003, HU004) y su baja lógica.

**Sin autenticación en esta fase, por diseño y de forma temporal** (Fase 11,
PR #10; `docs/SECURITY.md`). Toda ruta depende de `get_actor`, el punto de
enganche. La búsqueda es `POST /patients/search`, con el criterio en el cuerpo
y nunca en la URL, y lo exige: no hay listado abierto de pacientes.
"""

import time
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import Actor, get_actor
from app.api.v1.comun import ERRORES, registrar
from app.core.logging import request_id_var
from app.schemas.pagination import Page
from app.schemas.patients import PatientCreate, PatientOut, PatientSearch, PatientSummary, PatientUpdate
from app.services.patients import PatientService

router = APIRouter(prefix="/patients", tags=["patients"], dependencies=[Depends(get_actor)])


def _servicio(request: Request) -> PatientService:
    return request.app.state.patient_service


@router.post("", status_code=201, response_model=PatientOut, responses=ERRORES)
def create_patient(datos: PatientCreate, request: Request, actor: Actor = Depends(get_actor)) -> PatientOut:
    inicio = time.perf_counter()
    paciente = _servicio(request).create(datos.model_dump(), actor, request_id_var.get())
    registrar("patient.create", inicio)
    return PatientOut.model_validate(paciente)


@router.post("/search", response_model=Page[PatientSummary], responses=ERRORES)
def search_patients(criterio: PatientSearch, request: Request) -> Page[PatientSummary]:
    """Búsqueda de solo lectura: `POST` para que el criterio viaje en el cuerpo."""
    if criterio.name is not None:
        items, mas = _servicio(request).search_by_name(criterio.name, criterio.limit, criterio.offset)
    else:
        items, mas = _servicio(request).search_by_document(
            criterio.document_type, criterio.document_number, criterio.limit, criterio.offset
        )
    return Page[PatientSummary](items=items, limit=criterio.limit, offset=criterio.offset, has_more=mas)


@router.get("/{patient_id}", response_model=PatientOut, responses=ERRORES)
def get_patient(patient_id: UUID, request: Request) -> PatientOut:
    return PatientOut.model_validate(_servicio(request).get(patient_id))


@router.patch("/{patient_id}", response_model=PatientOut, responses=ERRORES)
def update_patient(
    patient_id: UUID, cambios: PatientUpdate, request: Request, actor: Actor = Depends(get_actor)
) -> PatientOut:
    inicio = time.perf_counter()
    paciente = _servicio(request).update(patient_id, cambios.model_dump(exclude_unset=True), actor, request_id_var.get())
    registrar("patient.update", inicio)
    return PatientOut.model_validate(paciente)


@router.delete("/{patient_id}", status_code=204, responses=ERRORES)
def deactivate_patient(patient_id: UUID, request: Request, actor: Actor = Depends(get_actor)) -> Response:
    """Baja **lógica**: la paciente deja de aparecer, pero su historial se conserva."""
    inicio = time.perf_counter()
    _servicio(request).deactivate(patient_id, actor, request_id_var.get())
    registrar("patient.deactivate", inicio)
    return Response(status_code=204)
