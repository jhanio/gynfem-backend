"""Runner de migraciones versionadas en SQL plano.

Uso (desde la raíz del repositorio):

    python -m app.db.migrate --env-file .env status
    python -m app.db.migrate --env-file .env up
    python -m app.db.migrate --env-file .env down [--steps N]

Cada migración es un par `migrations/NNNN_nombre.up.sql` / `.down.sql`,
numerado desde 0001 sin huecos. Reglas:

- **Atómica.** Cada migración corre en una sola transacción, junto con su
  registro en `gynfem_migrations.schema_migrations`. Si falla a medias,
  PostgreSQL deshace todo lo de esa migración; las anteriores quedan
  aplicadas. Por eso se rechazan las sentencias que no admiten transacción
  (`CONCURRENTLY`).
- **Inmutable una vez aplicada.** Se guarda el SHA-256 del `.up.sql` (con
  fines de línea normalizados). Si una migración aplicada cambió en disco, el
  runner aborta antes de tocar nada: el cambio va en una migración nueva.
- **Una sola ejecución a la vez**, con un bloqueo consultivo de sesión que se
  toma antes de tocar nada. Por eso las migraciones usan el pooler en modo
  Session, nunca el Transaction (puerto 6543), que el runner rechaza.
- **Sin control de transacción dentro de un archivo.** Un `COMMIT` intermedio
  confirmaría media migración sin registrarla: se rechazan `BEGIN`, `COMMIT`,
  `ROLLBACK`, `END`, `ABORT` y `START TRANSACTION` fuera de los cuerpos `$$`.
- **Con `lock_timeout`.** Si un `ALTER`/`DROP` espera un bloqueo exclusivo
  detrás de una transacción de la aplicación, falla a los `LOCK_TIMEOUT` en vez
  de encolar todas las consultas siguientes sobre esa tabla.
- **El checksum cubre el `.up.sql`.** Un `.down.sql` sí puede corregirse
  después de aplicado: no cambia lo que hay en la base.
- **Sin secretos en la salida.** La URL solo se lee de
  `GYNFEM_MIGRATIONS_DATABASE_URL`; de un error de conexión se informa el tipo,
  nunca el mensaje de libpq, que nombra host, puerto y usuario.

La aplicación no usa esta variable: usa `GYNFEM_DATABASE_URL` (modo
Transaction). Los tests usan este módulo como biblioteca contra un PostgreSQL
local.
"""

import argparse
import hashlib
import os
import re
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from dotenv import dotenv_values

from app.core.logging import configure_logging

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
MIGRATIONS_ENV_VAR = "GYNFEM_MIGRATIONS_DATABASE_URL"

CONTROL_SCHEMA = "gynfem_migrations"
CONTROL_TABLE = f"{CONTROL_SCHEMA}.schema_migrations"

#: Clave del bloqueo consultivo que serializa las ejecuciones del runner.
ADVISORY_LOCK_KEY = 90_020_026
CONNECT_TIMEOUT_S = 10
#: Espera máxima de una migración por un bloqueo de tabla.
LOCK_TIMEOUT = "5s"
#: Puerto del pooler de Supabase en modo Transaction.
TRANSACTION_POOLER_PORT = 6543

_NOMBRE_DE_ARCHIVO = re.compile(r"^(\d{4})_([a-z0-9_]+)\.(up|down)\.sql$")
_NO_TRANSACCIONAL = re.compile(r"\bCONCURRENTLY\b", re.IGNORECASE)
#: Cuerpos entre dólares (`$$ … $$`, `$tag$ … $tag$`) y comentarios de línea.
_CUERPOS_Y_COMENTARIOS = re.compile(r"\$([A-Za-z_]*)\$.*?\$\1\$|--[^\n]*", re.DOTALL)
_CONTROL_DE_TRANSACCION = frozenset({"BEGIN", "COMMIT", "ROLLBACK", "END", "ABORT", "START"})

_CREAR_CONTROL = f"""
CREATE SCHEMA IF NOT EXISTS {CONTROL_SCHEMA};
REVOKE ALL ON SCHEMA {CONTROL_SCHEMA} FROM PUBLIC, anon, authenticated;
CREATE TABLE IF NOT EXISTS {CONTROL_TABLE} (
    version     integer PRIMARY KEY,
    name        text NOT NULL,
    checksum    char(64) NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE {CONTROL_TABLE} ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE {CONTROL_TABLE} FROM PUBLIC, anon, authenticated;
"""


class MigrationError(Exception):
    """La serie de migraciones o su aplicación no son válidas. El mensaje nunca lleva la URL."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up_sql: str
    down_sql: str
    checksum: str

    @property
    def label(self) -> str:
        return f"{self.version:04d}_{self.name}"


def _leer(ruta: Path) -> str:
    return ruta.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _problema_de_transaccion(texto: str) -> str | None:
    """La primera sentencia que no admite ir dentro de la transacción del runner."""
    limpio = _CUERPOS_Y_COMENTARIOS.sub(" ", texto)
    if _NO_TRANSACCIONAL.search(limpio):
        return "usa CONCURRENTLY, que no admite transacción"
    for sentencia in limpio.split(";"):
        palabras = sentencia.split()
        if palabras and palabras[0].upper() in _CONTROL_DE_TRANSACCION:
            return f"contiene control de transacción ({palabras[0].upper()}), que rompería su atomicidad"
    return None


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Lee y valida la serie. Lanza `MigrationError` si hay huecos, pares incompletos,
    nombres inválidos o sentencias que no admiten transacción."""
    pares: dict[int, dict[str, Path]] = {}
    nombres: dict[int, str] = {}
    for ruta in sorted(directory.glob("*.sql")):
        coincidencia = _NOMBRE_DE_ARCHIVO.match(ruta.name)
        if not coincidencia:
            raise MigrationError(f"nombre de archivo inválido: {ruta.name}")
        version, nombre, sentido = int(coincidencia[1]), coincidencia[2], coincidencia[3]
        if nombres.setdefault(version, nombre) != nombre:
            raise MigrationError(f"la migración {version:04d} tiene dos nombres distintos")
        pares.setdefault(version, {})[sentido] = ruta

    migraciones = []
    for esperada, version in enumerate(sorted(pares), start=1):
        if version != esperada:
            raise MigrationError(f"falta la migración {esperada:04d}: la numeración tiene un hueco")
        for sentido in ("up", "down"):
            if sentido not in pares[version]:
                raise MigrationError(f"la migración {version:04d} no tiene su archivo .{sentido}.sql")
        up_sql, down_sql = _leer(pares[version]["up"]), _leer(pares[version]["down"])
        for sentido, texto in (("up", up_sql), ("down", down_sql)):
            problema = _problema_de_transaccion(texto)
            if problema:
                raise MigrationError(f"la migración {version:04d} ({sentido}) {problema}")
        migraciones.append(
            Migration(
                version=version,
                name=nombres[version],
                up_sql=up_sql,
                down_sql=down_sql,
                checksum=hashlib.sha256(up_sql.encode("utf-8")).hexdigest(),
            )
        )
    return migraciones


@contextmanager
def _conectar(url: str) -> Iterator[psycopg.Connection]:
    try:
        conexion = psycopg.connect(url, autocommit=True, connect_timeout=CONNECT_TIMEOUT_S)
    except psycopg.Error as exc:
        # El mensaje de libpq nombra host, puerto y usuario: solo se informa el tipo.
        raise MigrationError(
            f"no se pudo conectar con la base de datos ({type(exc).__name__})"
        ) from None
    with conexion:
        yield conexion


@contextmanager
def _sesion_exclusiva(url: str) -> Iterator[psycopg.Connection]:
    """Conexión con el bloqueo del runner tomado y, después, la tabla de control creada."""
    with _conectar(url) as conexion:
        tomado = conexion.execute("SELECT pg_try_advisory_lock(%s)", [ADVISORY_LOCK_KEY]).fetchone()[0]
        if not tomado:
            raise MigrationError("otra ejecución de migraciones está en curso")
        try:
            conexion.execute(_CREAR_CONTROL)
            yield conexion
        finally:
            # Si la conexión murió, el bloqueo de sesión ya se liberó con ella, y
            # un error aquí taparía el que dice qué migración falló.
            if not conexion.closed and not conexion.broken:
                conexion.execute("SELECT pg_advisory_unlock(%s)", [ADVISORY_LOCK_KEY])


def _aplicadas(conexion: psycopg.Connection) -> dict[int, str]:
    filas = conexion.execute(f"SELECT version, checksum FROM {CONTROL_TABLE}").fetchall()
    return {version: checksum for version, checksum in filas}


def _verificar(aplicadas: dict[int, str], migraciones: Sequence[Migration]) -> None:
    por_version = {m.version: m for m in migraciones}
    for version, checksum in sorted(aplicadas.items()):
        if version not in por_version:
            raise MigrationError(f"la migración {version:04d} está aplicada pero no existe en disco")
        if por_version[version].checksum != checksum:
            raise MigrationError(
                f"la migración {por_version[version].label} cambió después de aplicarse "
                "(checksum distinto): el cambio va en una migración nueva"
            )


def _ejecutar(conexion: psycopg.Connection, migracion: Migration, sql: str, registro) -> None:
    try:
        with conexion.transaction():
            conexion.execute("SELECT set_config('lock_timeout', %s, true)", [LOCK_TIMEOUT])
            conexion.execute(sql)
            registro()
    except psycopg.Error as exc:
        detalle = exc.diag.message_primary or type(exc).__name__
        raise MigrationError(
            f"la migración {migracion.label} falló y se deshizo por completo: {detalle}"
        ) from None


def upgrade(url: str, directory: Path = MIGRATIONS_DIR, target: int | None = None) -> list[int]:
    """Aplica en orden las pendientes hasta `target` (por defecto, todas). Devuelve las aplicadas."""
    migraciones = discover(directory)
    aplicadas_ahora: list[int] = []
    with _sesion_exclusiva(url) as conexion:
        aplicadas = _aplicadas(conexion)
        _verificar(aplicadas, migraciones)
        for m in migraciones:
            if m.version in aplicadas or (target is not None and m.version > target):
                continue
            _ejecutar(
                conexion,
                m,
                m.up_sql,
                lambda m=m: conexion.execute(
                    f"INSERT INTO {CONTROL_TABLE} (version, name, checksum) VALUES (%s, %s, %s)",
                    [m.version, m.name, m.checksum],
                ),
            )
            aplicadas_ahora.append(m.version)
    return aplicadas_ahora


def downgrade(url: str, directory: Path = MIGRATIONS_DIR, steps: int = 1) -> list[int]:
    """Revierte las `steps` últimas aplicadas, de la más reciente a la más antigua."""
    if steps < 1:
        raise MigrationError("steps debe ser al menos 1")
    migraciones = {m.version: m for m in discover(directory)}
    revertidas: list[int] = []
    with _sesion_exclusiva(url) as conexion:
        aplicadas = _aplicadas(conexion)
        _verificar(aplicadas, list(migraciones.values()))
        for version in sorted(aplicadas, reverse=True)[:steps]:
            m = migraciones[version]
            _ejecutar(
                conexion,
                m,
                m.down_sql,
                lambda v=version: conexion.execute(
                    f"DELETE FROM {CONTROL_TABLE} WHERE version = %s", [v]
                ),
            )
            revertidas.append(version)
    return revertidas


def status(url: str, directory: Path = MIGRATIONS_DIR) -> tuple[list[int], list[Migration]]:
    """(versiones aplicadas, migraciones pendientes). Verifica los checksums. Solo lee."""
    migraciones = discover(directory)
    with _conectar(url) as conexion:
        existe = conexion.execute("SELECT to_regclass(%s)", [CONTROL_TABLE]).fetchone()[0]
        aplicadas = _aplicadas(conexion) if existe is not None else {}
    _verificar(aplicadas, migraciones)
    return sorted(aplicadas), [m for m in migraciones if m.version not in aplicadas]


# --- Línea de comandos -------------------------------------------------------------


def _url(env_file: Path | None) -> str:
    if env_file is not None:
        if not env_file.is_file():
            raise MigrationError(f"no existe el archivo de entorno {env_file}")
        url = dotenv_values(env_file).get(MIGRATIONS_ENV_VAR)
    else:
        url = os.environ.get(MIGRATIONS_ENV_VAR)
    if not url:
        raise MigrationError(f"falta la variable {MIGRATIONS_ENV_VAR}")
    try:
        puerto = urlsplit(url).port
    except ValueError:
        puerto = None  # libpq lo rechazará al conectar, sin repetir la URL
    if puerto == TRANSACTION_POOLER_PORT:
        raise MigrationError(
            f"{MIGRATIONS_ENV_VAR} apunta al puerto {TRANSACTION_POOLER_PORT}, el pooler en modo "
            "Transaction: las migraciones necesitan el pooler en modo Session"
        )
    return url


def _escribir(texto: str) -> None:
    sys.stdout.write(f"{texto}\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.db.migrate",
        description=f"Migraciones de GynFem. Lee la URL de {MIGRATIONS_ENV_VAR} (pooler en modo Session).",
    )
    parser.add_argument("--env-file", type=Path, help="lee la variable de este archivo en vez del entorno")
    parser.add_argument("comando", choices=["up", "down", "status"])
    parser.add_argument("--steps", type=int, default=1, help="migraciones que revierte `down` (por defecto, 1)")
    args = parser.parse_args(argv)
    # psycopg puede registrar avisos con el mensaje de libpq (host, usuario).
    configure_logging("WARNING")

    try:
        url = _url(args.env_file)
        if args.comando == "up":
            aplicadas = upgrade(url)
            for version in aplicadas:
                _escribir(f"Aplicada {version:04d}")
            _escribir(f"Migraciones aplicadas en esta ejecución: {len(aplicadas)}.")
        elif args.comando == "down":
            for version in downgrade(url, steps=args.steps):
                _escribir(f"Revertida {version:04d}")
        else:
            aplicadas, pendientes = status(url)
            total = len(aplicadas) + len(pendientes)
            _escribir(f"{len(aplicadas)} de {total} migraciones aplicadas.")
            for m in pendientes:
                _escribir(f"Pendiente {m.label}")
    except MigrationError as exc:
        sys.stderr.write(f"Error de migración: {exc}\n")
        return 1
    except Exception as exc:  # noqa: BLE001 — nunca una traza ni un mensaje que pueda llevar la URL
        sys.stderr.write(f"Error de migración inesperado ({type(exc).__name__}).\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
