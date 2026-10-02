"""Métricas del modelo (HU010): médico y administrador.

`GET /model/metrics`: las métricas reales de la Fase 6, leídas de los artefactos
versionados, con sus limitaciones **en la misma respuesta**. No admite ningún
parámetro: no existe un modo de pedir solo las cifras.

El médico las ve porque quien usa la predicción necesita saber cuánto falla y
dónde no tiene respaldo; el administrador, porque no contienen datos de
pacientes. Solo lectura: no toca la base ni el modelo.
"""

from fastapi import APIRouter, Request

from app.api.access import requiere
from app.auth.roles import Role
from app.schemas.model_metrics import ModelMetricsResponse
from app.services.model_metrics import ModelMetricsService

router = APIRouter(tags=["model"], dependencies=[requiere(Role.MEDICO, Role.ADMINISTRADOR)])


def _servicio(request: Request) -> ModelMetricsService:
    return request.app.state.model_metrics_service


# `exclude_unset`: una cifra que no existe en los artefactos no aparece, ni como null.
@router.get("/model/metrics", response_model=ModelMetricsResponse, response_model_exclude_unset=True)
def model_metrics(request: Request) -> ModelMetricsResponse:
    return ModelMetricsResponse.model_validate(_servicio(request).metrics())
