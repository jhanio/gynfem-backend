"""`python -m ops.verificar_despliegue` (Fase 12, decisión D).

Se ejecuta contra la aplicación real en `production`, sin red: la capa HTTP del
guion se desvía a un `TestClient`, y el inicio de sesión en Supabase devuelve un
token firmado en la sesión. La readiness y el listado de usuarios, que necesitan
base, se sustituyen en la aplicación del test: aquí se prueba el guion, no la base.

Cada comprobación es vinculante: si la API responde otra cosa en ese punto, el
guion falla con código 1 (`test_cada_comprobacion_es_vinculante`, un falseo por
comprobación, incluida la latencia).

Fase 16: el guion comprueba además las métricas del modelo contra los artefactos
locales, la configuración y la auditoría con el administrador, y sus negativos
con una cuenta de médico. La configuración y la auditoría, que necesitan base,
también se sustituyen aquí; el flujo clínico y el cambio de parámetro se prueban
contra la base embebida en `tests/database/test_verificar_despliegue_fase16.py`.
"""

import json
from urllib.parse import urlsplit

import pytest

from .auth_claves import ADMIN_ID, MEDICO_ID

API = "https://gynfem-api.example.onrender.com"
SUPABASE = "https://abcdefghijklmnopqrst.supabase.co"
CORREO = "admin.verificacion@example.com"
CONTRASENA = "Contrasena-De-Verificacion-2026"
CORREO_MEDICO = "medica.verificacion@example.com"
CONTRASENA_MEDICO = "Contrasena-De-La-Medica-2026"
PUBLICABLE = "sb_publishable_ficticia"


@pytest.fixture
def app_produccion(crear_cliente):
    from app.services.readiness import ReadinessStatus

    cliente = crear_cliente(environment="production", cors_origins="https://gynfem-frontend.invalid", rol=None)
    estado = cliente.app.state
    estado.readiness_service.check = lambda: ReadinessStatus.READY
    estado.user_service.list_page = lambda limit, offset: ([], False)
    estado.system_settings_service.get_all = lambda: {
        "institution_name": {"value": "GynFem", "default": "GynFem", "updated_at": None, "updated_by": None},
        "history_default_page_size": {"value": 20, "default": 20, "updated_at": None, "updated_by": None},
    }
    estado.audit_query_service.list_page = lambda filtros, limit, offset: ([], False)
    return cliente


@pytest.fixture
def http_de(app_produccion, emisor):
    """Construye la función HTTP del guion; `alterar(metodo, ruta, estado, datos, cabeceras)` puede falsear una respuesta."""

    def _construir(alterar=None, login=(200, None), login_medico=(200, None)):
        llamadas = []

        def http(metodo, url, cuerpo=None, cabeceras=None):
            llamadas.append((metodo, url, cabeceras or {}))
            if url.startswith(SUPABASE):
                es_medico = (cuerpo or {}).get("email") == CORREO_MEDICO
                assert (cuerpo or {}).get("password") == (CONTRASENA_MEDICO if es_medico else CONTRASENA)
                estado, datos = login_medico if es_medico else login
                if estado == 200 and datos is None:
                    usuario = MEDICO_ID if es_medico else ADMIN_ID
                    datos = {"access_token": emisor.token(usuario), "token_type": "bearer"}
                return estado, datos, 0.01
            partes = urlsplit(url)
            ruta = partes.path + (f"?{partes.query}" if partes.query else "")
            respuesta = app_produccion.request(metodo, ruta, json=cuerpo, headers=cabeceras or {})
            datos = respuesta.json() if respuesta.content else None
            estado = respuesta.status_code
            if alterar is not None:
                estado, datos = alterar(metodo, partes.path, estado, datos, cabeceras or {})
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
        codigo = verificar_despliegue.main(["--url", API, "--repeticiones", "2", *extra], http=http)
        return codigo, capsys.readouterr()

    return _ejecutar


def test_contra_una_api_correcta_todas_las_comprobaciones_pasan(ejecutar, http_de):
    codigo, salida = ejecutar(http_de())

    assert codigo == 0, salida.out
    assert "FALLA" not in salida.out
    assert salida.out.count("OK ") >= 26


SECRETOS = (CONTRASENA, CORREO, CONTRASENA_MEDICO, CORREO_MEDICO, PUBLICABLE, "eyJ", "Bearer")


def test_la_salida_no_muestra_token_contrasena_correo_ni_clave(ejecutar, http_de, emisor):
    http = http_de()
    _, salida = ejecutar(http)
    token = emisor.token(ADMIN_ID).split(".")[1]  # la carga cambia por token; basta un fragmento estable
    for fuga in SECRETOS:
        assert fuga not in salida.out and fuga not in salida.err
    assert token[:10] not in salida.out
    assert emisor.token(MEDICO_ID).split(".")[1][:10] not in salida.out


def test_un_error_inesperado_no_muestra_credenciales_ni_traza(ejecutar, http_de, emisor):
    """Ni siquiera en un error: una excepción cuyo mensaje lleva las credenciales y el
    token termina en una línea con solo el tipo del error."""
    normal = http_de()

    def http(metodo, url, cuerpo=None, cabeceras=None):
        if url.endswith("/model/metrics"):
            raise RuntimeError(
                f"fallo con {CONTRASENA} {CORREO} {CONTRASENA_MEDICO} {CORREO_MEDICO} {PUBLICABLE} "
                f"{(cabeceras or {}).get('Authorization')}"
            )
        return normal(metodo, url, cuerpo, cabeceras)

    codigo, salida = ejecutar(http)

    assert codigo == 1
    assert "RuntimeError" in salida.out + salida.err, "se informa el tipo del error"
    for fuga in (*SECRETOS, "Traceback", "fallo con"):
        assert fuga not in salida.out and fuga not in salida.err, fuga


def test_cada_comprobacion_fallida_se_informa_sin_credenciales(ejecutar, http_de):
    """Todas las respuestas de la API falseadas a 500 con un cuerpo que repite las credenciales."""

    def alterar(metodo, ruta, estado, datos, cabeceras):
        if ruta == "/api/v1/health":
            return estado, datos
        return 500, {"error": {"code": f"{CONTRASENA}-{CORREO_MEDICO}", "message": cabeceras.get("Authorization", "")}}

    codigo, salida = ejecutar(http_de(alterar))

    assert codigo == 1 and "FALLA" in salida.out
    for fuga in (CONTRASENA, CORREO, CONTRASENA_MEDICO, CORREO_MEDICO, PUBLICABLE, "eyJ"):
        assert fuga not in salida.out and fuga not in salida.err, fuga


def test_el_login_usa_la_clave_publicable_y_la_contrasena_solo_contra_supabase(ejecutar, http_de):
    http = http_de()
    ejecutar(http)
    del_administrador, de_la_medica = [c for c in http.llamadas if c[1].startswith(SUPABASE)]

    for login in (del_administrador, de_la_medica):
        assert login[1] == f"{SUPABASE}/auth/v1/token?grant_type=password"
        assert login[2]["apikey"] == PUBLICABLE
    for metodo, url, cabeceras in http.llamadas:
        if url.startswith(API):
            assert PUBLICABLE not in json.dumps(cabeceras)


UUID_INEXISTENTE = "00000000-0000-4000-8000-000000000000"


def _desde_la_llamada(n: int, respuesta: tuple):
    """Deja pasar las primeras n-1 llamadas a la ruta y falsea las siguientes (la latencia)."""
    cuenta = {"i": 0}

    def cambio(e, d, c):
        cuenta["i"] += 1
        return respuesta if cuenta["i"] >= n else (e, d)

    return cambio


def _token_alterado(c: dict) -> bool:
    return c.get("Authorization", "").endswith("AAAA")


# Cada comprobación, falseada en su punto, hace fallar el guion. Los valores son
# fábricas: cada test recibe su propio falseo (algunos cuentan llamadas).
FALSEOS = {
    "health caído": ("GET", "/api/v1/health", lambda: lambda e, d, c: (503, d)),
    "versión distinta": ("GET", "/api/v1/health", lambda: lambda e, d, c: (200, {**d, "version": "9.9.9"})),
    "docs expuestas en producción": ("GET", "/api/v1/docs", lambda: lambda e, d, c: (200, {})),
    "openapi expuesto en producción": ("GET", "/api/v1/openapi.json", lambda: lambda e, d, c: (200, {"openapi": "3.1.0"})),
    "sin token aceptado": ("GET", "/api/v1/me",
                           lambda: lambda e, d, c: (200, {"id": "x", "role": "medico"}) if e == 401 and not c else (e, d)),
    "token alterado aceptado": ("GET", "/api/v1/me",
                                lambda: lambda e, d, c: (200, {"id": "x", "role": "administrador"}) if _token_alterado(c) else (e, d)),
    "rol que no es de administrador": ("GET", "/api/v1/me",
                                       lambda: lambda e, d, c: (e, {**d, "role": "medico"}) if e == 200 else (e, d)),
    "readiness no lista": ("GET", "/api/v1/health/ready",
                           lambda: lambda e, d, c: (503, {"error": {"code": "schema_outdated"}})),
    "administrador ve pacientes": ("POST", "/api/v1/patients/search", lambda: lambda e, d, c: (200, {"items": []})),
    "administrador sin usuarios": ("GET", "/api/v1/users", lambda: lambda e, d, c: (403, {"error": {"code": "forbidden"}})),
    "predicción sin advertencia clínica": ("POST", "/api/v1/predict",
                                           lambda: lambda e, d, c: (e, {k: v for k, v in d.items() if k != "clinical_disclaimer"}) if e == 200 else (e, d)),
    "extrapolación sin avisos": ("POST", "/api/v1/predict",
                                 lambda: lambda e, d, c: (e, {**d, "extrapolation_warnings": []}) if e == 200 and d.get("extrapolation_warnings") else (e, d)),
    "imposible aceptado": ("POST", "/api/v1/predict", lambda: lambda e, d, c: (200, {"risk_level": "low"}) if e == 422 else (e, d)),
    "error con traza": ("GET", "/api/v1/no-existe",
                        lambda: lambda e, d, c: (e, {**d, "traceback": 'File "/opt/render/project/src/app/main.py"'})),
    "405 sin el formato uniforme": ("PUT", "/api/v1/health", lambda: lambda e, d, c: (405, {"detail": "Method Not Allowed"})),
    # Fase 16.
    "métrica distinta de la del artefacto": ("GET", "/api/v1/model/metrics", lambda: lambda e, d, c: (
        e, {**d, "metrics": {**d["metrics"], "accuracy": d["metrics"]["accuracy"] + 0.001}})),
    "métrica ausente": ("GET", "/api/v1/model/metrics", lambda: lambda e, d, c: (
        e, {**d, "metrics": {k: v for k, v in d["metrics"].items() if k != "recall_macro"}})),
    "métricas de otra versión del modelo": ("GET", "/api/v1/model/metrics", lambda: lambda e, d, c: (
        e, {**d, "model": {**d["model"], "model_version": "9.9.9"}})),
    "métricas sin una limitación": ("GET", "/api/v1/model/metrics",
                                    lambda: lambda e, d, c: (e, {**d, "limitations": d["limitations"][1:]})),
    "métricas sin limitaciones": ("GET", "/api/v1/model/metrics", lambda: lambda e, d, c: (e, {**d, "limitations": []})),
    "métricas sin el detalle desplegado": ("GET", "/api/v1/model/metrics", lambda: lambda e, d, c: (
        e, {**d, "detail": None, "detail_unavailable_reason": "training_metrics_missing"})),
    "administrador sin configuración": ("GET", "/api/v1/settings",
                                        lambda: lambda e, d, c: (403, {"error": {"code": "forbidden"}}) if e == 200 else (e, d)),
    "configuración sin un parámetro": ("GET", "/api/v1/settings", lambda: lambda e, d, c: (
        e, {k: v for k, v in d.items() if k != "institution_name"}) if e == 200 else (e, d)),
    "administrador sin auditoría": ("GET", "/api/v1/audit-log",
                                    lambda: lambda e, d, c: (403, {"error": {"code": "forbidden"}}) if e == 200 else (e, d)),
    "médico ve la configuración": ("GET", "/api/v1/settings", lambda: lambda e, d, c: (200, {}) if e == 403 else (e, d)),
    "médico ve la auditoría": ("GET", "/api/v1/audit-log", lambda: lambda e, d, c: (200, {"items": []}) if e == 403 else (e, d)),
    "administrador ve el historial": ("GET", f"/api/v1/patients/{UUID_INEXISTENTE}/evaluations",
                                      lambda: lambda e, d, c: (200, {"items": []})),
    "administrador genera el reporte": ("POST", f"/api/v1/predictions/{UUID_INEXISTENTE}/report",
                                        lambda: lambda e, d, c: (200, {"patient": {}})),
    "historial inexistente en vez de prohibido": ("GET", f"/api/v1/patients/{UUID_INEXISTENTE}/evaluations",
                                                  lambda: lambda e, d, c: (404, {"error": {"code": "patient_not_found"}})),
    "la cuenta de médico no es de médico": ("GET", "/api/v1/me", lambda: lambda e, d, c: (
        e, {**d, "role": "administrador"}) if e == 200 and d.get("role") == "medico" else (e, d)),
    "latencia de /health con un error": ("GET", "/api/v1/health", lambda: _desde_la_llamada(3, (503, None))),
    "latencia de /health/ready con un error": ("GET", "/api/v1/health/ready", lambda: _desde_la_llamada(2, (503, None))),
    "latencia de /me con un error": ("GET", "/api/v1/me", lambda: _desde_la_llamada(6, (503, None))),
}


@pytest.mark.parametrize("falseo", list(FALSEOS))
def test_cada_comprobacion_es_vinculante(falseo, ejecutar, http_de):
    metodo, ruta, fabrica = FALSEOS[falseo]
    cambio = fabrica()

    def alterar(m, r, estado, datos, cabeceras):
        if (m, r) == (metodo, ruta):
            return cambio(estado, datos or {}, cabeceras)
        return estado, datos

    codigo, salida = ejecutar(http_de(alterar))

    assert codigo == 1, falseo
    assert "FALLA" in salida.out


def test_login_rechazado_falla_sin_mostrar_credenciales(ejecutar, http_de):
    codigo, salida = ejecutar(http_de(login=(400, {"error": "invalid_grant", "msg": f"bad {CORREO}"})))

    assert codigo == 1
    assert "inicio de sesión" in salida.out
    assert CORREO not in salida.out and CONTRASENA not in salida.out


def test_login_de_la_medica_rechazado_falla_y_sigue_sin_mostrar_credenciales(ejecutar, http_de):
    http = http_de(login_medico=(400, {"error": "invalid_grant", "msg": f"bad {CORREO_MEDICO} {CONTRASENA_MEDICO}"}))

    codigo, salida = ejecutar(http)

    assert codigo == 1
    assert "FALLA inicio de sesión de la cuenta de médico" in salida.out
    assert "Latencia /api/v1/health" in salida.out, "el resto de la verificación continúa"
    for fuga in SECRETOS:
        assert fuga not in salida.out and fuga not in salida.err


def test_sin_variables_explica_cuales_faltan_sin_valores(monkeypatch, capsys):
    from ops import verificar_despliegue

    for clave in ("GYNFEM_SUPABASE_URL", "GYNFEM_SUPABASE_PUBLISHABLE_KEY",
                  "GYNFEM_SMOKE_ADMIN_EMAIL", "GYNFEM_SMOKE_ADMIN_PASSWORD",
                  "GYNFEM_SMOKE_MEDICO_EMAIL", "GYNFEM_SMOKE_MEDICO_PASSWORD"):
        monkeypatch.delenv(clave, raising=False)
    codigo = verificar_despliegue.main(["--url", API], http=lambda *a, **k: pytest.fail("no debe llamar"))

    assert codigo == 1
    error = capsys.readouterr().err
    assert "GYNFEM_SMOKE_ADMIN_PASSWORD" in error and "GYNFEM_SMOKE_MEDICO_PASSWORD" in error


def test_sin_la_cuenta_de_medico_no_se_ejecuta_nada(ejecutar, monkeypatch, capsys):
    """Desde la Fase 16 la cuenta de médico es obligatoria: sin ella no hay negativos que comprobar."""
    from ops import verificar_despliegue

    for clave, valor in {"GYNFEM_SUPABASE_URL": SUPABASE, "GYNFEM_SUPABASE_PUBLISHABLE_KEY": PUBLICABLE,
                         "GYNFEM_SMOKE_ADMIN_EMAIL": CORREO, "GYNFEM_SMOKE_ADMIN_PASSWORD": CONTRASENA}.items():
        monkeypatch.setenv(clave, valor)
    codigo = verificar_despliegue.main(["--url", API], http=lambda *a, **k: pytest.fail("no debe llamar"))

    error = capsys.readouterr().err
    assert codigo == 1
    assert "GYNFEM_SMOKE_MEDICO_EMAIL" in error and CORREO not in error and CONTRASENA not in error


# --- Fase 16 ------------------------------------------------------------------------


def test_las_limitaciones_que_exige_el_guion_son_las_que_publica_la_api(app_produccion, emisor):
    from ops.verificar_despliegue import LIMITACIONES

    from .auth_claves import cabecera

    cuerpo = app_produccion.get("/api/v1/model/metrics", headers=cabecera(emisor.token(ADMIN_ID))).json()

    assert list(LIMITACIONES) == [limitacion["code"] for limitacion in cuerpo["limitations"]]


def test_las_metricas_se_comparan_con_los_artefactos_locales(ejecutar, http_de):
    _, salida = ejecutar(http_de())

    for nombre in ("métricas del modelo: iguales al artefacto local", "métricas del modelo: limitaciones completas",
                   "métricas del modelo: detalle desplegado"):
        assert f"OK    {nombre}" in salida.out, nombre


def test_si_el_esquema_no_coincide_se_informa_y_se_detiene(ejecutar, http_de):
    def alterar(metodo, ruta, estado, datos, cabeceras):
        if ruta == "/api/v1/health/ready":
            return 503, {"error": {"code": "schema_outdated", "message": "…", "request_id": "x"}}
        return estado, datos

    http = http_de(alterar)
    codigo, salida = ejecutar(http, "--flujo-clinico", "--cambio-de-parametro")

    assert codigo == 1
    assert "FALLA readiness (base y esquema)" in salida.out
    assert "DETENIDO" in salida.out and "schema_outdated" in salida.out and "migración" in salida.out
    rutas = [urlsplit(url).path for _, url, _ in http.llamadas if url.startswith(API)]
    posteriores = rutas[rutas.index("/api/v1/health/ready") + 1:]
    assert posteriores == [], f"tras el esquema desactualizado no se llama a nada más: {posteriores}"
    assert "Latencia" not in salida.out


def test_sin_los_indicadores_el_guion_solo_lee(ejecutar, http_de):
    """Sin `--flujo-clinico` ni `--cambio-de-parametro`: ninguna petición que escriba."""
    http = http_de()
    codigo, _ = ejecutar(http)

    assert codigo == 0
    escrituras = [
        (metodo, urlsplit(url).path) for metodo, url, _ in http.llamadas
        if url.startswith(API) and metodo != "GET"
    ]
    # Las únicas no-GET: la búsqueda y el reporte que el administrador tiene prohibidos (403),
    # las tres predicciones sin persistencia y el 405 de prueba.
    assert sorted(set(escrituras)) == sorted({
        ("POST", "/api/v1/patients/search"), ("POST", "/api/v1/predict"), ("PUT", "/api/v1/health"),
        ("POST", f"/api/v1/predictions/{UUID_INEXISTENTE}/report"),
    })


def test_el_guion_no_aplica_migraciones_ni_lee_su_credencial():
    import ast

    from .api_constantes import REPO_ROOT

    fuente = (REPO_ROOT / "ops" / "verificar_despliegue.py").read_text(encoding="utf-8")
    importados = [n.module for n in ast.walk(ast.parse(fuente)) if isinstance(n, ast.ImportFrom) and n.module]

    assert not any(modulo.startswith("app.db") for modulo in importados)
    for prohibido in ("MIGRATIONS_DATABASE_URL", "GYNFEM_DATABASE_URL", "SUPABASE_SECRET_KEY", "psycopg"):
        assert prohibido not in fuente, prohibido


@pytest.mark.parametrize("url", ["http://gynfem-api.onrender.com", "gynfem-api.onrender.com", "https://x.onrender.com/api/v1"])
def test_la_url_del_servicio_debe_ser_https_sin_ruta(url, monkeypatch, capsys):
    from ops import verificar_despliegue

    codigo = verificar_despliegue.main(["--url", url], http=lambda *a, **k: pytest.fail("no debe llamar"))
    assert codigo == 1


def test_mide_la_latencia_de_health_ready_y_me(ejecutar, http_de):
    http = http_de()
    _, salida = ejecutar(http)

    assert sum(1 for c in http.llamadas if c[1] == f"{API}/api/v1/health/ready") >= 3
    for ruta in ("/api/v1/health", "/api/v1/health/ready", "/api/v1/me"):
        assert f"Latencia {ruta}" in salida.out


#: Arranques en frío medidos en producción (Fase 12): 53.1 s, 22.7 s y 41.4 s.
ARRANQUE_EN_FRIO_MAS_LENTO_S = 53.1


def test_tolera_un_arranque_en_frio_del_plan_free():
    """La primera petición tras la suspensión del plan Free espera al arranque completo:
    el límite de cada petición debe superar con margen el peor arranque medido."""
    from ops.verificar_despliegue import TIMEOUT_S

    assert TIMEOUT_S >= 2 * ARRANQUE_EN_FRIO_MAS_LENTO_S


@pytest.mark.parametrize("limite, espera_ok", [(5, True), (1, False)])
def test_http_real_usa_el_limite_configurado(limite, espera_ok, monkeypatch):
    """Un servidor que tarda 2 s en responder: con el límite del guion se espera, con uno menor, no."""
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from ops import verificar_despliegue

    class Lento(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            time.sleep(2)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Lento)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    monkeypatch.setattr(verificar_despliegue, "TIMEOUT_S", limite)
    try:
        url = f"http://127.0.0.1:{servidor.server_address[1]}/"
        if espera_ok:
            assert verificar_despliegue.http_real("GET", url)[0] == 200
        else:
            # Tiempo agotado: estado 0, que hace fallar la comprobación (sin traza).
            assert verificar_despliegue.http_real("GET", url)[:2] == (0, None)
    finally:
        servidor.shutdown()
        servidor.server_close()


def test_un_servicio_inalcanzable_falla_con_su_nombre_y_sin_traza(monkeypatch):
    """Una conexión rechazada o un tiempo agotado es un estado 0: la comprobación
    falla con su nombre en el informe, en vez de cortarlo con una traza."""
    import socket

    from ops import verificar_despliegue

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    monkeypatch.setattr(verificar_despliegue, "TIMEOUT_S", 2)

    estado, datos, _ = verificar_despliegue.http_real("GET", f"http://127.0.0.1:{puerto}/api/v1/health")
    assert (estado, datos) == (0, None)


def test_la_url_de_supabase_debe_ser_https(monkeypatch, capsys):
    """La contraseña del administrador solo se envía a una URL https sin ruta."""
    from ops import verificar_despliegue

    for clave, valor in {
        "GYNFEM_SUPABASE_URL": "http://abcdefghijklmnopqrst.supabase.co",
        "GYNFEM_SUPABASE_PUBLISHABLE_KEY": PUBLICABLE,
        "GYNFEM_SMOKE_ADMIN_EMAIL": CORREO,
        "GYNFEM_SMOKE_ADMIN_PASSWORD": CONTRASENA,
        "GYNFEM_SMOKE_MEDICO_EMAIL": CORREO_MEDICO,
        "GYNFEM_SMOKE_MEDICO_PASSWORD": CONTRASENA_MEDICO,
    }.items():
        monkeypatch.setenv(clave, valor)
    codigo = verificar_despliegue.main(["--url", API], http=lambda *a, **k: pytest.fail("no debe llamar"))

    assert codigo == 1
    assert "GYNFEM_SUPABASE_URL" in capsys.readouterr().err
