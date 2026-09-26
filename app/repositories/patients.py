"""Consultas de `gynfem.patients`. SQL explícito y siempre parametrizado.

Reciben una conexión abierta: la transacción la abre el servicio. Solo leen
pacientes activas (`deleted_at IS NULL`); una baja se trata como inexistente.
"""

from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

COLUMNAS_PUBLICAS = "id, document_type, document_number, given_names, family_names, created_at, updated_at"


def insert_patient(conexion: psycopg.Connection, datos: dict[str, str], search_key: str, actor: UUID | None) -> dict[str, Any]:
    with conexion.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            "INSERT INTO gynfem.patients (document_type, document_number, given_names, family_names, search_key, created_by, updated_by) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {COLUMNAS_PUBLICAS}",
            [datos["document_type"], datos["document_number"], datos["given_names"], datos["family_names"],
             search_key, actor, actor],
        ).fetchone()


def get_active(conexion: psycopg.Connection, patient_id: UUID, *, for_update: bool = False) -> dict[str, Any] | None:
    bloqueo = " FOR UPDATE" if for_update else ""
    with conexion.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            f"SELECT {COLUMNAS_PUBLICAS} FROM gynfem.patients WHERE id = %s AND deleted_at IS NULL{bloqueo}",
            [patient_id],
        ).fetchone()


def update_patient(
    conexion: psycopg.Connection, patient_id: UUID, cambios: dict[str, str], search_key: str, actor: UUID | None
) -> dict[str, Any]:
    # Los nombres de columna salen de una lista cerrada, nunca del cliente.
    permitidas = ("document_type", "document_number", "given_names", "family_names")
    columnas = [c for c in permitidas if c in cambios]
    asignaciones = ", ".join(f"{c} = %s" for c in columnas)
    with conexion.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            f"UPDATE gynfem.patients SET {asignaciones}, search_key = %s, updated_by = %s "
            f"WHERE id = %s AND deleted_at IS NULL RETURNING {COLUMNAS_PUBLICAS}",
            [*(cambios[c] for c in columnas), search_key, actor, patient_id],
        ).fetchone()


def deactivate_patient(conexion: psycopg.Connection, patient_id: UUID, actor: UUID | None) -> bool:
    """Baja **lógica**: la fila y su historial se conservan."""
    cursor = conexion.execute(
        "UPDATE gynfem.patients SET deleted_at = now(), deleted_by = %s, updated_by = %s "
        "WHERE id = %s AND deleted_at IS NULL",
        [actor, actor, patient_id],
    )
    return cursor.rowcount == 1


def find_by_document(
    conexion: psycopg.Connection, document_type: str, document_number: str, limit: int, offset: int
) -> list[dict[str, Any]]:
    with conexion.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            f"SELECT {COLUMNAS_PUBLICAS} FROM gynfem.patients "
            "WHERE deleted_at IS NULL AND document_type = %s AND document_number = %s "
            "ORDER BY family_names, given_names, id LIMIT %s OFFSET %s",
            [document_type, document_number, limit, offset],
        ).fetchall()


def find_by_name_prefix(conexion: psycopg.Connection, prefijo: str, limit: int, offset: int) -> list[dict[str, Any]]:
    """`prefijo` ya normalizado. Coincide con el inicio de cualquier palabra de `search_key`."""
    patron = "% " + _escapar_like(prefijo) + "%"
    with conexion.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            f"SELECT {COLUMNAS_PUBLICAS} FROM gynfem.patients "
            "WHERE deleted_at IS NULL AND search_key LIKE %s ESCAPE '\\' "
            "ORDER BY family_names, given_names, id LIMIT %s OFFSET %s",
            [patron, limit, offset],
        ).fetchall()


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
