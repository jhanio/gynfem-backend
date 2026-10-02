"""`python -m ops.verificar_despliegue` (Fase 16): el flujo clínico y el cambio de parámetro.

Sin red: la capa HTTP del guion se desvía a la aplicación completa sobre el
PostgreSQL embebido, y el inicio de sesión en Supabase devuelve un token firmado
en la sesión. Así se comprueba lo que el guion **deja escrito**: la paciente
sintética dada de baja y las filas permanentes del cambio de parámetro.

La aplicación del test corre en `development` (el embebido no ofrece TLS, que
`production` exige): la documentación interactiva se falsea a 404, que es lo que
el guion espera de producción y no es lo que aquí se prueba.
"""

from urllib.parse import urlsplit

import pytest

from api.auth_claves import ADMIN_ID, MEDICO_ID

from .conftest import filas

API = "https://gynfem-api.example.onrender.com"
SUPABASE = "https://abcdefghijklmnopqrst.supabase.co"
CORREO = "admin.verificacion@example.com"
CONTRASENA = "Contrasena-De-Verificacion-2026"
CORREO_MEDICO = "medica.verificacion@example.com"
CONTRASENA_MEDICO = "Contrasena-De-La-Medica-2026"
PUBLICABLE = "sb_publishable_ficticia"
SECRETOS = (CONTRASENA, CORREO, CONTRASENA_MEDICO, CORREO_MEDICO, PUBLICABLE, "eyJ", "Bearer")
DOCUMENTACION = ("/api/v1/docs", "/api/v1/openapi.json")
DOCUMENTO = "FICTICIOF16"


@pytest.fixture
def http_de(cliente_bd, emisor):
    """La función HTTP del guion sobre la aplicación con base; `alterar(metodo, ruta, estado, datos)`
    puede falsear una respuesta **después** de que la aplicación la haya atendido."""
    cliente = cliente_bd(rol=None)

    def _construir(alterar=None):
        llamadas = []

        def http(metodo, url, cuerpo=None, cabeceras=None):
            if url.startswith(SUPABASE):
                es_medico = (cuerpo or {}).get("email") == CORREO_MEDICO
                usuario = MEDICO_ID if es_medico else ADMIN_ID
                return 200, {"access_token": emisor.token(usuario), "token_type": "bearer"}, 0.01
            partes = urlsplit(url)
            llamadas.append((metodo, partes.path))
            if partes.path in DOCUMENTACION:
                return 404, {"error": {"code": "not_found"}}, 0.01
            ruta = partes.path + (f"?{partes.query}" if partes.query else "")
            respuesta = cliente.request(metodo, ruta, json=cuerpo, headers=cabeceras or {})
            estado, datos = respuesta.status_code, (respuesta.json() if respuesta.content else None)
            if alterar is not None:
                estado, datos = alterar(metodo, partes.path, estado, datos)
            return estado, datos, 0.01

        http.llamadas = llamadas
        return http

    return _construir


@pytest.fixture
def ejecutar(monkeypatch, capsys):
    from ops import verificar_despliegue

    def _ejecutar(http, *extra):
        for clave, valor in {
            "GYNFEM_SUPABASE_URL": SUPABASE,
            "GYNFEM_SUPABASE_PUBLISHABLE_KEY": PUBLICABLE,
            "GYNFEM_SMOKE_ADMIN_EMAIL": CORREO,
            "GYNFEM_SMOKE_ADMIN_PASSWORD": CONTRASENA,
            "GYNFEM_SMOKE_MEDICO_EMAIL": CORREO_MEDICO,
            "GYNFEM_SMOKE_MEDICO_PASSWORD": CONTRASENA_MEDICO,
        }.items():
            monkeypatch.setenv(clave, valor)
        codigo = verificar_despliegue.main(["--url", API, "--repeticiones", "1", *extra], http=http)
        return codigo, capsys.readouterr()

    return _ejecutar


def conteos(url: str) -> dict[str, int]:
    tablas = ("patients", "clinical_measurements", "predictions", "audit_log", "system_settings")
    return {tabla: filas(url, f"SELECT count(*) FROM gynfem.{tabla}")[0][0] for tabla in tablas}


def pacientes_sinteticas(url: str) -> list[tuple]:
    return filas(
        url,
        "SELECT document_type, given_names, family_names, deleted_at IS NOT NULL FROM gynfem.patients "
        "WHERE document_number = %s ORDER BY created_at",
        [DOCUMENTO],
    )


# --- Sin indicadores: solo lectura ---------------------------------------------------------


def test_sin_indicadores_pasa_y_no_escribe_nada(ejecutar, http_de, base_migrada):
    antes = conteos(base_migrada)

    codigo, salida = ejecutar(http_de())

    assert codigo == 0, salida.out
    assert "FALLA" not in salida.out
    assert conteos(base_migrada) == antes
    assert "flujo clínico" not in salida.out and "parámetro:" not in salida.out


# --- Flujo clínico ---------------------------------------------------------------------------


def test_el_flujo_clinico_pasa_y_deja_a_la_paciente_dada_de_baja(ejecutar, http_de, base_migrada):
    codigo, salida = ejecutar(http_de(), "--flujo-clinico")

    assert codigo == 0, salida.out
    assert "FALLA" not in salida.out
    for nombre in (
        "flujo clínico: paciente sintética creada",
        "flujo clínico: dos mediciones registradas con su predicción",
        "flujo clínico: corrección registrada",
        "flujo clínico: historial con las tres evaluaciones y la original marcada como corregida",
        "flujo clínico: reporte con la paciente, la medición y la advertencia clínica",
        "flujo clínico: el administrador no ve el historial ni el reporte",
        "flujo clínico: baja lógica de la paciente",
        "flujo clínico: historial de la paciente dada de baja",
        "flujo clínico: reporte de la paciente dada de baja",
    ):
        assert f"OK    {nombre}" in salida.out, nombre
    # Los datos inequívocamente ficticios acordados, y la baja lógica: nada se borra.
    assert pacientes_sinteticas(base_migrada) == [("PASAPORTE", "Paciente Ficticia", "Sintetica Fdieciseis", True)]
    despues = conteos(base_migrada)
    assert (despues["patients"], despues["clinical_measurements"], despues["predictions"]) == (1, 3, 3)
    assert despues["system_settings"] == 0


def test_la_salida_del_flujo_no_muestra_credenciales_ni_datos_de_la_paciente(ejecutar, http_de, base_migrada):
    codigo, salida = ejecutar(http_de(), "--flujo-clinico", "--cambio-de-parametro")

    assert codigo == 0, salida.out
    [(paciente_id,)] = filas(base_migrada, "SELECT id::text FROM gynfem.patients")
    for fuga in (*SECRETOS, DOCUMENTO, "Paciente Ficticia", "Sintetica Fdieciseis", paciente_id):
        assert fuga not in salida.out and fuga not in salida.err, fuga


def test_una_paciente_sintetica_de_una_corrida_interrumpida_se_da_de_baja_antes(ejecutar, http_de, base_migrada, cliente_bd):
    cliente_bd().post("/api/v1/patients", json={
        "document_type": "PASAPORTE", "document_number": DOCUMENTO,
        "given_names": "Paciente Ficticia", "family_names": "Sintetica Fdieciseis",
    })
    assert [fila[3] for fila in pacientes_sinteticas(base_migrada)] == [False]

    codigo, salida = ejecutar(http_de(), "--flujo-clinico")

    assert codigo == 0, salida.out
    assert "OK    flujo clínico: baja de la paciente sintética de una corrida anterior" in salida.out
    assert [fila[3] for fila in pacientes_sinteticas(base_migrada)] == [True, True]


FALSEOS_DEL_FLUJO = {
    "historial con dos evaluaciones": (
        "GET", "/evaluations", lambda e, d: (e, {**d, "items": d["items"][:2]}) if e == 200 else (e, d)),
    "historial sin marcar la corregida": (
        "GET", "/evaluations",
        lambda e, d: (e, {**d, "items": [{**i, "status": "current"} for i in d["items"]]}) if e == 200 else (e, d)),
    "historial sin advertencia clínica": (
        "GET", "/evaluations",
        lambda e, d: (e, {k: v for k, v in d.items() if k != "clinical_disclaimer"}) if e == 200 else (e, d)),
    "reporte sin advertencia clínica": (
        "POST", "/report", lambda e, d: (e, {**d, "clinical_disclaimer": ""}) if e == 200 else (e, d)),
    "reporte de otra paciente": (
        "POST", "/report",
        lambda e, d: (e, {**d, "patient": {**d["patient"], "document_number": "00000001"}}) if e == 200 else (e, d)),
    "el administrador ve el historial": ("GET", "/evaluations", lambda e, d: (200, {"items": []}) if e == 403 else (e, d)),
    "el administrador genera el reporte": ("POST", "/report", lambda e, d: (200, {}) if e == 403 else (e, d)),
    "la baja falla": ("DELETE", "/patients/", lambda e, d: (500, {"error": {"code": "internal_error"}})),
    "el historial sigue visible tras la baja": (
        "GET", "/evaluations", lambda e, d: (200, {"items": []}) if e == 404 else (e, d)),
    "el reporte sigue disponible tras la baja": ("POST", "/report", lambda e, d: (200, {}) if e == 404 else (e, d)),
    "la corrección falla": ("POST", "/corrections", lambda e, d: (409, {"error": {"code": "measurement_already_corrected"}})),
    "una medición falla": ("POST", "/measurements", lambda e, d: (503, {"error": {"code": "database_unavailable"}})),
}


@pytest.mark.parametrize("falseo", list(FALSEOS_DEL_FLUJO))
def test_cada_comprobacion_del_flujo_es_vinculante(falseo, ejecutar, http_de, base_migrada):
    metodo, fragmento, cambio = FALSEOS_DEL_FLUJO[falseo]

    def alterar(m, ruta, estado, datos):
        # Solo las rutas de pacientes reales: las del UUID inexistente son de otra comprobación.
        if m == metodo and fragmento in ruta and "00000000-0000-4000-8000-000000000000" not in ruta:
            if fragmento == "/measurements" and ruta.endswith("/corrections"):
                return estado, datos
            return cambio(estado, datos or {})
        return estado, datos

    codigo, salida = ejecutar(http_de(alterar), "--flujo-clinico")

    assert codigo == 1, falseo
    assert "FALLA flujo clínico" in salida.out, salida.out
    # Falle lo que falle a mitad, la paciente sintética no queda activa.
    assert all(fila[3] for fila in pacientes_sinteticas(base_migrada)), "la paciente sintética quedó activa"
    assert len(pacientes_sinteticas(base_migrada)) == 1


# --- Cambio de parámetro -----------------------------------------------------------------------


def parametros(url: str) -> list[tuple]:
    return filas(url, "SELECT key, value FROM gynfem.system_settings ORDER BY id")


def test_el_cambio_de_parametro_se_restaura_y_deja_dos_filas_permanentes(ejecutar, http_de, base_migrada):
    codigo, salida = ejecutar(http_de(), "--cambio-de-parametro")

    assert codigo == 0, salida.out
    for nombre in ("parámetro: valor vigente leído", "parámetro: cambio aplicado",
                   "parámetro: cambio auditado con solo el nombre de la clave", "parámetro: valor anterior restaurado"):
        assert f"OK    {nombre}" in salida.out, nombre
    # Solo inserción: el cambio y su restauración quedan para siempre, en las dos tablas.
    assert parametros(base_migrada) == [
        ("institution_name", "Verificacion Fase Dieciseis"), ("institution_name", "GynFem"),
    ]
    assert filas(
        base_migrada, "SELECT action, changed_fields, actor_user_id FROM gynfem.audit_log ORDER BY id"
    ) == [("system_setting.update", ["institution_name"], ADMIN_ID)] * 2
    assert "2 filas permanentes" in salida.out
    assert conteos(base_migrada)["patients"] == 0


def test_se_restaura_el_valor_que_habia_no_el_valor_por_defecto(ejecutar, http_de, base_migrada, cliente_bd):
    cliente_bd(rol="administrador").patch("/api/v1/settings", json={"institution_name": "Centro Previo"})

    codigo, salida = ejecutar(http_de(), "--cambio-de-parametro")

    assert codigo == 0, salida.out
    assert [valor for _, valor in parametros(base_migrada)] == [
        "Centro Previo", "Verificacion Fase Dieciseis", "Centro Previo",
    ]
    assert "Centro Previo" not in salida.out, "el valor del parámetro no se imprime"


def test_si_el_valor_vigente_ya_es_el_de_verificacion_se_usa_otro(ejecutar, http_de, base_migrada, cliente_bd):
    cliente_bd(rol="administrador").patch("/api/v1/settings", json={"institution_name": "Verificacion Fase Dieciseis"})

    codigo, salida = ejecutar(http_de(), "--cambio-de-parametro")

    assert codigo == 0, salida.out
    valores = [valor for _, valor in parametros(base_migrada)]
    assert len(valores) == 3 and valores[0] == valores[2] == "Verificacion Fase Dieciseis" and valores[1] != valores[0]


FALSEOS_DEL_PARAMETRO = {
    "el cambio no se aplica": lambda vez, e, d: (e, {**d, "institution_name": {**d["institution_name"], "value": "GynFem"}}) if vez == 1 else (e, d),
    "el cambio se rechaza": lambda vez, e, d: (422, {"error": {"code": "validation_error"}}) if vez == 1 else (e, d),
    "la restauración falla": lambda vez, e, d: (500, {"error": {"code": "internal_error"}}) if vez == 2 else (e, d),
    "la restauración deja otro valor": lambda vez, e, d: (e, {**d, "institution_name": {**d["institution_name"], "value": "Otro"}}) if vez == 2 else (e, d),
}


@pytest.mark.parametrize("falseo", list(FALSEOS_DEL_PARAMETRO))
def test_cada_comprobacion_del_parametro_es_vinculante(falseo, ejecutar, http_de, base_migrada):
    cambio = FALSEOS_DEL_PARAMETRO[falseo]
    veces = []

    def alterar(metodo, ruta, estado, datos):
        if (metodo, ruta) == ("PATCH", "/api/v1/settings"):
            veces.append(1)
            return cambio(len(veces), estado, datos or {})
        return estado, datos

    codigo, salida = ejecutar(http_de(alterar), "--cambio-de-parametro")

    assert codigo == 1, falseo
    assert "FALLA parámetro:" in salida.out
    assert len(veces) == 2, "la restauración se intenta siempre"


def test_un_cambio_sin_auditoria_hace_fallar_el_guion(ejecutar, http_de, base_migrada):
    def alterar(metodo, ruta, estado, datos):
        if (metodo, ruta) == ("GET", "/api/v1/audit-log") and estado == 200 and datos["items"]:
            return estado, {**datos, "items": [{**datos["items"][0], "changed_fields": None}]}
        return estado, datos

    codigo, salida = ejecutar(http_de(alterar), "--cambio-de-parametro")

    assert codigo == 1
    assert "FALLA parámetro: cambio auditado con solo el nombre de la clave" in salida.out
    assert [valor for _, valor in parametros(base_migrada)][-1] == "GynFem", "aun así se restaura"
