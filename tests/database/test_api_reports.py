"""HU009: reporte de una evaluación, con los datos de la paciente, sus mediciones,
el resultado y la advertencia clínica.

Contra la aplicación completa y el PostgreSQL embebido, con datos sintéticos.
El reporte no inventa ni recalcula nada: contiene lo ya almacenado. Es `POST`
porque cada generación deja un registro de auditoría (`prediction.report`): es
el punto en que datos personales salen del sistema.
"""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from api.api_constantes import CAMPOS_CLINICOS, ENTRADA_EXTRAPOLADA, ENTRADA_NORMAL
from api.auth_claves import MEDICO_ID

from .conftest import filas
from .datos_sinteticos import CAMPOS_INTERNOS, PACIENTE

PACIENTES = "/api/v1/patients"
CONFIGURACION = "/api/v1/settings"
UUID_INEXISTENTE = "00000000-0000-4000-8000-000000000000"

CLAVES_REPORTE = {"institution_name", "generated_at", "patient", "measurement", "prediction", "clinical_disclaimer"}
CLAVES_PACIENTE = {"id", "document_type", "document_number", "given_names", "family_names"}
CLAVES_MEDICION = {"id", "measured_at", *CAMPOS_CLINICOS}
CLAVES_PREDICCION = {
    "id", "risk_level", "probabilities", "extrapolation_warnings",
    "model_version", "conversion_schema_version", "predicted_at", "status",
}
CLAVES_PROBABILIDADES = {"high", "mid", "low"}
CLAVES_AVISO = {"field", "direction", "unit", "training_min", "training_max", "message"}

#: Centinelas: identidad y valores clínicos que nunca deben verse en un log.
PACIENTE_CENTINELA = {
    "document_type": "PASAPORTE", "document_number": "CENTINELA16",
    "given_names": "Centinelanombre", "family_names": "Centinelapellido",
}
MEDIDAS_CENTINELA = {
    "age_years": 31.4159, "temperature_c": 36.7182, "heart_rate_bpm": 83.1415,
    "systolic_bp_mmhg": 123.4567, "diastolic_bp_mmhg": 76.5432, "bmi_kg_m2": 23.4567,
    "hba1c_percent": 5.4321, "fasting_glucose_mg_dl": 91.2345,
}
INSTITUCION_CENTINELA = "Centinelainstitucion Zeta"


def evaluar(cliente, entrada=ENTRADA_NORMAL, datos=PACIENTE) -> tuple[dict, dict]:
    """Paciente sintética con una evaluación: la paciente y la evaluación, como las devolvió la API."""
    paciente = cliente.post(PACIENTES, json=datos)
    assert paciente.status_code == 201, paciente.text
    evaluacion = cliente.post(f"{PACIENTES}/{paciente.json()['id']}/measurements", json=entrada)
    assert evaluacion.status_code == 201, evaluacion.text
    return paciente.json(), evaluacion.json()


def reporte(cliente, prediction_id: str, **kwargs):
    return cliente.post(f"/api/v1/predictions/{prediction_id}/report", **kwargs)


def auditoria_de_reportes(url: str) -> list[tuple]:
    return filas(
        url,
        "SELECT action, entity_type, entity_id::text, outcome, actor_user_id, request_id, changed_fields "
        "FROM gynfem.audit_log WHERE action = 'prediction.report' ORDER BY id",
    )


def sin_request_id(respuesta) -> dict:
    error = dict(respuesta.json()["error"])
    error.pop("request_id")
    return error


# --- Contrato -----------------------------------------------------------------------------


def test_el_reporte_tiene_exactamente_las_claves_documentadas(cliente_bd):
    cliente = cliente_bd()
    _, evaluacion = evaluar(cliente, ENTRADA_EXTRAPOLADA)

    respuesta = reporte(cliente, evaluacion["prediction"]["id"])

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert set(cuerpo) == CLAVES_REPORTE
    assert set(cuerpo["patient"]) == CLAVES_PACIENTE
    assert set(cuerpo["measurement"]) == CLAVES_MEDICION
    assert set(cuerpo["prediction"]) == CLAVES_PREDICCION
    assert set(cuerpo["prediction"]["probabilities"]) == CLAVES_PROBABILIDADES
    assert len(cuerpo["prediction"]["extrapolation_warnings"]) == 2, "control: la entrada extrapola"
    for aviso in cuerpo["prediction"]["extrapolation_warnings"]:
        assert set(aviso) == CLAVES_AVISO


def test_el_reporte_no_expone_campos_internos(cliente_bd):
    cliente = cliente_bd()
    _, evaluacion = evaluar(cliente)

    respuesta = reporte(cliente, evaluacion["prediction"]["id"])

    assert respuesta.status_code == 200, "control: se inspecciona un reporte, no un error"
    for campo in (*CAMPOS_INTERNOS, "input_", "model_input", "patient_id", "created_at", "updated_at"):
        assert campo not in respuesta.text, campo


# --- Solo lo almacenado ---------------------------------------------------------------------


def test_el_reporte_contiene_exactamente_lo_almacenado(cliente_bd):
    cliente = cliente_bd()
    paciente, evaluacion = evaluar(cliente, ENTRADA_EXTRAPOLADA)
    pid = evaluacion["prediction"]["id"]
    guardada = cliente.get(f"/api/v1/predictions/{pid}").json()
    ficha = cliente.get(f"{PACIENTES}/{paciente['id']}").json()

    cuerpo = reporte(cliente, pid).json()

    assert cuerpo["patient"] == {clave: ficha[clave] for clave in CLAVES_PACIENTE}
    assert cuerpo["patient"]["document_number"] == "00000001", "el documento va completo, sin enmascarar"
    assert cuerpo["measurement"] == {clave: evaluacion["measurement"][clave] for clave in CLAVES_MEDICION}
    assert {c: cuerpo["measurement"][c] for c in CAMPOS_CLINICOS} == guardada["input"]
    for clave in CLAVES_PREDICCION - {"status"}:
        assert cuerpo["prediction"][clave] == guardada[clave], clave
    assert cuerpo["prediction"]["status"] == "current"
    assert cuerpo["institution_name"] == "GynFem"


def test_generar_el_reporte_no_vuelve_a_predecir(cliente_bd, espia, modelo_espiado):
    cliente = cliente_bd(modelo=modelo_espiado)
    _, evaluacion = evaluar(cliente)
    assert len(espia.llamadas) == 1, "control: la evaluación sí predijo"

    assert reporte(cliente, evaluacion["prediction"]["id"]).status_code == 200
    assert reporte(cliente, evaluacion["prediction"]["id"]).status_code == 200

    assert len(espia.llamadas) == 1


def test_el_reporte_lleva_la_advertencia_clinica(cliente_bd):
    from app.services.prediction import CLINICAL_DISCLAIMER

    cliente = cliente_bd()
    _, evaluacion = evaluar(cliente)

    cuerpo = reporte(cliente, evaluacion["prediction"]["id"]).json()

    assert cuerpo["clinical_disclaimer"] == CLINICAL_DISCLAIMER
    assert cuerpo["clinical_disclaimer"].strip()


def test_generated_at_es_la_hora_utc_de_la_generacion(cliente_bd):
    cliente = cliente_bd()
    _, evaluacion = evaluar(cliente)
    antes = datetime.now(UTC)

    cuerpo = reporte(cliente, evaluacion["prediction"]["id"]).json()

    generado = datetime.fromisoformat(cuerpo["generated_at"])
    assert generado.utcoffset() == timedelta(0)
    assert antes - timedelta(seconds=5) <= generado <= datetime.now(UTC) + timedelta(seconds=5)


def test_el_reporte_de_una_evaluacion_corregida_indica_corrected(cliente_bd):
    cliente = cliente_bd()
    _, original = evaluar(cliente, ENTRADA_EXTRAPOLADA)
    correccion = cliente.post(
        f"/api/v1/measurements/{original['measurement']['id']}/corrections", json=ENTRADA_NORMAL
    ).json()

    de_la_original = reporte(cliente, original["prediction"]["id"]).json()
    de_la_correccion = reporte(cliente, correccion["prediction"]["id"]).json()

    assert de_la_original["prediction"]["status"] == "corrected"
    assert de_la_correccion["prediction"]["status"] == "current"
    # La evaluación corregida se reporta con sus propios valores y su propio riesgo.
    assert de_la_original["measurement"]["bmi_kg_m2"] == ENTRADA_EXTRAPOLADA["bmi_kg_m2"]
    assert de_la_original["prediction"]["risk_level"] == original["prediction"]["risk_level"]
    assert de_la_correccion["measurement"]["bmi_kg_m2"] == ENTRADA_NORMAL["bmi_kg_m2"]


# --- El nombre de la institución es un parámetro (HU011) -------------------------------------


def test_el_reporte_usa_el_nombre_de_institucion_vigente(cliente_bd):
    cliente = cliente_bd()
    _, evaluacion = evaluar(cliente)
    pid = evaluacion["prediction"]["id"]
    administrador = cliente_bd(rol="administrador")

    assert reporte(cliente, pid).json()["institution_name"] == "GynFem"
    administrador.patch(CONFIGURACION, json={"institution_name": "Centro de Prueba"})
    assert reporte(cliente, pid).json()["institution_name"] == "Centro de Prueba"
    administrador.patch(CONFIGURACION, json={"institution_name": "Otro Centro"})
    assert reporte(cliente, pid).json()["institution_name"] == "Otro Centro"


# --- 404 ---------------------------------------------------------------------------------------


def test_prediccion_inexistente_y_de_paciente_dada_de_baja_dan_el_mismo_404(cliente_bd, base_migrada):
    cliente = cliente_bd()
    paciente, evaluacion = evaluar(cliente)
    assert reporte(cliente, evaluacion["prediction"]["id"]).status_code == 200, "control: antes de la baja hay reporte"
    assert cliente.delete(f"{PACIENTES}/{paciente['id']}").status_code == 204
    auditados = len(auditoria_de_reportes(base_migrada))

    de_baja, inexistente = reporte(cliente, evaluacion["prediction"]["id"]), reporte(cliente, UUID_INEXISTENTE)

    assert de_baja.status_code == inexistente.status_code == 404
    assert sin_request_id(de_baja) == sin_request_id(inexistente) == {
        "code": "prediction_not_found", "message": "Predicción no encontrada.",
    }
    for dato in (PACIENTE["document_number"], PACIENTE["given_names"], PACIENTE["family_names"]):
        assert dato not in de_baja.text
    assert len(auditoria_de_reportes(base_migrada)) == auditados, "un reporte que no se entrega no se audita"


def test_id_que_no_es_uuid_422(cliente_bd):
    assert reporte(cliente_bd(), "no-es-un-uuid").status_code == 422


# --- Auditoría de la generación ------------------------------------------------------------------


def test_generar_reporte_audita_prediction_report(cliente_bd, base_migrada):
    cliente = cliente_bd()
    _, evaluacion = evaluar(cliente)
    pid = evaluacion["prediction"]["id"]
    assert auditoria_de_reportes(base_migrada) == []

    respuesta = reporte(cliente, pid, headers={"X-Request-ID": "reporte-16"})

    assert respuesta.status_code == 200
    assert auditoria_de_reportes(base_migrada) == [
        ("prediction.report", "prediction", pid, "success", MEDICO_ID, "reporte-16", None)
    ]


def test_cada_generacion_se_audita(cliente_bd, base_migrada):
    cliente = cliente_bd()
    _, evaluacion = evaluar(cliente)

    for _ in range(3):
        assert reporte(cliente, evaluacion["prediction"]["id"]).status_code == 200

    assert len(auditoria_de_reportes(base_migrada)) == 3


def test_si_falla_la_auditoria_no_se_entrega_el_reporte(cliente_bd, base_migrada, monkeypatch):
    """Sin su registro de auditoría, los datos personales no salen."""
    from app.services import reports

    cliente = cliente_bd()
    _, evaluacion = evaluar(cliente, MEDIDAS_CENTINELA, PACIENTE_CENTINELA)

    def fallar(*args, **kwargs):
        raise RuntimeError("fallo forzado de la auditoría")

    monkeypatch.setattr(reports.audit_repo, "insert_audit", fallar)

    respuesta = reporte(cliente, evaluacion["prediction"]["id"])

    assert respuesta.status_code == 500
    assert set(respuesta.json()) == {"error"}
    assert respuesta.json()["error"]["code"] == "internal_error"
    prohibidos = [*PACIENTE_CENTINELA.values(), *(str(v) for v in MEDIDAS_CENTINELA.values()), "risk_level", "patient"]
    for prohibido in prohibidos:
        assert prohibido not in respuesta.text, f"la respuesta fallida expone {prohibido!r}"
    assert auditoria_de_reportes(base_migrada) == []


def test_el_reporte_solo_escribe_su_auditoria(cliente_bd, base_migrada):
    cliente = cliente_bd()
    _, evaluacion = evaluar(cliente)
    tablas = ("patients", "clinical_measurements", "predictions", "system_settings")
    antes = [filas(base_migrada, f"SELECT count(*), max(updated_at) FROM gynfem.{t}") if t != "system_settings"
             else filas(base_migrada, f"SELECT count(*) FROM gynfem.{t}") for t in tablas]
    auditoria_antes = filas(base_migrada, "SELECT count(*) FROM gynfem.audit_log")[0][0]

    assert reporte(cliente, evaluacion["prediction"]["id"]).status_code == 200

    despues = [filas(base_migrada, f"SELECT count(*), max(updated_at) FROM gynfem.{t}") if t != "system_settings"
               else filas(base_migrada, f"SELECT count(*) FROM gynfem.{t}") for t in tablas]
    assert despues == antes
    assert filas(base_migrada, "SELECT count(*) FROM gynfem.audit_log")[0][0] == auditoria_antes + 1


# --- Datos personales: sin caché -------------------------------------------------------------------


def test_el_reporte_no_se_almacena_en_cache(cliente_bd):
    cliente = cliente_bd()
    _, evaluacion = evaluar(cliente)

    respuesta = reporte(cliente, evaluacion["prediction"]["id"])

    assert respuesta.status_code == 200
    assert respuesta.headers["cache-control"] == "no-store"


# --- Acceso ------------------------------------------------------------------------------------------


def test_administrador_403_exista_o_no_la_prediccion(cliente_bd, base_migrada):
    medico = cliente_bd()
    _, evaluacion = evaluar(medico)
    administrador = cliente_bd(rol="administrador")

    existente = reporte(administrador, evaluacion["prediction"]["id"])
    inexistente = reporte(administrador, UUID_INEXISTENTE)

    assert existente.status_code == inexistente.status_code == 403
    assert sin_request_id(existente) == sin_request_id(inexistente)
    assert existente.json()["error"]["code"] == "forbidden"
    assert "patient" not in existente.text
    assert auditoria_de_reportes(base_migrada) == []


def test_sin_token_401_exista_o_no_la_prediccion(cliente_bd, base_migrada):
    medico = cliente_bd()
    _, evaluacion = evaluar(medico)
    anonimo = cliente_bd(rol=None)

    existente = reporte(anonimo, evaluacion["prediction"]["id"])
    inexistente = reporte(anonimo, UUID_INEXISTENTE)

    assert existente.status_code == inexistente.status_code == 401
    assert sin_request_id(existente) == sin_request_id(inexistente)
    assert auditoria_de_reportes(base_migrada) == []


def test_el_reporte_no_se_pide_con_get(cliente_bd):
    """`GET` no existe: una lectura cacheable o precargada por el navegador no debe
    sacar datos personales ni escribir auditoría."""
    cliente = cliente_bd()
    _, evaluacion = evaluar(cliente)

    assert cliente.get(f"/api/v1/predictions/{evaluacion['prediction']['id']}/report").status_code == 405


# --- Logs ------------------------------------------------------------------------------------------------


def test_los_logs_del_reporte_no_llevan_identidad_ni_valores_clinicos(cliente_bd, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    cliente = cliente_bd()
    cliente_bd(rol="administrador").patch(CONFIGURACION, json={"institution_name": INSTITUCION_CENTINELA})
    paciente, evaluacion = evaluar(cliente, MEDIDAS_CENTINELA, PACIENTE_CENTINELA)

    respuesta = reporte(cliente, evaluacion["prediction"]["id"])

    assert respuesta.status_code == 200
    assert respuesta.json()["patient"]["given_names"] == "Centinelanombre", "control: el reporte sí lleva la identidad"
    capturado = capsys.readouterr()
    de_la_aplicacion = [r for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))]
    registros = "\n".join(r.getMessage() for r in de_la_aplicacion) + capturado.out + capturado.err
    assert '"route": "/api/v1/predictions/{prediction_id}/report"' in capturado.out, (
        "control positivo: el reporte se registró con la plantilla de la ruta"
    )
    assert '"action": "prediction.report"' in capturado.out, "control positivo: hubo log de la generación"
    prohibidos = [
        "Centinelanombre", "Centinelapellido", "CENTINELA16", "centinela16", "Centinelainstitucion",
        paciente["id"], evaluacion["prediction"]["id"], evaluacion["measurement"]["id"],
        *(str(v) for v in MEDIDAS_CENTINELA.values()),
    ]
    for prohibido in prohibidos:
        assert prohibido not in registros, f"los logs exponen {prohibido!r}"
