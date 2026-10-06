"""`python -m ops.matriz_rbac` (Fase 17): la lógica del guion, sin red ni base.

Aquí se prueba que el guion lee la matriz de `docs/API_SPEC.md`, que tiene una
sonda para cada ruta, qué espera en cada celda y cuándo se detiene sin pedir
nada protegido. Que la matriz **pasa contra la aplicación real y no escribe
nada** se prueba contra la base embebida en `tests/database/test_matriz_rbac.py`,
que también falsea respuestas para comprobar que cada celda es vinculante.
"""

import json

import pytest

API = "https://gynfem-api.example.onrender.com"
SUPABASE = "https://abcdefghijklmnopqrst.supabase.co"
CORREO = "admin.verificacion@example.com"
CONTRASENA = "Contrasena-De-Verificacion-2026"
CORREO_MEDICO = "medica.verificacion@example.com"
CONTRASENA_MEDICO = "Contrasena-De-La-Medica-2026"
PUBLICABLE = "sb_publishable_ficticia"
TOKEN = "eyJhbGciOiJFUzI1NiJ9.ficticio.firma"
SECRETOS = (CONTRASENA, CORREO, CONTRASENA_MEDICO, CORREO_MEDICO, PUBLICABLE, TOKEN, "eyJ", "Bearer")


@pytest.fixture
def variables(monkeypatch):
    for clave, valor in {
        "GYNFEM_SUPABASE_URL": SUPABASE,
        "GYNFEM_SUPABASE_PUBLISHABLE_KEY": PUBLICABLE,
        "GYNFEM_SMOKE_ADMIN_EMAIL": CORREO,
        "GYNFEM_SMOKE_ADMIN_PASSWORD": CONTRASENA,
        "GYNFEM_SMOKE_MEDICO_EMAIL": CORREO_MEDICO,
        "GYNFEM_SMOKE_MEDICO_PASSWORD": CONTRASENA_MEDICO,
    }.items():
        monkeypatch.setenv(clave, valor)


def http_minimo(version=None, login=200, roles=("administrador", "medico")):
    """Responde a la salud, al inicio de sesión y a `/me`; lo demás, estado 0. Registra todo lo que se pide.

    `roles`: el rol que `/me` devuelve para el token del administrador y para el de la médica.
    """
    from app import __version__

    llamadas = []
    token_de = {CORREO: TOKEN + "a", CORREO_MEDICO: TOKEN + "m"}
    rol_de = {f"Bearer {TOKEN}a": roles[0], f"Bearer {TOKEN}m": roles[1]}

    def http(metodo, url, cuerpo=None, cabeceras=None):
        llamadas.append((metodo, url))
        if url.startswith(SUPABASE):
            if login != 200:
                return login, {"error": "invalid_grant"}, 0.01
            return 200, {"access_token": token_de[(cuerpo or {})["email"]]}, 0.01
        if url.endswith("/api/v1/health"):
            return 200, {"status": "ok", "version": version or __version__}, 0.01
        if url.endswith("/api/v1/me") and (cabeceras or {}).get("Authorization") in rol_de:
            return 200, {"id": "x", "role": rol_de[cabeceras["Authorization"]]}, 0.01
        return 0, None, 0.01

    http.llamadas = llamadas
    return http


def protegidas_pedidas(http) -> list:
    return [(m, u) for m, u in http.llamadas
            if u.startswith(API) and not u.endswith(("/api/v1/health", "/api/v1/me"))]


# --- La matriz y las sondas -------------------------------------------------------------------


def test_lee_las_28_filas_de_api_spec_con_sus_tres_celdas():
    from ops.matriz_rbac import IDENTIDADES, leer_matriz

    filas = leer_matriz()

    assert len(filas) == 28
    assert len({(f.metodo, f.ruta) for f in filas}) == 28
    permitidas = {i: sum(f.celdas[i] == "✔" for f in filas) for i in IDENTIDADES}
    assert permitidas == {"anonimo": 3, "medico": 18, "administrador": 17}
    assert all(f.celdas[i] in {"✔", "401", "403"} for f in filas for i in IDENTIDADES)


def test_hay_una_sonda_por_ruta_protegida_sin_sobrantes():
    from ops.matriz_rbac import SONDAS, leer_matriz

    protegidas = {(f.metodo, f.ruta) for f in leer_matriz() if f.celdas["anonimo"] != "✔"}

    assert set(SONDAS) == protegidas


def test_ninguna_sonda_lleva_datos_de_una_persona():
    """Los cuerpos solo llevan valores clínicos sintéticos o nombres que dicen «ficticio»."""
    from ops.matriz_rbac import SONDAS

    texto = json.dumps([s.cuerpo for s in SONDAS.values()], ensure_ascii=False)
    assert "@" not in texto
    assert all(s.estado in {200, 404, 422} for s in SONDAS.values())


@pytest.mark.parametrize(
    ("metodo", "ruta", "identidad", "esperado"),
    [
        ("GET", "/api/v1/health", "anonimo", (200, None)),
        ("GET", "/api/v1/openapi.json", "medico", (404, "not_found")),
        ("GET", "/api/v1/docs", "administrador", (404, "not_found")),
        ("GET", "/api/v1/me", "anonimo", (401, "not_authenticated")),
        ("POST", "/api/v1/patients", "administrador", (403, "forbidden")),
        ("GET", "/api/v1/settings", "medico", (403, "forbidden")),
        ("GET", "/api/v1/health/ready", "medico", (403, "forbidden")),
        ("DELETE", "/api/v1/patients/{patient_id}", "medico", (404, "patient_not_found")),
        ("POST", "/api/v1/patients", "medico", (422, "validation_error")),
        ("POST", "/api/v1/users/{user_id}/deactivate", "administrador", (404, "user_not_found")),
        ("GET", "/api/v1/model/metrics", "administrador", (200, None)),
    ],
)
def test_esperado_por_celda(metodo, ruta, identidad, esperado):
    from ops.matriz_rbac import esperado_de, leer_matriz

    fila = next(f for f in leer_matriz() if (f.metodo, f.ruta) == (metodo, ruta))

    assert esperado_de(fila, identidad) == esperado


def test_cada_corrida_usa_un_uuid_nuevo_en_las_rutas_con_id():
    from ops.matriz_rbac import ruta_concreta

    a = ruta_concreta("/api/v1/patients/{patient_id}")
    b = ruta_concreta("/api/v1/patients/{patient_id}")

    assert a != b and "{" not in a and a.startswith("/api/v1/patients/")


# --- Se detiene antes de pedir nada protegido ----------------------------------------------


def test_sin_variables_no_arranca_y_no_muestra_valores(monkeypatch, capsys):
    from ops import matriz_rbac

    for clave in ("GYNFEM_SUPABASE_URL", "GYNFEM_SMOKE_MEDICO_PASSWORD"):
        monkeypatch.delenv(clave, raising=False)
    http = http_minimo()

    codigo = matriz_rbac.main(["--url", API], http=http)

    assert codigo == 1
    assert "GYNFEM_SUPABASE_URL" in capsys.readouterr().err
    assert http.llamadas == []


def test_la_url_debe_ser_https(variables, capsys):
    from ops import matriz_rbac

    assert matriz_rbac.main(["--url", "http://gynfem-api.example.onrender.com"], http=http_minimo()) == 1


def test_version_desplegada_distinta_detiene_la_matriz(variables, tmp_path, capsys):
    from ops import matriz_rbac

    http = http_minimo(version="0.0.1")

    codigo = matriz_rbac.main(["--url", API, "--salida", str(tmp_path / "m.jsonl")], http=http)

    assert codigo == 1
    assert "DETENIDO" in capsys.readouterr().out
    assert protegidas_pedidas(http) == []


@pytest.mark.parametrize("estado", [400, 0])
def test_un_inicio_de_sesion_fallido_detiene_la_matriz(variables, tmp_path, capsys, estado):
    from ops import matriz_rbac

    http = http_minimo(login=estado)

    codigo = matriz_rbac.main(["--url", API, "--salida", str(tmp_path / "m.jsonl")], http=http)

    assert codigo == 1
    assert "DETENIDO" in capsys.readouterr().out
    assert protegidas_pedidas(http) == []


@pytest.mark.parametrize("roles", [("medico", "medico"), ("administrador", "administrador")])
def test_una_cuenta_con_otro_rol_detiene_la_matriz(variables, tmp_path, capsys, roles):
    """Si la cuenta «de médica» no es médica, la matriz no prueba lo que dice: se detiene."""
    from ops import matriz_rbac

    http = http_minimo(roles=roles)

    codigo = matriz_rbac.main(["--url", API, "--salida", str(tmp_path / "m.jsonl")], http=http)

    assert codigo == 1
    assert "DETENIDO" in capsys.readouterr().out
    assert protegidas_pedidas(http) == []


def test_la_salida_no_contiene_credenciales_ni_tokens(variables, tmp_path, capsys):
    """Una API que responde 0 a todo: falla cada celda, y aun así nada secreto sale."""
    from ops import matriz_rbac

    salida = tmp_path / "m.jsonl"

    codigo = matriz_rbac.main(["--url", API, "--salida", str(salida)], http=http_minimo())

    texto = capsys.readouterr().out + salida.read_text(encoding="utf-8")
    assert codigo == 1
    assert not [s for s in SECRETOS if s in texto]


def test_la_evidencia_jsonl_tiene_una_linea_por_celda(variables, tmp_path, capsys):
    from ops import matriz_rbac

    salida = tmp_path / "sub" / "m.jsonl"

    matriz_rbac.main(["--url", API, "--salida", str(salida)], http=http_minimo())

    registros = [json.loads(linea) for linea in salida.read_text(encoding="utf-8").splitlines()]
    assert len(registros) == 84
    assert set(registros[0]) == {
        "metodo", "ruta", "identidad", "esperado_estado", "esperado_codigo",
        "estado", "codigo", "request_id", "ok",
    }
    assert {r["identidad"] for r in registros} == {"anonimo", "medico", "administrador"}


def test_por_defecto_la_evidencia_va_a_una_carpeta_ignorada_por_git():
    from ops.matriz_rbac import CARPETA_DE_EVIDENCIAS, REPO_ROOT

    ignorado = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert CARPETA_DE_EVIDENCIAS == REPO_ROOT / "reports" / "fase17"
    assert "reports/fase17/" in ignorado
