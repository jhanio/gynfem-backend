"""Gestión de usuarios y roles (HU002). No conoce HTTP.

- **Crear**: Supabase Auth crea la cuenta (la contraseña nunca pasa por la
  base); después, en **una** transacción, el perfil con su rol y la auditoría.
  Si la transacción falla, se borra la cuenta recién creada en Supabase
  (compensación). No es atómico: queda una cuenta de Auth sin perfil si la
  compensación falla, si la respuesta de Supabase se pierde o si el proceso
  termina entre los dos pasos. Esa cuenta no puede operar (403) y se borra a
  mano (`docs/SECURITY.md`, riesgos residuales).
- **Nunca sin administrador**: desactivar o degradar al último administrador
  activo se rechaza (`LastActiveAdmin`), con sus filas bloqueadas.
- Toda escritura se audita con `entity_type = 'user'` y solo nombres de campo.
"""

import logging
from typing import Any
from uuid import UUID

from psycopg_pool import ConnectionPool

from app.auth.roles import Role
from app.auth.supabase_admin import AuthAdmin
from app.core.config import Settings
from app.core.logging import LOGGER_RAIZ
from app.db.pool import database_transaction
from app.repositories import audit as audit_repo
from app.repositories import users as users_repo
from app.services.actor import Actor
from app.services.errors import LastActiveAdmin, UserNotFound

logger = logging.getLogger(f"{LOGGER_RAIZ}.auth")


class UserService:
    def __init__(self, pool: ConnectionPool, settings: Settings, admin: AuthAdmin) -> None:
        self._pool = pool
        self._settings = settings
        self._admin = admin

    def create(
        self, email: str, password: str, full_name: str, role: str, actor: Actor, request_id: str | None
    ) -> dict[str, Any]:
        user_id = self._admin.create_user(email, password)
        try:
            with database_transaction(self._pool, self._settings) as conexion:
                users_repo.insert_profile(conexion, user_id, role, full_name, actor.user_id)
                audit_repo.insert_audit(
                    conexion, action="user.create", entity_type="user", entity_id=user_id,
                    actor_user_id=actor.user_id, request_id=request_id,
                )
                return users_repo.get(conexion, user_id)
        except Exception:
            self._compensar(user_id)
            raise

    def _compensar(self, user_id: UUID) -> None:
        try:
            self._admin.delete_user(user_id)
        except Exception as exc:  # noqa: BLE001 — el error original es el que se propaga
            # Sin perfil, esa cuenta no puede operar (403); queda para limpieza manual.
            logger.error("no se pudo borrar la cuenta huérfana", extra={"user_id": str(user_id),
                                                                        "error_type": type(exc).__name__})

    def get(self, user_id: UUID) -> dict[str, Any]:
        with database_transaction(self._pool, self._settings) as conexion:
            usuario = users_repo.get(conexion, user_id)
        if usuario is None:
            raise UserNotFound()
        return usuario

    def list_page(self, limit: int, offset: int) -> tuple[list[dict[str, Any]], bool]:
        with database_transaction(self._pool, self._settings) as conexion:
            filas = users_repo.list_page(conexion, limit + 1, offset)
        return filas[:limit], len(filas) > limit

    def update(self, user_id: UUID, cambios: dict[str, Any], actor: Actor, request_id: str | None) -> dict[str, Any]:
        degrada = cambios.get("role") not in (None, Role.ADMINISTRADOR)
        return self._cambiar(user_id, cambios, "user.update", degrada, actor, request_id, sorted(cambios))

    def set_active(self, user_id: UUID, activo: bool, actor: Actor, request_id: str | None) -> dict[str, Any]:
        accion = "user.activate" if activo else "user.deactivate"
        return self._cambiar(user_id, {"is_active": activo}, accion, not activo, actor, request_id, None)

    def _cambiar(
        self, user_id: UUID, cambios: dict[str, Any], accion: str, quita_admin: bool,
        actor: Actor, request_id: str | None, campos: list[str] | None,
    ) -> dict[str, Any]:
        with database_transaction(self._pool, self._settings) as conexion:
            if quita_admin:
                activos = users_repo.lock_active_admins(conexion)
                if activos == [user_id]:
                    raise LastActiveAdmin()
            if not users_repo.update_profile(conexion, user_id, cambios, actor.user_id):
                raise UserNotFound()
            audit_repo.insert_audit(
                conexion, action=accion, entity_type="user", entity_id=user_id,
                actor_user_id=actor.user_id, request_id=request_id, changed_fields=campos,
            )
            return users_repo.get(conexion, user_id)
