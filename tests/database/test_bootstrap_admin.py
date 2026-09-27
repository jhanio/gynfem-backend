"""Creación del primer administrador (decisión E): `python -m app.auth.bootstrap`.

Con el registro público cerrado, es la única forma de entrar a una base limpia
(también en Render, Fase 12). Reproducible: se niega si ya hay un administrador
activo, y reutiliza un usuario de Auth que ya exista (recuperación tras un fallo
a medias). La contraseña se lee sin eco y nunca se imprime.
"""

import io
import uuid

import pytest

from .auth_bd import crear_usuario
from .conftest import filas

CORREO = "primera.admin@example.com"
CONTRASENA = "Primera-Admin-Prueba-2026"


@pytest.fixture
def ejecutar(base_migrada, configurar, admin_falso, monkeypatch, capsys):
    """Ejecuta la CLI con el entorno del test; devuelve (código, stdout, stderr)."""
    from app.auth import bootstrap

    def _ejecutar(*argumentos: str, contrasenas=(CONTRASENA, CONTRASENA), stdin: str | None = None):
        configurar(environment="development", cors_origins="http://localhost:5173", database_url=base_migrada)
        respuestas = iter(contrasenas)
        pedidas = []
        monkeypatch.setattr(bootstrap.getpass, "getpass", lambda prompt="": pedidas.append(prompt) or next(respuestas))
        if stdin is not None:
            monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        codigo = bootstrap.main(["--email", CORREO, "--full-name", "Primera Admin", *argumentos], admin=admin_falso)
        salida = capsys.readouterr()
        return codigo, salida.out, salida.err, pedidas

    return _ejecutar


def administradores(url: str) -> list[tuple]:
    return filas(url, "SELECT id, is_active, full_name FROM gynfem.user_profiles WHERE role = 'administrador'")


def test_crea_el_primer_administrador(ejecutar, base_migrada, admin_falso):
    codigo, salida, error, pedidas = ejecutar()

    assert codigo == 0, error
    [(admin_id, activo, nombre)] = administradores(base_migrada)
    assert (activo, nombre) == (True, "Primera Admin")
    assert admin_falso.creados == [(CORREO, CONTRASENA)]
    assert str(admin_id) in salida
    assert len(pedidas) == 2, "la contraseña se pide dos veces, sin eco"
    assert filas(base_migrada, "SELECT action, entity_type, entity_id, actor_user_id FROM gynfem.audit_log") == [
        ("user.bootstrap_admin", "user", admin_id, None)
    ]


def test_no_imprime_el_correo_ni_la_contrasena(ejecutar):
    _, salida, error, _ = ejecutar()

    for fuga in (CORREO, CONTRASENA):
        assert fuga not in salida and fuga not in error


def test_se_niega_si_ya_hay_un_administrador_activo(ejecutar, base_migrada, admin_falso):
    crear_usuario(base_migrada, "administrador")
    codigo, _, error, pedidas = ejecutar()

    assert codigo == 1
    assert "ya existe un administrador activo" in error
    assert admin_falso.creados == []
    assert pedidas == [], "no pide la contraseña si no va a crear nada"
    assert len(administradores(base_migrada)) == 1


def test_un_administrador_inactivo_no_impide_el_procedimiento(ejecutar, base_migrada):
    crear_usuario(base_migrada, "administrador", activo=False)
    assert ejecutar()[0] == 0


def test_reutiliza_un_usuario_de_auth_existente_sin_pedir_contrasena(ejecutar, base_migrada, admin_falso):
    """Recuperación: la base se limpió (o falló a medias), pero el usuario sigue en Supabase Auth."""
    existente = uuid.uuid4()
    filas(base_migrada, "INSERT INTO auth.users (id, email) VALUES (%s, %s) RETURNING id", [existente, CORREO.upper()])
    codigo, salida, _, pedidas = ejecutar()

    assert codigo == 0
    assert admin_falso.creados == []
    assert pedidas == []
    assert administradores(base_migrada) == [(existente, True, "Primera Admin")]
    assert str(existente) in salida


def test_restablece_como_administrador_un_perfil_existente(ejecutar, base_migrada):
    """Si todos los administradores se perdieron, un usuario existente vuelve a serlo."""
    usuario = crear_usuario(base_migrada, "medico", activo=False, email=CORREO)
    assert ejecutar()[0] == 0
    assert administradores(base_migrada) == [(usuario, True, "Primera Admin")]


def test_contrasenas_distintas_no_crean_nada(ejecutar, base_migrada, admin_falso):
    codigo, _, error, _ = ejecutar(contrasenas=(CONTRASENA, CONTRASENA + "x"))

    assert codigo == 1
    assert "no coinciden" in error
    assert admin_falso.creados == []
    assert administradores(base_migrada) == []


@pytest.mark.parametrize("contrasena", ["corta-11car", "x" * 73])
def test_contrasena_fuera_de_longitud_no_crea_nada(contrasena, ejecutar, admin_falso):
    codigo, _, error, _ = ejecutar(contrasenas=(contrasena, contrasena))

    assert codigo == 1
    assert "12" in error and "72" in error
    assert admin_falso.creados == []


def test_password_stdin_para_automatizar(ejecutar, base_migrada, admin_falso):
    codigo, _, _, pedidas = ejecutar("--password-stdin", stdin=f"{CONTRASENA}\n")

    assert codigo == 0
    assert pedidas == []
    assert admin_falso.creados == [(CORREO, CONTRASENA)]


def test_si_falla_la_base_se_borra_el_usuario_creado(ejecutar, base_migrada, admin_falso, monkeypatch):
    import psycopg

    from app.repositories import users as users_repo

    def fallar(*args, **kwargs):
        raise psycopg.OperationalError("caída simulada")

    monkeypatch.setattr(users_repo, "upsert_admin_profile", fallar)
    codigo, _, error, _ = ejecutar()

    assert codigo == 1
    assert len(admin_falso.borrados) == 1
    assert "caída simulada" not in error
    assert administradores(base_migrada) == []


def test_sin_la_migracion_0008_explica_que_falta(base_vacia, configurar, capsys):
    from app.auth import bootstrap
    from app.db.migrate import upgrade

    from .auth_bd import AdminFalso

    admin_falso = AdminFalso(base_vacia)  # no la fixture: pediría `base_migrada`, que migra todo

    upgrade(base_vacia, target=7)
    configurar(environment="development", cors_origins="http://localhost:5173", database_url=base_vacia)
    codigo = bootstrap.main(["--email", CORREO, "--full-name", "Primera Admin"], admin=admin_falso)

    assert codigo == 1
    assert "migraciones" in capsys.readouterr().err
    assert admin_falso.creados == []
