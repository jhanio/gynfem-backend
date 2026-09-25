"""`POST /api/v1/predict` y `GET /api/v1/prediction/schema` (HU006, HU007).

Capa HTTP delgada: valida la petición (nivel a, `app/schemas/prediction.py`) y
delega en `PredictionService`, cargado una sola vez al arrancar.

El log de la predicción solo lleva el resultado agregado —nivel de riesgo y
número de avisos— con su `request_id` y latencia; nunca un valor clínico ni el
vector enviado al modelo (`docs/SECURITY.md`).
"""

import logging
import time
from dataclasses import asdict

from fastapi import APIRouter, Request

from app.core.logging import LOGGER_RAIZ
from app.schemas.prediction import PredictionRequest, PredictionResponse, PredictionSchemaResponse
from app.services.prediction import PredictionService

router = APIRouter(tags=["prediction"])

logger = logging.getLogger(f"{LOGGER_RAIZ}.prediction")


def _servicio(request: Request) -> PredictionService:
    return request.app.state.prediction_service


@router.post("/predict", response_model=PredictionResponse)
def predict(peticion: PredictionRequest, request: Request) -> PredictionResponse:
    inicio = time.perf_counter()
    resultado = _servicio(request).predict(peticion.model_dump())
    logger.info(
        "predicción realizada",
        extra={
            "risk_level": resultado.risk_level,
            "warning_count": len(resultado.extrapolation_warnings),
            "duration_ms": round((time.perf_counter() - inicio) * 1000, 2),
        },
    )
    return PredictionResponse.model_validate(asdict(resultado))


@router.get("/prediction/schema", response_model=PredictionSchemaResponse)
def prediction_schema(request: Request) -> PredictionSchemaResponse:
    return PredictionSchemaResponse.model_validate(_servicio(request).schema())
