"""Consultas de `gynfem.user_profiles` (migración 0008). SQL explícito y parametrizado.

El correo no se copia al perfil: se lee de `auth.users`, la tabla de Supabase
Auth, que es su única fuente. Reciben una conexión abierta: la transacción la
abre el servicio.
"""

from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

_COLUMNAS = "p.id, u.email, p.full_name, p.role, p.is_active, p.created_at, p.updated_at"
_DESDE = "FROM gynfem.user_profiles p JOIN auth.users u ON u.id = p.id"
ADMINISTRADOR = "administrador"


def get_status(conexion: psycopg.Connection, user_id: UUID) -> dict[str, Any] | None:
    """Rol y estado: lo único que consulta la autorización en cada petición."""
    with conexion.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            "SELECT role, is_active FROM gynfem.user_profiles WHERE id = %s", [user_id]
        ).fetchone()


def get(conexion: psycopg.Connection, user_id: UUID) -> dict[str, Any] | None:
    with conexion.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(f"SELECT {_COLUMNAS} {_DESDE} WHERE p.id = %s", [user_id]).fetchone()


def list_page(conexion: psycopg.Connection, limit: int, offset: int) -> list[dict[str, Any]]:
    with conexion.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            f"SELECT {_COLUMNAS} {_DESDE} ORDER BY p.created_at, p.id LIMIT %s OFFSET %s", [limit, offset]
        ).fetchall()


def insert_profile(
    conexion: psycopg.Connection, user_id: UUID, role: str, full_name: str, actor: UUID | None
) -> None:
    conexion.execute(
        "INSERT INTO gynfem.user_profiles (id, role, full_name, created_by, updated_by) VALUES (%s, %s, %s, %s, %s)",
        [user_id, role, full_name, actor, actor],
    )


def update_profile(conexion: psycopg.Connection, user_id: UUID, cambios: dict[str, Any], actor: UUID | None) -> bool:
    # Los nombres de columna salen de una lista cerrada, nunca del cliente.
    permitidas = ("full_name", "role", "is_active")
    columnas = [c for c in permitidas if c in cambios]
    asignaciones = "".join(f"{c} = %s, " for c in columnas)
    cursor = conexion.execute(
        f"UPDATE gynfem.user_profiles SET {asignaciones}updated_by = %s WHERE id = %s",
        [*(cambios[c] for c in columnas), actor, user_id],
    )
    return cursor.rowcount == 1


def lock_active_admins(conexion: psycopg.Connection) -> list[UUID]:
    """Bloquea las filas de los administradores activos hasta el fin de la transacción.

    Dos administradores que se desactivan a la vez se serializan aquí: el
    segundo ve el resultado del primero y no deja el sistema sin ninguno.
    """
    filas = conexion.execute(
        "SELECT id FROM gynfem.user_profiles WHERE role = %s AND is_active ORDER BY id FOR UPDATE",
        [ADMINISTRADOR],
    ).fetchall()
    return [fila[0] for fila in filas]


def find_auth_user_by_email(conexion: psycopg.Connection, email: str) -> UUID | None:
    fila = conexion.execute("SELECT id FROM auth.users WHERE lower(email) = lower(%s)", [email]).fetchone()
    return None if fila is None else fila[0]


def upsert_admin_profile(conexion: psycopg.Connection, user_id: UUID, full_name: str) -> None:
    """Primer administrador: crea el perfil, o convierte en administrador activo uno existente."""
    conexion.execute(
        "INSERT INTO gynfem.user_profiles (id, role, is_active, full_name) VALUES (%s, %s, true, %s) "
        "ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role, is_active = true, full_name = EXCLUDED.full_name",
        [user_id, ADMINISTRADOR, full_name],
    )
