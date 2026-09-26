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
- **Una conexión muerta no cuelga un worker.** `connect_timeout` acota la
  conexión y `statement_timeout` la sentencia en el servidor; si el peer
  desaparece con la conexión ya abierta (red, NAT, reinicio del pooler), los
  keepalives TCP y `tcp_user_timeout` la cortan, y el pool comprueba cada
  conexión antes de entregarla y reemplaza la que ya no responde.
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
#: Keepalives TCP: primera sonda tras 30 s sin tráfico, luego cada 10 s, y la
#: conexión se da por muerta tras 3 sin respuesta.
KEEPALIVES_IDLE_S = 30
KEEPALIVES_INTERVAL_S = 10
KEEPALIVES_COUNT = 3
#: Margen de `tcp_user_timeout` sobre `statement_timeout`: el corte TCP nunca
#: debe adelantarse al límite de la propia sentencia.
TCP_USER_TIMEOUT_MARGIN_MS = 5000
#: Con 3, PostgreSQL envía cada `float8` con los dígitos justos para releerlo exacto.
EXTRA_FLOAT_DIGITS = "3"


def create_pool(settings: Settings) -> ConnectionPool:
    """Pool cerrado: no conecta hasta `open_pool()`."""
    return ConnectionPool(
        conninfo=settings.database_url.get_secret_value(),
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        timeout=settings.db_pool_timeout_s,
        name=POOL_NAME,
        open=False,
        check=ConnectionPool.check_connection,
        kwargs={
            "prepare_threshold": None,
            "connect_timeout": settings.db_connect_timeout_s,
            "autocommit": False,
            "keepalives": 1,
            "keepalives_idle": KEEPALIVES_IDLE_S,
            "keepalives_interval": KEEPALIVES_INTERVAL_S,
            "keepalives_count": KEEPALIVES_COUNT,
            "tcp_user_timeout": settings.db_statement_timeout_ms + TCP_USER_TIMEOUT_MARGIN_MS,
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

    También fija `extra_float_digits` para esta transacción: Supabase lo tiene
    en 0, y así un `float8` se lee con solo 15 dígitos (6.11111111111111 en vez
    de 6.111111111111111). Con 3, cada valor se relee exacto, bit a bit: la
    trazabilidad de una predicción depende de ello (`docs/ML_SPEC.md` §6).
    """
    with pool.connection() as conexion, conexion.transaction():
        conexion.execute(
            "SELECT set_config('statement_timeout', %s, true), set_config('extra_float_digits', %s, true)",
            [f"{settings.db_statement_timeout_ms}ms", EXTRA_FLOAT_DIGITS],
        )
        yield conexion
