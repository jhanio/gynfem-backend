"""Reporte de una evaluación (HU009). No conoce HTTP.

El reporte **no inventa ni recalcula nada**: reúne lo ya almacenado (la paciente,
la medición y su predicción), el nombre de la institución (parámetro del
sistema, HU011) y la advertencia clínica obligatoria.

Generarlo es el punto en que datos personales salen del sistema, así que cada
generación se audita (`prediction.report`) en la **misma transacción** que la
lectura: si la auditoría falla, no hay reporte. La predicción de una paciente
dada de baja no existe para el reporte (`PredictionNotFound`), igual que una
inexistente, y un reporte que no se entrega no se audita.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg_pool import ConnectionPool

from app.core.config import Settings
from app.db.pool import database_transaction
from app.repositories import audit as audit_repo
from app.repositories import evaluations as evaluations_repo
from app.services.actor import Actor
from app.services.errors import PredictionNotFound
from app.services.history import CORRECTED, CURRENT
from app.services.prediction import CLINICAL_DISCLAIMER
from app.services.settings_catalog import INSTITUTION_NAME
from app.services.system_settings import current_value


class ReportService:
    def __init__(self, pool: ConnectionPool, settings: Settings) -> None:
        self._pool = pool
        self._settings = settings

    def generate(self, prediction_id: UUID, actor: Actor, request_id: str | None) -> dict[str, Any]:
        with database_transaction(self._pool, self._settings) as conexion:
            evaluacion = evaluations_repo.get_with_patient(conexion, prediction_id)
            if evaluacion is None:
                raise PredictionNotFound()
            institucion = current_value(conexion, INSTITUTION_NAME)
            audit_repo.insert_audit(
                conexion, action="prediction.report", entity_type="prediction", entity_id=prediction_id,
                actor_user_id=actor.user_id, request_id=request_id,
            )
        medicion = {clave: valor for clave, valor in evaluacion["measurement"].items() if clave != "patient_id"}
        return {
            "institution_name": institucion,
            "generated_at": datetime.now(UTC),
            "patient": evaluacion["patient"],
            "measurement": medicion,
            "prediction": {**evaluacion["prediction"], "status": CORRECTED if evaluacion["corrected"] else CURRENT},
            "clinical_disclaimer": CLINICAL_DISCLAIMER,
        }
