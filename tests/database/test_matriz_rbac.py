"""`python -m ops.matriz_rbac` (Fase 17): la matriz contra la aplicación real, sin escribir nada.

Sin red: la capa HTTP del guion se desvía a la aplicación completa sobre el
PostgreSQL embebido, y el inicio de sesión en Supabase devuelve un token firmado
en la sesión. Así se comprueba lo que importa antes de ejecutarla en
producción: que las 84 celdas pasan contra el código real y que **ninguna tabla
gana ni pierde una fila**, tampoco la auditoría ni el stub de `auth.users`.

Cada celda es vinculante: si la API respondiera otra cosa en esa celda, el
guion falla (`test_cada_celda_es_vinculante`).

La aplicación del test corre en `development` (el embebido no ofrece TLS, que
`production` exige): la documentación interactiva se falsea a 404, que es lo que
la matriz espera de producción.
"""

import json
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


@pytest.fixture
def http_de(cliente_bd, emisor):
    """La función HTTP del guion sobre la aplicación con base; `alterar(metodo, ruta, cabeceras, estado, datos)`
    puede falsear una respuesta **después** de que la aplicación la haya atendido."""
    cliente = cliente_bd(rol=None)

    def _construir(alterar=None):
        def http(metodo, url, cuerpo=None, cabeceras=None):
            if url.startswith(SUPABASE):
                es_medico = (cuerpo or {}).get("email") == CORREO_MEDICO
                usuario = MEDICO_ID if es_medico else ADMIN_ID
                return 200, {"access_token": emisor.token(usuario), "token_type": "bearer"}, 0.01
            partes = urlsplit(url)
            if partes.path in DOCUMENTACION:
                estado, datos = 404, {"error": {"code": "not_found", "message": "-", "request_id": "r"}}
            else:
                ruta = partes.path + (f"?{partes.query}" if partes.query else "")
                respuesta = cliente.request(metodo, ruta, json=cuerpo, headers=cabeceras or {})
                estado, datos = respuesta.status_code, (respuesta.json() if respuesta.content else None)
            if alterar is not None:
                estado, datos = alterar(metodo, partes.path, cabeceras or {}, estado, datos)
            return estado, datos, 0.01

        return http

    return _construir


@pytest.fixture
def ejecutar(monkeypatch, capsys, tmp_path):
    from ops import matriz_rbac

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
        salida = tmp_path / "matriz.jsonl"
        codigo = matriz_rbac.main(["--url", API, "--salida", str(salida)], http=http)
        registros = [json.loads(linea) for linea in salida.read_text(encoding="utf-8").splitlines()] \
            if salida.exists() else []
        return codigo, capsys.readouterr(), registros

    return _ejecutar


def conteos(url: str) -> dict[str, int]:
    """Filas de **todas** las tablas fuera de los esquemas del sistema (`gynfem`, `auth`, control
    del runner…): también las futuras."""
    tablas = filas(url, "SELECT schemaname, tablename FROM pg_tables "
                        "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') ORDER BY 1, 2")
    assert {"audit_log", "patients", "user_profiles", "system_settings"} <= {t for s, t in tablas if s == "gynfem"}
    assert ("auth", "users") in tablas
    return {f"{s}.{t}": filas(url, f'SELECT count(*) FROM "{s}"."{t}"')[0][0] for s, t in tablas}


def test_la_matriz_pasa_contra_la_aplicacion_real_y_no_escribe_nada(ejecutar, http_de, base_migrada, admin_falso):
    antes = conteos(base_migrada)

    codigo, salida, registros = ejecutar(http_de())

    assert codigo == 0, salida.out
    assert "FALLA" not in salida.out
    assert len(registros) == 84 and all(r["ok"] for r in registros)
    assert conteos(base_migrada) == antes
    assert admin_falso.creados == [] and admin_falso.borrados == []


def test_la_salida_no_contiene_credenciales_ni_tokens(ejecutar, http_de, base_migrada):
    codigo, salida, registros = ejecutar(http_de())

    texto = salida.out + salida.err + json.dumps(registros)
    assert codigo == 0
    assert not [s for s in SECRETOS if s in texto]


def _celdas():
    from ops.matriz_rbac import IDENTIDADES, leer_matriz

    return [(f.metodo, f.ruta, i) for f in leer_matriz() for i in IDENTIDADES]


#: Respuestas que falsean una celda: cualquiera de ellas debe hacer fallar el guion.
FALSEOS = {
    "403 en vez de lo esperado": (403, {"error": {"code": "forbidden", "message": "-", "request_id": "r"}}),
    "200 en vez de lo esperado": (200, {}),
    "500": (500, {"error": {"code": "internal_error", "message": "-", "request_id": "r"}}),
}


@pytest.mark.parametrize("celda", _celdas(), ids=lambda c: f"{c[0]} {c[1]} {c[2]}")
def test_cada_celda_es_vinculante(celda, ejecutar, http_de, base_migrada):
    """Un falseo por celda: si la API respondiera otra cosa justo ahí, el guion lo detecta."""
    import re

    from ops.matriz_rbac import esperado_de, leer_matriz

    metodo, ruta, identidad = celda
    fila = next(f for f in leer_matriz() if (f.metodo, f.ruta) == (metodo, ruta))
    esperado = esperado_de(fila, identidad)
    falso = next(r for r in FALSEOS.values() if r[0] != esperado[0])
    patron = re.compile("^" + re.sub(r"\\\{\w+\\\}", "[^/]+", re.escape(ruta)) + "$")
    vistos = {}

    def alterar(m, path, cabeceras, estado, datos):
        token = cabeceras.get("Authorization", "")
        if token and token not in vistos:
            # La primera petición de cada token es la comprobación de identidad del guion (GET /me):
            # de ella se aprende quién es, y se deja pasar sin falsear.
            vistos[token] = datos["role"]
            return estado, datos
        quien = vistos[token] if token else "anonimo"
        # Antes de comprobar las dos cuentas, el guion solo despierta el servicio (GET /health):
        # falsearlo lo detendría sin llegar a las celdas (eso lo prueban los tests unitarios).
        celdas_en_curso = len(vistos) == 2
        if celdas_en_curso and m == metodo and patron.match(path) and quien == identidad:
            return falso
        return estado, datos

    codigo, salida, registros = ejecutar(http_de(alterar))

    assert codigo == 1
    fallidas = [(r["metodo"], r["ruta"], r["identidad"]) for r in registros if not r["ok"]]
    assert fallidas == [celda]
