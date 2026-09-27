"""`python -m ops.verificar_despliegue` (Fase 12, decisión D).

Se ejecuta contra la aplicación real en `production`, sin red: la capa HTTP del
guion se desvía a un `TestClient`, y el inicio de sesión en Supabase devuelve un
token firmado en la sesión. La readiness y el listado de usuarios, que necesitan
base, se sustituyen en la aplicación del test: aquí se prueba el guion, no la base.

Cada comprobación es vinculante: si la API responde otra cosa en ese punto, el
guion falla con código 1.
"""

import json
from urllib.parse import urlsplit

import pytest

from .auth_claves import ADMIN_ID

API = "https://gynfem-api.example.onrender.com"
SUPABASE = "https://abcdefghijklmnopqrst.supabase.co"
CORREO = "admin.verificacion@example.com"
CONTRASENA = "Contrasena-De-Verificacion-2026"
PUBLICABLE = "sb_publishable_ficticia"


@pytest.fixture
def app_produccion(crear_cliente):
    from app.services.readiness import ReadinessStatus

    cliente = crear_cliente(environment="production", cors_origins="https://gynfem-frontend.invalid", rol=None)
    estado = cliente.app.state
    estado.readiness_service.check = lambda: ReadinessStatus.READY
    estado.user_service.list_page = lambda limit, offset: ([], False)
    return cliente


@pytest.fixture
def http_de(app_produccion, emisor):
    """Construye la función HTTP del guion; `alterar(metodo, ruta, estado, datos)` puede falsear una respuesta."""

    def _construir(alterar=None, login=(200, None)):
        llamadas = []

        def http(metodo, url, cuerpo=None, cabeceras=None):
            llamadas.append((metodo, url, cabeceras or {}))
            if url.startswith(SUPABASE):
                estado, datos = login
                if estado == 200 and datos is None:
                    datos = {"access_token": emisor.token(ADMIN_ID), "token_type": "bearer"}
                return estado, datos, 0.01
            partes = urlsplit(url)
            ruta = partes.path + (f"?{partes.query}" if partes.query else "")
            respuesta = app_produccion.request(metodo, ruta, json=cuerpo, headers=cabeceras or {})
            datos = respuesta.json() if respuesta.content else None
            estado = respuesta.status_code
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
        }.items():
            monkeypatch.setenv(clave, valor)
        codigo = verificar_despliegue.main(["--url", API, "--repeticiones", "2", *extra], http=http)
        return codigo, capsys.readouterr()

    return _ejecutar


def test_contra_una_api_correcta_todas_las_comprobaciones_pasan(ejecutar, http_de):
    codigo, salida = ejecutar(http_de())

    assert codigo == 0, salida.out
    assert "FALLA" not in salida.out
    assert salida.out.count("OK ") >= 14


def test_la_salida_no_muestra_token_contrasena_correo_ni_clave(ejecutar, http_de, emisor):
    http = http_de()
    _, salida = ejecutar(http)
    token = emisor.token(ADMIN_ID).split(".")[1]  # la carga cambia por token; basta un fragmento estable
    for fuga in (CONTRASENA, CORREO, PUBLICABLE, "eyJ"):
        assert fuga not in salida.out and fuga not in salida.err
    assert token[:10] not in salida.out


def test_el_login_usa_la_clave_publicable_y_la_contrasena_solo_contra_supabase(ejecutar, http_de):
    http = http_de()
    ejecutar(http)
    [login] = [c for c in http.llamadas if c[1].startswith(SUPABASE)]

    assert login[1] == f"{SUPABASE}/auth/v1/token?grant_type=password"
    assert login[2]["apikey"] == PUBLICABLE
    for metodo, url, cabeceras in http.llamadas:
        if url.startswith(API):
            assert PUBLICABLE not in json.dumps(cabeceras)


# Cada comprobación, falseada en su punto, hace fallar el guion.
FALSEOS = {
    "health caído": ("GET", "/api/v1/health", lambda e, d: (503, d)),
    "versión distinta": ("GET", "/api/v1/health", lambda e, d: (200, {**d, "version": "9.9.9"})),
    "docs expuestas en producción": ("GET", "/api/v1/docs", lambda e, d: (200, {})),
    "sin token aceptado": ("GET", "/api/v1/me", lambda e, d: (200, {"id": "x", "role": "medico"}) if e == 401 else (e, d)),
    "rol que no es de administrador": ("GET", "/api/v1/me", lambda e, d: (e, {**d, "role": "medico"}) if e == 200 else (e, d)),
    "readiness no lista": ("GET", "/api/v1/health/ready", lambda e, d: (503, {"error": {"code": "schema_outdated"}})),
    "administrador ve pacientes": ("POST", "/api/v1/patients/search", lambda e, d: (200, {"items": []})),
    "administrador sin usuarios": ("GET", "/api/v1/users", lambda e, d: (403, {"error": {"code": "forbidden"}})),
    "predicción sin advertencia clínica": ("POST", "/api/v1/predict",
                                           lambda e, d: (e, {k: v for k, v in d.items() if k != "clinical_disclaimer"}) if e == 200 else (e, d)),
    "imposible aceptado": ("POST", "/api/v1/predict", lambda e, d: (200, {"risk_level": "low"}) if e == 422 else (e, d)),
    "error con traza": ("GET", "/api/v1/no-existe", lambda e, d: (e, {**d, "traceback": 'File "/opt/render/project/src/app/main.py"'})),
}


@pytest.mark.parametrize("falseo", list(FALSEOS))
def test_cada_comprobacion_es_vinculante(falseo, ejecutar, http_de):
    metodo, ruta, cambio = FALSEOS[falseo]

    def alterar(m, r, estado, datos):
        if (m, r) == (metodo, ruta):
            return cambio(estado, datos or {})
        return estado, datos

    codigo, salida = ejecutar(http_de(alterar))

    assert codigo == 1, falseo
    assert "FALLA" in salida.out


def test_login_rechazado_falla_sin_mostrar_credenciales(ejecutar, http_de):
    codigo, salida = ejecutar(http_de(login=(400, {"error": "invalid_grant", "msg": f"bad {CORREO}"})))

    assert codigo == 1
    assert "inicio de sesión" in salida.out
    assert CORREO not in salida.out and CONTRASENA not in salida.out


def test_sin_variables_explica_cuales_faltan_sin_valores(monkeypatch, capsys):
    from ops import verificar_despliegue

    for clave in ("GYNFEM_SUPABASE_URL", "GYNFEM_SUPABASE_PUBLISHABLE_KEY",
                  "GYNFEM_SMOKE_ADMIN_EMAIL", "GYNFEM_SMOKE_ADMIN_PASSWORD"):
        monkeypatch.delenv(clave, raising=False)
    codigo = verificar_despliegue.main(["--url", API], http=lambda *a, **k: pytest.fail("no debe llamar"))

    assert codigo == 1
    assert "GYNFEM_SMOKE_ADMIN_PASSWORD" in capsys.readouterr().err


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
