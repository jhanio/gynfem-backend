"""Historial de evaluaciones de una paciente (HU008). No conoce HTTP. Solo lee.

- Una paciente inexistente y una dada de baja son lo mismo: `PatientNotFound`.
- El tamaño de página por defecto es un parámetro del sistema (HU011): se lee
  **solo** cuando quien llama no indica `limit`, en la misma transacción.
- Nada se recalcula: cada evaluación sale tal como se guardó.
"""

from typing import Any
from uuid import UUID

from psycopg_pool import ConnectionPool

from app.core.config import Settings
from app.db.pool import database_transaction
from app.repositories import evaluations as evaluations_repo
from app.repositories import patients as patients_repo
from app.services.errors import PatientNotFound
from app.services.settings_catalog import HISTORY_DEFAULT_PAGE_SIZE
from app.services.system_settings import current_value

CURRENT = "current"
CORRECTED = "corrected"


class EvaluationHistoryService:
    def __init__(self, pool: ConnectionPool, settings: Settings) -> None:
        self._pool = pool
        self._settings = settings

    def list_page(self, patient_id: UUID, limit: int | None, offset: int) -> tuple[list[dict[str, Any]], int, bool]:
        """Devuelve la página, el límite aplicado y si hay más."""
        with database_transaction(self._pool, self._settings) as conexion:
            if patients_repo.get_active(conexion, patient_id) is None:
                raise PatientNotFound()
            if limit is None:
                limit = current_value(conexion, HISTORY_DEFAULT_PAGE_SIZE)
            filas = evaluations_repo.list_for_patient(conexion, patient_id, limit + 1, offset)
        items = [
            {
                "measurement": fila["measurement"],
                "prediction": fila["prediction"],
                "status": CORRECTED if fila["corrected"] else CURRENT,
            }
            for fila in filas[:limit]
        ]
        return items, limit, len(filas) > limit
