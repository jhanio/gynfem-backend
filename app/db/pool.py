"""Pool de conexiones a PostgreSQL (Supabase, pooler en modo Transaction).

- **Se crea cerrado** en `create_app()` y se abre en el ciclo de vida de la
  aplicación (`app/factory.py`), sin esperar a que la base responda: si
  Supabase está caída o pausada, la aplicación arranca igual, `/health` sigue
  respondiendo y `/health/ready` informa la caída.
- **Compatible con Supavisor en modo Transaction**: sin sentencias preparadas
  (`prepare_threshold=None`), porque cada transacción puede ir a una conexión
  de servidor distinta. Por la misma razón, el límite por sentencia se fija con
  `set_config(..., true)` dentro de cada transacción y nunca con un `SET` de
  sesión, que quedaría en una conexión compartida con otros clientes.
- **La URL no sale de aquí**: se toma de `SecretStr` solo para conectar.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool

from app.core.config import Settings

POOL_NAME = "gynfem"
#: Segundos que espera el cierre ordenado a que se devuelvan las conexiones.
CLOSE_TIMEOUT_S = 5.0


def create_pool(settings: Settings) -> ConnectionPool:
    """Pool cerrado: no conecta hasta `open_pool()`."""
    return ConnectionPool(
        conninfo=settings.database_url.get_secret_value(),
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        timeout=settings.db_pool_timeout_s,
        name=POOL_NAME,
        open=False,
        kwargs={
            "prepare_threshold": None,
            "connect_timeout": settings.db_connect_timeout_s,
            "autocommit": False,
        },
    )


def open_pool(pool: ConnectionPool) -> None:
    """Abre el pool sin esperar a la base: los workers conectan en segundo plano."""
    pool.open(wait=False)


def close_pool(pool: ConnectionPool) -> None:
    pool.close(timeout=CLOSE_TIMEOUT_S)


@contextmanager
def database_transaction(pool: ConnectionPool, settings: Settings) -> Iterator[psycopg.Connection]:
    """Una conexión del pool dentro de una transacción con límite por sentencia.

    Espera como mucho `db_pool_timeout_s` por la conexión (`PoolTimeout`); el
    límite de `db_statement_timeout_ms` vale solo para esta transacción.
    """
    with pool.connection() as conexion, conexion.transaction():
        conexion.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            [f"{settings.db_statement_timeout_ms}ms"],
        )
        yield conexion
