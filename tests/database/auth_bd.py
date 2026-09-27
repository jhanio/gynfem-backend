"""Usuarios de prueba en la base embebida y un doble de la Admin API de Supabase.

`auth.users` es un **stub**: `pgserver` no trae el esquema `auth` de Supabase,
así que `conftest.py` crea en `template1` solo las columnas que usa el backend
(`id`, `email`). Los correos son sintéticos (`@example.com`).
"""

import uuid
from uuid import UUID

import psycopg

#: Lo que crea `conftest.py` en `template1`: cada base de test lo hereda.
STUB_AUTH_USERS = """
CREATE SCHEMA auth;
CREATE TABLE auth.users (id uuid PRIMARY KEY, email text UNIQUE);
"""


def crear_usuario(
    url: str, rol: str, *, activo: bool = True, user_id: UUID | None = None,
    email: str | None = None, nombre: str = "Usuaria Prueba",
) -> UUID:
    """Usuario de Auth con su perfil, insertado directamente en la base."""
    user_id = user_id or uuid.uuid4()
    email = email or f"usuario.{user_id.hex}@example.com"
    with psycopg.connect(url) as conexion:
        conexion.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s) ON CONFLICT DO NOTHING", [user_id, email])
        conexion.execute(
            "INSERT INTO gynfem.user_profiles (id, role, is_active, full_name) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (id) DO NOTHING",
            [user_id, rol, activo, nombre],
        )
    return user_id


class AdminFalso:
    """Doble de `SupabaseAdminClient`: escribe en el stub de `auth.users` de la base del test."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.creados: list[tuple[str, str]] = []
        self.borrados: list[UUID] = []
        self.fallar_con: Exception | None = None

    def create_user(self, email: str, password: str) -> UUID:
        from app.services.errors import UserAlreadyExists

        if self.fallar_con is not None:
            raise self.fallar_con
        with psycopg.connect(self.url) as conexion:
            if conexion.execute("SELECT 1 FROM auth.users WHERE lower(email) = lower(%s)", [email]).fetchone():
                raise UserAlreadyExists()
            nuevo = uuid.uuid4()
            conexion.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s)", [nuevo, email])
        self.creados.append((email, password))
        return nuevo

    def delete_user(self, user_id: UUID) -> None:
        with psycopg.connect(self.url) as conexion:
            conexion.execute("DELETE FROM auth.users WHERE id = %s", [user_id])
        self.borrados.append(user_id)
