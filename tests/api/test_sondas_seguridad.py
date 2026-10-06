"""`python -m ops.sondas_seguridad` (Fase 17): la lógica del guion, sin red ni base.

Aquí se prueba que hay sondas para cada caso aprobado (S1, S2, S3, S5, S6, S8,
S9, S11 y S12), que los tokens manipulados se construyen bien en local, que el
detector de fugas reconoce trazas y rutas, y cuándo se detiene el guion sin
enviar ninguna sonda. Que las sondas **pasan contra la aplicación real, no
escriben nada y cada una es vinculante** se prueba contra la base embebida en
`tests/database/test_sondas_seguridad.py`.
"""

import base64
import json

import pytest

from .auth_claves import MEDICO_ID

API = "https://gynfem-api.example.onrender.com"
SUPABASE = "https://abcdefghijklmnopqrst.supabase.co"
CORREO = "admin.verificacion@example.com"
CONTRASENA = "Contrasena-De-Verificacion-2026"
CORREO_MEDICO = "medica.verificacion@example.com"
CONTRASENA_MEDICO = "Contrasena-De-La-Medica-2026"
PUBLICABLE = "sb_publishable_ficticia"
CASOS = {"S1", "S2", "S3", "S5", "S6", "S8", "S9", "S11", "S12"}


def _segmento(token: str, i: int) -> dict:
    parte = token.split(".")[i]
    return json.loads(base64.urlsafe_b64decode(parte + "=" * (-len(parte) % 4)))


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


@pytest.fixture
def http_minimo(emisor):
    """Responde a la salud, al inicio de sesión y a `/me`; lo demás, estado 0. Registra lo que se pide."""
    from app import __version__
    from ops.sondas_seguridad import Respuesta

    def _construir(version=None, login=200, roles=("administrador", "medico")):
        llamadas = []
        tokens = {CORREO: emisor.token(MEDICO_ID) + "", CORREO_MEDICO: emisor.token(MEDICO_ID, jti="m")}
        rol_de = {f"Bearer {tokens[CORREO]}": roles[0], f"Bearer {tokens[CORREO_MEDICO]}": roles[1]}

        def http(metodo, url, cuerpo=None, cabeceras=None):
            llamadas.append((metodo, url))
            if url.startswith(SUPABASE):
                if login != 200:
                    return Respuesta(login, {}, '{"error":"invalid_grant"}')
                correo = json.loads(cuerpo)["email"]
                return Respuesta(200, {}, json.dumps({"access_token": tokens[correo]}))
            if metodo == "GET" and url.endswith("/api/v1/health"):
                return Respuesta(200, {}, json.dumps({"status": "ok", "version": version or __version__}))
            autorizacion = (cabeceras or {}).get("Authorization")
            if url.endswith("/api/v1/me") and autorizacion in rol_de:
                return Respuesta(200, {}, json.dumps({"id": "x", "role": rol_de[autorizacion]}))
            return Respuesta(0, {}, "")

        http.llamadas = llamadas
        http.tokens = tokens
        return http

    return _construir


def sondas_enviadas(http) -> list:
    return [(m, u) for m, u in http.llamadas
            if u.startswith(API) and not u.endswith(("/api/v1/health", "/api/v1/me"))]


def contexto(emisor):
    from ops.sondas_seguridad import Contexto

    return Contexto(
        base=API + "/api/v1", supabase_url=SUPABASE,
        medico={"Authorization": f"Bearer {emisor.token(MEDICO_ID)}"},
        admin={"Authorization": f"Bearer {emisor.token(MEDICO_ID, jti='a')}"},
    )


# --- Las sondas ----------------------------------------------------------------------------


def test_hay_sondas_para_cada_caso_aprobado_y_ningun_otro(emisor):
    from ops.sondas_seguridad import construir_sondas

    sondas = construir_sondas(contexto(emisor))

    assert {s.caso for s in sondas} == CASOS
    assert len({s.nombre for s in sondas}) == len(sondas)


def test_las_rutas_con_id_usan_uuids_nuevos_en_cada_corrida(emisor):
    from ops.sondas_seguridad import construir_sondas

    a = {s.ruta for s in construir_sondas(contexto(emisor)) if s.caso == "S6"}
    b = {s.ruta for s in construir_sondas(contexto(emisor)) if s.caso == "S6"}

    assert a and a.isdisjoint(b)


def test_ninguna_sonda_lleva_correos_ni_documentos(emisor):
    from ops.sondas_seguridad import construir_sondas

    cuerpos = b"".join(s.cuerpo or b"" for s in construir_sondas(contexto(emisor)))

    assert b"@" not in cuerpos
    assert b"document_number" not in cuerpos


# --- Tokens manipulados, construidos en local ------------------------------------------------


def test_token_alterado_cambia_la_carga_y_conserva_la_firma(emisor):
    from ops.sondas_seguridad import token_alterado

    original = emisor.token(MEDICO_ID)
    alterado = token_alterado(original)

    assert alterado.split(".")[0] == original.split(".")[0]
    assert alterado.split(".")[2] == original.split(".")[2]
    assert _segmento(alterado, 1)["sub"] != _segmento(original, 1)["sub"]


def test_token_con_firma_truncada(emisor):
    from ops.sondas_seguridad import token_firma_truncada

    original = emisor.token(MEDICO_ID)
    truncado = token_firma_truncada(original)

    assert truncado.split(".")[:2] == original.split(".")[:2]
    assert 0 < len(truncado.split(".")[2]) < len(original.split(".")[2])


def test_token_hs256_firmado_con_una_clave_inventada():
    from ops.sondas_seguridad import token_hs256

    token = token_hs256(SUPABASE)

    assert _segmento(token, 0)["alg"] == "HS256"
    carga = _segmento(token, 1)
    assert carga["iss"] == f"{SUPABASE}/auth/v1" and carga["aud"] == "authenticated"
    assert len(token.split(".")[2]) > 0


def test_token_alg_none_sin_firma():
    from ops.sondas_seguridad import token_alg_none

    token = token_alg_none(SUPABASE)

    assert _segmento(token, 0)["alg"] == "none"
    assert token.split(".")[2] == ""


# --- Detector de fugas ---------------------------------------------------------------------


@pytest.mark.parametrize("texto", [
    'Traceback (most recent call last):', 'File "/opt/render/project/src/app/x.py", line 3',
    "/usr/lib/python3.12/site-packages/fastapi", "psycopg.errors.UndefinedTable", "app/services/patients.py",
])
def test_el_detector_reconoce_trazas_y_rutas(texto):
    from ops.sondas_seguridad import tiene_fuga

    assert tiene_fuga(texto)


def test_un_error_uniforme_no_es_una_fuga():
    from ops.sondas_seguridad import tiene_fuga

    assert not tiene_fuga(json.dumps({"error": {"code": "not_found", "message": "Recurso no encontrado.",
                                                "request_id": "0f1e2d3c-4b5a-4968-8776-655443322110"}}))


# --- Se detiene antes de enviar ninguna sonda -------------------------------------------------


def test_sin_variables_no_arranca(monkeypatch, http_minimo, capsys):
    from ops import sondas_seguridad

    monkeypatch.delenv("GYNFEM_SUPABASE_URL", raising=False)
    http = http_minimo()

    assert sondas_seguridad.main(["--url", API], http=http) == 1
    assert "GYNFEM_SUPABASE_URL" in capsys.readouterr().err
    assert http.llamadas == []


def test_la_url_debe_ser_https(variables, http_minimo):
    from ops import sondas_seguridad

    http = http_minimo()

    assert sondas_seguridad.main(["--url", "http://gynfem-api.example.onrender.com"], http=http) == 1
    assert http.llamadas == []


@pytest.mark.parametrize("ajuste", [
    {"version": "0.0.1"}, {"login": 400}, {"login": 0},
    {"roles": ("medico", "medico")}, {"roles": ("administrador", "administrador")},
])
def test_se_detiene_sin_enviar_sondas(ajuste, variables, http_minimo, tmp_path, capsys):
    from ops import sondas_seguridad

    http = http_minimo(**ajuste)

    codigo = sondas_seguridad.main(["--url", API, "--salida", str(tmp_path / "s.jsonl")], http=http)

    assert codigo == 1
    assert "DETENIDO" in capsys.readouterr().out
    assert sondas_enviadas(http) == []


def test_la_salida_no_contiene_credenciales_ni_tokens(variables, http_minimo, tmp_path, capsys):
    """Una API que responde 0 a todo: falla cada sonda, y aun así nada secreto sale."""
    from ops import sondas_seguridad

    http = http_minimo()
    salida = tmp_path / "s.jsonl"

    codigo = sondas_seguridad.main(["--url", API, "--salida", str(salida)], http=http)

    texto = capsys.readouterr().out + salida.read_text(encoding="utf-8")
    secretos = (CONTRASENA, CORREO, CONTRASENA_MEDICO, CORREO_MEDICO, PUBLICABLE, "eyJ", "Bearer",
                *http.tokens.values())
    assert codigo == 1
    assert not [s for s in secretos if s in texto]


def test_la_evidencia_jsonl_tiene_una_linea_por_sonda(variables, http_minimo, tmp_path, capsys):
    from ops import sondas_seguridad

    salida = tmp_path / "sub" / "s.jsonl"

    sondas_seguridad.main(["--url", API, "--salida", str(salida)], http=http_minimo())

    registros = [json.loads(linea) for linea in salida.read_text(encoding="utf-8").splitlines()]
    assert {r["caso"] for r in registros} == CASOS
    assert set(registros[0]) == {"caso", "nombre", "metodo", "estado", "codigo", "request_id", "ok", "diagnostico"}
    # La única que acierta: la salud sin CORS ajeno, que el doble sí responde.
    assert [r["nombre"] for r in registros if r["ok"]] == ["S12 GET desde un origen ajeno"]


def test_por_defecto_la_evidencia_va_a_la_carpeta_ignorada():
    from ops.sondas_seguridad import CARPETA_DE_EVIDENCIAS, REPO_ROOT

    assert CARPETA_DE_EVIDENCIAS == REPO_ROOT / "reports" / "fase17"


# --- Diagnóstico de respuestas que no son de la API ------------------------------------------
#
# Un 403 sin el formato de la API (S8 y S9 en producción, 2026-10-06) no dice quién lo emitió.
# Solo de una respuesta cuyo cuerpo **no es JSON** se guardan `server`, `cf-ray`, `content-type`
# y los primeros 80 caracteres del cuerpo. Un JSON (un error uniforme o un 200 de la API, que
# puede llevar datos) nunca se guarda.

HTML_DEL_BORDE = "<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare</title></head>" + "x" * 200


def test_de_una_respuesta_que_no_es_json_se_guarda_el_diagnostico():
    from ops.sondas_seguridad import Respuesta, diagnostico

    r = Respuesta(403, {"server": "cloudflare", "cf-ray": "8c1f2e3d4c5b6a79-SJC",
                        "content-type": "text/html; charset=UTF-8", "set-cookie": "__cf_bm=abc"}, HTML_DEL_BORDE)

    d = diagnostico(r)

    assert d == {"server": "cloudflare", "cf-ray": "8c1f2e3d4c5b6a79-SJC",
                 "content-type": "text/html; charset=UTF-8", "cuerpo": HTML_DEL_BORDE[:80]}


def test_sin_esas_cabeceras_quedan_en_null():
    from ops.sondas_seguridad import Respuesta, diagnostico

    assert diagnostico(Respuesta(403, {}, "Forbidden")) == {
        "server": None, "cf-ray": None, "content-type": None, "cuerpo": "Forbidden"}


@pytest.mark.parametrize("texto", [
    json.dumps({"error": {"code": "forbidden", "message": "Sin permiso.", "request_id": "r"}}),
    json.dumps({"items": [{"given_names": "Paciente Ficticia"}], "has_more": False}),
    json.dumps({"status": "ok"}),
])
def test_de_una_respuesta_json_no_se_guarda_nada(texto):
    from ops.sondas_seguridad import Respuesta, diagnostico

    assert diagnostico(Respuesta(403, {"server": "uvicorn", "content-type": "application/json"}, texto)) is None


def test_el_fragmento_tacha_correos_tokens_y_saltos_de_linea():
    from ops.sondas_seguridad import Respuesta, diagnostico

    texto = "a\nusuario@example.com eyJhbGciOiJFUzI1NiJ9.eyJzdWIiOiJ4In0.firma fin"

    cuerpo = diagnostico(Respuesta(403, {}, texto))["cuerpo"]

    assert "@" not in cuerpo and "eyJ" not in cuerpo and "\n" not in cuerpo
    assert cuerpo.startswith("a ") and cuerpo.endswith("fin")


def test_el_registro_de_una_sonda_lleva_el_diagnostico_solo_si_no_es_json(variables, emisor, tmp_path, capsys):
    from ops import sondas_seguridad
    from ops.sondas_seguridad import Respuesta

    base = sondas_seguridad.construir_sondas(contexto(emisor))
    nombre_html, nombre_json = base[0].nombre, base[1].nombre

    def http(metodo, url, cuerpo=None, cabeceras=None):
        from app import __version__

        if url.startswith(SUPABASE):
            return Respuesta(200, {}, json.dumps({"access_token": emisor.token(MEDICO_ID, jti=json.loads(cuerpo)["email"])}))
        if url.endswith("/health") and metodo == "GET":
            return Respuesta(200, {}, json.dumps({"status": "ok", "version": __version__}))
        autorizacion = (cabeceras or {}).get("Authorization", "")
        if url.endswith("/me") and autorizacion.count(".") == 2 and not http.preparado:
            # Comprobación de identidad del guion: el `jti` de cada token es el correo de su cuenta.
            correo = _segmento(autorizacion.removeprefix("Bearer "), 1)["jti"]
            http.preparado = correo == CORREO
            return Respuesta(200, {}, json.dumps({"role": "medico" if correo == CORREO_MEDICO else "administrador"}))
        if url.endswith("/me") and not autorizacion:
            # La primera sonda (S1 sin Authorization): HTML de un intermediario.
            return Respuesta(403, {"server": "cloudflare", "content-type": "text/html"}, HTML_DEL_BORDE)
        # El resto, como la segunda (S1 esquema Basic): un error en el formato de la API.
        return Respuesta(403, {"server": "uvicorn"}, json.dumps({"error": {"code": "forbidden"}}))

    http.preparado = False

    salida = tmp_path / "s.jsonl"
    sondas_seguridad.main(["--url", API, "--salida", str(salida)], http=http)

    registros = {r["nombre"]: r for r in map(json.loads, salida.read_text(encoding="utf-8").splitlines())}
    assert registros[nombre_html]["diagnostico"]["server"] == "cloudflare"
    assert registros[nombre_html]["diagnostico"]["cuerpo"] == HTML_DEL_BORDE[:80]
    assert registros[nombre_json]["diagnostico"] is None


# --- Repetir solo algunas sondas -----------------------------------------------------------------


def test_solo_envia_las_sondas_nombradas(variables, http_minimo, tmp_path, capsys):
    from ops import sondas_seguridad

    http = http_minimo()
    salida = tmp_path / "s.jsonl"
    elegidas = ["S8 id no UUID: SQL", "S9 nombre con SQL rechazado"]

    sondas_seguridad.main(["--url", API, "--salida", str(salida), "--solo", elegidas[0], "--solo", elegidas[1]],
                          http=http)

    registros = [json.loads(linea) for linea in salida.read_text(encoding="utf-8").splitlines()]
    assert [r["nombre"] for r in registros] == elegidas
    assert len(sondas_enviadas(http)) == 2


def test_un_nombre_desconocido_en_solo_detiene_sin_enviar_sondas(variables, http_minimo, tmp_path, capsys):
    from ops import sondas_seguridad

    http = http_minimo()

    codigo = sondas_seguridad.main(["--url", API, "--salida", str(tmp_path / "s.jsonl"), "--solo", "S99 no existe"],
                                   http=http)

    assert codigo == 1
    assert "DETENIDO" in capsys.readouterr().out
    assert sondas_enviadas(http) == []
