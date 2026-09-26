"""HU003 (registrar paciente), HU004 (consultar, buscar y actualizar) y la baja lógica.

Contra la aplicación completa y un PostgreSQL embebido: cada afirmación sobre
la base se comprueba consultándola directamente.
"""

import pytest

from .conftest import filas
from .datos_sinteticos import (
    BUSQUEDA,
    CAMPOS_INTERNOS,
    CLAVES_PACIENTE,
    CLAVES_PAGINA,
    CLAVES_RESUMEN,
    PACIENTE,
    PACIENTE_DOS,
    buscar,
    documento,
)

PACIENTES = "/api/v1/patients"
UUID_INEXISTENTE = "00000000-0000-4000-8000-000000000000"


def crear(cliente, **cambios) -> dict:
    respuesta = cliente.post(PACIENTES, json={**PACIENTE, **cambios})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def auditoria(url: str) -> list[tuple]:
    return filas(
        url,
        "SELECT action, entity_type, entity_id, outcome, changed_fields, actor_user_id, request_id "
        "FROM gynfem.audit_log ORDER BY id",
    )


# --- HU003: registrar paciente -----------------------------------------------------


def test_crear_paciente_201_con_datos_validos(cliente_bd, base_migrada):
    cuerpo = crear(cliente_bd())

    assert set(cuerpo) == CLAVES_PACIENTE
    assert {k: cuerpo[k] for k in PACIENTE} == PACIENTE
    assert filas(
        base_migrada,
        "SELECT document_type, document_number, given_names, family_names, deleted_at FROM gynfem.patients WHERE id = %s",
        [cuerpo["id"]],
    ) == [("DNI", "00000001", "Sintética", "Prueba Uno", None)]


def test_crear_paciente_normaliza_espacios_y_mayusculas_del_documento(cliente_bd):
    cuerpo = crear(
        cliente_bd(),
        document_type="PASAPORTE",
        document_number=" prueba0009 ",
        given_names="  Sintética   Ana ",
    )
    assert cuerpo["document_number"] == "PRUEBA0009"
    assert cuerpo["given_names"] == "Sintética Ana"


@pytest.mark.parametrize(
    "cambios, campo",
    [
        ({"document_number": "0000001"}, "document_number"),
        ({"document_number": "000000001"}, "document_number"),
        ({"document_number": "0000000A"}, "document_number"),
        ({"document_type": "LIBRETA"}, "document_type"),
        ({"document_type": "PASAPORTE", "document_number": "AB1"}, "document_number"),
        ({"document_type": "CE", "document_number": "PRUEBA-01"}, "document_number"),
        ({"given_names": ""}, "given_names"),
        ({"given_names": "   "}, "given_names"),
        ({"family_names": "Prueba 2"}, "family_names"),
        ({"family_names": "x" * 101}, "family_names"),
        ({"given_names": 12345}, "given_names"),
    ],
)
def test_crear_paciente_422_con_datos_invalidos(cambios, campo, cliente_bd, base_migrada):
    respuesta = cliente_bd().post(PACIENTES, json={**PACIENTE, **cambios})

    assert respuesta.status_code == 422
    error = respuesta.json()["error"]
    assert error["code"] == "validation_error"
    assert any(d["loc"][-1] == campo for d in error["details"])
    for valor in cambios.values():
        if isinstance(valor, str) and valor.strip():
            assert valor.strip() not in respuesta.text, "el 422 no repite el valor"
    assert filas(base_migrada, "SELECT count(*) FROM gynfem.patients") == [(0,)]


@pytest.mark.parametrize("faltante", list(PACIENTE))
def test_crear_paciente_422_si_falta_un_campo(faltante, cliente_bd):
    cuerpo = {k: v for k, v in PACIENTE.items() if k != faltante}
    assert cliente_bd().post(PACIENTES, json=cuerpo).status_code == 422


def test_crear_paciente_422_con_campo_extra(cliente_bd):
    assert cliente_bd().post(PACIENTES, json={**PACIENTE, "birth_date": "1990-01-01"}).status_code == 422


def test_documento_duplicado_409(cliente_bd, base_migrada):
    cliente = cliente_bd()
    crear(cliente)
    respuesta = cliente.post(PACIENTES, json={**PACIENTE, "given_names": "Otra"})

    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["code"] == "patient_already_exists"
    assert "00000001" not in respuesta.text
    assert filas(base_migrada, "SELECT count(*) FROM gynfem.patients") == [(1,)]


def test_documento_de_paciente_desactivada_se_puede_reutilizar(cliente_bd):
    cliente = cliente_bd()
    primera = crear(cliente)
    assert cliente.delete(f"{PACIENTES}/{primera['id']}").status_code == 204

    segunda = crear(cliente)
    assert segunda["id"] != primera["id"]


def test_crear_paciente_audita_patient_create(cliente_bd, base_migrada):
    cliente = cliente_bd()
    respuesta = cliente.post(PACIENTES, json=PACIENTE)
    cuerpo = respuesta.json()

    assert auditoria(base_migrada) == [
        ("patient.create", "patient", _uuid(cuerpo["id"]), "success", None, None, respuesta.headers["x-request-id"])
    ]


# --- HU004: consultar ----------------------------------------------------------------


def test_consultar_paciente_por_id(cliente_bd):
    cliente = cliente_bd()
    creada = crear(cliente)
    respuesta = cliente.get(f"{PACIENTES}/{creada['id']}")

    assert respuesta.status_code == 200
    assert respuesta.json() == creada


def test_paciente_inexistente_404(cliente_bd):
    respuesta = cliente_bd().get(f"{PACIENTES}/{UUID_INEXISTENTE}")
    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "patient_not_found"


def test_paciente_desactivada_404(cliente_bd):
    cliente = cliente_bd()
    creada = crear(cliente)
    cliente.delete(f"{PACIENTES}/{creada['id']}")
    assert cliente.get(f"{PACIENTES}/{creada['id']}").status_code == 404


def test_identificador_malformado_422(cliente_bd):
    assert cliente_bd().get(f"{PACIENTES}/123").status_code == 422


# --- HU004: buscar -------------------------------------------------------------------


def test_buscar_por_documento_exacto(cliente_bd):
    cliente = cliente_bd()
    creada = crear(cliente)
    crear(cliente, document_number=documento(2), given_names="Otra")

    exacta = buscar(cliente, {"document_type": "DNI", "document_number": "00000001"}).json()
    parecida = buscar(cliente, {"document_type": "DNI", "document_number": "00000009"}).json()

    assert set(exacta) == CLAVES_PAGINA
    assert [p["id"] for p in exacta["items"]] == [creada["id"]]
    assert parecida["items"] == []


def test_buscar_por_nombre_prefijo_sin_tildes_ni_mayusculas(cliente_bd):
    cliente = cliente_bd()
    dos = cliente.post(PACIENTES, json=PACIENTE_DOS).json()
    crear(cliente)

    for termino in ("perez", "PÉREZ", "Ensa", "ficticia pérez", "fic"):
        items = buscar(cliente, {"name": termino}).json()["items"]
        assert [p["id"] for p in items] == [dos["id"]], termino
    assert buscar(cliente, {"name": "rez"}).json()["items"] == [], "prefijo de palabra, no subcadena"


def test_buscar_con_comodines_sql_no_los_interpreta(cliente_bd):
    """`_` y `%` se buscan literalmente: sin escaparlos, «prueb_» encontraría «Prueba»."""
    cliente = cliente_bd()
    crear(cliente)
    assert buscar(cliente, {"name": "prueba"}).json()["items"] != [], "control positivo"
    for termino in ("prueb_", "pru%ba", "pru__a"):
        respuesta = buscar(cliente, {"name": termino})
        assert respuesta.status_code == 200
        assert respuesta.json()["items"] == [], termino


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"name": "pe"},
        {"name": "\u0301\u0301\u0301"},
        {"name": "a\u0301\u0301"},
        {"name": "---"},
        {"name": "' -"},
        {"name": "%%"},
        {"document_type": "DNI", "document_number": "0000000"},
        {"document_type": "PASAPORTE", "document_number": "AB"},
        {"name": "   "},
        {"document_type": "DNI"},
        {"document_number": "00000001"},
        {"name": "prueba", "document_type": "DNI", "document_number": "00000001"},
        {"name": "prueba", "limit": 51},
        {"name": "prueba", "limit": 0},
        {"name": "prueba", "offset": -1},
        {"name": 12345},
        {"name": "prueba", "extra": 1},
        {"document_type": "LIBRETA", "document_number": "00000001"},
    ],
)
def test_busqueda_invalida_422(params, cliente_bd):
    respuesta = buscar(cliente_bd(), params)
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["code"] == "validation_error"


def test_busqueda_enmascara_el_documento(cliente_bd):
    cliente = cliente_bd()
    crear(cliente)
    item = buscar(cliente, {"name": "sintetica"}).json()["items"][0]

    assert set(item) == CLAVES_RESUMEN
    assert item["document_number_masked"] == "*****001"
    assert "00000001" not in buscar(cliente, {"name": "sintetica"}).text


def test_busqueda_no_devuelve_desactivadas(cliente_bd):
    cliente = cliente_bd()
    creada = crear(cliente)
    cliente.delete(f"{PACIENTES}/{creada['id']}")

    assert buscar(cliente, {"name": "sintetica"}).json()["items"] == []
    assert buscar(cliente, {"document_type": "DNI", "document_number": "00000001"}).json()["items"] == []


def test_listado_paginado_respeta_el_limite(cliente_bd):
    cliente = cliente_bd()
    for n in range(1, 61):
        crear(cliente, document_number=documento(n))

    por_defecto = buscar(cliente, {"name": "prueba"}).json()
    maxima = buscar(cliente, {"name": "prueba", "limit": 50}).json()
    resto = buscar(cliente, {"name": "prueba", "limit": 50, "offset": 50}).json()

    assert (len(por_defecto["items"]), por_defecto["limit"], por_defecto["has_more"]) == (20, 20, True)
    assert (len(maxima["items"]), maxima["has_more"]) == (50, True)
    assert (len(resto["items"]), resto["offset"], resto["has_more"]) == (10, 50, False)
    ids = [p["id"] for p in maxima["items"]] + [p["id"] for p in resto["items"]]
    assert len(set(ids)) == 60, "las páginas no se solapan ni pierden filas"


# --- HU004: actualizar ---------------------------------------------------------------


def test_actualizar_paciente_parcial_200(cliente_bd, base_migrada):
    cliente = cliente_bd()
    creada = crear(cliente)
    respuesta = cliente.patch(f"{PACIENTES}/{creada['id']}", json={"given_names": "Sintética Actualizada"})

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["given_names"] == "Sintética Actualizada"
    assert cuerpo["family_names"] == creada["family_names"]
    assert cuerpo["created_at"] == creada["created_at"]
    assert cuerpo["updated_at"] > creada["updated_at"]
    assert buscar(cliente, {"name": "actualiz"}).json()["items"][0]["id"] == creada["id"]


def test_actualizar_documento_exige_tipo_y_numero_juntos(cliente_bd):
    cliente = cliente_bd()
    creada = crear(cliente)
    assert cliente.patch(f"{PACIENTES}/{creada['id']}", json={"document_number": "00000009"}).status_code == 422
    respuesta = cliente.patch(
        f"{PACIENTES}/{creada['id']}", json={"document_type": "DNI", "document_number": "00000009"}
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["document_number"] == "00000009"


def test_actualizar_audita_solo_nombres_de_campos(cliente_bd, base_migrada):
    cliente = cliente_bd()
    creada = crear(cliente)
    cliente.patch(f"{PACIENTES}/{creada['id']}", json={"given_names": "Sintética Dos"})

    ultima = auditoria(base_migrada)[-1]
    assert ultima[:5] == ("patient.update", "patient", _uuid(creada["id"]), "success", ["given_names"])
    assert "Dos" not in repr(auditoria(base_migrada))


def test_actualizar_a_documento_existente_409(cliente_bd):
    cliente = cliente_bd()
    crear(cliente)
    otra = crear(cliente, document_number=documento(2))
    respuesta = cliente.patch(
        f"{PACIENTES}/{otra['id']}", json={"document_type": "DNI", "document_number": "00000001"}
    )
    assert respuesta.status_code == 409


@pytest.mark.parametrize("cuerpo", [{}, {"given_names": ""}, {"deleted_at": None}, {"id": UUID_INEXISTENTE}])
def test_patch_invalido_422(cuerpo, cliente_bd):
    cliente = cliente_bd()
    creada = crear(cliente)
    assert cliente.patch(f"{PACIENTES}/{creada['id']}", json=cuerpo).status_code == 422


def test_actualizar_paciente_inexistente_404(cliente_bd):
    respuesta = cliente_bd().patch(f"{PACIENTES}/{UUID_INEXISTENTE}", json={"given_names": "Nadie"})
    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "patient_not_found"


# --- Baja lógica (decisión 5) ----------------------------------------------------------


def test_desactivar_es_logico_y_el_historial_sobrevive(cliente_bd, base_migrada):
    from api.api_constantes import ENTRADA_NORMAL

    cliente = cliente_bd()
    creada = crear(cliente)
    medicion = cliente.post(f"{PACIENTES}/{creada['id']}/measurements", json=ENTRADA_NORMAL).json()

    respuesta = cliente.delete(f"{PACIENTES}/{creada['id']}")

    assert respuesta.status_code == 204
    assert respuesta.content == b""
    assert filas(base_migrada, "SELECT deleted_at IS NOT NULL FROM gynfem.patients WHERE id = %s", [creada["id"]]) == [(True,)]
    assert filas(base_migrada, "SELECT count(*) FROM gynfem.clinical_measurements WHERE patient_id = %s", [creada["id"]]) == [(1,)]
    assert filas(base_migrada, "SELECT count(*) FROM gynfem.predictions WHERE id = %s", [medicion["prediction"]["id"]]) == [(1,)]


def test_desactivar_dos_veces_404(cliente_bd):
    cliente = cliente_bd()
    creada = crear(cliente)
    assert cliente.delete(f"{PACIENTES}/{creada['id']}").status_code == 204
    assert cliente.delete(f"{PACIENTES}/{creada['id']}").status_code == 404


def test_desactivar_audita_patient_deactivate(cliente_bd, base_migrada):
    cliente = cliente_bd()
    creada = crear(cliente)
    cliente.delete(f"{PACIENTES}/{creada['id']}")

    assert auditoria(base_migrada)[-1][:4] == ("patient.deactivate", "patient", _uuid(creada["id"]), "success")


def test_respuestas_de_pacientes_sin_campos_internos(cliente_bd):
    cliente = cliente_bd()
    creada = crear(cliente)
    textos = [
        cliente.get(f"{PACIENTES}/{creada['id']}").text,
        buscar(cliente, {"name": "sintetica"}).text,
        cliente.patch(f"{PACIENTES}/{creada['id']}", json={"given_names": "Sintética"}).text,
    ]
    for texto in textos:
        for campo in CAMPOS_INTERNOS:
            assert campo not in texto


def _uuid(texto: str):
    import uuid

    return uuid.UUID(texto)


# --- Autorrevisión de PR #9 -----------------------------------------------------------


def test_la_busqueda_por_nombre_nunca_lista_a_todas(cliente_bd):
    """Un término que normalizado queda vacío o muy corto no puede convertirse en un listado abierto."""
    cliente = cliente_bd()
    crear(cliente)
    for termino in ("\u0301\u0301\u0301", "a\u0301\u0301", "   \u0301\u0301\u0301"):
        respuesta = buscar(cliente, {"name": termino})
        assert respuesta.status_code == 422, repr(termino)


def test_buscar_documento_en_minusculas_se_normaliza(cliente_bd):
    cliente = cliente_bd()
    creada = cliente.post(PACIENTES, json=PACIENTE_DOS).json()
    items = buscar(cliente, {"document_type": "PASAPORTE", "document_number": " prueba0002 "}).json()["items"]
    assert [p["id"] for p in items] == [creada["id"]]


def test_nombre_en_unicode_descompuesto_se_admite_y_se_guarda_compuesto(cliente_bd, base_migrada):
    """«José» escrito como J-o-s-e + tilde combinante (NFD) es un nombre válido."""
    cliente = cliente_bd()
    respuesta = cliente.post(PACIENTES, json={**PACIENTE, "given_names": "Jose\u0301"})

    assert respuesta.status_code == 201
    assert respuesta.json()["given_names"] == "Jos\u00e9"
    assert filas(base_migrada, "SELECT given_names FROM gynfem.patients") == [("Jos\u00e9",)]


# --- La búsqueda nunca lleva identidad en la URL (hallazgo 5, opción B) -------------


def test_la_busqueda_por_url_ya_no_existe(cliente_bd):
    """`GET /patients?name=…` dejaba el nombre o el documento en la URL: en proxies,
    CDN o el historial del navegador. Ya no es una ruta."""
    cliente = cliente_bd()
    crear(cliente)
    respuesta = cliente.get(PACIENTES, params={"name": "sintetica"})

    assert respuesta.status_code == 405
    assert respuesta.json()["error"]["code"] == "method_not_allowed"
    assert "Sintética" not in respuesta.text


def test_la_busqueda_ignora_criterios_en_la_url(cliente_bd):
    """Un criterio en la query string no se lee: sin criterio en el cuerpo, 422."""
    cliente = cliente_bd()
    crear(cliente)
    respuesta = cliente.post(f"{BUSQUEDA}?name=sintetica&document_type=DNI&document_number=00000001", json={})
    assert respuesta.status_code == 422


def test_la_ruta_de_busqueda_no_declara_parametros_de_url(cliente_bd):
    """Ni criterio ni paginación en la URL: todo va en el cuerpo."""
    operacion = cliente_bd().get("/api/v1/openapi.json").json()["paths"]["/api/v1/patients/search"]["post"]
    assert [p for p in operacion.get("parameters", []) if p["in"] == "query"] == []
    assert "requestBody" in operacion


def test_la_busqueda_responde_200_y_no_crea_nada(cliente_bd, base_migrada):
    cliente = cliente_bd()
    crear(cliente)
    respuesta = buscar(cliente, {"name": "sintetica"})

    assert respuesta.status_code == 200
    assert filas(base_migrada, "SELECT count(*) FROM gynfem.patients") == [(1,)]
    assert filas(base_migrada, "SELECT count(*) FROM gynfem.audit_log WHERE action NOT LIKE 'patient.create'") == [(0,)]
