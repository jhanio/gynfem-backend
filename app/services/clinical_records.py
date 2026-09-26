"""Mediciones clínicas y predicción persistida (HU005).

**Orden de una evaluación** (`docs/ARCHITECTURE.md`):

1. la entrada ya pasó el nivel a de la validación (esquema de la ruta);
2. se predice **en memoria**, con el `PredictionService` de la Fase 8, sin
   tocar la base: si el modelo falla, no hay nada que deshacer;
3. se abre **una** transacción y se escriben la medición, la predicción y sus
   dos registros de auditoría. Si cualquier escritura falla, PostgreSQL
   deshace todas: nunca queda una medición sin su predicción.

Una corrección sigue el mismo orden y, en la misma transacción, da de baja la
medición original, cuya predicción se conserva intacta (decisión C).
La conversión de unidades es solo de `PredictionService`: aquí no se repite.
"""

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg_pool import ConnectionPool

from app.core.config import Settings
from app.db.pool import database_transaction
from app.repositories import audit as audit_repo
from app.repositories import measurements as measurements_repo
from app.repositories import patients as patients_repo
from app.repositories import predictions as predictions_repo
from app.services.actor import Actor
from app.services.errors import MeasurementAlreadyCorrected, MeasurementNotFound, PatientNotFound, PredictionNotFound
from app.services.prediction import CLINICAL_DISCLAIMER, PredictionResult, PredictionService


def _prediccion_publica(prediccion_id: UUID, resultado: PredictionResult) -> dict[str, Any]:
    return {
        "id": prediccion_id,
        "risk_level": resultado.risk_level,
        "probabilities": resultado.probabilities,
        "extrapolation_warnings": [asdict(a) for a in resultado.extrapolation_warnings],
        "clinical_disclaimer": resultado.clinical_disclaimer,
        "model_version": resultado.model_version,
        "conversion_schema_version": resultado.conversion_schema_version,
        "predicted_at": resultado.predicted_at,
    }


class ClinicalRecordService:
    def __init__(
        self,
        pool: ConnectionPool,
        settings: Settings,
        prediction_service: PredictionService,
        feature_order: Sequence[str],
    ) -> None:
        self._pool = pool
        self._settings = settings
        self._prediccion = prediction_service
        self._feature_order = tuple(feature_order)

    def evaluate(
        self, patient_id: UUID, valores: Mapping[str, float], measured_at: datetime | None,
        actor: Actor, request_id: str | None,
    ) -> dict[str, Any]:
        resultado = self._prediccion.predict(valores)
        with database_transaction(self._pool, self._settings) as conexion:
            if patients_repo.get_active(conexion, patient_id, for_update=True) is None:
                raise PatientNotFound()
            return self._guardar(conexion, patient_id, measured_at, resultado, actor, request_id)

    def correct(
        self, measurement_id: UUID, valores: Mapping[str, float], measured_at: datetime | None,
        actor: Actor, request_id: str | None,
    ) -> dict[str, Any]:
        resultado = self._prediccion.predict(valores)
        try:
            with database_transaction(self._pool, self._settings) as conexion:
                original = measurements_repo.get_active(conexion, measurement_id, for_update=True)
                if original is None:
                    raise MeasurementNotFound()
                measurements_repo.deactivate_measurement(conexion, measurement_id, actor.user_id)
                return self._guardar(
                    conexion, original["patient_id"], measured_at or original["measured_at"], resultado,
                    actor, request_id, replaces=measurement_id,
                )
        except psycopg.errors.UniqueViolation:
            raise MeasurementAlreadyCorrected() from None

    def _guardar(
        self, conexion: psycopg.Connection, patient_id: UUID, measured_at: datetime | None,
        resultado: PredictionResult, actor: Actor, request_id: str | None, replaces: UUID | None = None,
    ) -> dict[str, Any]:
        medicion = measurements_repo.insert_measurement(
            conexion, patient_id, measured_at, resultado.input, actor.user_id, replaces=replaces
        )
        audit_repo.insert_audit(
            conexion, action="clinical_measurement.correct" if replaces else "clinical_measurement.create",
            entity_type="clinical_measurement", entity_id=medicion["id"],
            actor_user_id=actor.user_id, request_id=request_id,
        )
        prediccion_id = predictions_repo.insert_prediction(
            conexion, medicion["id"],
            clinical_input=resultado.input,
            # El vector exacto que recibió el modelo, en el orden de su contrato.
            model_input={f: resultado.model_input[f] for f in self._feature_order},
            risk_level=resultado.risk_level,
            probabilities=resultado.probabilities,
            extrapolation_warnings=[asdict(a) for a in resultado.extrapolation_warnings],
            model_version=resultado.model_version,
            conversion_schema_version=resultado.conversion_schema_version,
            predicted_at=resultado.predicted_at,
            actor=actor.user_id,
        )
        audit_repo.insert_audit(
            conexion, action="prediction.create", entity_type="prediction", entity_id=prediccion_id,
            actor_user_id=actor.user_id, request_id=request_id,
        )
        return {"measurement": medicion, "prediction": _prediccion_publica(prediccion_id, resultado)}

    def list_measurements(self, patient_id: UUID, limit: int, offset: int) -> tuple[list, bool]:
        with database_transaction(self._pool, self._settings) as conexion:
            if patients_repo.get_active(conexion, patient_id) is None:
                raise PatientNotFound()
            filas = measurements_repo.list_for_patient(conexion, patient_id, limit + 1, offset)
        return filas[:limit], len(filas) > limit

    def get_prediction(self, prediction_id: UUID) -> dict[str, Any]:
        with database_transaction(self._pool, self._settings) as conexion:
            prediccion = predictions_repo.get_active(conexion, prediction_id, self._feature_order)
        if prediccion is None:
            raise PredictionNotFound()
        return {**prediccion, "clinical_disclaimer": CLINICAL_DISCLAIMER}
