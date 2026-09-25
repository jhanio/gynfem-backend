"""El esquema que dejan las migraciones: tablas, columnas, relaciones y seguridad.

Todo se consulta del catálogo de un PostgreSQL real (el embebido de
`conftest.py`), nunca de los archivos SQL. Las columnas que dependen del modelo
o de la API se derivan de su fuente (`model_metadata.json`, `PredictionRequest`),
no de una lista escrita a mano.
"""

import json
import math
import re
import pandas as pd
import psycopg
import pytest
from psycopg.types.json import Jsonb

from api.api_constantes import ENTRADA_EXTRAPOLADA, METADATA_JSON

ESQUEMA = "gynfem"
ESQUEMAS_PROPIOS = ("gynfem", "gynfem_migrations")
TABLAS_DE_NEGOCIO = ("patients", "clinical_measurements", "predictions")
TABLAS = (*TABLAS_DE_NEGOCIO, "audit_log")

UUID_GENERADO = ("uuid", True, "gen_random_uuid()")
MARCA_DE_TIEMPO = ("timestamp with time zone", True, "now()")
ESTRUCTURALES = {
    "id": UUID_GENERADO,
    "created_at": MARCA_DE_TIEMPO,
    "updated_at": MARCA_DE_TIEMPO,
    "deleted_at": ("timestamp with time zone", False, None),
    "created_by": ("uuid", False, None),
    "updated_by": ("uuid", False, None),
    "deleted_by": ("uuid", False, None),
}
MEDIDA = ("double precision", True, None)


def campos_clinicos() -> list[str]:
    from app.schemas.prediction import PredictionRequest

    return list(PredictionRequest.model_fields)


def features_del_modelo() -> list[str]:
    metadata = json.loads(METADATA_JSON.read_text(encoding="utf-8"))
    return [f["name"] for f in sorted(metadata["features"], key=lambda f: f["position"])]


def niveles_de_riesgo() -> set[str]:
    from app.services.prediction import RISK_LEVELS

    metadata = json.loads(METADATA_JSON.read_text(encoding="utf-8"))
    return {RISK_LEVELS[clase] for clase in metadata["classes"]}


def columnas_esperadas() -> dict[str, dict[str, tuple]]:
    clinicas = campos_clinicos()
    return {
        "patients": dict(ESTRUCTURALES),
        "clinical_measurements": {
            **ESTRUCTURALES,
            "patient_id": ("uuid", True, None),
            "measured_at": ("timestamp with time zone", True, None),
            **{campo: MEDIDA for campo in clinicas},
        },
        "predictions": {
            **ESTRUCTURALES,
            "measurement_id": ("uuid", True, None),
            **{f"input_{campo}": MEDIDA for campo in clinicas},
            **{f"model_{feature}": MEDIDA for feature in features_del_modelo()},
            "risk_level": ("text", True, None),
            "prob_high": MEDIDA,
            "prob_mid": MEDIDA,
            "prob_low": MEDIDA,
            "extrapolation_warnings": ("jsonb", True, "'[]'::jsonb"),
            "model_version": ("text", True, None),
            "conversion_schema_version": ("text", True, None),
            "predicted_at": ("timestamp with time zone", True, None),
        },
        "audit_log": {
            "id": ("bigint", True, None),
            "created_at": MARCA_DE_TIEMPO,
            "updated_at": MARCA_DE_TIEMPO,
            "actor_user_id": ("uuid", False, None),
            "action": ("text", True, None),
            "entity_type": ("text", True, None),
            "entity_id": ("uuid", False, None),
            "request_id": ("text", False, None),
            "outcome": ("text", True, None),
            "changed_fields": ("text[]", False, None),
        },
    }


def columnas(conexion, tabla: str) -> dict[str, tuple]:
    filas = conexion.execute(
        """
        SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
               pg_get_expr(d.adbin, d.adrelid)
        FROM pg_attribute a
        LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        [f"{ESQUEMA}.{tabla}"],
    ).fetchall()
    return {nombre: (tipo, no_nulo, defecto) for nombre, tipo, no_nulo, defecto in filas}


def tablas_propias(conexion) -> list[tuple[str, str]]:
    return conexion.execute(
        """
        SELECT n.nspname, c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p') AND n.nspname = ANY(%s)
        """,
        [list(ESQUEMAS_PROPIOS)],
    ).fetchall()


# --- Inserciones mínimas válidas -------------------------------------------------


def insertar_paciente(conexion) -> str:
    return conexion.execute(f"INSERT INTO {ESQUEMA}.patients DEFAULT VALUES RETURNING id").fetchone()[0]


def insertar_medicion(conexion, paciente, valores: dict | None = None) -> str:
    valores = valores or {c: float(v) for c, v in ENTRADA_EXTRAPOLADA.items()}
    nombres = ", ".join(valores)
    marcas = ", ".join(["%s"] * len(valores))
    return conexion.execute(
        f"INSERT INTO {ESQUEMA}.clinical_measurements (patient_id, measured_at, {nombres}) "
        f"VALUES (%s, now(), {marcas}) RETURNING id",
        [paciente, *valores.values()],
    ).fetchone()[0]


def fila_de_prediccion(resultado, medicion) -> dict:
    """Las columnas de `predictions` a partir de un `PredictionResult` real."""
    return {
        "measurement_id": medicion,
        **{f"input_{k}": v for k, v in resultado.input.items()},
        **{f"model_{k}": v for k, v in resultado.model_input.items()},
        "risk_level": resultado.risk_level,
        "prob_high": resultado.probabilities["high"],
        "prob_mid": resultado.probabilities["mid"],
        "prob_low": resultado.probabilities["low"],
        "extrapolation_warnings": Jsonb([_aviso(a) for a in resultado.extrapolation_warnings]),
        "model_version": resultado.model_version,
        "conversion_schema_version": resultado.conversion_schema_version,
        "predicted_at": resultado.predicted_at,
    }


def _aviso(aviso) -> dict:
    from dataclasses import asdict

    return asdict(aviso)


def insertar_prediccion(conexion, fila: dict) -> str:
    nombres = ", ".join(fila)
    marcas = ", ".join(["%s"] * len(fila))
    return conexion.execute(
        f"INSERT INTO {ESQUEMA}.predictions ({nombres}) VALUES ({marcas}) RETURNING id",
        list(fila.values()),
    ).fetchone()[0]


@pytest.fixture
def servicio(modelo_real):
    from app.services.prediction import PredictionService

    return PredictionService(modelo_real)


@pytest.fixture
def prediccion_real(servicio):
    return servicio.predict({c: float(v) for c, v in ENTRADA_EXTRAPOLADA.items()})


@pytest.fixture
def cadena(conexion, prediccion_real):
    """Paciente, medición y predicción reales encadenadas: sus ids."""
    paciente = insertar_paciente(conexion)
    medicion = insertar_medicion(conexion, paciente)
    prediccion = insertar_prediccion(conexion, fila_de_prediccion(prediccion_real, medicion))
    return {"patients": paciente, "clinical_measurements": medicion, "predictions": prediccion}


def insertar_auditoria(conexion) -> int:
    return conexion.execute(
        f"INSERT INTO {ESQUEMA}.audit_log (action, entity_type, outcome) "
        "VALUES ('patient.create', 'patient', 'success') RETURNING id"
    ).fetchone()[0]


# --- Estructura ------------------------------------------------------------------


def test_tablas_exactas(conexion):
    assert sorted(t for e, t in tablas_propias(conexion) if e == ESQUEMA) == sorted(TABLAS)


@pytest.mark.parametrize("tabla", TABLAS)
def test_columnas_tipos_y_nulabilidad(tabla, conexion):
    assert columnas(conexion, tabla) == columnas_esperadas()[tabla]


def test_auditoria_usa_identidad(conexion):
    identidad = conexion.execute(
        "SELECT attidentity FROM pg_attribute WHERE attrelid = %s::regclass AND attname = 'id'",
        [f"{ESQUEMA}.audit_log"],
    ).fetchone()[0]
    assert identidad == "a", "audit_log.id debe ser GENERATED ALWAYS AS IDENTITY"


def test_claves_foraneas(conexion):
    filas = conexion.execute(
        """
        SELECT conrelid::regclass::text, a.attname, confrelid::regclass::text, fa.attname,
               confdeltype, confupdtype
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        JOIN pg_attribute fa ON fa.attrelid = c.confrelid AND fa.attnum = c.confkey[1]
        WHERE c.contype = 'f' AND c.connamespace = %s::regnamespace
        """,
        [ESQUEMA],
    ).fetchall()

    # 'r' = RESTRICT: nunca se borra ni se reasigna en cascada.
    assert sorted(filas) == sorted(
        [
            (f"{ESQUEMA}.clinical_measurements", "patient_id", f"{ESQUEMA}.patients", "id", "r", "r"),
            (f"{ESQUEMA}.predictions", "measurement_id", f"{ESQUEMA}.clinical_measurements", "id", "r", "r"),
        ]
    )


def test_una_medicion_huerfana_se_rechaza(conexion):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        insertar_medicion(conexion, "00000000-0000-4000-8000-000000000000")


def test_una_prediccion_huerfana_se_rechaza(conexion, prediccion_real):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        insertar_prediccion(
            conexion, fila_de_prediccion(prediccion_real, "00000000-0000-4000-8000-000000000000")
        )


def test_indices_de_las_consultas_previstas(conexion):
    definiciones = [
        d for (d,) in conexion.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = %s", [ESQUEMA]
        ).fetchall()
    ]
    esperados = [
        "clinical_measurements USING btree (patient_id, measured_at DESC)",
        "predictions USING btree (measurement_id)",
        "predictions USING btree (predicted_at)",
        "audit_log USING btree (entity_type, entity_id)",
        "audit_log USING btree (created_at)",
    ]
    for esperado in esperados:
        assert any(esperado in d for d in definiciones), f"falta el índice {esperado}"


# --- Seguridad -------------------------------------------------------------------


def test_rls_habilitado_en_todas_las_tablas(conexion):
    """Toda tabla de los esquemas propios, también las que se añadan después."""
    sin_rls = conexion.execute(
        """
        SELECT n.nspname || '.' || c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p') AND n.nspname = ANY(%s) AND NOT c.relrowsecurity
        """,
        [list(ESQUEMAS_PROPIOS)],
    ).fetchall()

    assert len(tablas_propias(conexion)) == len(TABLAS) + 1
    assert sin_rls == []


@pytest.mark.parametrize("rol", ["anon", "authenticated"])
def test_roles_de_la_data_api_sin_privilegios(rol, conexion):
    for esquema in ESQUEMAS_PROPIOS:
        assert conexion.execute(
            "SELECT has_schema_privilege(%s, %s, 'USAGE')", [rol, esquema]
        ).fetchone() == (False,), f"{rol} tiene USAGE sobre {esquema}"
    for esquema, tabla in tablas_propias(conexion):
        for privilegio in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert conexion.execute(
                "SELECT has_table_privilege(%s, %s, %s)", [rol, f"{esquema}.{tabla}", privilegio]
            ).fetchone() == (False,), f"{rol} tiene {privilegio} sobre {esquema}.{tabla}"


@pytest.mark.parametrize("rol", ["anon", "authenticated"])
def test_roles_de_la_data_api_no_leen_nada(rol, conexion):
    insertar_paciente(conexion)
    conexion.execute(f"SET ROLE {rol}")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conexion.execute(f"SELECT * FROM {ESQUEMA}.patients").fetchall()
    finally:
        conexion.execute("RESET ROLE")


@pytest.mark.parametrize("rol", ["anon", "authenticated"])
def test_el_esquema_cierra_el_paso_aunque_una_tabla_se_conceda(rol, conexion):
    """Segunda barrera: sin USAGE sobre el esquema, un GRANT por error en una tabla futura no basta."""
    conexion.execute(f"CREATE TABLE {ESQUEMA}.futura (id int)")
    conexion.execute(f"GRANT SELECT ON {ESQUEMA}.futura TO {rol}")
    conexion.execute(f"SET ROLE {rol}")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conexion.execute(f"SELECT * FROM {ESQUEMA}.futura").fetchall()
    finally:
        conexion.execute("RESET ROLE")


PATRON_CONTRASENA = re.compile(r"pass|pwd|hash|secret|contrase|clave|credential", re.IGNORECASE)


def test_ninguna_tabla_tiene_campos_de_contrasena(conexion):
    nombres = [
        f"{e}.{t}.{c}"
        for e, t in tablas_propias(conexion)
        for (c,) in conexion.execute(
            "SELECT attname FROM pg_attribute WHERE attrelid = %s::regclass AND attnum > 0",
            [f"{e}.{t}"],
        ).fetchall()
    ]
    assert nombres, "no se leyó ninguna columna"
    assert [n for n in nombres if PATRON_CONTRASENA.search(n)] == []


# --- Trazabilidad ----------------------------------------------------------------


def test_vector_almacenado_sigue_el_contrato_del_modelo(conexion):
    """Una columna `model_<feature>` por feature de `model_metadata.json`, en su orden."""
    del_modelo = [c for c in columnas(conexion, "predictions") if c.startswith("model_") and c != "model_version"]

    assert del_modelo == [f"model_{f}" for f in features_del_modelo()]
    for columna in del_modelo:
        assert columnas(conexion, "predictions")[columna] == MEDIDA


def test_entrada_clinica_almacenada_son_los_campos_de_la_api(conexion):
    clinicas = campos_clinicos()
    en_prediccion = [c.removeprefix("input_") for c in columnas(conexion, "predictions") if c.startswith("input_")]
    en_medicion = [c for c in columnas(conexion, "clinical_measurements") if c in clinicas]

    assert en_prediccion == clinicas
    assert en_medicion == clinicas


def test_prediccion_real_se_guarda_y_se_reproduce(conexion, cadena, prediccion_real, modelo_real):
    """Lo guardado basta para reconstruir la predicción, bit a bit."""
    fila = conexion.execute(
        f"SELECT * FROM {ESQUEMA}.predictions WHERE id = %s", [cadena["predictions"]]
    ).fetchone()
    nombres = [d.name for d in conexion.execute(f"SELECT * FROM {ESQUEMA}.predictions LIMIT 0").description]
    guardada = dict(zip(nombres, fila, strict=True))

    for campo, valor in prediccion_real.input.items():
        assert guardada[f"input_{campo}"] == valor
    for feature, valor in prediccion_real.model_input.items():
        assert guardada[f"model_{feature}"] == valor
    assert guardada["model_version"] == prediccion_real.model_version
    assert guardada["conversion_schema_version"] == prediccion_real.conversion_schema_version
    assert guardada["extrapolation_warnings"] == [_aviso(a) for a in prediccion_real.extrapolation_warnings]
    assert len(guardada["extrapolation_warnings"]) == 2
    assert guardada["risk_level"] == prediccion_real.risk_level

    orden = features_del_modelo()
    X = pd.DataFrame([[guardada[f"model_{f}"] for f in orden]], columns=orden)
    reproducidas = dict(zip(modelo_real.classes, modelo_real.pipeline.predict_proba(X)[0], strict=True))
    from app.services.prediction import RISK_LEVELS

    for clase, p in reproducidas.items():
        assert guardada[f"prob_{RISK_LEVELS[clase]}"] == float(p)


@pytest.mark.parametrize(
    "columna", ["model_version", "conversion_schema_version", "extrapolation_warnings", "model_bmi_kg_m2"]
)
def test_trazabilidad_obligatoria(columna, conexion, prediccion_real):
    paciente = insertar_paciente(conexion)
    medicion = insertar_medicion(conexion, paciente)
    fila = fila_de_prediccion(prediccion_real, medicion)
    fila[columna] = None

    with pytest.raises(psycopg.errors.NotNullViolation):
        insertar_prediccion(conexion, fila)


@pytest.mark.parametrize("version", ["1.0", "v1.0.0", "", "1.0.0-beta"])
def test_versiones_con_formato_semver(version, conexion, prediccion_real):
    paciente = insertar_paciente(conexion)
    medicion = insertar_medicion(conexion, paciente)
    for columna in ("model_version", "conversion_schema_version"):
        fila = fila_de_prediccion(prediccion_real, medicion)
        fila[columna] = version
        with pytest.raises(psycopg.errors.CheckViolation):
            insertar_prediccion(conexion, fila)


def test_avisos_deben_ser_una_lista(conexion, prediccion_real):
    paciente = insertar_paciente(conexion)
    medicion = insertar_medicion(conexion, paciente)
    fila = fila_de_prediccion(prediccion_real, medicion)
    fila["extrapolation_warnings"] = Jsonb({"field": "bmi_kg_m2"})

    with pytest.raises(psycopg.errors.CheckViolation):
        insertar_prediccion(conexion, fila)


# --- Integridad de los valores ---------------------------------------------------


@pytest.mark.parametrize("valor", [math.nan, math.inf, -math.inf])
def test_no_finitos_rechazados_en_la_medicion(valor, conexion):
    paciente = insertar_paciente(conexion)
    for campo in campos_clinicos():
        valores = {c: float(v) for c, v in ENTRADA_EXTRAPOLADA.items()}
        valores[campo] = valor
        with pytest.raises(psycopg.errors.CheckViolation):
            insertar_medicion(conexion, paciente, valores)


@pytest.mark.parametrize("valor", [math.nan, math.inf, -math.inf])
def test_no_finitos_rechazados_en_la_prediccion(valor, conexion, prediccion_real):
    paciente = insertar_paciente(conexion)
    medicion = insertar_medicion(conexion, paciente)
    columnas_numericas = [
        *(f"input_{c}" for c in campos_clinicos()),
        *(f"model_{f}" for f in features_del_modelo()),
    ]
    for columna in columnas_numericas:
        fila = fila_de_prediccion(prediccion_real, medicion)
        fila[columna] = valor
        with pytest.raises(psycopg.errors.CheckViolation):
            insertar_prediccion(conexion, fila)


@pytest.mark.parametrize(
    "alterar",
    [
        {"prob_high": -0.1, "prob_mid": 1.1, "prob_low": 0.0},
        {"prob_high": 0.5, "prob_mid": 0.5, "prob_low": 0.5},
        {"prob_high": math.nan},
    ],
    ids=["fuera de [0, 1]", "no suman 1", "NaN"],
)
def test_probabilidades_invalidas_rechazadas(alterar, conexion, prediccion_real):
    paciente = insertar_paciente(conexion)
    medicion = insertar_medicion(conexion, paciente)
    fila = {**fila_de_prediccion(prediccion_real, medicion), **alterar}

    with pytest.raises(psycopg.errors.CheckViolation):
        insertar_prediccion(conexion, fila)


def test_solo_se_admiten_los_niveles_de_riesgo_del_modelo(conexion, prediccion_real):
    paciente = insertar_paciente(conexion)
    medicion = insertar_medicion(conexion, paciente)
    for nivel in niveles_de_riesgo():
        insertar_prediccion(conexion, {**fila_de_prediccion(prediccion_real, medicion), "risk_level": nivel})
    for nivel in ("high risk", "medium", "HIGH", ""):
        with pytest.raises(psycopg.errors.CheckViolation):
            insertar_prediccion(conexion, {**fila_de_prediccion(prediccion_real, medicion), "risk_level": nivel})


def test_ids_uuid_generados_por_la_base(conexion, cadena):
    for tabla, identificador in cadena.items():
        assert str(identificador).count("-") == 4
        assert str(identificador)[14] == "4", f"{tabla}: se espera un UUID v4"


# --- Marcas de tiempo, borrado lógico e inmutabilidad ----------------------------


@pytest.mark.parametrize("tabla", TABLAS_DE_NEGOCIO)
def test_updated_at_avanza_al_actualizar(tabla, conexion, cadena):
    identificador = cadena[tabla]
    antes = conexion.execute(
        f"SELECT created_at, updated_at FROM {ESQUEMA}.{tabla} WHERE id = %s", [identificador]
    ).fetchone()
    # `now()` es la hora de inicio de la transacción: cada sentencia en autocommit es otra.
    conexion.execute(
        f"UPDATE {ESQUEMA}.{tabla} SET deleted_at = now() WHERE id = %s", [identificador]
    )
    creado, actualizado = conexion.execute(
        f"SELECT created_at, updated_at FROM {ESQUEMA}.{tabla} WHERE id = %s", [identificador]
    ).fetchone()

    assert creado == antes[0]
    assert actualizado > antes[1]
    assert actualizado.utcoffset() is not None


@pytest.mark.parametrize("tabla", TABLAS)
def test_borrado_fisico_rechazado(tabla, conexion, cadena):
    identificador = cadena.get(tabla) or insertar_auditoria(conexion)

    with pytest.raises(psycopg.errors.RaiseException):
        conexion.execute(f"DELETE FROM {ESQUEMA}.{tabla} WHERE id = %s", [identificador])
    with pytest.raises(psycopg.errors.RaiseException):
        conexion.execute(f"TRUNCATE {ESQUEMA}.{tabla} CASCADE")
    assert conexion.execute(
        f"SELECT count(*) FROM {ESQUEMA}.{tabla} WHERE id = %s", [identificador]
    ).fetchone() == (1,)


@pytest.mark.parametrize(
    "asignacion",
    [
        "model_version = '9.9.9'",
        "conversion_schema_version = '9.9.9'",
        "model_hba1c_mmol_mol = 1.0",
        "input_bmi_kg_m2 = 20.0",
        "risk_level = 'low'",
        "prob_high = 0.2",
        "extrapolation_warnings = '[]'::jsonb",
        "predicted_at = now()",
        "measurement_id = gen_random_uuid()",
        "created_at = now()",
    ],
)
def test_prediccion_inmutable(asignacion, conexion, cadena):
    with pytest.raises(psycopg.errors.RaiseException):
        conexion.execute(
            f"UPDATE {ESQUEMA}.predictions SET {asignacion} WHERE id = %s", [cadena["predictions"]]
        )


def test_prediccion_admite_el_borrado_logico(conexion, cadena):
    conexion.execute(
        f"UPDATE {ESQUEMA}.predictions SET deleted_at = now(), deleted_by = %s WHERE id = %s",
        ["00000000-0000-4000-8000-000000000001", cadena["predictions"]],
    )
    assert conexion.execute(
        f"SELECT deleted_at IS NOT NULL FROM {ESQUEMA}.predictions WHERE id = %s", [cadena["predictions"]]
    ).fetchone() == (True,)


def test_auditoria_solo_insercion(conexion):
    identificador = insertar_auditoria(conexion)

    with pytest.raises(psycopg.errors.RaiseException):
        conexion.execute(
            f"UPDATE {ESQUEMA}.audit_log SET outcome = 'error' WHERE id = %s", [identificador]
        )


def test_auditoria_sin_espacio_para_valores_clinicos(conexion):
    """Ni jsonb ni texto libre: cada columna de texto tiene su restricción de formato."""
    tipos = {nombre: tipo for nombre, (tipo, _, _) in columnas(conexion, "audit_log").items()}
    assert "jsonb" not in tipos.values() and "json" not in tipos.values()

    validos = {"action": "patient.create", "entity_type": "patient", "outcome": "success"}
    invalidos = {
        "action": "temperature_c=36.8",
        "entity_type": "36.8",
        "outcome": "36.8",
        "request_id": "36.8 °C",
    }
    for columna, valor in invalidos.items():
        fila = {**validos, columna: valor}
        with pytest.raises(psycopg.errors.CheckViolation):
            conexion.execute(
                f"INSERT INTO {ESQUEMA}.audit_log ({', '.join(fila)}) VALUES ({', '.join(['%s'] * len(fila))})",
                list(fila.values()),
            )
    with pytest.raises(psycopg.errors.CheckViolation):
        conexion.execute(
            f"INSERT INTO {ESQUEMA}.audit_log (action, entity_type, outcome, changed_fields) "
            "VALUES ('patient.update', 'patient', 'success', %s)",
            [["bmi_kg_m2", "36.8"]],
        )
