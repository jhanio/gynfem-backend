"""Garantías transversales de la persistencia clínica (Fase 10).

- `/predict` sigue sin estado, igual que en el PR #7.
- Ningún valor clínico, nombre ni documento llega a los logs.
- Una caída de la base en una escritura responde 503 uniforme.
- Toda ruta clínica depende de `get_actor`, el punto de enganche de la Fase 11.
"""

import logging

import pytest
from fastapi.routing import APIRoute
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


def test_predict_no_toca_la_base(cliente_bd, monkeypatch):
    cliente = cliente_bd()
    pool = cliente.app.state.db_pool
    pedidas = []
    original = pool.connection
    monkeypatch.setattr(pool, "connection", lambda *a, **k: pedidas.append(1) or original(*a, **k))

    assert cliente.post("/api/v1/predict", json=ENTRADA_EXTRAPOLADA).status_code == 200
    assert pedidas == []


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
    prohibidos = [NOMBRE_CENTINELA, APELLIDO_CENTINELA, DOCUMENTO_CENTINELA.lower(), DOCUMENTO_CENTINELA,
                  pid, medicion["measurement"]["id"], *(str(v) for v in MEDIDAS_CENTINELA.values())]
    for prohibido in prohibidos:
        assert prohibido not in registros, f"los logs exponen {prohibido!r}"


def test_escritura_con_la_base_caida_503(configurar, modelo_real, capsys):
    from app.factory import create_app

    url = f"postgresql://gynfem@127.0.0.1:{puerto_cerrado()}/gynfem"
    configurar(environment="development", cors_origins=ORIGEN_LOCAL, database_url=url, db_pool_timeout_s="1")
    with TestClient(create_app(model=modelo_real), raise_server_exceptions=False) as cliente:
        respuesta = cliente.post(PACIENTES, json={
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


PREFIJOS_CLINICOS = ("/api/v1/patients", "/api/v1/measurements", "/api/v1/predictions")


def _depende_de(dependant, objetivo) -> bool:
    return any(d.call is objetivo or _depende_de(d, objetivo) for d in dependant.dependencies)


def _rutas_efectivas(app) -> list:
    """Rutas con su ruta completa y sus dependencias efectivas.

    Desde FastAPI 0.141, `app.routes` agrupa lo incluido con `include_router` en
    un `_IncludedRouter`; sus rutas efectivas salen de `effective_route_contexts`.
    """
    rutas = []
    for ruta in app.routes:
        if isinstance(ruta, APIRoute):
            rutas.append(ruta)
        contextos = getattr(ruta, "effective_route_contexts", None)
        if contextos is not None:
            rutas.extend(contextos() if callable(contextos) else contextos)
    return rutas


def test_toda_ruta_clinica_depende_de_get_actor(configurar, modelo_real):
    """El punto de enganche de la autenticación (Fase 11): ninguna ruta clínica lo olvida."""
    from app.api.deps import get_actor
    from app.factory import create_app

    configurar(environment="development", cors_origins=ORIGEN_LOCAL)
    rutas = _rutas_efectivas(create_app(model=modelo_real))
    clinicas = [r for r in rutas if r.path.startswith(PREFIJOS_CLINICOS)]
    logging.getLogger("gynfem").handlers.clear()

    assert len(clinicas) >= 8
    for ruta in clinicas:
        assert _depende_de(ruta.dependant, get_actor), f"{sorted(ruta.methods)} {ruta.path} no depende de get_actor"


def test_get_actor_es_anonimo_hasta_la_fase_11():
    from app.api.deps import Actor, get_actor

    assert get_actor() == Actor(user_id=None, role=None)


@pytest.mark.parametrize("ruta", ["/api/v1/predict", "/api/v1/prediction/schema", "/api/v1/health"])
def test_rutas_sin_estado_no_cambian_de_politica(ruta, configurar, modelo_real):
    """La Fase 10 no decide la política de acceso de las rutas de las Fases 7 y 8."""
    from app.api.deps import get_actor
    from app.factory import create_app

    configurar(environment="development", cors_origins=ORIGEN_LOCAL)
    rutas = {r.path: r for r in _rutas_efectivas(create_app(model=modelo_real))}
    logging.getLogger("gynfem").handlers.clear()
    assert not _depende_de(rutas[ruta].dependant, get_actor)


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
