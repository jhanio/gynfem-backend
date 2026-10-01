"""Reporte de una evaluación (HU009): solo el médico.

`POST /predictions/{id}/report`, sin cuerpo: los datos de la paciente, la
medición, el resultado y la advertencia clínica, tal como están almacenados.

**Por qué es `POST` aunque no cree nada clínico.** Cada generación escribe un
registro de auditoría (`prediction.report`): es el punto en que datos
personales salen del sistema. Un `GET` debe ser seguro —sin efectos—, y un
navegador o un proxy puede repetirlo, precargarlo o guardarlo en caché; con
`POST` nada de eso ocurre y cada reporte entregado tiene su registro.

La respuesta lleva `Cache-Control: no-store`: contiene datos personales.
"""

import time
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.api.access import requiere
from app.api.deps import Actor, get_actor
from app.api.v1.comun import ERRORES, registrar
from app.auth.roles import Role
from app.core.logging import request_id_var
from app.schemas.reports import EvaluationReport
from app.services.reports import ReportService

router = APIRouter(tags=["clinical"], dependencies=[requiere(Role.MEDICO)])


def _servicio(request: Request) -> ReportService:
    return request.app.state.report_service


@router.post("/predictions/{prediction_id}/report", response_model=EvaluationReport, responses=ERRORES)
def generate_report(
    prediction_id: UUID, request: Request, response: Response, actor: Actor = Depends(get_actor)
) -> EvaluationReport:
    inicio = time.perf_counter()
    reporte = _servicio(request).generate(prediction_id, actor, request_id_var.get())
    registrar("prediction.report", inicio)
    response.headers["Cache-Control"] = "no-store"
    return EvaluationReport.model_validate(reporte)
