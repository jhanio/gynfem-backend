"""Configuración de parámetros básicos (HU011). No conoce HTTP.

- **Sin caché**: cada consulta lee la base, así que un cambio rige desde la
  petición siguiente, en cualquier instancia y sin reiniciar.
- **Un cambio es una fila nueva** en `gynfem.system_settings` más su registro
  `system_setting.update` en la auditoría, en **una** transacción: si una
  escritura falla, PostgreSQL deshace las dos.
- **Un valor igual al vigente no escribe nada**: ni fila ni auditoría. La
  operación responde igual que si hubiera cambiado, con el estado vigente
  (un `PATCH` repetido es idempotente), y no deja ruido en la auditoría.
- En la auditoría va solo el **nombre** de la clave (`changed_fields`), nunca el
  valor: los valores anteriores se conservan en la propia tabla.
"""

from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool

from app.core.config import Settings
from app.db.pool import database_transaction
from app.repositories import audit as audit_repo
from app.repositories import system_settings as settings_repo
from app.services.actor import Actor
from app.services.settings_catalog import VALORES_POR_DEFECTO, a_texto, de_texto


def _estado(conexion: psycopg.Connection) -> dict[str, dict[str, Any]]:
    """Cada clave del catálogo con su valor vigente; sin fila guardada, el valor por defecto."""
    guardados = settings_repo.current_values(conexion)
    estado = {}
    for clave, por_defecto in VALORES_POR_DEFECTO.items():
        fila = guardados.get(clave)
        estado[clave] = {
            "value": por_defecto if fila is None else de_texto(clave, fila["value"]),
            "default": por_defecto,
            "updated_at": None if fila is None else fila["created_at"],
            "updated_by": None if fila is None else fila["created_by"],
        }
    return estado


class SystemSettingsService:
    def __init__(self, pool: ConnectionPool, settings: Settings) -> None:
        self._pool = pool
        self._settings = settings

    def get_all(self) -> dict[str, dict[str, Any]]:
        with database_transaction(self._pool, self._settings) as conexion:
            return _estado(conexion)

    def update(
        self, cambios: Mapping[str, str | int], actor: Actor, request_id: str | None
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        """Devuelve el estado vigente y los nombres de las claves que cambiaron de verdad."""
        with database_transaction(self._pool, self._settings) as conexion:
            settings_repo.lock_changes(conexion)
            vigente = _estado(conexion)
            cambiadas = sorted(clave for clave, valor in cambios.items() if valor != vigente[clave]["value"])
            if not cambiadas:
                return vigente, []
            for clave in cambiadas:
                settings_repo.insert_value(conexion, clave, a_texto(cambios[clave]), actor.user_id)
            audit_repo.insert_audit(
                conexion, action="system_setting.update", entity_type="system_setting", entity_id=None,
                actor_user_id=actor.user_id, request_id=request_id,
                # Solo los nombres de las claves, nunca sus valores.
                changed_fields=cambiadas,
            )
            return _estado(conexion), cambiadas
