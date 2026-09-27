"""Creación del primer administrador (decisión E): `python -m app.auth.bootstrap`.

Con el registro público de Supabase cerrado, una base limpia (en local o en
Render) no tiene a nadie que pueda crear usuarios. Este comando lo resuelve de
forma reproducible:

1. Se niega si ya hay un administrador **activo**: a partir de ahí se gestiona
   con la API (HU002). Si se pierden todos, vuelve a funcionar (emergencia).
2. Si el correo ya existe en Supabase Auth (fallo a medias, base limpiada),
   reutiliza esa cuenta sin pedir contraseña; si no, la crea con la Admin API.
3. En una transacción, crea (o restablece) el perfil como administrador activo
   y lo audita como `user.bootstrap_admin`.

La contraseña se pide dos veces **sin eco** (`getpass`), o se lee de stdin con
`--password-stdin`; nunca es un argumento, porque quedaría en el historial.
Solo se imprime el id: nunca el correo ni la contraseña.

    .venv\\Scripts\\python.exe -m app.auth.bootstrap --env-file .env --email <correo> --full-name "<Nombre>"
"""

import argparse
import getpass
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

import psycopg
from pydantic_core import PydanticCustomError

from app.auth.supabase_admin import AuthAdmin, SupabaseAdminClient
from app.core.config import ConfigurationError, Settings, load_settings
from app.core.logging import configure_logging
from app.repositories import audit as audit_repo
from app.repositories import users as users_repo
from app.schemas.users import CONTRASENA_MAX, CONTRASENA_MIN, normalizar_correo


class BootstrapError(Exception):
    """Motivo legible para quien ejecuta el comando; nunca lleva datos."""


def _leer_contrasena(desde_stdin: bool) -> str:
    if desde_stdin:
        contrasena = sys.stdin.readline().rstrip("\r\n")
    else:
        contrasena = getpass.getpass("Contraseña del administrador: ")
        if getpass.getpass("Repita la contraseña: ") != contrasena:
            raise BootstrapError("las contraseñas no coinciden")
    if not CONTRASENA_MIN <= len(contrasena.encode()) <= CONTRASENA_MAX:
        raise BootstrapError(f"la contraseña debe tener de {CONTRASENA_MIN} a {CONTRASENA_MAX} bytes")
    return contrasena


def _conectar(settings: Settings) -> psycopg.Connection:
    return psycopg.connect(
        settings.database_url.get_secret_value(),
        connect_timeout=settings.db_connect_timeout_s,
        prepare_threshold=None,
    )


def _comprobar(settings: Settings, email: str) -> UUID | None:
    """Falla si ya hay un administrador activo. Devuelve el id de Auth si el correo ya existe."""
    with _conectar(settings) as conexion:
        if conexion.execute("SELECT to_regclass('gynfem.user_profiles')").fetchone()[0] is None:
            raise BootstrapError("falta la tabla de perfiles: aplique antes las migraciones (app.db.migrate up)")
        if users_repo.lock_active_admins(conexion):
            raise BootstrapError("ya existe un administrador activo; gestione los usuarios con la API")
        return users_repo.find_auth_user_by_email(conexion, email)


def _guardar(settings: Settings, user_id: UUID, full_name: str) -> None:
    with _conectar(settings) as conexion, conexion.transaction():
        # Serializa dos ejecuciones simultáneas: solo una crea al primer administrador.
        if users_repo.lock_active_admins(conexion):
            raise BootstrapError("ya existe un administrador activo; gestione los usuarios con la API")
        users_repo.upsert_admin_profile(conexion, user_id, full_name)
        audit_repo.insert_audit(
            conexion, action="user.bootstrap_admin", entity_type="user", entity_id=user_id,
            actor_user_id=None, request_id=str(uuid.uuid4()),
        )


def crear_primer_administrador(
    settings: Settings, admin: AuthAdmin, email: str, full_name: str, password_stdin: bool
) -> tuple[UUID, bool]:
    """(id, creado): `creado` es `False` si se reutilizó una cuenta existente de Auth."""
    existente = _comprobar(settings, email)
    if existente is not None:
        _guardar(settings, existente, full_name)
        return existente, False
    user_id = admin.create_user(email, _leer_contrasena(password_stdin))
    try:
        _guardar(settings, user_id, full_name)
    except Exception:
        try:
            admin.delete_user(user_id)
        except Exception:  # noqa: BLE001 — se informa el error original
            sys.stderr.write(f"Aviso: la cuenta {user_id} quedó en Supabase Auth sin perfil; bórrela en el panel.\n")
        raise
    return user_id, True


def main(argv: Sequence[str] | None = None, admin: AuthAdmin | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.auth.bootstrap",
        description="Crea el primer administrador de GynFem (solo si no hay ninguno activo).",
    )
    parser.add_argument("--env-file", type=Path, help="lee la configuración de este archivo en vez del entorno")
    parser.add_argument("--email", required=True, help="correo de la cuenta del administrador")
    parser.add_argument("--full-name", required=True, help="nombre y apellidos")
    parser.add_argument("--password-stdin", action="store_true", help="lee la contraseña de stdin (automatización)")
    args = parser.parse_args(argv)
    # psycopg puede registrar avisos con el mensaje de libpq (host, usuario).
    configure_logging("WARNING")

    try:
        from app.schemas.patients import _normalizar_nombre

        try:
            email = normalizar_correo(args.email)
            full_name = _normalizar_nombre(args.full_name)
        except PydanticCustomError:
            raise BootstrapError("el correo o el nombre no tienen un formato válido") from None
        settings = load_settings(args.env_file)
        admin = admin or SupabaseAdminClient(
            settings.supabase_url, settings.supabase_secret_key, settings.auth_http_timeout_s
        )
        user_id, creado = crear_primer_administrador(settings, admin, email, full_name, args.password_stdin)
    except (BootstrapError, ConfigurationError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    except Exception as exc:  # noqa: BLE001 — nunca una traza ni un mensaje con datos
        sys.stderr.write(f"Error inesperado ({type(exc).__name__}). No se creó ningún administrador.\n")
        return 1
    accion = "creado" if creado else "restablecido con la cuenta existente"
    sys.stdout.write(f"Administrador {accion}: {user_id}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
