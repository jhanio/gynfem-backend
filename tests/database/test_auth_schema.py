"""Migración 0008 (Fase 11): perfiles de usuario, actor con clave foránea y RLS definitivo.

Todo se comprueba en el catálogo y con consultas reales del PostgreSQL
embebido. RLS se prueba por su **efecto**: aunque un `GRANT` equivocado diera
privilegios a los roles de la Data API, no verían ni escribirían una fila.
"""

import uuid

import psycopg
import pytest

from .test_schema import (
    ESQUEMA,
    ESQUEMAS_PROPIOS,
    columnas,
    insertar_auditoria,
    insertar_paciente,
    insertar_perfil,
    tablas_propias,
)

ROLES_DE_LA_DATA_API = ("anon", "authenticated")


def test_rol_invalido_rechazado(conexion):
    usuario = uuid.uuid4()
    conexion.execute("INSERT INTO auth.users (id) VALUES (%s)", [usuario])
    for rol in ("superusuario", "Medico", "admin", ""):
        with pytest.raises(psycopg.errors.CheckViolation):
            conexion.execute(
                f"INSERT INTO {ESQUEMA}.user_profiles (id, role, full_name) VALUES (%s, %s, 'Prueba')", [usuario, rol]
            )


@pytest.mark.parametrize("nombre", ["", "   ", "x" * 101])
def test_nombre_vacio_o_largo_rechazado(nombre, conexion):
    usuario = uuid.uuid4()
    conexion.execute("INSERT INTO auth.users (id) VALUES (%s)", [usuario])
    with pytest.raises(psycopg.errors.CheckViolation):
        conexion.execute(
            f"INSERT INTO {ESQUEMA}.user_profiles (id, role, full_name) VALUES (%s, 'medico', %s)", [usuario, nombre]
        )


def test_perfil_exige_usuario_de_supabase_auth(conexion):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conexion.execute(
            f"INSERT INTO {ESQUEMA}.user_profiles (id, role, full_name) VALUES (%s, 'medico', 'Prueba')",
            [uuid.uuid4()],
        )


def test_usuario_con_perfil_no_se_borra_de_auth(conexion):
    perfil = insertar_perfil(conexion)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conexion.execute("DELETE FROM auth.users WHERE id = %s", [perfil])


def test_el_perfil_no_guarda_correo_ni_contrasena(conexion):
    """El correo vive solo en `auth.users` (una fuente) y la contraseña solo en Supabase."""
    nombres = set(columnas(conexion, "user_profiles"))
    assert not {n for n in nombres if any(p in n for p in ("mail", "pass", "hash", "secret", "token"))}


def test_estado_por_defecto_activo(conexion):
    perfil = insertar_perfil(conexion)
    assert conexion.execute(
        f"SELECT is_active FROM {ESQUEMA}.user_profiles WHERE id = %s", [perfil]
    ).fetchone() == (True,)


def test_created_del_perfil_es_inmutable(conexion):
    perfil = insertar_perfil(conexion)
    otro = insertar_perfil(conexion)
    for asignacion in ("created_at = now() - interval '1 day'", f"created_by = '{otro}'"):
        with pytest.raises(psycopg.errors.RaiseException):
            conexion.execute(f"UPDATE {ESQUEMA}.user_profiles SET {asignacion} WHERE id = %s", [perfil])


def test_rol_y_estado_del_perfil_se_pueden_cambiar(conexion):
    perfil = insertar_perfil(conexion)
    conexion.execute(
        f"UPDATE {ESQUEMA}.user_profiles SET role = 'administrador', is_active = false WHERE id = %s", [perfil]
    )
    assert conexion.execute(
        f"SELECT role, is_active FROM {ESQUEMA}.user_profiles WHERE id = %s", [perfil]
    ).fetchone() == ("administrador", False)


@pytest.mark.parametrize(
    "sentencia",
    [
        f"INSERT INTO {ESQUEMA}.patients (document_type, document_number, given_names, family_names, search_key, created_by) "
        "VALUES ('DNI', '00000077', 'Sintética', 'Prueba', ' sintetica prueba ', %s)",
        f"INSERT INTO {ESQUEMA}.audit_log (action, entity_type, outcome, actor_user_id) "
        "VALUES ('patient.create', 'patient', 'success', %s)",
    ],
)
def test_actor_sin_perfil_viola_la_clave_foranea(sentencia, conexion):
    """Nadie puede figurar como autor de un registro si no es un usuario con perfil."""
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conexion.execute(sentencia, [uuid.uuid4()])
    conexion.execute(sentencia, [insertar_perfil(conexion)])


def test_la_auditoria_admite_la_entidad_user(conexion):
    perfil = insertar_perfil(conexion, "administrador")
    conexion.execute(
        f"INSERT INTO {ESQUEMA}.audit_log (action, entity_type, entity_id, outcome, actor_user_id) "
        "VALUES ('user.create', 'user', %s, 'success', %s)",
        [insertar_perfil(conexion), perfil],
    )


# --- Políticas RLS definitivas -------------------------------------------------------


def politicas(conexion) -> list[tuple]:
    return conexion.execute(
        "SELECT schemaname, tablename, policyname, permissive, roles::text[], cmd, qual, with_check "
        "FROM pg_policies WHERE schemaname = ANY(%s) ORDER BY schemaname, tablename",
        [list(ESQUEMAS_PROPIOS)],
    ).fetchall()


def test_politicas_rls_definitivas(conexion):
    """Una política restrictiva de denegación total para la Data API por tabla, y ninguna permisiva.

    Una política permisiva es la única forma de que RLS y el RBAC de la
    aplicación se contradigan (docs/SECURITY.md): cualquiera hace fallar este test.
    """
    tablas = sorted(tablas_propias(conexion))
    encontradas = politicas(conexion)

    assert sorted((e, t) for e, t, *_ in encontradas) == tablas
    for esquema, tabla, nombre, permisiva, roles, comando, usando, comprobacion in encontradas:
        assert nombre == f"{tabla}_deny_data_api", f"{esquema}.{tabla}"
        assert permisiva == "RESTRICTIVE", f"{esquema}.{tabla}"
        assert sorted(roles) == sorted(ROLES_DE_LA_DATA_API), f"{esquema}.{tabla}"
        assert comando == "ALL", f"{esquema}.{tabla}"
        assert (usando, comprobacion) == ("false", "false"), f"{esquema}.{tabla}"


@pytest.mark.parametrize("permisiva", [False, True], ids=["sin_politica_permisiva", "con_politica_permisiva"])
@pytest.mark.parametrize("rol", ROLES_DE_LA_DATA_API)
def test_rls_niega_aunque_se_concedan_privilegios(rol, permisiva, conexion):
    """Simula un `GRANT` por error y, en el segundo caso, además una política permisiva
    `USING (true)` añadida por error: la restrictiva sigue sin dejar ver ni escribir una
    fila. Sin la restrictiva, el segundo caso lo dejaría ver todo."""
    insertar_paciente(conexion)
    insertar_perfil(conexion)
    insertar_auditoria(conexion)
    for esquema in ESQUEMAS_PROPIOS:
        conexion.execute(f"GRANT USAGE ON SCHEMA {esquema} TO {rol}")
        conexion.execute(f"GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA {esquema} TO {rol}")
    tablas = tablas_propias(conexion)
    if permisiva:
        for esquema, tabla in tablas:
            conexion.execute(
                f"CREATE POLICY abierta_por_error ON {esquema}.{tabla} FOR ALL TO {rol} USING (true) WITH CHECK (true)"
            )

    conexion.execute(f"SET ROLE {rol}")
    try:
        for esquema, tabla in tablas:
            assert conexion.execute(f"SELECT count(*) FROM {esquema}.{tabla}").fetchone() == (0,), f"{esquema}.{tabla}"
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conexion.execute(
                f"INSERT INTO {ESQUEMA}.patients (document_type, document_number, given_names, family_names, search_key) "
                "VALUES ('DNI', '00000088', 'Sintética', 'Prueba', ' sintetica prueba ')"
            )
    finally:
        conexion.execute("RESET ROLE")
    assert conexion.execute(f"SELECT count(*) FROM {ESQUEMA}.patients").fetchone() == (1,), "control: hay datos"


def test_0008_revierte_aunque_la_auditoria_ya_tenga_registros_de_usuarios(base_migrada, conexion):
    """La auditoría es de solo inserción: sus filas `'user'` no se pueden borrar, así que la
    reversión no puede exigirles la restricción anterior. Encontrado al revertir en Supabase."""
    from app.db.migrate import downgrade, upgrade

    perfil = insertar_perfil(conexion, "administrador")
    conexion.execute(
        f"INSERT INTO {ESQUEMA}.audit_log (action, entity_type, entity_id, outcome) "
        "VALUES ('user.bootstrap_admin', 'user', %s, 'success')",
        [perfil],
    )

    # La 0009 (Fase 16) va encima: se revierten las dos.
    assert downgrade(base_migrada, steps=2) == [9, 8]
    # Las filas nuevas vuelven a exigir las entidades anteriores a la 0008.
    with pytest.raises(psycopg.errors.CheckViolation):
        conexion.execute(
            f"INSERT INTO {ESQUEMA}.audit_log (action, entity_type, outcome) VALUES ('user.create', 'user', 'success')"
        )
    assert upgrade(base_migrada) == [8, 9]
