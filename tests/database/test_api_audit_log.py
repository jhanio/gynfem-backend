"""Consulta de la auditoría: de solo lectura, paginada y solo para el administrador.

Contra la aplicación completa y el PostgreSQL embebido. La auditoría no tiene
columnas donde quepa un valor clínico (Fase 9), y la consulta tampoco los
muestra: solo quién hizo qué acción, sobre qué entidad (un id opaco) y cuándo.
No se crea, no se modifica y no se borra por la API.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from api.auth_claves import ADMIN_ID, MEDICO_ID

from .conftest import filas

AUDITORIA = "/api/v1/audit-log"
PACIENTES = "/api/v1/patients"
CONFIGURACION = "/api/v1/settings"

CLAVES_PAGINA = {"items", "limit", "offset", "has_more"}
CLAVES_ITEM = {
    "created_at", "actor_user_id", "action", "entity_type", "entity_id", "request_id", "outcome", "changed_fields",
}

PACIENTE_CENTINELA = {
    "document_type": "PASAPORTE", "document_number": "CENTINELA16",
    "given_names": "Centinelanombre", "family_names": "Centinelapellido",
}
MEDIDAS_CENTINELA = {
    "age_years": 31.4159, "temperature_c": 36.7182, "heart_rate_bpm": 83.1415,
    "systolic_bp_mmhg": 123.4567, "diastolic_bp_mmhg": 76.5432, "bmi_kg_m2": 23.4567,
    "hba1c_percent": 5.4321, "fasting_glucose_mg_dl": 91.2345,
}
BASE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def insertar(url: str, *, cuando: datetime = BASE, action: str = "patient.create", entity_type: str = "patient",
             entity_id=None, actor=None, request_id: str | None = None, changed_fields=None) -> None:
    """Una fila de auditoría con la hora indicada (`updated_at` debe ser igual a `created_at`)."""
    with psycopg.connect(url) as conexion:
        conexion.execute(
            "INSERT INTO gynfem.audit_log (created_at, updated_at, action, entity_type, entity_id, actor_user_id, "
            "request_id, outcome, changed_fields) VALUES (%s, %s, %s, %s, %s, %s, %s, 'success', %s)",
            [cuando, cuando, action, entity_type, entity_id, actor, request_id, changed_fields],
        )


def total(url: str) -> int:
    return filas(url, "SELECT count(*) FROM gynfem.audit_log")[0][0]


def consultar(cliente, **parametros):
    return cliente.get(AUDITORIA, params=parametros)


def items(respuesta) -> list[dict]:
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["items"]


def marcas(respuesta) -> list[str]:
    return [item["request_id"] for item in items(respuesta)]


@pytest.fixture
def admin(cliente_bd):
    return cliente_bd(rol="administrador")


@pytest.fixture
def flujo_clinico(cliente_bd):
    """Un flujo real con centinelas: alta, medición, corrección, actualización y un cambio de parámetro."""
    medico = cliente_bd()
    paciente = medico.post(PACIENTES, json=PACIENTE_CENTINELA).json()
    evaluacion = medico.post(f"{PACIENTES}/{paciente['id']}/measurements", json=MEDIDAS_CENTINELA).json()
    medico.patch(f"{PACIENTES}/{paciente['id']}", json={"family_names": "Centinelapellido Dos"})
    medico.post(f"/api/v1/predictions/{evaluacion['prediction']['id']}/report")
    return {"paciente": paciente, "evaluacion": evaluacion}


# --- Acceso -------------------------------------------------------------------------------


def test_medico_403_y_anonimo_401(cliente_bd, base_migrada):
    insertar(base_migrada, request_id="fila-secreta")

    del_medico, del_anonimo = consultar(cliente_bd(rol="medico")), consultar(cliente_bd(rol=None))

    assert del_medico.status_code == 403 and del_medico.json()["error"]["code"] == "forbidden"
    assert del_anonimo.status_code == 401 and del_anonimo.json()["error"]["code"] == "not_authenticated"
    for respuesta in (del_medico, del_anonimo):
        assert "fila-secreta" not in respuesta.text and "items" not in respuesta.text


# --- Solo lectura ---------------------------------------------------------------------------


@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
def test_la_auditoria_no_admite_escritura(metodo, admin, base_migrada):
    insertar(base_migrada)
    antes = filas(base_migrada, "SELECT id, action, created_at, updated_at FROM gynfem.audit_log ORDER BY id")
    cuerpo = {"action": "patient.create", "entity_type": "patient", "outcome": "success"}

    respuesta = getattr(admin, metodo)(AUDITORIA, **({} if metodo == "delete" else {"json": cuerpo}))

    assert respuesta.status_code == 405
    assert respuesta.json()["error"]["code"] == "method_not_allowed"
    assert filas(base_migrada, "SELECT id, action, created_at, updated_at FROM gynfem.audit_log ORDER BY id") == antes


def test_la_ruta_de_auditoria_solo_declara_get(admin):
    from api.test_auth_rbac import rutas_de

    de_auditoria = [r for r in rutas_de(admin.app) if "audit" in getattr(r, "path", "")]

    assert [(r.path, sorted(r.methods)) for r in de_auditoria] == [(AUDITORIA, ["GET"])]


def test_ningun_modulo_de_la_consulta_escribe_en_la_auditoria():
    from api.api_constantes import REPO_ROOT

    for modulo in ("app/repositories/audit_query.py", "app/services/audit_query.py", "app/api/v1/audit.py"):
        fuente = (REPO_ROOT / modulo).read_text(encoding="utf-8").upper()
        for sentencia in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE ", "INSERT_AUDIT"):
            assert sentencia not in fuente, f"{modulo} contiene {sentencia.strip()}"


def test_consultar_la_auditoria_no_escribe_auditoria(admin, base_migrada, flujo_clinico):
    antes = total(base_migrada)
    assert antes > 0

    for parametros in ({}, {"limit": 1}, {"action": "patient.create"}, {"entity_type": "prediction", "offset": 1}):
        assert consultar(admin, **parametros).status_code == 200

    assert total(base_migrada) == antes
    assert filas(base_migrada, "SELECT count(*) FROM gynfem.system_settings") == [(0,)]


# --- Contenido --------------------------------------------------------------------------------


def test_cada_item_tiene_exactamente_las_claves_documentadas(admin, base_migrada, flujo_clinico):
    respuesta = consultar(admin)

    cuerpo = respuesta.json()
    assert set(cuerpo) == CLAVES_PAGINA, "sin el total de filas"
    assert len(cuerpo["items"]) >= 5
    for item in cuerpo["items"]:
        assert set(item) == CLAVES_ITEM
    assert '"id"' not in respuesta.text, "el id numérico interno nunca se expone"


def test_la_fila_se_devuelve_tal_como_se_guardo(admin, base_migrada, flujo_clinico):
    paciente = flujo_clinico["paciente"]

    [alta] = items(consultar(admin, action="patient.create"))
    [cambio] = items(consultar(admin, action="patient.update"))

    guardada = filas(
        base_migrada,
        "SELECT created_at, request_id FROM gynfem.audit_log WHERE action = 'patient.create'",
    )[0]
    assert alta == {
        "created_at": alta["created_at"], "actor_user_id": str(MEDICO_ID), "action": "patient.create",
        "entity_type": "patient", "entity_id": paciente["id"], "request_id": guardada[1],
        "outcome": "success", "changed_fields": None,
    }
    assert datetime.fromisoformat(alta["created_at"]) == guardada[0]
    assert cambio["changed_fields"] == ["family_names"], "solo el nombre del campo, nunca su valor"


def test_el_cambio_de_un_parametro_sale_sin_entidad_y_con_el_nombre_de_la_clave(admin):
    admin.patch(CONFIGURACION, json={"institution_name": "Centinelainstitucion Zeta"})

    respuesta = consultar(admin, entity_type="system_setting")

    [cambio] = items(respuesta)
    assert (cambio["action"], cambio["entity_id"], cambio["changed_fields"], cambio["actor_user_id"]) == (
        "system_setting.update", None, ["institution_name"], str(ADMIN_ID)
    )
    assert "Centinelainstitucion" not in respuesta.text


def test_la_auditoria_no_muestra_datos_clinicos_en_claro(admin, flujo_clinico):
    respuesta = consultar(admin, limit=50)

    acciones = {item["action"] for item in items(respuesta)}
    assert {"patient.create", "clinical_measurement.create", "prediction.create", "patient.update",
            "prediction.report"} <= acciones, "control positivo: están las filas del flujo con centinelas"
    assert flujo_clinico["paciente"]["id"] in respuesta.text, "control positivo: el id opaco sí va"
    prohibidos = [
        "Centinelanombre", "Centinelapellido", "CENTINELA16", "centinela16",
        *(str(v) for v in MEDIDAS_CENTINELA.values()),
        flujo_clinico["evaluacion"]["prediction"]["risk_level"] + '"',
    ]
    for prohibido in prohibidos:
        assert prohibido not in respuesta.text, f"la auditoría expone {prohibido!r}"


def test_el_id_de_entidad_es_opaco_para_el_administrador(admin, flujo_clinico):
    """El administrador ve el id, pero no puede resolverlo: recibe 403 en todo lo clínico."""
    [alta] = items(consultar(admin, action="patient.create"))
    [prediccion] = items(consultar(admin, action="prediction.create"))

    assert admin.get(f"{PACIENTES}/{alta['entity_id']}").status_code == 403
    assert admin.get(f"{PACIENTES}/{alta['entity_id']}/evaluations").status_code == 403
    assert admin.get(f"/api/v1/predictions/{prediccion['entity_id']}").status_code == 403
    assert admin.post(f"/api/v1/predictions/{prediccion['entity_id']}/report").status_code == 403


# --- Orden y paginación ---------------------------------------------------------------------------


def test_ordena_de_la_mas_reciente_a_la_mas_antigua(admin, base_migrada):
    for marca, minutos in (("b", 10), ("d", 30), ("a", 0), ("c", 20)):
        insertar(base_migrada, cuando=BASE + timedelta(minutes=minutos), request_id=marca)

    assert marcas(consultar(admin)) == ["d", "c", "b", "a"]


def test_con_la_misma_hora_no_se_repite_ni_se_pierde_ninguna_fila(admin, base_migrada):
    # Las filas de una misma transacción comparten `created_at`: desempata el id, descendente.
    for n in range(1, 6):
        insertar(base_migrada, request_id=f"fila-{n}")

    paginas = [consultar(admin, limit=2, offset=desplazamiento) for desplazamiento in (0, 2, 4)]

    assert [len(items(p)) for p in paginas] == [2, 2, 1]
    assert [p.json()["has_more"] for p in paginas] == [True, True, False]
    assert [(p.json()["limit"], p.json()["offset"]) for p in paginas] == [(2, 0), (2, 2), (2, 4)]
    recorridas = [marca for p in paginas for marca in marcas(p)]
    assert recorridas == ["fila-5", "fila-4", "fila-3", "fila-2", "fila-1"]
    assert len({item["created_at"] for p in paginas for item in items(p)}) == 1, "control: la hora es idéntica"


def test_el_limite_por_defecto_es_20_y_no_el_parametro_del_historial(admin, base_migrada):
    for n in range(24):
        insertar(base_migrada, request_id=f"fila-{n}")
    assert admin.patch(CONFIGURACION, json={"history_default_page_size": 3}).status_code == 200

    cuerpo = consultar(admin).json()

    assert (len(cuerpo["items"]), cuerpo["limit"], cuerpo["has_more"]) == (20, 20, True)


def test_limite_maximo_50(admin, base_migrada):
    for n in range(51):
        insertar(base_migrada, request_id=f"fila-{n}")

    cuerpo = consultar(admin, limit=50).json()

    assert (len(cuerpo["items"]), cuerpo["has_more"]) == (50, True)


# --- Filtros ---------------------------------------------------------------------------------------


@pytest.fixture
def variadas(base_migrada):
    """Seis filas que difieren en acción, entidad, id, actor y hora."""
    from .auth_bd import crear_usuario

    otro = crear_usuario(base_migrada, "medico")
    e1, e2 = uuid.uuid4(), uuid.uuid4()
    datos = [
        ("f1", 0, "patient.create", "patient", e1, MEDICO_ID),
        ("f2", 10, "patient.update", "patient", e1, MEDICO_ID),
        ("f3", 20, "patient.create", "patient", e2, otro),
        ("f4", 30, "prediction.create", "prediction", e2, otro),
        ("f5", 40, "user.create", "user", None, ADMIN_ID),
        ("f6", 50, "patient.deactivate", "patient", e1, otro),
    ]
    for marca, minutos, action, entity_type, entity_id, actor in datos:
        insertar(base_migrada, cuando=BASE + timedelta(minutes=minutos), action=action, entity_type=entity_type,
                 entity_id=entity_id, actor=actor, request_id=marca)
    return {"e1": str(e1), "e2": str(e2), "otro": str(otro)}


def test_filtro_por_accion(admin, variadas):
    assert marcas(consultar(admin, action="patient.create")) == ["f3", "f1"]


def test_filtro_por_tipo_de_entidad(admin, variadas):
    assert marcas(consultar(admin, entity_type="patient")) == ["f6", "f3", "f2", "f1"]


def test_filtro_por_entidad(admin, variadas):
    assert marcas(consultar(admin, entity_id=variadas["e1"])) == ["f6", "f2", "f1"]


def test_filtro_por_actor(admin, variadas):
    assert marcas(consultar(admin, actor_user_id=variadas["otro"])) == ["f6", "f4", "f3"]


def test_filtro_por_fechas_desde_inclusive_hasta_exclusive(admin, variadas):
    desde, hasta = (BASE + timedelta(minutes=10)).isoformat(), (BASE + timedelta(minutes=40)).isoformat()

    assert marcas(consultar(admin, **{"from": desde})) == ["f6", "f5", "f4", "f3", "f2"]
    assert marcas(consultar(admin, to=hasta)) == ["f4", "f3", "f2", "f1"]
    assert marcas(consultar(admin, **{"from": desde, "to": hasta})) == ["f4", "f3", "f2"]


def test_los_filtros_se_combinan(admin, variadas):
    desde = (BASE + timedelta(minutes=5)).isoformat()

    assert marcas(consultar(admin, entity_type="patient", actor_user_id=variadas["otro"])) == ["f6", "f3"]
    assert marcas(consultar(admin, entity_id=variadas["e1"], actor_user_id=str(MEDICO_ID), **{"from": desde})) == ["f2"]
    assert marcas(consultar(admin, action="patient.create", entity_id=variadas["e2"], entity_type="patient",
                            actor_user_id=variadas["otro"])) == ["f3"]
    assert marcas(consultar(admin, action="user.create", entity_type="patient")) == []


def test_los_filtros_se_combinan_con_la_paginacion(admin, variadas):
    primera = consultar(admin, entity_type="patient", limit=3)
    segunda = consultar(admin, entity_type="patient", limit=3, offset=3)

    assert (marcas(primera), primera.json()["has_more"]) == (["f6", "f3", "f2"], True)
    assert (marcas(segunda), segunda.json()["has_more"]) == (["f1"], False)


def test_una_zona_horaria_distinta_de_utc_se_respeta(admin, variadas):
    # 12:10 UTC escrito en la hora de Lima (UTC−5).
    assert marcas(consultar(admin, **{"from": "2026-09-01T07:10:00-05:00", "to": "2026-09-01T07:11:00-05:00"})) == ["f2"]


def test_desde_igual_a_hasta_es_un_intervalo_vacio(admin, variadas):
    instante = (BASE + timedelta(minutes=10)).isoformat()

    respuesta = consultar(admin, **{"from": instante, "to": instante})

    assert respuesta.status_code == 200
    assert respuesta.json() == {"items": [], "limit": 20, "offset": 0, "has_more": False}


def test_desde_posterior_a_hasta_422(admin, variadas):
    desde, hasta = (BASE + timedelta(minutes=40)).isoformat(), (BASE + timedelta(minutes=10)).isoformat()

    respuesta = consultar(admin, **{"from": desde, "to": hasta})

    assert respuesta.status_code == 422
    assert [d["type"] for d in respuesta.json()["error"]["details"]] == ["date_range_inverted"]


VALOR_INVALIDO = "valor-invalido-4242"


@pytest.mark.parametrize(
    "parametros",
    [
        {"action": VALOR_INVALIDO}, {"action": "patient.create; DROP TABLE"}, {"action": "x" * 101 + ".y"},
        {"entity_type": VALOR_INVALIDO}, {"entity_type": "paciente"},
        {"entity_id": VALOR_INVALIDO}, {"actor_user_id": VALOR_INVALIDO},
        {"from": VALOR_INVALIDO}, {"to": VALOR_INVALIDO},
        {"from": "2026-09-01T12:00:00"}, {"to": "2026-09-01"},
        {"limit": 0}, {"limit": 51}, {"limit": VALOR_INVALIDO}, {"offset": -1},
        {"outcome": "success"}, {"id": 1}, {"order": "asc"},
    ],
    ids=[
        "acción sin formato", "acción con SQL", "acción demasiado larga", "entidad desconocida", "entidad traducida",
        "entidad que no es UUID", "actor que no es UUID", "desde que no es fecha", "hasta que no es fecha",
        "desde sin zona horaria", "hasta sin hora", "límite 0", "límite 51", "límite no numérico", "desplazamiento -1",
        "filtro no admitido", "id interno", "orden no admitido",
    ],
)
def test_filtro_invalido_422_sin_repetir_el_valor(parametros, admin, base_migrada):
    insertar(base_migrada, request_id="fila-secreta")

    respuesta = consultar(admin, **parametros)

    assert respuesta.status_code == 422, respuesta.text
    assert respuesta.json()["error"]["code"] == "validation_error"
    assert "fila-secreta" not in respuesta.text
    for valor in parametros.values():
        if isinstance(valor, str):
            assert valor not in respuesta.text, "el 422 no repite el valor recibido"


# --- Sin caché y sin rastro en los logs -------------------------------------------------------------------


def test_la_auditoria_no_se_almacena_en_cache(admin, base_migrada):
    insertar(base_migrada)

    respuesta = consultar(admin)

    assert respuesta.status_code == 200
    assert respuesta.headers["cache-control"] == "no-store"


def test_consultar_la_auditoria_no_deja_valores_en_los_logs(admin, flujo_clinico, caplog, capsys):
    capsys.readouterr()
    caplog.clear()
    caplog.set_level(logging.DEBUG)
    paciente_id = flujo_clinico["paciente"]["id"]

    respuesta = consultar(admin, entity_id=paciente_id, action="patient.update",
                          **{"from": "2026-01-01T00:00:00Z"})

    assert len(items(respuesta)) == 1
    capturado = capsys.readouterr()
    de_la_aplicacion = [r for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))]
    registros = "\n".join(r.getMessage() for r in de_la_aplicacion) + capturado.out + capturado.err
    assert '"route": "/api/v1/audit-log"' in capturado.out, "control positivo: la consulta se registró"
    for prohibido in (paciente_id, "patient.update", "family_names", "2026-01-01", "Centinelanombre", "CENTINELA16"):
        assert prohibido not in registros, f"los logs exponen {prohibido!r}"
