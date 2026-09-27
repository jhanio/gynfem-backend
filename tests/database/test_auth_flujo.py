"""El flujo clínico de la Fase 10 con autenticación real (HU001 sobre HU003–HU005).

- La identidad sale siempre del token verificado, nunca del cuerpo, la URL ni
  una cabecera (decisión aprobada 3).
- Cada escritura registra al médico del token en `*_by` y en la auditoría.
- Un 401 o un 403 no revelan si el recurso existe (decisión aprobada 9).
"""

import uuid

from api.api_constantes import ENTRADA_EXTRAPOLADA, ENTRADA_NORMAL

from .auth_bd import crear_usuario
from .conftest import filas
from .datos_sinteticos import PACIENTE, buscar

PACIENTES = "/api/v1/patients"
UUID_INEXISTENTE = "00000000-0000-4000-8000-000000000000"


def test_flujo_clinico_completo_registra_al_medico_del_token(cliente_bd, base_migrada, usuarios):
    medico = cliente_bd(rol="medico")
    creada = medico.post(PACIENTES, json=PACIENTE)
    assert creada.status_code == 201
    pid = creada.json()["id"]

    assert buscar(medico, {"name": "Sintética"}).status_code == 200
    assert medico.get(f"{PACIENTES}/{pid}").status_code == 200
    assert medico.patch(f"{PACIENTES}/{pid}", json={"family_names": "Prueba Dos"}).status_code == 200
    evaluacion = medico.post(f"{PACIENTES}/{pid}/measurements", json=ENTRADA_EXTRAPOLADA)
    assert evaluacion.status_code == 201
    mid = evaluacion.json()["measurement"]["id"]
    assert medico.get(f"{PACIENTES}/{pid}/measurements").status_code == 200
    corregida = medico.post(f"/api/v1/measurements/{mid}/corrections", json=ENTRADA_NORMAL)
    assert corregida.status_code == 201
    assert medico.get(f"/api/v1/predictions/{corregida.json()['prediction']['id']}").status_code == 200
    assert medico.delete(f"{PACIENTES}/{pid}").status_code == 204

    yo = usuarios["medico"]
    assert filas(base_migrada, "SELECT created_by, updated_by, deleted_by FROM gynfem.patients") == [(yo, yo, yo)]
    assert set(filas(base_migrada, "SELECT created_by, updated_by FROM gynfem.clinical_measurements")) == {(yo, yo)}
    assert set(filas(base_migrada, "SELECT created_by FROM gynfem.predictions")) == {(yo,)}
    assert set(filas(base_migrada, "SELECT actor_user_id FROM gynfem.audit_log")) == {(yo,)}


def test_identidad_del_cuerpo_no_anula_la_del_token(cliente_bd, base_migrada, usuarios):
    otro = crear_usuario(base_migrada, "medico")
    medico = cliente_bd(rol="medico")

    for campo in ("created_by", "actor_user_id", "user_id"):
        assert medico.post(PACIENTES, json={**PACIENTE, campo: str(otro)}).status_code == 422
    respuesta = medico.post(PACIENTES, json=PACIENTE, headers={"X-User-Id": str(otro), "X-Actor": str(otro)})

    assert respuesta.status_code == 201
    assert filas(base_migrada, "SELECT created_by FROM gynfem.patients") == [(usuarios["medico"],)]
    assert filas(base_migrada, "SELECT actor_user_id FROM gynfem.audit_log") == [(usuarios["medico"],)]


def test_el_administrador_no_ve_datos_clinicos(cliente_bd):
    creada = cliente_bd(rol="medico").post(PACIENTES, json=PACIENTE).json()
    admin = cliente_bd(rol="administrador")

    for respuesta in (
        admin.get(f"{PACIENTES}/{creada['id']}"),
        buscar(admin, {"name": "Sintética"}),
        admin.get(f"{PACIENTES}/{creada['id']}/measurements"),
    ):
        assert respuesta.status_code == 403
        assert "Sintética" not in respuesta.text


def test_403_no_revela_si_la_paciente_existe(cliente_bd):
    creada = cliente_bd(rol="medico").post(PACIENTES, json=PACIENTE).json()
    admin = cliente_bd(rol="administrador")

    existente = admin.get(f"{PACIENTES}/{creada['id']}")
    inexistente = admin.get(f"{PACIENTES}/{UUID_INEXISTENTE}")

    assert existente.status_code == inexistente.status_code == 403
    assert _sin_request_id(existente.json()) == _sin_request_id(inexistente.json())


def test_401_no_revela_si_la_paciente_existe(cliente_bd):
    creada = cliente_bd(rol="medico").post(PACIENTES, json=PACIENTE).json()
    anonimo = cliente_bd(rol=None)

    existente = anonimo.get(f"{PACIENTES}/{creada['id']}")
    inexistente = anonimo.get(f"{PACIENTES}/{UUID_INEXISTENTE}")

    assert existente.status_code == inexistente.status_code == 401
    assert _sin_request_id(existente.json()) == _sin_request_id(inexistente.json())


def test_403_de_usuarios_no_revela_si_el_usuario_existe(cliente_bd, usuarios):
    medico = cliente_bd(rol="medico")

    existente = medico.get(f"/api/v1/users/{usuarios['administrador']}")
    inexistente = medico.get(f"/api/v1/users/{uuid.uuid4()}")

    assert existente.status_code == inexistente.status_code == 403
    assert _sin_request_id(existente.json()) == _sin_request_id(inexistente.json())


def test_usuario_desactivado_no_escribe(cliente_bd, base_migrada, token_de):
    inactivo = crear_usuario(base_migrada, "medico", activo=False)
    cliente = cliente_bd(rol=None)
    cliente.headers.update(token_de(inactivo))

    respuesta = cliente.post(PACIENTES, json=PACIENTE)

    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["code"] == "account_disabled"
    assert filas(base_migrada, "SELECT count(*) FROM gynfem.patients") == [(0,)]


def test_usuario_de_auth_sin_perfil_no_opera(cliente_bd, base_migrada, token_de):
    huerfano = uuid.uuid4()
    filas_insertadas = filas(base_migrada, "INSERT INTO auth.users (id) VALUES (%s) RETURNING id", [huerfano])
    assert filas_insertadas == [(huerfano,)]
    cliente = cliente_bd(rol=None)
    cliente.headers.update(token_de(huerfano))

    assert cliente.post("/api/v1/predict", json=ENTRADA_NORMAL).status_code == 403


def _sin_request_id(cuerpo: dict) -> dict:
    return {**cuerpo, "error": {k: v for k, v in cuerpo["error"].items() if k != "request_id"}}
