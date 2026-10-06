"""`python -m ops.sondas_seguridad` (Fase 17): las sondas contra la aplicación real, sin escribir nada.

Sin red: la capa HTTP del guion se desvía a la aplicación completa sobre el
PostgreSQL embebido, y el inicio de sesión en Supabase devuelve un token firmado
en la sesión. El emisor del guion es el de la aplicación del test, así que un
token HS256 o `none` se rechaza por su algoritmo, no por su emisor.

Se comprueba, antes de ejecutarlo en producción:

- que todas las sondas pasan contra el código real;
- que **ninguna tabla gana ni pierde una fila**;
- que cada sonda es **vinculante**: si la API respondiera otra cosa justo en
  esa sonda (un 500, o la respuesta correcta con un defecto propio del caso:
  sin `WWW-Authenticate`, con una traza, con CORS abierto, repitiendo el valor
  recibido o con resultados de búsqueda), el guion falla en esa sonda y solo en
  esa.
"""

import base64
import json
from urllib.parse import urlsplit

import pytest

from api.auth_claves import ADMIN_ID, MEDICO_ID, URL_SUPABASE_FICTICIA

from .conftest import filas

API = "https://gynfem-api.example.onrender.com"
SUPABASE = URL_SUPABASE_FICTICIA
CORREO = "admin.verificacion@example.com"
CONTRASENA = "Contrasena-De-Verificacion-2026"
CORREO_MEDICO = "medica.verificacion@example.com"
CONTRASENA_MEDICO = "Contrasena-De-La-Medica-2026"
PUBLICABLE = "sb_publishable_ficticia"
#: Peticiones del guion antes de la primera sonda: salud, y por cada cuenta, inicio de sesión y `/me`.
PREPARACION = 5


def _jwt_ficticio() -> str:
    b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{b64({'alg': 'ES256'})}.{b64({'sub': 'x'})}.firma"


def _sondas_sin_red():
    from ops.sondas_seguridad import Contexto, construir_sondas

    cabecera = {"Authorization": f"Bearer {_jwt_ficticio()}"}
    return construir_sondas(Contexto(base=API + "/api/v1", supabase_url=SUPABASE, medico=cabecera, admin=cabecera))


SONDAS = [(i, s.caso, s.nombre) for i, s in enumerate(_sondas_sin_red())]


@pytest.fixture
def http_de(cliente_bd, emisor):
    """La función HTTP del guion sobre la aplicación con base. `alterar(indice, respuesta)` puede falsear
    la respuesta de la sonda número `indice` **después** de que la aplicación la haya atendido."""
    from ops.sondas_seguridad import Respuesta

    cliente = cliente_bd(rol=None)

    def _construir(alterar=None):
        cuenta = {"n": 0}

        def http(metodo, url, cuerpo=None, cabeceras=None):
            if url.startswith(SUPABASE):
                es_medico = json.loads(cuerpo)["email"] == CORREO_MEDICO
                token = emisor.token(MEDICO_ID if es_medico else ADMIN_ID)
                cuenta["n"] += 1
                return Respuesta(200, {}, json.dumps({"access_token": token}))
            partes = urlsplit(url)
            ruta = partes.path + (f"?{partes.query}" if partes.query else "")
            r = cliente.request(metodo, ruta, content=cuerpo, headers=cabeceras or {})
            respuesta = Respuesta(r.status_code, {k.lower(): v for k, v in r.headers.items()}, r.text)
            indice = cuenta["n"] - PREPARACION
            cuenta["n"] += 1
            if alterar is not None and indice >= 0:
                respuesta = alterar(indice, respuesta)
            return respuesta

        return http

    return _construir


@pytest.fixture
def ejecutar(monkeypatch, capsys, tmp_path):
    from ops import sondas_seguridad

    def _ejecutar(http):
        for clave, valor in {
            "GYNFEM_SUPABASE_URL": SUPABASE,
            "GYNFEM_SUPABASE_PUBLISHABLE_KEY": PUBLICABLE,
            "GYNFEM_SMOKE_ADMIN_EMAIL": CORREO,
            "GYNFEM_SMOKE_ADMIN_PASSWORD": CONTRASENA,
            "GYNFEM_SMOKE_MEDICO_EMAIL": CORREO_MEDICO,
            "GYNFEM_SMOKE_MEDICO_PASSWORD": CONTRASENA_MEDICO,
        }.items():
            monkeypatch.setenv(clave, valor)
        salida = tmp_path / "sondas.jsonl"
        codigo = sondas_seguridad.main(["--url", API, "--salida", str(salida)], http=http)
        registros = [json.loads(linea) for linea in salida.read_text(encoding="utf-8").splitlines()] \
            if salida.exists() else []
        return codigo, capsys.readouterr(), registros

    return _ejecutar


def conteos(url: str) -> dict[str, int]:
    """Filas de **todas** las tablas fuera de los esquemas del sistema: también las futuras."""
    tablas = filas(url, "SELECT schemaname, tablename FROM pg_tables "
                        "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') ORDER BY 1, 2")
    assert ("gynfem", "audit_log") in tablas and ("auth", "users") in tablas
    return {f"{s}.{t}": filas(url, f'SELECT count(*) FROM "{s}"."{t}"')[0][0] for s, t in tablas}


def test_las_sondas_pasan_contra_la_aplicacion_real_y_no_escriben_nada(ejecutar, http_de, base_migrada,
                                                                        admin_falso):
    antes = conteos(base_migrada)

    codigo, salida, registros = ejecutar(http_de())

    assert codigo == 0, salida.out
    assert "FALLA" not in salida.out
    assert len(registros) == len(SONDAS) and all(r["ok"] for r in registros)
    # Solo el preflight rechazado, que Starlette responde en texto plano, no es JSON: los errores
    # uniformes y los 200 de la API nunca dejan cabeceras ni cuerpo en la evidencia.
    assert [r["nombre"] for r in registros if r["diagnostico"] is not None] == ["S12 preflight desde un origen ajeno"]
    assert conteos(base_migrada) == antes
    assert admin_falso.creados == [] and admin_falso.borrados == []


def test_la_salida_no_contiene_credenciales_ni_tokens(ejecutar, http_de, base_migrada):
    codigo, salida, registros = ejecutar(http_de())

    texto = salida.out + salida.err + json.dumps(registros)
    secretos = (CONTRASENA, CORREO, CONTRASENA_MEDICO, CORREO_MEDICO, PUBLICABLE, "eyJ", "Bearer")
    assert codigo == 0
    assert not [s for s in secretos if s in texto]


# --- S9: los comodines se tratan como literales -------------------------------------------------
#
# Con la base vacía, «búsqueda sin resultados» pasaría aunque los comodines no se escaparan.
# Aquí se siembra (solo en la base embebida) una paciente ficticia cuyo nombre sí coincide con
# `zq%x%w` y `zq_x_w` **si** `%` y `_` actuaran como comodines.

COMODINES = {"S9 búsqueda literal: comodín %", "S9 búsqueda literal: comodín _"}


@pytest.fixture
def paciente_que_casaria_con_comodines(cliente_bd):
    respuesta = cliente_bd(rol="medico").post("/api/v1/patients", json={
        "document_type": "PASAPORTE", "document_number": "FICTICIOF17L",
        "given_names": "Zqaxaw", "family_names": "Sintetica Fdiecisiete",
    })
    assert respuesta.status_code == 201


def test_con_una_paciente_que_casaria_los_comodines_siguen_sin_resultados(
        paciente_que_casaria_con_comodines, ejecutar, http_de, base_migrada):
    codigo, salida, registros = ejecutar(http_de())

    assert codigo == 0, salida.out
    assert {r["nombre"] for r in registros if r["ok"]} >= COMODINES


def test_sin_escapar_los_comodines_las_sondas_lo_detectan(
        paciente_que_casaria_con_comodines, ejecutar, http_de, base_migrada, monkeypatch):
    """Mutación de la aplicación: `_escapar_like` deja pasar `%` y `_` sin escapar."""
    from app.repositories import patients

    monkeypatch.setattr(patients, "_escapar_like", lambda texto: texto)

    codigo, salida, registros = ejecutar(http_de())

    assert codigo == 1
    assert {r["nombre"] for r in registros if not r["ok"]} == COMODINES


# --- Cada sonda es vinculante ------------------------------------------------------------------


def _error_500(respuesta):
    from ops.sondas_seguridad import Respuesta

    cuerpo = {"error": {"code": "internal_error", "message": "Error interno.", "request_id": "r"}}
    return Respuesta(500, {"x-request-id": "r"}, json.dumps(cuerpo))


def _con_cuerpo(respuesta, cambiar):
    from ops.sondas_seguridad import Respuesta

    return Respuesta(respuesta.estado, respuesta.cabeceras, json.dumps(cambiar(json.loads(respuesta.texto))))


def _sin_www_authenticate(respuesta):
    from ops.sondas_seguridad import Respuesta

    cabeceras = {k: v for k, v in respuesta.cabeceras.items() if k != "www-authenticate"}
    return Respuesta(respuesta.estado, cabeceras, respuesta.texto)


def _con_traza(respuesta):
    def cambiar(cuerpo):
        cuerpo["error"]["message"] += ' File "/opt/render/project/src/app/main.py", line 1'
        return cuerpo

    return _con_cuerpo(respuesta, cambiar)


def _cors_abierto(respuesta):
    from ops.sondas_seguridad import ORIGEN_AJENO, Respuesta

    return Respuesta(respuesta.estado, {**respuesta.cabeceras, "access-control-allow-origin": ORIGEN_AJENO},
                     respuesta.texto)


def _repite_lo_recibido(respuesta):
    def cambiar(cuerpo):
        for detalle in cuerpo["error"].get("details") or [{}]:
            detalle["input"] = "1 OR 1=1"
        cuerpo["error"].setdefault("details", [{"input": "1 OR 1=1"}])
        return cuerpo

    return _con_cuerpo(respuesta, cambiar)


def _con_resultados(respuesta):
    return _con_cuerpo(respuesta, lambda c: {**c, "items": [{"id": "x"}]})


def _repite_el_id(respuesta):
    def cambiar(cuerpo):
        cuerpo["error"]["message"] += " 00000000-0000-4000-8000-000000000000"
        return cuerpo

    return _con_cuerpo(respuesta, cambiar)


#: El defecto propio de cada caso: la respuesta casi correcta que la sonda debe rechazar.
DEFECTO_DEL_CASO = {
    "S1": _sin_www_authenticate,
    "S2": _sin_www_authenticate,
    "S3": _sin_www_authenticate,
    "S5": _con_traza,
    "S6": _repite_el_id,
    "S8": _repite_lo_recibido,
    "S9": None,  # depende de la sonda: resultados en la búsqueda, traza en los errores
    "S11": _con_traza,
    "S12": _cors_abierto,
}


def _verificar_vinculante(ejecutar, http_de, indice, falseo):
    codigo, salida, registros = ejecutar(http_de(lambda i, r: falseo(r) if i == indice else r))

    assert codigo == 1, salida.out
    fallidas = [n for n, r in enumerate(registros) if not r["ok"]]
    assert fallidas == [indice], salida.out


@pytest.mark.parametrize(("indice", "caso", "nombre"), SONDAS, ids=[n for _, _, n in SONDAS])
def test_cada_sonda_rechaza_un_500(indice, caso, nombre, ejecutar, http_de, base_migrada):
    _verificar_vinculante(ejecutar, http_de, indice, _error_500)


@pytest.mark.parametrize(("indice", "caso", "nombre"), SONDAS, ids=[n for _, _, n in SONDAS])
def test_cada_sonda_rechaza_el_defecto_de_su_caso(indice, caso, nombre, ejecutar, http_de, base_migrada):
    defecto = DEFECTO_DEL_CASO[caso]
    if caso == "S9":
        defecto = _con_resultados if "búsqueda" in nombre else _con_traza
    _verificar_vinculante(ejecutar, http_de, indice, defecto)
