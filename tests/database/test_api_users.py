"""HU002: el administrador crea, consulta, modifica, asigna rol, activa y desactiva usuarios.

Contra la aplicación completa y el PostgreSQL embebido. La Admin API de
Supabase se sustituye por `AdminFalso`, que escribe en el stub de `auth.users`
de la base del test (`auth_bd.py`). Correos sintéticos (`@example.com`).
"""

import uuid

import psycopg
import pytest

from api.api_constantes import ENTRADA_NORMAL

from .auth_bd import crear_usuario
from .conftest import filas

USUARIOS = "/api/v1/users"
UUID_INEXISTENTE = "00000000-0000-4000-8000-000000000000"
CLAVES_USUARIO = {"id", "email", "full_name", "role", "is_active", "created_at", "updated_at"}
NUEVO = {
    "email": "Medica.Nueva@Example.com",
    "password": "Temporal-De-Prueba-2026",
    "full_name": "Médica Nueva",
    "role": "medico",
}


def auditoria_de_usuarios(url: str) -> list[tuple]:
    return filas(
        url,
        "SELECT action, entity_type, entity_id, outcome, changed_fields, actor_user_id "
        "FROM gynfem.audit_log WHERE entity_type = 'user' ORDER BY id",
    )


def perfiles(url: str) -> list[tuple]:
    return filas(url, "SELECT id, role, is_active, full_name FROM gynfem.user_profiles ORDER BY created_at, id")


def crear(cliente, **cambios) -> dict:
    respuesta = cliente.post(USUARIOS, json={**NUEVO, **cambios})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


@pytest.fixture
def admin(cliente_bd):
    return cliente_bd(rol="administrador")


# --- Crear ---------------------------------------------------------------------------


def test_admin_crea_usuario_201(admin, admin_falso, base_migrada, usuarios):
    cuerpo = crear(admin)

    assert set(cuerpo) == CLAVES_USUARIO
    assert (cuerpo["email"], cuerpo["full_name"], cuerpo["role"], cuerpo["is_active"]) == (
        "medica.nueva@example.com", "Médica Nueva", "medico", True,
    )
    assert admin_falso.creados == [("medica.nueva@example.com", NUEVO["password"])]
    assert filas(base_migrada, "SELECT role, is_active, created_by FROM gynfem.user_profiles WHERE id = %s",
                 [cuerpo["id"]]) == [("medico", True, usuarios["administrador"])]
    assert auditoria_de_usuarios(base_migrada) == [
        ("user.create", "user", uuid.UUID(cuerpo["id"]), "success", None, usuarios["administrador"])
    ]


def test_la_contrasena_no_vuelve_en_la_respuesta(admin):
    respuesta = admin.post(USUARIOS, json=NUEVO)

    assert NUEVO["password"] not in respuesta.text
    assert "password" not in respuesta.json()


def test_crear_usuario_con_correo_existente_409(admin, admin_falso, base_migrada):
    crear(admin)
    antes = perfiles(base_migrada)
    respuesta = admin.post(USUARIOS, json={**NUEVO, "email": "medica.nueva@example.com"})

    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["code"] == "user_already_exists"
    assert perfiles(base_migrada) == antes


@pytest.mark.parametrize(
    "cambios",
    [
        {"password": "corta-11car"},
        {"password": "x" * 73},
        {"email": "sin-arroba.example.com"},
        {"email": "dos@@example.com"},
        {"email": "a@b"},
        {"role": "superusuario"},
        {"role": "Administrador"},
        {"full_name": ""},
        {"full_name": "Nombre 123"},
        {"is_active": False},
        {"id": UUID_INEXISTENTE},
    ],
)
def test_crear_usuario_con_entrada_invalida_422_sin_llamar_a_supabase(cambios, admin, admin_falso):
    respuesta = admin.post(USUARIOS, json={**NUEVO, **cambios})

    assert respuesta.status_code == 422
    assert admin_falso.creados == []
    for valor in cambios.values():
        if isinstance(valor, str) and len(valor) > 3:
            assert valor not in respuesta.text


def test_supabase_caido_503_sin_escribir(admin, admin_falso, base_migrada):
    from app.auth.errors import AuthUnavailable

    admin_falso.fallar_con = AuthUnavailable()
    antes = perfiles(base_migrada)
    respuesta = admin.post(USUARIOS, json=NUEVO)

    assert respuesta.status_code == 503
    assert respuesta.json()["error"]["code"] == "auth_unavailable"
    assert perfiles(base_migrada) == antes
    assert auditoria_de_usuarios(base_migrada) == []


def test_si_falla_la_base_se_borra_el_usuario_creado_en_supabase(admin, admin_falso, base_migrada, monkeypatch):
    """Compensación: no queda un usuario de Auth huérfano, sin perfil."""
    from app.repositories import users as users_repo

    def fallar(*args, **kwargs):
        raise psycopg.OperationalError("caída simulada")

    monkeypatch.setattr(users_repo, "insert_profile", fallar)
    respuesta = admin.post(USUARIOS, json=NUEVO)

    assert respuesta.status_code == 503
    assert len(admin_falso.creados) == 1
    assert len(admin_falso.borrados) == 1
    assert filas(base_migrada, "SELECT count(*) FROM auth.users WHERE email = %s", ["medica.nueva@example.com"]) == [(0,)]


def test_contrasena_debil_segun_supabase_422(admin, admin_falso):
    from app.services.errors import WeakPassword

    admin_falso.fallar_con = WeakPassword()
    respuesta = admin.post(USUARIOS, json=NUEVO)

    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["code"] == "weak_password"


# --- Consultar -------------------------------------------------------------------------


def test_listar_usuarios_paginado_con_correo(admin, usuarios):
    creado = crear(admin)
    primera = admin.get(USUARIOS, params={"limit": 2, "offset": 0}).json()
    segunda = admin.get(USUARIOS, params={"limit": 2, "offset": 2}).json()

    assert set(primera) == {"items", "limit", "offset", "has_more"}
    assert primera["has_more"] is True and segunda["has_more"] is False
    todos = primera["items"] + segunda["items"]
    assert {u["id"] for u in todos} == {str(usuarios["medico"]), str(usuarios["administrador"]), creado["id"]}
    assert all(set(u) == CLAVES_USUARIO for u in todos)
    assert any(u["email"] == "medica.nueva@example.com" for u in todos)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 51}, {"offset": -1}])
def test_listar_con_paginacion_invalida_422(params, admin):
    assert admin.get(USUARIOS, params=params).status_code == 422


def test_consultar_usuario(admin):
    creado = crear(admin)
    assert admin.get(f"{USUARIOS}/{creado['id']}").json() == creado


def test_consultar_inexistente_404(admin):
    respuesta = admin.get(f"{USUARIOS}/{UUID_INEXISTENTE}")

    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "user_not_found"


# --- Modificar y asignar rol -----------------------------------------------------------------


def test_asignar_rol_audita_solo_el_nombre_del_campo(admin, base_migrada, usuarios):
    creado = crear(admin)
    respuesta = admin.patch(f"{USUARIOS}/{creado['id']}", json={"role": "administrador"})

    assert respuesta.status_code == 200
    assert respuesta.json()["role"] == "administrador"
    assert auditoria_de_usuarios(base_migrada)[-1] == (
        "user.update", "user", uuid.UUID(creado["id"]), "success", ["role"], usuarios["administrador"],
    )
    assert filas(base_migrada, "SELECT updated_by FROM gynfem.user_profiles WHERE id = %s",
                 [creado["id"]]) == [(usuarios["administrador"],)]


def test_modificar_nombre(admin, base_migrada):
    creado = crear(admin)
    respuesta = admin.patch(f"{USUARIOS}/{creado['id']}", json={"full_name": "  Médica   Renombrada "})

    assert respuesta.json()["full_name"] == "Médica Renombrada"
    assert auditoria_de_usuarios(base_migrada)[-1][4] == ["full_name"]
    assert "Renombrada" not in repr(auditoria_de_usuarios(base_migrada))


@pytest.mark.parametrize(
    "cuerpo", [{}, {"is_active": False}, {"email": "otro@example.com"}, {"role": "x"}, {"password": "Nueva-Clave-2026"}]
)
def test_modificar_con_cuerpo_invalido_422(cuerpo, admin):
    creado = crear(admin)
    assert admin.patch(f"{USUARIOS}/{creado['id']}", json=cuerpo).status_code == 422


def test_modificar_inexistente_404(admin):
    assert admin.patch(f"{USUARIOS}/{UUID_INEXISTENTE}", json={"full_name": "Nadie"}).status_code == 404


# --- Activar y desactivar ----------------------------------------------------------------------


def test_desactivar_y_activar_auditados(admin, base_migrada, usuarios):
    creado = crear(admin)
    desactivado = admin.post(f"{USUARIOS}/{creado['id']}/deactivate")
    activado = admin.post(f"{USUARIOS}/{creado['id']}/activate")

    assert (desactivado.status_code, desactivado.json()["is_active"]) == (200, False)
    assert (activado.status_code, activado.json()["is_active"]) == (200, True)
    assert [f[0] for f in auditoria_de_usuarios(base_migrada)] == ["user.create", "user.deactivate", "user.activate"]
    assert {f[5] for f in auditoria_de_usuarios(base_migrada)} == {usuarios["administrador"]}


@pytest.mark.parametrize("accion", ["activate", "deactivate"])
def test_activar_o_desactivar_inexistente_404(accion, admin):
    assert admin.post(f"{USUARIOS}/{UUID_INEXISTENTE}/{accion}").status_code == 404


def test_el_token_de_un_usuario_desactivado_deja_de_servir(admin, cliente_bd, token_de):
    """Decisión 8: el token sigue siendo válido, pero el backend lo rechaza desde la siguiente petición."""
    creado = crear(admin)
    medico = cliente_bd(rol=None)
    medico.headers.update(token_de(uuid.UUID(creado["id"])))
    assert medico.post("/api/v1/predict", json=ENTRADA_NORMAL).status_code == 200

    admin.post(f"{USUARIOS}/{creado['id']}/deactivate")
    respuesta = medico.post("/api/v1/predict", json=ENTRADA_NORMAL)
    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["code"] == "account_disabled"

    admin.post(f"{USUARIOS}/{creado['id']}/activate")
    assert medico.post("/api/v1/predict", json=ENTRADA_NORMAL).status_code == 200


def test_el_rol_asignado_rige_desde_la_siguiente_peticion(admin, cliente_bd, token_de):
    creado = crear(admin)
    usuario = cliente_bd(rol=None)
    usuario.headers.update(token_de(uuid.UUID(creado["id"])))
    assert usuario.get(USUARIOS).status_code == 403

    admin.patch(f"{USUARIOS}/{creado['id']}", json={"role": "administrador"})
    assert usuario.get(USUARIOS).status_code == 200


# --- Nunca sin administrador ---------------------------------------------------------------


def test_no_se_puede_desactivar_al_ultimo_administrador_activo(admin, usuarios, base_migrada):
    respuesta = admin.post(f"{USUARIOS}/{usuarios['administrador']}/deactivate")

    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["code"] == "last_active_admin"
    assert filas(base_migrada, "SELECT is_active FROM gynfem.user_profiles WHERE id = %s",
                 [usuarios["administrador"]]) == [(True,)]


def test_no_se_puede_degradar_al_ultimo_administrador_activo(admin, usuarios):
    respuesta = admin.patch(f"{USUARIOS}/{usuarios['administrador']}", json={"role": "medico"})

    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["code"] == "last_active_admin"


def test_con_otro_administrador_activo_si_se_puede(admin, usuarios, base_migrada):
    crear_usuario(base_migrada, "administrador")
    assert admin.patch(f"{USUARIOS}/{usuarios['administrador']}", json={"role": "medico"}).status_code == 200


def test_un_administrador_inactivo_no_cuenta_como_respaldo(admin, usuarios, base_migrada):
    crear_usuario(base_migrada, "administrador", activo=False)
    assert admin.post(f"{USUARIOS}/{usuarios['administrador']}/deactivate").status_code == 409


def test_modificar_el_nombre_del_ultimo_administrador_si_se_puede(admin, usuarios):
    assert admin.patch(f"{USUARIOS}/{usuarios['administrador']}", json={"full_name": "Admin Renombrada"}).status_code == 200


# --- Solo el administrador ------------------------------------------------------------------


def test_gestion_de_usuarios_solo_para_el_administrador(cliente_bd, admin, admin_falso, usuarios):
    creado = crear(admin)
    medico = cliente_bd(rol="medico")
    anonimo = cliente_bd(rol=None)
    rutas = [
        ("POST", USUARIOS, {**NUEVO, "email": "otra@example.com"}),
        ("GET", USUARIOS, None),
        ("GET", f"{USUARIOS}/{creado['id']}", None),
        ("PATCH", f"{USUARIOS}/{creado['id']}", {"role": "administrador"}),
        ("POST", f"{USUARIOS}/{creado['id']}/deactivate", None),
        ("POST", f"{USUARIOS}/{creado['id']}/activate", None),
    ]
    for metodo, ruta, cuerpo in rutas:
        assert medico.request(metodo, ruta, json=cuerpo).status_code == 403, f"{metodo} {ruta}"
        assert anonimo.request(metodo, ruta, json=cuerpo).status_code == 401, f"{metodo} {ruta}"
    assert len(admin_falso.creados) == 1
    assert admin.get(f"{USUARIOS}/{creado['id']}").json()["role"] == "medico"


def test_el_medico_no_se_puede_elevar_a_si_mismo(cliente_bd, usuarios, base_migrada):
    medico = cliente_bd(rol="medico")
    respuesta = medico.patch(f"{USUARIOS}/{usuarios['medico']}", json={"role": "administrador"})

    assert respuesta.status_code == 403
    assert filas(base_migrada, "SELECT role FROM gynfem.user_profiles WHERE id = %s",
                 [usuarios["medico"]]) == [("medico",)]


def test_me_con_la_base(cliente_bd, usuarios):
    assert cliente_bd(rol="medico").get("/api/v1/me").json() == {"id": str(usuarios["medico"]), "role": "medico"}
