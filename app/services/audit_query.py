"""Consulta de la auditoría. No conoce HTTP. Solo lee.

La auditoría no se crea, no se modifica y no se borra desde aquí: cada registro
lo escribe, en su propia transacción, la operación que audita. Consultarla no
se audita.
"""

from collections.abc import Mapping
from typing import Any

from psycopg_pool import ConnectionPool

from app.core.config import Settings
from app.db.pool import database_transaction
from app.repositories import audit_query as audit_query_repo


class AuditQueryService:
    def __init__(self, pool: ConnectionPool, settings: Settings) -> None:
        self._pool = pool
        self._settings = settings

    def list_page(self, filtros: Mapping[str, Any], limit: int, offset: int) -> tuple[list[dict[str, Any]], bool]:
        with database_transaction(self._pool, self._settings) as conexion:
            filas = audit_query_repo.list_page(conexion, filtros, limit + 1, offset)
        return filas[:limit], len(filas) > limit
