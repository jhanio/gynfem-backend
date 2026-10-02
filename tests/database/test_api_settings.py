"""HU011: el administrador configura los parámetros básicos sin tocar código.

Contra la aplicación completa y el PostgreSQL embebido. El catálogo es cerrado y
no clínico. Cada cambio inserta una fila en `gynfem.system_settings` y su
registro de auditoría en la misma transacción; en la auditoría y en los logs va
solo el **nombre** de la clave, nunca el valor.
"""

import logging

import pytest

from api.auth_claves import ADMIN_ID

from .conftest import filas

CONFIGURACION = "/api/v1/settings"
CLAVES = {"institution_name", "history_default_page_size"}
CLAVES_DE_UN_PARAMETRO = {"value", "default", "updated_at", "updated_by"}
#: Texto reconocible que nunca debe verse en un log ni en una fila de auditoría.
CENTINELA = "Centinelainstitucion Zeta"


def parametros_guardados(url: str) -> list[tuple]:
    return filas(url, "SELECT key, value, created_by FROM gynfem.system_settings ORDER BY id")


def auditoria(url: str) -> list[tuple]:
    return filas(
        url,
        "SELECT action, entity_type, entity_id, outcome, changed_fields, actor_user_id "
        "FROM gynfem.audit_log ORDER BY id",
    )


@pytest.fixture
def admin(cliente_bd):
    return cliente_bd(rol="administrador")


# --- Consultar -------------------------------------------------------------------------


def test_sin_cambios_rigen_los_valores_por_defecto(admin, base_migrada):
    from app.services.settings_catalog import VALORES_POR_DEFECTO

    respuesta = admin.get(CONFIGURACION)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert set(cuerpo) == CLAVES
    for clave, parametro in cuerpo.items():
        assert set(parametro) == CLAVES_DE_UN_PARAMETRO, clave
        assert parametro["value"] == parametro["default"] == VALORES_POR_DEFECTO[clave], clave
        assert (parametro["updated_at"], parametro["updated_by"]) == (None, None), clave
    assert parametros_guardados(base_migrada) == []


def test_el_catalogo_es_cerrado_y_su_paginacion_por_defecto_es_la_de_la_api():
    from app.schemas.pagination import LIMITE_POR_DEFECTO
    from app.services.settings_catalog import VALORES_POR_DEFECTO

    assert set(VALORES_POR_DEFECTO) == CLAVES
    assert VALORES_POR_DEFECTO["history_default_page_size"] == LIMITE_POR_DEFECTO


# --- Cambiar ---------------------------------------------------------------------------


def test_un_cambio_inserta_una_fila_y_su_auditoria(admin, base_migrada):
    respuesta = admin.patch(CONFIGURACION, json={"institution_name": "Centro de Prueba"})

    assert respuesta.status_code == 200
    nombre = respuesta.json()["institution_name"]
    assert (nombre["value"], nombre["default"], nombre["updated_by"]) == ("Centro de Prueba", "GynFem", str(ADMIN_ID))
    assert nombre["updated_at"] is not None
    assert parametros_guardados(base_migrada) == [("institution_name", "Centro de Prueba", ADMIN_ID)]
    assert auditoria(base_migrada) == [
        ("system_setting.update", "system_setting", None, "success", ["institution_name"], ADMIN_ID)
    ]


def test_la_auditoria_lleva_el_request_id_de_la_peticion(admin, base_migrada):
    respuesta = admin.patch(CONFIGURACION, json={"history_default_page_size": 10}, headers={"X-Request-ID": "cambio-16"})

    assert respuesta.headers["x-request-id"] == "cambio-16"
    assert filas(base_migrada, "SELECT request_id FROM gynfem.audit_log") == [("cambio-16",)]


def test_cambiar_las_dos_claves_audita_una_vez_con_ambos_nombres(admin, base_migrada):
    respuesta = admin.patch(CONFIGURACION, json={"history_default_page_size": 5, "institution_name": "Centro de Prueba"})

    assert respuesta.status_code == 200
    assert respuesta.json()["history_default_page_size"]["value"] == 5
    assert sorted(parametros_guardados(base_migrada)) == [
        ("history_default_page_size", "5", ADMIN_ID), ("institution_name", "Centro de Prueba", ADMIN_ID),
    ]
    assert [fila[4] for fila in auditoria(base_migrada)] == [["history_default_page_size", "institution_name"]]


def test_el_cambio_rige_en_la_siguiente_peticion_sin_reiniciar(admin, cliente_bd):
    admin.patch(CONFIGURACION, json={"history_default_page_size": 7})

    assert admin.get(CONFIGURACION).json()["history_default_page_size"]["value"] == 7
    # Otra instancia de la aplicación lo lee de la base: no hay caché ni estado en memoria.
    assert cliente_bd(rol="administrador").get(CONFIGURACION).json()["history_default_page_size"]["value"] == 7


def test_cada_cambio_conserva_el_valor_anterior(admin, base_migrada):
    admin.patch(CONFIGURACION, json={"institution_name": "Primera"})
    admin.patch(CONFIGURACION, json={"institution_name": "Segunda"})

    assert [fila[1] for fila in parametros_guardados(base_migrada)] == ["Primera", "Segunda"]
    assert admin.get(CONFIGURACION).json()["institution_name"]["value"] == "Segunda"
    assert len(auditoria(base_migrada)) == 2


def test_si_falla_la_auditoria_no_queda_el_parametro(admin, base_migrada, monkeypatch):
    """Misma transacción: sin su registro de auditoría, el cambio no existe."""
    from app.services import system_settings

    def fallar(*args, **kwargs):
        raise RuntimeError("fallo forzado de la auditoría")

    monkeypatch.setattr(system_settings.audit_repo, "insert_audit", fallar)

    respuesta = admin.patch(CONFIGURACION, json={"institution_name": "Centro de Prueba"})

    assert respuesta.status_code == 500
    assert respuesta.json()["error"]["code"] == "internal_error"
    assert parametros_guardados(base_migrada) == []
    assert auditoria(base_migrada) == []
    monkeypatch.undo()
    assert admin.get(CONFIGURACION).json()["institution_name"]["value"] == "GynFem"


def test_si_falla_el_parametro_no_queda_la_auditoria(admin, base_migrada, monkeypatch):
    """El caso inverso: dos claves, la segunda inserción falla y no queda nada de la primera."""
    from app.services import system_settings

    original = system_settings.settings_repo.insert_value
    llamadas = []

    def fallar_en_la_segunda(*args, **kwargs):
        llamadas.append(1)
        if len(llamadas) == 2:
            raise RuntimeError("fallo forzado del parámetro")
        return original(*args, **kwargs)

    monkeypatch.setattr(system_settings.settings_repo, "insert_value", fallar_en_la_segunda)

    respuesta = admin.patch(CONFIGURACION, json={"history_default_page_size": 5, "institution_name": "Centro de Prueba"})

    assert respuesta.status_code == 500
    assert llamadas == [1, 1]
    assert parametros_guardados(base_migrada) == []
    assert auditoria(base_migrada) == []


# --- Un valor igual al vigente no escribe nada -------------------------------------------


def test_un_valor_igual_al_por_defecto_no_escribe_nada(admin, base_migrada):
    respuesta = admin.patch(CONFIGURACION, json={"institution_name": "GynFem", "history_default_page_size": 20})

    assert respuesta.status_code == 200
    assert respuesta.json() == admin.get(CONFIGURACION).json()
    assert respuesta.json()["institution_name"]["updated_at"] is None
    assert parametros_guardados(base_migrada) == []
    assert auditoria(base_migrada) == []


def test_repetir_el_valor_vigente_no_escribe_nada(admin, base_migrada):
    primera = admin.patch(CONFIGURACION, json={"institution_name": "Centro de Prueba"})
    repetida = admin.patch(CONFIGURACION, json={"institution_name": "Centro de Prueba"})

    assert repetida.status_code == 200
    assert repetida.json() == primera.json()
    assert len(parametros_guardados(base_migrada)) == 1
    assert len(auditoria(base_migrada)) == 1


def test_solo_se_escribe_y_audita_la_clave_que_cambia(admin, base_migrada):
    admin.patch(CONFIGURACION, json={"institution_name": "Centro de Prueba"})

    respuesta = admin.patch(CONFIGURACION, json={"institution_name": "Centro de Prueba", "history_default_page_size": 9})

    assert respuesta.status_code == 200
    assert [fila[:2] for fila in parametros_guardados(base_migrada)] == [
        ("institution_name", "Centro de Prueba"), ("history_default_page_size", "9"),
    ]
    assert [fila[4] for fila in auditoria(base_migrada)] == [["institution_name"], ["history_default_page_size"]]


# --- Validación -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cuerpo, tipo",
    [
        ({}, "empty_update"),
        ({"institution_name": None}, "null_field"),
        ({"risk_threshold_high": 0.5}, "extra_forbidden"),
        ({"institution_name": "Centro", "clinical_disclaimer": "otro"}, "extra_forbidden"),
        ({"history_default_page_size": 0}, "greater_than_equal"),
        ({"history_default_page_size": 51}, "less_than_equal"),
        ({"history_default_page_size": "20"}, "int_type"),
        ({"history_default_page_size": 20.5}, "int_type"),
        ({"history_default_page_size": True}, "int_type"),
        ({"institution_name": 16}, "string_type"),
        ({"institution_name": ""}, "institution_name_length"),
        ({"institution_name": "   "}, "institution_name_length"),
        ({"institution_name": "x" * 101}, "institution_name_length"),
        ({"institution_name": "Centro\u0000Prueba"}, "control_character"),
        ({"institution_name": "Centro\nPrueba"}, "control_character"),
        ({"institution_name": "Centro\tPrueba"}, "control_character"),
        ({"institution_name": "Centro​Prueba"}, "control_character"),
        ({"institution_name": "Centro‮Prueba"}, "control_character"),
        ({"institution_name": "Centro Prueba"}, "control_character"),
    ],
    ids=[
        "vacío", "nulo", "clave desconocida", "clave desconocida junto a una válida", "página 0", "página 51",
        "página como texto", "página decimal", "página booleana", "nombre numérico", "nombre vacío",
        "nombre en blanco", "nombre de 101", "NUL", "salto de línea", "tabulador", "ancho cero",
        "inversión de dirección", "separador de línea",
    ],
)
def test_entrada_invalida_422_sin_escribir_nada(cuerpo, tipo, admin, base_migrada):
    respuesta = admin.patch(CONFIGURACION, json=cuerpo)

    assert respuesta.status_code == 422, respuesta.text
    assert tipo in [d["type"] for d in respuesta.json()["error"]["details"]]
    assert parametros_guardados(base_migrada) == []
    assert auditoria(base_migrada) == []


def test_el_nombre_se_normaliza_a_nfc_y_se_recorta(admin, base_migrada):
    # «Clínica José» con las tildes combinantes (NFD) y espacios sobrantes.
    respuesta = admin.patch(CONFIGURACION, json={"institution_name": "  Clínica   José  "})

    assert respuesta.status_code == 200
    assert respuesta.json()["institution_name"]["value"] == "Clínica José"
    assert [fila[1] for fila in parametros_guardados(base_migrada)] == ["Clínica José"]


def test_la_misma_palabra_en_nfd_es_el_valor_vigente(admin, base_migrada):
    admin.patch(CONFIGURACION, json={"institution_name": "Clínica"})

    assert admin.patch(CONFIGURACION, json={"institution_name": "Clínica"}).status_code == 200
    assert len(parametros_guardados(base_migrada)) == 1


def test_el_limite_de_longitud_se_mide_tras_normalizar(admin):
    # 100 «é» en NFD son 200 caracteres; normalizados, 100: se admiten.
    assert admin.patch(CONFIGURACION, json={"institution_name": "é" * 100}).status_code == 200


# --- Acceso -----------------------------------------------------------------------------


def test_medico_403_en_configuracion(cliente_bd, base_migrada):
    medico = cliente_bd(rol="medico")

    for respuesta in (medico.get(CONFIGURACION), medico.patch(CONFIGURACION, json={"institution_name": "Centro"})):
        assert respuesta.status_code == 403
        assert respuesta.json()["error"]["code"] == "forbidden"
    assert parametros_guardados(base_migrada) == []
    assert auditoria(base_migrada) == []


def test_sin_token_401_en_configuracion(cliente_bd, base_migrada):
    anonimo = cliente_bd(rol=None)

    for respuesta in (anonimo.get(CONFIGURACION), anonimo.patch(CONFIGURACION, json={"institution_name": "Centro"})):
        assert respuesta.status_code == 401
    assert parametros_guardados(base_migrada) == []


@pytest.mark.parametrize("metodo", ["post", "put", "delete"])
def test_la_configuracion_no_se_crea_ni_se_borra(metodo, admin):
    assert getattr(admin, metodo)(CONFIGURACION).status_code == 405


# --- El valor no sale de la tabla de parámetros --------------------------------------------


def test_el_valor_no_llega_a_los_logs_ni_a_la_auditoria(admin, base_migrada, caplog, capsys):
    caplog.set_level(logging.DEBUG)

    assert admin.patch(CONFIGURACION, json={"institution_name": CENTINELA}).status_code == 200
    assert admin.patch(CONFIGURACION, json={"institution_name": CENTINELA}).status_code == 200
    assert admin.patch(CONFIGURACION, json={"institution_name": CENTINELA + "\n"}).status_code == 422
    assert admin.get(CONFIGURACION).json()["institution_name"]["value"] == CENTINELA

    capturado = capsys.readouterr()
    de_la_aplicacion = [r for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))]
    registros = "\n".join(r.getMessage() for r in de_la_aplicacion) + capturado.out + capturado.err
    assert '"logger": "gynfem.access"' in capturado.out, "control positivo: hubo log de acceso"
    assert '"action": "system_setting.update"' in capturado.out, "control positivo: hubo log del cambio"
    assert capturado.out.count('"action": "system_setting.update"') == 1, "el cambio repetido no se registra"
    for prohibido in (CENTINELA, "Centinelainstitucion", "Zeta"):
        assert prohibido not in registros, f"los logs exponen {prohibido!r}"

    (fila_de_auditoria,) = filas(base_migrada, "SELECT row_to_json(a)::text FROM gynfem.audit_log a")
    assert "institution_name" in fila_de_auditoria[0], "control positivo: la auditoría nombra la clave"
    for prohibido in (CENTINELA, "Centinelainstitucion", "Zeta"):
        assert prohibido not in fila_de_auditoria[0], f"la auditoría expone {prohibido!r}"
