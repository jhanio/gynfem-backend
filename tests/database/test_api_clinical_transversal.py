"""Garantías transversales de la persistencia clínica (Fase 10).

- `/predict` sigue sin estado, igual que en el PR #7.
- Ningún valor clínico, nombre ni documento llega a los logs.
- Una caída de la base en una escritura responde 503 uniforme.
- Desde la Fase 11, la decisión de acceso de cada ruta la verifican
  `tests/api/test_auth_rbac.py` (matriz) y `test_auth_flujo.py` (actor real).
"""

import logging

import pytest
from fastapi.testclient import TestClient

from api.api_constantes import ENTRADA_EXTRAPOLADA, ORIGEN_LOCAL

from .conftest import filas, puerto_cerrado
from .datos_sinteticos import buscar

PACIENTES = "/api/v1/patients"


def test_predict_sin_paciente_sigue_igual_y_no_escribe(cliente_bd, base_migrada):
    respuesta = cliente_bd().post("/api/v1/predict", json=ENTRADA_EXTRAPOLADA)

    assert respuesta.status_code == 200
    assert set(respuesta.json()) == {
        "risk_level", "probabilities", "extrapolation_warnings", "clinical_disclaimer",
        "input", "model_input", "model_version", "conversion_schema_version", "predicted_at",
    }
    for tabla in ("patients", "clinical_measurements", "predictions", "audit_log"):
        assert filas(base_migrada, f"SELECT count(*) FROM gynfem.{tabla}") == [(0,)], tabla


def test_predict_solo_lee_el_perfil_del_usuario(cliente_bd, base_migrada, monkeypatch):
    """Fase 11: `/predict` pide una sola conexión, la que lee el rol y el estado del
    usuario (decisión 8: se comprueban en cada petición). No escribe nada."""
    cliente = cliente_bd()
    pool = cliente.app.state.db_pool
    pedidas = []
    original = pool.connection
    monkeypatch.setattr(pool, "connection", lambda *a, **k: pedidas.append(1) or original(*a, **k))

    assert cliente.post("/api/v1/predict", json=ENTRADA_EXTRAPOLADA).status_code == 200
    assert pedidas == [1]
    for tabla in ("patients", "clinical_measurements", "predictions", "audit_log"):
        assert filas(base_migrada, f"SELECT count(*) FROM gynfem.{tabla}") == [(0,)], tabla


#: Centinelas: valores clínicos, nombres y documento que nunca deben verse en un log.
NOMBRE_CENTINELA = "Centinelanombre"
APELLIDO_CENTINELA = "Centinelapellido"
DOCUMENTO_CENTINELA = "CENTINELA42"
MEDIDAS_CENTINELA = {
    "age_years": 31.4159, "temperature_c": 36.7182, "heart_rate_bpm": 83.1415,
    "systolic_bp_mmhg": 123.4567, "diastolic_bp_mmhg": 76.5432, "bmi_kg_m2": 23.4567,
    "hba1c_percent": 5.4321, "fasting_glucose_mg_dl": 91.2345,
}


def test_logs_sin_valores_clinicos_nombres_ni_documentos(cliente_bd, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    cliente = cliente_bd()
    creada = cliente.post(PACIENTES, json={
        "document_type": "PASAPORTE", "document_number": DOCUMENTO_CENTINELA,
        "given_names": NOMBRE_CENTINELA, "family_names": APELLIDO_CENTINELA,
    }).json()
    pid = creada["id"]
    medicion = cliente.post(f"{PACIENTES}/{pid}/measurements", json=MEDIDAS_CENTINELA).json()
    cliente.get(f"{PACIENTES}/{pid}")
    buscar(cliente, {"name": NOMBRE_CENTINELA})
    buscar(cliente, {"document_type": "PASAPORTE", "document_number": DOCUMENTO_CENTINELA})
    cliente.patch(f"{PACIENTES}/{pid}", json={"family_names": APELLIDO_CENTINELA + "b"})
    cliente.get(f"{PACIENTES}/{pid}/measurements")
    cliente.post(f"/api/v1/measurements/{medicion['measurement']['id']}/corrections", json=MEDIDAS_CENTINELA)
    cliente.get(f"/api/v1/predictions/{medicion['prediction']['id']}")
    # Fase 16 (HU008): el historial, con la original corregida y la corrección.
    historial = cliente.get(f"{PACIENTES}/{pid}/evaluations")
    assert len(historial.json()["items"]) == 2, "control positivo: el historial devolvió las evaluaciones"
    cliente.get(f"{PACIENTES}/{pid}/evaluations", params={"limit": 1, "offset": 1})
    cliente.post(PACIENTES, json={"document_type": "DNI", "document_number": DOCUMENTO_CENTINELA,
                                  "given_names": NOMBRE_CENTINELA, "family_names": "x"})
    cliente.delete(f"{PACIENTES}/{pid}")

    capturado = capsys.readouterr()
    # El cliente de pruebas (httpx2, bajo TestClient) registra la URL de cada petición
    # que él mismo envía; no forma parte de la aplicación ni existe en producción.
    de_la_aplicacion = [r for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))]
    assert len(de_la_aplicacion) < len(caplog.records), "control: el filtro solo quita al cliente de pruebas"
    registros = "\n".join(r.getMessage() for r in de_la_aplicacion) + capturado.out + capturado.err
    assert '"logger": "gynfem.access"' in capturado.out, "control positivo: hubo log de acceso"
    assert '"logger": "gynfem.clinical"' in capturado.out, "control positivo: hubo log de las escrituras"
    assert '"route": "/api/v1/patients/{patient_id}/evaluations"' in capturado.out, (
        "control positivo: el historial se registró con la plantilla de la ruta"
    )
    prohibidos = [NOMBRE_CENTINELA, APELLIDO_CENTINELA, DOCUMENTO_CENTINELA.lower(), DOCUMENTO_CENTINELA,
                  pid, medicion["measurement"]["id"], *(str(v) for v in MEDIDAS_CENTINELA.values())]
    for prohibido in prohibidos:
        assert prohibido not in registros, f"los logs exponen {prohibido!r}"


def test_escritura_con_la_base_caida_503(configurar, modelo_real, emisor, capsys):
    """Desde la Fase 11 la base se consulta ya al autorizar: la caída da el mismo 503."""
    from uuid import UUID

    from api.auth_claves import EMISOR_FICTICIO, FuenteDeClavesEnMemoria, cabecera
    from app.auth.tokens import TokenVerifier
    from app.factory import create_app

    url = f"postgresql://gynfem@127.0.0.1:{puerto_cerrado()}/gynfem"
    configurar(environment="development", cors_origins=ORIGEN_LOCAL, database_url=url, db_pool_timeout_s="1")
    verificador = TokenVerifier(FuenteDeClavesEnMemoria(emisor), EMISOR_FICTICIO)
    with TestClient(create_app(model=modelo_real, token_verifier=verificador), raise_server_exceptions=False) as cliente:
        # Un id que no contiene el documento centinela: el log sí registra el user_id.
        usuario = UUID("abcdefab-cdef-4abc-8def-abcdefabcdef")
        respuesta = cliente.post(PACIENTES, headers=cabecera(emisor.token(usuario)), json={
            "document_type": "DNI", "document_number": "00000001",
            "given_names": "Sintética", "family_names": "Prueba",
        })
    logging.getLogger("gynfem").handlers.clear()

    assert respuesta.status_code == 503
    error = respuesta.json()["error"]
    assert error["code"] == "database_unavailable"
    assert "127.0.0.1" not in respuesta.text
    salida = capsys.readouterr().out
    assert '"logger": "gynfem.errors"' in salida, "control positivo: la caída se registró"
    for prohibido in ("Sintética", "00000001", "127.0.0.1"):
        assert prohibido not in salida


def test_las_columnas_clinicas_del_repositorio_son_los_campos_de_la_api():
    """El repositorio declara las columnas de su tabla; deben ser los campos de `PredictionRequest`."""
    from app.repositories.measurements import CAMPOS_CLINICOS
    from app.schemas.prediction import PredictionRequest

    assert list(CAMPOS_CLINICOS) == list(PredictionRequest.model_fields)


def test_los_repositorios_no_dependen_de_capas_superiores():
    """`api → services → repositories`, nunca al revés (`docs/ARCHITECTURE.md`)."""
    import ast

    from api.api_constantes import REPO_ROOT

    for archivo in (REPO_ROOT / "app" / "repositories").glob("*.py"):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        importados = [
            n.module for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom) and n.module
        ] + [a.name for n in ast.walk(arbol) if isinstance(n, ast.Import) for a in n.names]
        for modulo in importados:
            assert not modulo.startswith(("app.services", "app.api", "app.schemas")), f"{archivo.name} importa {modulo}"
