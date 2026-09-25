"""Disponibilidad de la aplicación para atender peticiones que usen la base.

«Lista» significa: la base responde dentro de los tiempos configurados **y**
tiene aplicadas exactamente las migraciones que este código espera. Lo segundo
detecta un despliegue que se adelantó a su migración.

Un fallo se registra con su tipo, nunca con su mensaje: el de libpq nombra
host, puerto y usuario.
"""

import logging
from enum import StrEnum

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from app.core.config import Settings
from app.core.logging import LOGGER_RAIZ
from app.db.pool import database_transaction
from app.repositories.database_health import applied_migration_versions

logger = logging.getLogger(f"{LOGGER_RAIZ}.readiness")


class ReadinessStatus(StrEnum):
    READY = "ready"
    DATABASE_UNAVAILABLE = "database_unavailable"
    SCHEMA_OUTDATED = "schema_outdated"


class ReadinessService:
    def __init__(
        self, pool: ConnectionPool, settings: Settings, expected_versions: frozenset[int]
    ) -> None:
        self._pool = pool
        self._settings = settings
        self._expected_versions = expected_versions

    def check(self) -> ReadinessStatus:
        try:
            with database_transaction(self._pool, self._settings) as conexion:
                aplicadas = applied_migration_versions(conexion)
        except (psycopg.Error, PoolTimeout) as exc:
            logger.warning("base de datos no disponible", extra={"error_type": type(exc).__name__})
            return ReadinessStatus.DATABASE_UNAVAILABLE
        if aplicadas != self._expected_versions:
            logger.warning("el esquema no coincide con las migraciones del código")
            return ReadinessStatus.SCHEMA_OUTDATED
        return ReadinessStatus.READY
