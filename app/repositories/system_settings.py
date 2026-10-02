"""Consultas de `gynfem.system_settings` (HU011). SQL explícito y parametrizado.

La tabla es de solo inserción: un cambio es una fila nueva, y el valor vigente
de una clave es su fila más reciente (migración 0009).
"""

from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


def lock_changes(conexion: psycopg.Connection) -> None:
    """Serializa los cambios hasta el fin de la transacción: dos peticiones simultáneas
    con el mismo valor no insertan dos filas."""
    conexion.execute("SELECT pg_advisory_xact_lock(hashtext('gynfem.system_settings'))")


def current_values(conexion: psycopg.Connection) -> dict[str, dict[str, Any]]:
    """Clave → su fila vigente (`value`, `created_at`, `created_by`). Sin fila, la clave no aparece."""
    with conexion.cursor(row_factory=dict_row) as cursor:
        filas = cursor.execute(
            "SELECT DISTINCT ON (key) key, value, created_at, created_by "
            "FROM gynfem.system_settings ORDER BY key, id DESC"
        ).fetchall()
    return {fila["key"]: fila for fila in filas}


def insert_value(conexion: psycopg.Connection, key: str, value: str, actor: UUID) -> None:
    conexion.execute(
        "INSERT INTO gynfem.system_settings (key, value, created_by) VALUES (%s, %s, %s)", [key, value, actor]
    )
