"""Pacientes: `/api/v1/patients` (HU003, HU004) y su baja lógica.

**Sin autenticación en esta fase, por diseño y de forma temporal** (Fase 11,
PR #10; `docs/SECURITY.md`). Toda ruta depende de `get_actor`, el punto de
enganche. La búsqueda exige un criterio: no hay listado abierto de pacientes.
"""

import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.exceptions import RequestValidationError

from app.api.deps import Actor, get_actor
from app.core.logging import LOGGER_RAIZ, request_id_var
from app.schemas.error import ErrorResponse
from app.schemas.pagination import LIMITE_POR_DEFECTO, Limit, Offset, Page
from app.schemas.patients import (
    NOMBRE_BUSQUEDA_MIN,
    NOMBRE_MAX,
    DocumentType,
    PatientCreate,
    PatientOut,
    PatientSummary,
    PatientUpdate,
)
from app.services.patients import PatientService

router = APIRouter(prefix="/patients", tags=["patients"], dependencies=[Depends(get_actor)])
logger = logging.getLogger(f"{LOGGER_RAIZ}.clinical")

ERRORES = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}


def _servicio(request: Request) -> PatientService:
    return request.app.state.patient_service


def registrar(accion: str, inicio: float) -> None:
    """Solo la acción y la latencia: nunca ids, nombres, documentos ni valores."""
    logger.info("escritura clínica", extra={"action": accion, "duration_ms": round((time.perf_counter() - inicio) * 1000, 2)})


def _criterio_invalido(motivo: str) -> RequestValidationError:
    return RequestValidationError([{"loc": ("query",), "type": motivo, "msg": motivo, "input": None}])


@router.post("", status_code=201, response_model=PatientOut, responses=ERRORES)
def create_patient(datos: PatientCreate, request: Request, actor: Actor = Depends(get_actor)) -> PatientOut:
    inicio = time.perf_counter()
    paciente = _servicio(request).create(datos.model_dump(), actor, request_id_var.get())
    registrar("patient.create", inicio)
    return PatientOut.model_validate(paciente)


@router.get("", response_model=Page[PatientSummary], responses=ERRORES)
def search_patients(
    request: Request,
    document_type: DocumentType | None = None,
    document_number: str | None = Query(default=None, max_length=20),
    name: str | None = Query(default=None, max_length=NOMBRE_MAX),
    limit: Limit = LIMITE_POR_DEFECTO,
    offset: Offset = 0,
) -> Page[PatientSummary]:
    por_documento = document_type is not None or document_number is not None
    if por_documento and name is not None:
        raise _criterio_invalido("single_search_criterion")
    if por_documento:
        if document_type is None or document_number is None:
            raise _criterio_invalido("document_pair_required")
        items, mas = _servicio(request).search_by_document(document_type, document_number.strip().upper(), limit, offset)
    elif name is not None and len(name.strip()) >= NOMBRE_BUSQUEDA_MIN:
        items, mas = _servicio(request).search_by_name(name, limit, offset)
    else:
        raise _criterio_invalido("search_criterion_required")
    return Page[PatientSummary](items=items, limit=limit, offset=offset, has_more=mas)


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
