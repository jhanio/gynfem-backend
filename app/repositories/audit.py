"""Escritura en `gynfem.audit_log`. Solo inserción y nunca valores: nombres de
campo, tipo de entidad, su id opaco, el actor y el `request_id`."""

from collections.abc import Sequence
from uuid import UUID

import psycopg


def insert_audit(
    conexion: psycopg.Connection,
    *,
    action: str,
    entity_type: str,
    entity_id: UUID,
    actor_user_id: UUID | None,
    request_id: str | None,
    changed_fields: Sequence[str] | None = None,
) -> None:
    conexion.execute(
        "INSERT INTO gynfem.audit_log (action, entity_type, entity_id, actor_user_id, request_id, outcome, changed_fields) "
        "VALUES (%s, %s, %s, %s, %s, 'success', %s)",
        [action, entity_type, entity_id, actor_user_id, request_id, list(changed_fields) if changed_fields else None],
    )
