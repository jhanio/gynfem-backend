"""Pool de conexiones y `GET /api/v1/health/ready`.

`/health` sigue sin dependencias externas (Fase 7). `/health/ready` consulta la
base y el estado de las migraciones, y nunca devuelve ni registra detalles de
la conexión. Sin red: la base es el PostgreSQL embebido, o un puerto de
loopback cerrado o mudo para simular una caída.
"""

import logging
import time

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict

from api.api_constantes import ORIGEN_LOCAL

from .conftest import HOSTS_LOOPBACK, puerto_cerrado

READY = "/api/v1/health/ready"
CENTINELAS = ("usuario-centinela", "clave-centinela", "base-centinela")


@pytest.fixture
def crear_app(configurar, modelo_real):
    from app.factory import create_app

    def _crear(database_url: str, **variables: str):
        configurar(
            environment="development", cors_origins=ORIGEN_LOCAL, database_url=database_url, **variables
        )
        return create_app(model=modelo_real)

    yield _crear
    logging.getLogger("gynfem").handlers.clear()


def url_caida(puerto: int | None = None) -> str:
    puerto = puerto or puerto_cerrado()
    return f"postgresql://{CENTINELAS[0]}:{CENTINELAS[1]}@127.0.0.1:{puerto}/{CENTINELAS[2]}"


@pytest.fixture(params=["puerto cerrado", "rol inexistente"])
def base_que_rechaza(request, servidor_pg):
    """(url, puerto) de una base que falla al conectar.

    Con el puerto cerrado, libpq solo informa un tiempo agotado. Con el
    servidor alcanzable y un rol inexistente, su mensaje nombra host, puerto y
    usuario: es el caso que de verdad pone a prueba los logs.
    """
    if request.param == "puerto cerrado":
        puerto = puerto_cerrado()
        return url_caida(puerto), puerto
    datos = conninfo_to_dict(servidor_pg)
    url = f"postgresql://{CENTINELAS[0]}:{CENTINELAS[1]}@{datos['host']}:{datos['port']}/{CENTINELAS[2]}"
    return url, int(datos["port"])


# --- Pool -------------------------------------------------------------------------


def test_la_suite_solo_usa_loopback(servidor_pg, base_vacia):
    assert conninfo_to_dict(servidor_pg)["host"] in HOSTS_LOOPBACK
    assert conninfo_to_dict(base_vacia)["host"] in HOSTS_LOOPBACK


def test_pool_se_abre_al_arrancar_y_se_cierra_al_apagar(crear_app, base_migrada):
    app = crear_app(base_migrada)
    pool = app.state.db_pool
    assert pool.closed, "crear la aplicación no debe conectar con la base"

    with TestClient(app):
        assert not pool.closed
        with pool.connection() as conexion:
            assert conexion.execute("SELECT 1").fetchone() == (1,)

    assert pool.closed


def test_pool_configurado_para_el_pooler_transaction(crear_app, base_migrada):
    app = crear_app(
        base_migrada,
        db_pool_min_size="2",
        db_pool_max_size="3",
        db_connect_timeout_s="3",
        db_pool_timeout_s="1.5",
    )
    pool = app.state.db_pool

    assert (pool.min_size, pool.max_size, pool.timeout) == (2, 3, 1.5)
    with TestClient(app), pool.connection() as conexion:
        # Supavisor en modo Transaction no admite sentencias preparadas.
        assert conexion.prepare_threshold is None
        assert conninfo_to_dict(conexion.info.dsn)["connect_timeout"] == "3"


def test_statement_timeout_solo_dentro_de_la_transaccion(crear_app, base_migrada):
    from app.db.pool import database_transaction

    app = crear_app(base_migrada, db_statement_timeout_ms="1500", db_pool_max_size="1")
    pool = app.state.db_pool
    with TestClient(app):
        # Una transacción que termina bien: si el límite fuera de sesión, sobreviviría al COMMIT.
        with database_transaction(pool, app.state.settings) as conexion:
            assert conexion.execute("SHOW statement_timeout").fetchone() == ("1500ms",)
        # Con un pool de una conexión, esta es la misma: el límite no se filtró a la sesión.
        with pool.connection() as conexion:
            assert conexion.execute("SHOW statement_timeout").fetchone() == ("0",)
        # Y el límite se aplica: una sentencia más larga se cancela.
        with pytest.raises(psycopg.errors.QueryCanceled):
            with database_transaction(pool, app.state.settings) as conexion:
                conexion.execute("SELECT pg_sleep(3)")


def test_la_app_arranca_aunque_la_base_no_responda(crear_app):
    app = crear_app(url_caida(), db_pool_timeout_s="1")

    with TestClient(app) as cliente:
        assert cliente.get("/api/v1/health").status_code == 200
        assert cliente.get(READY).status_code == 503


# --- /health/ready ----------------------------------------------------------------


def test_ready_200_con_base_disponible_y_esquema_al_dia(crear_app, base_migrada):
    with TestClient(crear_app(base_migrada)) as cliente:
        respuesta = cliente.get(READY)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ready", "checks": {"database": "ok", "schema": "ok"}}


def _error(respuesta) -> dict:
    cuerpo = respuesta.json()
    assert set(cuerpo) == {"error"}
    assert set(cuerpo["error"]) == {"code", "message", "request_id"}
    assert cuerpo["error"]["request_id"] == respuesta.headers["x-request-id"]
    return cuerpo["error"]


def test_ready_503_si_la_base_no_responde(crear_app):
    with TestClient(crear_app(url_caida(), db_pool_timeout_s="1")) as cliente:
        respuesta = cliente.get(READY)

    assert respuesta.status_code == 503
    assert _error(respuesta)["code"] == "database_unavailable"


def test_ready_503_si_faltan_migraciones(crear_app, base_vacia):
    from app.db.migrate import MIGRATIONS_DIR, discover, upgrade

    with TestClient(crear_app(base_vacia)) as cliente:
        sin_ninguna = cliente.get(READY)
        upgrade(base_vacia, target=len(discover(MIGRATIONS_DIR)) - 1)
        sin_la_ultima = cliente.get(READY)

    for respuesta in (sin_ninguna, sin_la_ultima):
        assert respuesta.status_code == 503
        assert _error(respuesta)["code"] == "schema_outdated"


def test_ready_no_expone_detalles_de_conexion(crear_app, base_que_rechaza):
    url, puerto = base_que_rechaza
    with TestClient(crear_app(url, db_pool_timeout_s="1")) as cliente:
        respuesta = cliente.get(READY)

    assert respuesta.status_code == 503
    texto = respuesta.text + repr(dict(respuesta.headers))
    for prohibido in (*CENTINELAS, url, "127.0.0.1", str(puerto), "psycopg", "Error", "failed"):
        assert prohibido not in texto, f"la respuesta expone {prohibido!r}"


def test_ready_200_no_expone_la_base(crear_app, base_migrada):
    datos = conninfo_to_dict(base_migrada)
    with TestClient(crear_app(base_migrada)) as cliente:
        texto = cliente.get(READY).text

    for prohibido in (datos["dbname"], datos["port"], datos["host"], datos["user"]):
        assert prohibido not in texto


def test_health_no_toca_la_base_y_ready_si(crear_app, base_migrada, monkeypatch):
    app = crear_app(base_migrada)
    pool = app.state.db_pool
    pedidas = []
    original = pool.connection

    def espia(*args, **kwargs):
        pedidas.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(pool, "connection", espia)
    with TestClient(app) as cliente:
        assert cliente.get("/api/v1/health").status_code == 200
        assert pedidas == []
        assert cliente.get(READY).status_code == 200
        assert pedidas == [1], "control positivo: /health/ready sí usa el pool"


def test_logs_sin_cadena_de_conexion(crear_app, base_que_rechaza, caplog, capsys):
    """Ni el log de la aplicación ni el de psycopg: los errores de libpq nombran host y puerto."""
    url, puerto = base_que_rechaza
    caplog.set_level(logging.DEBUG)

    with TestClient(crear_app(url, db_pool_timeout_s="1")) as cliente:
        assert cliente.get(READY).status_code == 503
        time.sleep(1.5)  # deja reintentar a los workers del pool, que registran sus fallos

    capturado = capsys.readouterr()
    registros = caplog.text + capturado.out + capturado.err
    assert '"logger": "gynfem.readiness"' in capturado.out, (
        "control positivo: el fallo debe registrarse, aunque sin detalles"
    )
    assert "psycopg" in registros, "control positivo: el pool también registra sus fallos"
    for prohibido in (*CENTINELAS, url, f"port {puerto}", f":{puerto}", '"127.0.0.1"'):
        assert prohibido not in registros, f"los logs exponen {prohibido!r}"


def test_ready_respeta_el_tiempo_limite(crear_app, servidor_mudo):
    """Una base que acepta la conexión y nunca responde no bloquea /health/ready."""
    app = crear_app(url_caida(servidor_mudo), db_pool_timeout_s="1", db_connect_timeout_s="2")

    with TestClient(app) as cliente:
        inicio = time.perf_counter()
        respuesta = cliente.get(READY)
        duracion = time.perf_counter() - inicio

    assert respuesta.status_code == 503
    assert duracion < 3.5, f"/health/ready tardó {duracion:.1f} s"


def test_el_log_de_readiness_registra_el_tipo_y_nunca_el_mensaje(crear_app, base_migrada, monkeypatch, capsys):
    """Cualquier error de la base se registra por su tipo: su mensaje puede nombrar host o usuario."""
    import app.services.readiness as readiness

    def fallar(conexion):
        raise psycopg.OperationalError(f"fallo en {CENTINELAS[0]}@{CENTINELAS[2]}")

    monkeypatch.setattr(readiness, "applied_migration_versions", fallar)
    with TestClient(crear_app(base_migrada)) as cliente:
        respuesta = cliente.get(READY)

    salida = capsys.readouterr().out
    assert respuesta.status_code == 503
    assert '"error_type": "OperationalError"' in salida, "control positivo: el tipo sí se registra"
    for centinela in CENTINELAS:
        assert centinela not in salida


# --- Autorrevisión de PR #8 --------------------------------------------------------


def test_el_pool_detecta_conexiones_muertas_con_keepalives(crear_app, base_migrada):
    """Una conexión abierta cuyo peer desaparece no debe colgar un worker hasta la
    retransmisión TCP del sistema: keepalives y `tcp_user_timeout` la acotan."""
    from app.db.pool import KEEPALIVES_COUNT, KEEPALIVES_IDLE_S, KEEPALIVES_INTERVAL_S

    app = crear_app(base_migrada, db_statement_timeout_ms="4000")
    with TestClient(app), app.state.db_pool.connection() as conexion:
        parametros = conninfo_to_dict(conexion.info.dsn)
    assert parametros["keepalives"] == "1"
    assert parametros["keepalives_idle"] == str(KEEPALIVES_IDLE_S)
    assert parametros["keepalives_interval"] == str(KEEPALIVES_INTERVAL_S)
    assert parametros["keepalives_count"] == str(KEEPALIVES_COUNT)
    assert int(parametros["tcp_user_timeout"]) > 4000, "no debe cortar una sentencia dentro de su límite"


def test_una_conexion_terminada_se_reemplaza_antes_de_entregarla(crear_app, base_migrada, servidor_pg):
    app = crear_app(base_migrada, db_pool_max_size="1")
    pool = app.state.db_pool
    with TestClient(app) as cliente:
        with pool.connection() as conexion:
            pid = conexion.info.backend_pid
        with psycopg.connect(servidor_pg, autocommit=True) as admin:
            admin.execute("SELECT pg_terminate_backend(%s)", [pid])
        respuesta = cliente.get(READY)

    assert respuesta.status_code == 200, "el pool debe descartar la conexión muerta y abrir otra"


def test_ready_503_si_la_base_va_adelantada(crear_app, base_migrada):
    """Una base con una migración que el código no conoce tampoco está lista para este código."""
    with psycopg.connect(base_migrada, autocommit=True) as conexion:
        conexion.execute(
            "INSERT INTO gynfem_migrations.schema_migrations (version, name, checksum) VALUES (999, 'futura', %s)",
            ["0" * 64],
        )
    with TestClient(crear_app(base_migrada)) as cliente:
        respuesta = cliente.get(READY)

    assert respuesta.status_code == 503
    error = _error(respuesta)
    assert error["code"] == "schema_outdated"
    assert "no coincide" in error["message"], "el mensaje no debe afirmar que la base está atrasada"
