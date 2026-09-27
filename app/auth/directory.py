"""Rol y estado de un usuario, leídos de la base **en cada petición** (decisiones 4 y 8).

Una sola fuente: `gynfem.user_profiles` (migración 0008). Sin caché, a
propósito: desactivar a un usuario o cambiar su rol rige desde la petición
siguiente, aunque el usuario conserve un token válido.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import psycopg
from psycopg_pool import ConnectionPool

from app.auth.errors import SchemaOutdated
from app.core.config import Settings
from app.db.pool import database_transaction
from app.repositories import users as users_repo


@dataclass(frozen=True)
class UserStatus:
    role: str
    is_active: bool


class UserDirectory(Protocol):
    def status(self, user_id: UUID) -> UserStatus | None:
        """`None` si el usuario no tiene perfil."""


class DatabaseUserDirectory:
    def __init__(self, pool: ConnectionPool, settings: Settings) -> None:
        self._pool = pool
        self._settings = settings

    def status(self, user_id: UUID) -> UserStatus | None:
        try:
            with database_transaction(self._pool, self._settings) as conexion:
                fila = users_repo.get_status(conexion, user_id)
        except psycopg.errors.UndefinedTable:
            raise SchemaOutdated() from None
        return None if fila is None else UserStatus(role=fila["role"], is_active=fila["is_active"])
