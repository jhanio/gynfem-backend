"""Fixtures de la suite de base de datos.

Sin red y sin la Supabase real: un PostgreSQL embebido (`pgserver`, de
`requirements-dev.txt`) arranca **una vez por sesión** en un directorio
temporal y escucha solo en `127.0.0.1`. Cada test recibe su propia base de
datos, creada y destruida alrededor del test.

Supabase trae los roles `anon`, `authenticated` y `service_role`; un
PostgreSQL vacío no. Se crean aquí, sin login, para que las migraciones
(que les revocan privilegios) se prueben tal como correrán en Supabase.
Tampoco trae `auth.users`, al que apuntan los perfiles desde la Fase 11: se
crea un stub mínimo en `template1` (`auth_bd.py`), que cada base hereda.

Las fixtures de entorno y del modelo se reutilizan de `tests/api/conftest.py`:
la variable `GYNFEM_*` del shell tampoco llega a esta suite.
"""

import socket
import threading
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from api.conftest import configurar, emisor, entorno_limpio, modelo_real  # noqa: F401

from .auth_bd import STUB_AUTH_USERS, AdminFalso, crear_usuario

ROLES_DE_SUPABASE = ("anon", "authenticated", "service_role")
HOSTS_LOOPBACK = {"127.0.0.1", "localhost"}


def url_de(conninfo: str, dbname: str) -> str:
    """URL `postgresql://` hacia `dbname` en el servidor embebido."""
    datos = conninfo_to_dict(conninfo)
    return f"postgresql://{datos['user']}@{datos['host']}:{datos['port']}/{dbname}"


@pytest.fixture(scope="session")
def servidor_pg(tmp_path_factory):
    """URL de la base `postgres` del servidor embebido."""
    import pgserver

    servidor = pgserver.get_server(tmp_path_factory.mktemp("pgdata"), cleanup_mode="stop")
    uri = servidor.get_uri()
    assert conninfo_to_dict(uri)["host"] in HOSTS_LOOPBACK
    with psycopg.connect(uri, autocommit=True) as conexion:
        for rol in ROLES_DE_SUPABASE:
            conexion.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(rol)))
    with psycopg.connect(url_de(uri, "template1"), autocommit=True) as conexion:
        conexion.execute(STUB_AUTH_USERS)
    yield uri
    servidor.cleanup()


@pytest.fixture
def base_vacia(servidor_pg) -> str:
    """URL de una base de datos nueva y vacía, solo para este test."""
    nombre = f"t_{uuid.uuid4().hex[:16]}"
    with psycopg.connect(servidor_pg, autocommit=True) as conexion:
        conexion.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nombre)))
    yield url_de(servidor_pg, nombre)
    with psycopg.connect(servidor_pg, autocommit=True) as conexion:
        conexion.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(nombre))
        )


@pytest.fixture
def base_migrada(base_vacia) -> str:
    """URL de una base con todas las migraciones del repositorio aplicadas."""
    from app.db.migrate import upgrade

    upgrade(base_vacia)
    return base_vacia


@pytest.fixture
def conexion(base_migrada):
    """Conexión en autocommit a la base migrada."""
    with psycopg.connect(base_migrada, autocommit=True) as c:
        yield c


def puerto_cerrado() -> int:
    """Un puerto de loopback en el que nadie escucha."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def servidor_mudo():
    """Puerto de loopback que acepta conexiones y nunca responde."""
    oyente = socket.socket()
    oyente.bind(("127.0.0.1", 0))
    oyente.listen()
    aceptadas: list[socket.socket] = []
    parar = threading.Event()

    def aceptar() -> None:
        oyente.settimeout(0.2)
        while not parar.is_set():
            try:
                aceptadas.append(oyente.accept()[0])
            except OSError:
                continue

    hilo = threading.Thread(target=aceptar, daemon=True)
    hilo.start()
    yield oyente.getsockname()[1]
    parar.set()
    hilo.join(timeout=2)
    for s in aceptadas:
        s.close()
    oyente.close()


# --- Fase 10: la aplicación completa contra la base embebida -------------------------

from api.conftest import espia, modelo_espiado  # noqa: E402,F401


@pytest.fixture
def usuarios(base_migrada) -> dict[str, "uuid.UUID"]:
    """Un médico y un administrador activos, con perfil en la base del test."""
    from api.auth_claves import ADMIN_ID, ADMINISTRADOR, MEDICO, MEDICO_ID

    return {
        MEDICO: crear_usuario(base_migrada, MEDICO, user_id=MEDICO_ID, nombre="Médica Prueba"),
        ADMINISTRADOR: crear_usuario(base_migrada, ADMINISTRADOR, user_id=ADMIN_ID, nombre="Admin Prueba"),
    }


@pytest.fixture
def admin_falso(base_migrada) -> AdminFalso:
    return AdminFalso(base_migrada)


@pytest.fixture
def token_de(emisor):
    """`token_de(user_id)` → cabecera `Authorization` con un token firmado en la sesión."""
    from api.auth_claves import cabecera

    return lambda user_id: cabecera(emisor.token(user_id))


@pytest.fixture
def cliente_bd(base_migrada, configurar, modelo_real, emisor, usuarios, admin_falso, token_de):
    """`TestClient` con el ciclo de vida abierto (pool conectado a la base migrada).

    Autenticación real: el token lo firma la clave de la sesión y el rol y el
    estado se leen de `gynfem.user_profiles` en cada petición, como en
    producción. Por defecto envía el token del médico; `cliente_bd(rol=…)` elige
    otro, y `rol=None` no envía ninguno. `cliente_bd(modelo=…)` permite inyectar
    un modelo espiado. Se cierra al terminar el test.
    """
    from fastapi.testclient import TestClient

    from api.auth_claves import EMISOR_FICTICIO, FuenteDeClavesEnMemoria
    from app.auth.tokens import TokenVerifier
    from app.factory import create_app

    abiertos = []

    def _crear(modelo=None, rol: str | None = "medico"):
        configurar(environment="development", cors_origins="http://localhost:5173", database_url=base_migrada)
        app = create_app(
            model=modelo or modelo_real,
            token_verifier=TokenVerifier(FuenteDeClavesEnMemoria(emisor), EMISOR_FICTICIO),
            auth_admin=admin_falso,
        )
        cliente = TestClient(app, raise_server_exceptions=False)
        cliente.__enter__()
        if rol is not None:
            cliente.headers.update(token_de(usuarios[rol]))
        abiertos.append(cliente)
        return cliente

    yield _crear
    for cliente in abiertos:
        cliente.__exit__(None, None, None)
    import logging

    logging.getLogger("gynfem").handlers.clear()


def filas(url: str, consulta: str, parametros=()) -> list[tuple]:
    """Consulta directa a la base, fuera de la aplicación."""
    with psycopg.connect(url) as c:
        return c.execute(consulta, parametros).fetchall()
