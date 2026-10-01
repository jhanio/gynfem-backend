"""Migración 0009 (Fase 16): parámetros del sistema (HU011), de solo inserción.

Cada cambio de un parámetro es una **fila nueva** con su autor; el valor vigente
es la última fila de su clave. Nada se actualiza ni se borra, así que la tabla
conserva todos los valores anteriores. La auditoría admite la entidad
`system_setting`. Todo se comprueba en el PostgreSQL embebido.
"""

import uuid

import psycopg
import pytest

from .test_schema import ESQUEMA, insertar_parametro, insertar_perfil

INSERTAR = f"INSERT INTO {ESQUEMA}.system_settings (key, value, created_by) VALUES (%s, %s, %s)"
AUDITAR = (
    f"INSERT INTO {ESQUEMA}.audit_log (action, entity_type, outcome) "
    "VALUES ('system_setting.update', 'system_setting', 'success')"
)


@pytest.mark.parametrize(
    "asignacion", ["value = 'Otra'", "key = 'otra_clave'", "created_at = now()", "created_by = created_by"]
)
def test_un_parametro_guardado_no_se_reescribe(asignacion, conexion):
    identificador = insertar_parametro(conexion)

    with pytest.raises(psycopg.errors.RaiseException):
        conexion.execute(f"UPDATE {ESQUEMA}.system_settings SET {asignacion} WHERE id = %s", [identificador])
    assert conexion.execute(
        f"SELECT value FROM {ESQUEMA}.system_settings WHERE id = %s", [identificador]
    ).fetchone() == ("Institución de prueba",)


def test_cada_cambio_conserva_el_valor_anterior(conexion):
    primero = insertar_parametro(conexion, valor="Primera")
    segundo = insertar_parametro(conexion, valor="Segunda")

    assert segundo > primero
    assert conexion.execute(
        f"SELECT value FROM {ESQUEMA}.system_settings WHERE key = 'institution_name' ORDER BY id"
    ).fetchall() == [("Primera",), ("Segunda",)]


@pytest.mark.parametrize(
    "clave", ["", "Institution", "institution name", "1clave", "clave-con-guion", "temperature_c=36.8"]
)
def test_clave_con_formato_invalido_rechazada(clave, conexion):
    with pytest.raises(psycopg.errors.CheckViolation):
        conexion.execute(INSERTAR, [clave, "valor", insertar_perfil(conexion, "administrador")])


@pytest.mark.parametrize("valor", ["", "x" * 201])
def test_valor_vacio_o_demasiado_largo_rechazado(valor, conexion):
    with pytest.raises(psycopg.errors.CheckViolation):
        conexion.execute(INSERTAR, ["institution_name", valor, insertar_perfil(conexion, "administrador")])


def test_un_cambio_sin_autor_se_rechaza(conexion):
    with pytest.raises(psycopg.errors.NotNullViolation):
        conexion.execute(INSERTAR, ["institution_name", "valor", None])


def test_el_autor_de_un_cambio_es_un_usuario_con_perfil(conexion):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conexion.execute(INSERTAR, ["institution_name", "valor", uuid.uuid4()])


def test_la_auditoria_admite_la_entidad_system_setting(conexion):
    """Un parámetro no tiene id de entidad: se identifica por su clave en `changed_fields`."""
    conexion.execute(
        f"INSERT INTO {ESQUEMA}.audit_log (action, entity_type, outcome, actor_user_id, changed_fields) "
        "VALUES ('system_setting.update', 'system_setting', 'success', %s, %s)",
        [insertar_perfil(conexion, "administrador"), ["institution_name"]],
    )


def test_0009_revierte_aunque_la_auditoria_ya_tenga_registros_de_parametros(base_migrada, conexion):
    """Como en la 0008: las filas `'system_setting'` de la auditoría no se pueden borrar, así
    que la reversión no puede exigirles la restricción anterior."""
    from app.db.migrate import downgrade, upgrade

    conexion.execute(AUDITAR)

    assert downgrade(base_migrada, steps=1) == [9]
    with pytest.raises(psycopg.errors.CheckViolation):
        conexion.execute(AUDITAR)
    assert conexion.execute("SELECT to_regclass('gynfem.system_settings')").fetchone() == (None,)
    assert upgrade(base_migrada) == [9]
