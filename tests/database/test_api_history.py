"""HU008: historial de evaluaciones de una paciente, ordenado en el tiempo y con su riesgo.

Contra la aplicación completa y el PostgreSQL embebido, con datos sintéticos.
Una evaluación es una medición con su predicción. El historial incluye las
corregidas, marcadas como tales: el médico pudo decidir con ellas.
"""

import psycopg
import pytest

from api.api_constantes import CAMPOS_CLINICOS, ENTRADA_EXTRAPOLADA, ENTRADA_NORMAL

from .conftest import filas
from .datos_sinteticos import CAMPOS_INTERNOS, CLAVES_MEDICION, PACIENTE, PACIENTE_DOS

PACIENTES = "/api/v1/patients"
CONFIGURACION = "/api/v1/settings"
UUID_INEXISTENTE = "00000000-0000-4000-8000-000000000000"
MISMA_HORA = "2026-09-01T10:00:00Z"

CLAVES_HISTORIAL = {"items", "limit", "offset", "has_more", "clinical_disclaimer"}
CLAVES_ITEM = {"measurement", "prediction", "status"}
#: La advertencia va una vez, en la página: no se repite en cada ítem.
CLAVES_PREDICCION_DEL_HISTORIAL = {
    "id", "risk_level", "probabilities", "extrapolation_warnings",
    "model_version", "conversion_schema_version", "predicted_at",
}


def crear_paciente(cliente, datos=PACIENTE) -> str:
    respuesta = cliente.post(PACIENTES, json=datos)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def medir(cliente, pid: str, entrada=ENTRADA_NORMAL, **extra) -> dict:
    respuesta = cliente.post(f"{PACIENTES}/{pid}/measurements", json={**entrada, **extra})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def historial(cliente, pid: str, **parametros):
    return cliente.get(f"{PACIENTES}/{pid}/evaluations", params=parametros)


def ids_de_medicion(respuesta) -> list[str]:
    assert respuesta.status_code == 200, respuesta.text
    return [item["measurement"]["id"] for item in respuesta.json()["items"]]


def sin_request_id(respuesta) -> dict:
    error = dict(respuesta.json()["error"])
    error.pop("request_id")
    return error


# --- Contenido --------------------------------------------------------------------------


def test_paciente_sin_evaluaciones_200_vacio(cliente_bd):
    from app.services.prediction import CLINICAL_DISCLAIMER

    cliente = cliente_bd()
    respuesta = historial(cliente, crear_paciente(cliente))

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "items": [], "limit": 20, "offset": 0, "has_more": False, "clinical_disclaimer": CLINICAL_DISCLAIMER,
    }


def test_cada_item_lleva_sus_variables_su_riesgo_sus_avisos_y_sus_versiones(cliente_bd):
    cliente = cliente_bd()
    pid = crear_paciente(cliente)
    creada = medir(cliente, pid, ENTRADA_EXTRAPOLADA)

    cuerpo = historial(cliente, pid).json()

    assert set(cuerpo) == CLAVES_HISTORIAL, "sin el total de filas"
    (item,) = cuerpo["items"]
    assert set(item) == CLAVES_ITEM
    assert set(item["measurement"]) == CLAVES_MEDICION
    assert set(item["prediction"]) == CLAVES_PREDICCION_DEL_HISTORIAL
    # Exactamente lo que devolvió el registro de la evaluación, sin recalcular nada.
    assert item["measurement"] == creada["measurement"]
    assert {c: item["measurement"][c] for c in CAMPOS_CLINICOS} == {c: float(v) for c, v in ENTRADA_EXTRAPOLADA.items()}
    esperada = {k: v for k, v in creada["prediction"].items() if k != "clinical_disclaimer"}
    assert item["prediction"] == esperada
    assert item["prediction"]["risk_level"] == "high"
    assert [a["field"] for a in item["prediction"]["extrapolation_warnings"]] == ["bmi_kg_m2", "hba1c_percent"]
    assert item["status"] == "current"


def test_el_historial_lleva_la_advertencia_clinica(cliente_bd):
    from app.services.prediction import CLINICAL_DISCLAIMER

    cliente = cliente_bd()
    pid = crear_paciente(cliente)
    medir(cliente, pid)

    assert historial(cliente, pid).json()["clinical_disclaimer"] == CLINICAL_DISCLAIMER


# --- Orden y paginación -------------------------------------------------------------------


def test_ordena_de_la_medicion_mas_reciente_a_la_mas_antigua(cliente_bd):
    cliente = cliente_bd()
    pid = crear_paciente(cliente)
    # Registradas en desorden: el orden lo da `measured_at`, no el de registro.
    marzo = medir(cliente, pid, measured_at="2026-03-10T09:00:00Z")["measurement"]["id"]
    enero = medir(cliente, pid, measured_at="2026-01-10T09:00:00Z")["measurement"]["id"]
    mayo = medir(cliente, pid, measured_at="2026-05-10T09:00:00Z")["measurement"]["id"]
    febrero = medir(cliente, pid, measured_at="2026-02-10T09:00:00Z")["measurement"]["id"]

    assert ids_de_medicion(historial(cliente, pid)) == [mayo, marzo, febrero, enero]


def test_con_la_misma_hora_de_medicion_desempata_la_registrada_despues(cliente_bd):
    cliente = cliente_bd()
    pid = crear_paciente(cliente)
    registradas = [medir(cliente, pid, measured_at=MISMA_HORA)["measurement"]["id"] for _ in range(5)]

    assert ids_de_medicion(historial(cliente, pid)) == registradas[::-1]


def test_la_paginacion_no_repite_ni_pierde_filas_con_horas_identicas(cliente_bd):
    cliente = cliente_bd()
    pid = crear_paciente(cliente)
    registradas = [medir(cliente, pid, measured_at=MISMA_HORA)["measurement"]["id"] for _ in range(5)]

    paginas = [historial(cliente, pid, limit=2, offset=desplazamiento) for desplazamiento in (0, 2, 4)]

    assert [len(p.json()["items"]) for p in paginas] == [2, 2, 1]
    assert [p.json()["has_more"] for p in paginas] == [True, True, False]
    assert [(p.json()["limit"], p.json()["offset"]) for p in paginas] == [(2, 0), (2, 2), (2, 4)]
    recorridas = [mid for p in paginas for mid in ids_de_medicion(p)]
    assert recorridas == registradas[::-1], "la unión de las páginas es el historial completo, en su orden"
    assert len(set(recorridas)) == 5


def test_con_hora_y_registro_identicos_desempata_el_id(cliente_bd, base_migrada):
    """`created_at` es la hora de la transacción: dos mediciones insertadas en la misma
    transacción empatan también en él, y solo el id fija el orden."""
    cliente = cliente_bd()
    pid = crear_paciente(cliente)
    primera = medir(cliente, pid, measured_at=MISMA_HORA)
    columnas_m = ", ".join(CAMPOS_CLINICOS)
    with psycopg.connect(base_migrada) as c:
        for _ in range(4):
            nueva = c.execute(
                f"INSERT INTO gynfem.clinical_measurements (patient_id, measured_at, created_at, {columnas_m}) "
                f"SELECT patient_id, measured_at, created_at, {columnas_m} FROM gynfem.clinical_measurements "
                "WHERE id = %s RETURNING id",
                [primera["measurement"]["id"]],
            ).fetchone()[0]
            columnas_p = [
                d.name for d in c.execute("SELECT * FROM gynfem.predictions LIMIT 0").description
                if d.name not in ("id", "measurement_id")
            ]
            c.execute(
                f"INSERT INTO gynfem.predictions (measurement_id, {', '.join(columnas_p)}) "
                f"SELECT %s, {', '.join(columnas_p)} FROM gynfem.predictions WHERE id = %s",
                [nueva, primera["prediction"]["id"]],
            )
    todos = sorted(str(i) for (i,) in filas(base_migrada, "SELECT id FROM gynfem.clinical_measurements"))
    assert len(todos) == 5

    completo = ids_de_medicion(historial(cliente, pid))
    paginado = [mid for d in (0, 2, 4) for mid in ids_de_medicion(historial(cliente, pid, limit=2, offset=d))]

    assert completo == todos, "con todo lo demás igual, ordena el id"
    assert paginado == completo


@pytest.mark.parametrize("parametros", [{"limit": 0}, {"limit": 51}, {"offset": -1}, {"limit": "abc"}])
def test_paginacion_invalida_422(parametros, cliente_bd):
    cliente = cliente_bd()

    assert historial(cliente, crear_paciente(cliente), **parametros).status_code == 422


# --- El límite por defecto es un parámetro (HU011) ------------------------------------------


def test_sin_limit_rige_el_parametro_configurado(cliente_bd):
    cliente = cliente_bd()
    pid = crear_paciente(cliente)
    for _ in range(5):
        medir(cliente, pid)
    assert cliente_bd(rol="administrador").patch(CONFIGURACION, json={"history_default_page_size": 3}).status_code == 200

    cuerpo = historial(cliente, pid).json()

    assert (len(cuerpo["items"]), cuerpo["limit"], cuerpo["has_more"]) == (3, 3, True)


def test_un_limit_explicito_manda_sobre_el_parametro(cliente_bd):
    cliente = cliente_bd()
    pid = crear_paciente(cliente)
    for _ in range(5):
        medir(cliente, pid)
    cliente_bd(rol="administrador").patch(CONFIGURACION, json={"history_default_page_size": 3})

    cuerpo = historial(cliente, pid, limit=4).json()

    assert (len(cuerpo["items"]), cuerpo["limit"], cuerpo["has_more"]) == (4, 4, True)


def test_el_parametro_solo_se_consulta_cuando_se_omite_limit(cliente_bd, monkeypatch):
    from app.repositories import system_settings as settings_repo

    cliente = cliente_bd()
    pid = crear_paciente(cliente)
    medir(cliente, pid)
    lecturas = []
    original = settings_repo.current_values
    monkeypatch.setattr(settings_repo, "current_values", lambda conexion: lecturas.append(1) or original(conexion))

    assert historial(cliente, pid, limit=10).status_code == 200
    assert lecturas == [], "con limit explícito no se lee el parámetro"
    assert historial(cliente, pid).status_code == 200
    assert lecturas == [1], "sin limit se lee una vez"


# --- Una sola consulta, sin N+1 ---------------------------------------------------------------


@pytest.fixture
def consultas(monkeypatch) -> list[str]:
    """Toda sentencia SQL que ejecuta el proceso, en orden."""
    ejecutadas: list[str] = []
    original = psycopg.Cursor.execute

    def espia(self, query, *args, **kwargs):
        ejecutadas.append(str(query))
        return original(self, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Cursor, "execute", espia)
    return ejecutadas


def test_el_numero_de_consultas_no_depende_del_numero_de_evaluaciones(cliente_bd, consultas):
    cliente = cliente_bd()
    con_una = crear_paciente(cliente)
    medir(cliente, con_una)
    con_cinco = crear_paciente(cliente, PACIENTE_DOS)
    for _ in range(5):
        medir(cliente, con_cinco)
    historial(cliente, con_una, limit=10)  # la primera petición puede abrir la conexión

    consultas.clear()
    assert len(historial(cliente, con_una, limit=10).json()["items"]) == 1
    para_una = list(consultas)
    consultas.clear()
    assert len(historial(cliente, con_cinco, limit=10).json()["items"]) == 5
    para_cinco = list(consultas)

    assert para_una, "control: el espía ve las consultas"
    assert para_cinco == para_una, "las mismas sentencias para 1 que para 5 evaluaciones"
    assert sum("gynfem.predictions" in c for c in para_cinco) == 1, "una sola consulta, con join, trae el historial"


# --- Aislamiento entre pacientes y bajas -------------------------------------------------------


def test_el_historial_no_incluye_evaluaciones_de_otra_paciente(cliente_bd):
    cliente = cliente_bd()
    una, otra = crear_paciente(cliente), crear_paciente(cliente, PACIENTE_DOS)
    de_una = [medir(cliente, una)["measurement"]["id"] for _ in range(2)]
    de_otra = [medir(cliente, otra, ENTRADA_EXTRAPOLADA)["measurement"]["id"] for _ in range(3)]

    respuesta_una, respuesta_otra = historial(cliente, una), historial(cliente, otra)

    assert sorted(ids_de_medicion(respuesta_una)) == sorted(de_una)
    assert sorted(ids_de_medicion(respuesta_otra)) == sorted(de_otra)
    assert {i["measurement"]["patient_id"] for i in respuesta_una.json()["items"]} == {una}
    assert {i["measurement"]["patient_id"] for i in respuesta_otra.json()["items"]} == {otra}
    for ajeno in de_otra:
        assert ajeno not in respuesta_una.text


def test_paciente_inexistente_y_dada_de_baja_dan_el_mismo_404(cliente_bd):
    cliente = cliente_bd()
    pid = crear_paciente(cliente)
    medir(cliente, pid)
    assert cliente.delete(f"{PACIENTES}/{pid}").status_code == 204

    de_baja, inexistente = historial(cliente, pid), historial(cliente, UUID_INEXISTENTE)

    assert de_baja.status_code == inexistente.status_code == 404
    assert sin_request_id(de_baja) == sin_request_id(inexistente) == {
        "code": "patient_not_found", "message": "Paciente no encontrada.",
    }


def test_la_consulta_no_devuelve_evaluaciones_de_una_paciente_dada_de_baja(cliente_bd, base_migrada):
    """Segunda barrera, en la propia consulta: aunque el servicio dejara de comprobar a la
    paciente, sus evaluaciones no saldrían."""
    from app.repositories import evaluations as evaluations_repo

    cliente = cliente_bd()
    pid = crear_paciente(cliente)
    medir(cliente, pid)
    with psycopg.connect(base_migrada) as conexion:
        assert len(evaluations_repo.list_for_patient(conexion, pid, 10, 0)) == 1, "control: activa, sale"
    cliente.delete(f"{PACIENTES}/{pid}")

    with psycopg.connect(base_migrada) as conexion:
        assert evaluations_repo.list_for_patient(conexion, pid, 10, 0) == []


def test_tras_la_baja_el_documento_reutilizado_empieza_sin_historial(cliente_bd):
    cliente = cliente_bd()
    anterior = crear_paciente(cliente)
    medir(cliente, anterior)
    cliente.delete(f"{PACIENTES}/{anterior}")

    nueva = crear_paciente(cliente)

    assert nueva != anterior
    assert historial(cliente, nueva).json()["items"] == []


# --- Correcciones --------------------------------------------------------------------------------


def test_la_corregida_sale_como_corrected_y_la_nueva_como_current(cliente_bd):
    cliente = cliente_bd()
    pid = crear_paciente(cliente)
    original = medir(cliente, pid, ENTRADA_EXTRAPOLADA)
    otra = medir(cliente, pid, measured_at="2026-01-10T09:00:00Z")
    correccion = cliente.post(
        f"/api/v1/measurements/{original['measurement']['id']}/corrections", json=ENTRADA_NORMAL
    ).json()

    items = historial(cliente, pid).json()["items"]

    estados = {item["measurement"]["id"]: item["status"] for item in items}
    assert estados == {
        original["measurement"]["id"]: "corrected",
        correccion["measurement"]["id"]: "current",
        otra["measurement"]["id"]: "current",
    }
    # La evaluación corregida conserva su predicción original, intacta.
    corregida = next(i for i in items if i["status"] == "corrected")
    assert corregida["prediction"]["id"] == original["prediction"]["id"]
    assert corregida["prediction"]["risk_level"] == original["prediction"]["risk_level"]
    assert corregida["measurement"]["bmi_kg_m2"] == ENTRADA_EXTRAPOLADA["bmi_kg_m2"]


def test_el_historial_no_expone_campos_internos(cliente_bd):
    cliente = cliente_bd()
    pid = crear_paciente(cliente)
    original = medir(cliente, pid)
    cliente.post(f"/api/v1/measurements/{original['measurement']['id']}/corrections", json=ENTRADA_EXTRAPOLADA)

    respuesta = historial(cliente, pid)

    assert len(respuesta.json()["items"]) == 2
    for campo in (*CAMPOS_INTERNOS, "input_", "model_input", "document_number", "given_names", "family_names"):
        assert campo not in respuesta.text, campo


def test_consultar_el_historial_no_escribe_nada(cliente_bd, base_migrada):
    cliente = cliente_bd()
    pid = crear_paciente(cliente)
    medir(cliente, pid)
    tablas = ("patients", "clinical_measurements", "predictions", "audit_log", "system_settings")
    antes = [filas(base_migrada, f"SELECT count(*) FROM gynfem.{t}") for t in tablas]

    assert historial(cliente, pid).status_code == 200
    assert historial(cliente, pid, limit=1).status_code == 200

    assert [filas(base_migrada, f"SELECT count(*) FROM gynfem.{t}") for t in tablas] == antes


# --- Acceso ------------------------------------------------------------------------------------------


def test_administrador_403_exista_o_no_la_paciente(cliente_bd):
    medico = cliente_bd()
    pid = crear_paciente(medico)
    medir(medico, pid)
    administrador = cliente_bd(rol="administrador")

    existente, inexistente = historial(administrador, pid), historial(administrador, UUID_INEXISTENTE)

    assert existente.status_code == inexistente.status_code == 403
    assert sin_request_id(existente) == sin_request_id(inexistente)
    assert existente.json()["error"]["code"] == "forbidden"
    assert "items" not in existente.text


def test_sin_token_401_exista_o_no_la_paciente(cliente_bd):
    medico = cliente_bd()
    pid = crear_paciente(medico)
    anonimo = cliente_bd(rol=None)

    existente, inexistente = historial(anonimo, pid), historial(anonimo, UUID_INEXISTENTE)

    assert existente.status_code == inexistente.status_code == 401
    assert sin_request_id(existente) == sin_request_id(inexistente)
