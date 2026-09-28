"""Verificación repetible de la API desplegada (Fase 12, decisión D).

    .venv\\Scripts\\python.exe -m ops.verificar_despliegue --url https://<servicio>.onrender.com --env-file .env

Comprueba salud, documentación cerrada, autenticación, autorización, las tres
clases de predicción, el formato de los errores y la latencia. **No crea datos
clínicos**: solo usa al administrador, que puede predecir y consultar usuarios,
y a quien se le niegan los pacientes. Se puede ejecutar tras cada despliegue,
también con datos reales en la base.

Las credenciales se leen por **nombre** de `--env-file` (o del entorno): la URL
del proyecto, la clave publicable (para iniciar sesión, como hará el frontend) y
el correo y la contraseña del administrador de verificación. Nunca se imprime un
token, una contraseña, un correo ni una clave: solo estados y códigos. Sale con
código 1 si alguna comprobación falla.
"""

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

from app import __version__

#: Variables que solo usa este guion (la URL del proyecto es de la aplicación).
VARIABLES_DEL_GUION = (
    "GYNFEM_SUPABASE_PUBLISHABLE_KEY",
    "GYNFEM_SMOKE_ADMIN_EMAIL",
    "GYNFEM_SMOKE_ADMIN_PASSWORD",
)
NECESARIAS = ("GYNFEM_SUPABASE_URL", *VARIABLES_DEL_GUION)
PREFIJO = "/api/v1"
#: Un despertar del plan Free tarda alrededor de un minuto (documentación de Render).
TIMEOUT_S = 120

ENTRADA_NORMAL = {"age_years": 28, "temperature_c": 36.8, "heart_rate_bpm": 80, "systolic_bp_mmhg": 118,
                  "diastolic_bp_mmhg": 76, "bmi_kg_m2": 22.5, "hba1c_percent": 5.2, "fasting_glucose_mg_dl": 85}
#: IMC 32 y HbA1c 7.2 %: fuera del rango de entrenamiento (docs/API_SPEC.md §3.2).
ENTRADA_EXTRAPOLADA = {**ENTRADA_NORMAL, "age_years": 34, "temperature_c": 37.0, "heart_rate_bpm": 88,
                       "systolic_bp_mmhg": 132, "diastolic_bp_mmhg": 86, "bmi_kg_m2": 32.0,
                       "hba1c_percent": 7.2, "fasting_glucose_mg_dl": 110}
#: 98.6 °F escritos en el campo en °C: imposible, 422 sin predecir.
ENTRADA_IMPOSIBLE = {**ENTRADA_NORMAL, "temperature_c": 98.6}
FUGAS_EN_ERRORES = ("Traceback", 'File "', "/opt/render", "/app/", "site-packages")

Http = Callable[..., tuple[int, dict | None, float]]


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_SinRedirecciones)


def http_real(metodo: str, url: str, cuerpo: dict | None = None, cabeceras: dict | None = None):
    """(estado, JSON o None, segundos). No sigue redirecciones: el token no sale del servicio.

    Una conexión rechazada o un tiempo agotado devuelve el estado 0: la comprobación
    falla con su nombre en el informe, sin cortarlo con una traza.
    """
    datos = None if cuerpo is None else json.dumps(cuerpo).encode()
    peticion = urllib.request.Request(url, data=datos, method=metodo,
                                      headers={"Content-Type": "application/json", **(cabeceras or {})})
    inicio = time.perf_counter()
    try:
        with _opener.open(peticion, timeout=TIMEOUT_S) as respuesta:
            estado, contenido = respuesta.status, respuesta.read()
    except urllib.error.HTTPError as error:
        estado, contenido = error.code, error.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, None, time.perf_counter() - inicio
    segundos = time.perf_counter() - inicio
    try:
        return estado, (json.loads(contenido) if contenido else None), segundos
    except ValueError:
        return estado, None, segundos


class Informe:
    def __init__(self) -> None:
        self.fallos = 0

    def comprobar(self, nombre: str, correcto: bool, detalle: str) -> bool:
        if not correcto:
            self.fallos += 1
        print(f"{'OK   ' if correcto else 'FALLA'} {nombre} — {detalle}", flush=True)
        return correcto


def _codigo(datos: dict | None) -> str:
    error = (datos or {}).get("error")
    return error.get("code", "?") if isinstance(error, dict) else "-"


def _leer_variables(env_file: Path | None) -> dict[str, str]:
    fuente = dotenv_values(env_file) if env_file is not None else os.environ
    return {nombre: fuente.get(nombre) or "" for nombre in NECESARIAS}


def _url_valida(url: str) -> bool:
    partes = urlsplit(url)
    return partes.scheme == "https" and bool(partes.hostname) and partes.path in ("", "/") and not partes.query


def verificar(api: str, variables: dict[str, str], http: Http, repeticiones: int) -> int:
    informe = Informe()
    base = api.rstrip("/") + PREFIJO

    # 1-2. Salud y superficie pública.
    estado, datos, segundos = http("GET", f"{base}/health")
    informe.comprobar("salud", estado == 200 and (datos or {}).get("status") == "ok",
                      f"estado {estado}; primera respuesta en {segundos:.1f} s")
    informe.comprobar("versión desplegada", (datos or {}).get("version") == __version__,
                      f"esperada {__version__}, recibida {(datos or {}).get('version')}")
    for ruta in ("/docs", "/openapi.json"):
        estado, _, _ = http("GET", f"{base}{ruta}")
        informe.comprobar(f"sin documentación interactiva ({ruta})", estado == 404, f"estado {estado}")

    # 3. Autenticación sin token.
    estado, datos, _ = http("GET", f"{base}/me")
    informe.comprobar("sin token", estado == 401 and _codigo(datos) == "not_authenticated",
                      f"estado {estado}, {_codigo(datos)}")

    # Inicio de sesión como lo hará el frontend: contra Supabase Auth, con la clave publicable.
    estado, datos, _ = http(
        "POST", f"{variables['GYNFEM_SUPABASE_URL'].rstrip('/')}/auth/v1/token?grant_type=password",
        {"email": variables["GYNFEM_SMOKE_ADMIN_EMAIL"], "password": variables["GYNFEM_SMOKE_ADMIN_PASSWORD"]},
        {"apikey": variables["GYNFEM_SUPABASE_PUBLISHABLE_KEY"]},
    )
    token = (datos or {}).get("access_token") if estado == 200 else None
    if not informe.comprobar("inicio de sesión en Supabase", bool(token), f"estado {estado}"):
        return 1
    admin = {"Authorization": f"Bearer {token}"}

    estado, datos, _ = http("GET", f"{base}/me", cabeceras={"Authorization": f"Bearer {token[:-4]}AAAA"})
    informe.comprobar("token alterado", estado == 401 and _codigo(datos) == "invalid_token",
                      f"estado {estado}, {_codigo(datos)}")
    estado, datos, _ = http("GET", f"{base}/me", cabeceras=admin)
    informe.comprobar("token válido: rol de la base", estado == 200 and (datos or {}).get("role") == "administrador",
                      f"estado {estado}, rol {(datos or {}).get('role')}")

    # 4. Autorización.
    estado, datos, _ = http("GET", f"{base}/health/ready", cabeceras=admin)
    informe.comprobar("readiness (base y esquema)", estado == 200 and (datos or {}).get("status") == "ready",
                      f"estado {estado}, {(datos or {}).get('status') or _codigo(datos)}")
    estado, datos, _ = http("POST", f"{base}/patients/search", {"name": "verificacion"}, admin)
    informe.comprobar("rol insuficiente: administrador en pacientes", estado == 403 and _codigo(datos) == "forbidden",
                      f"estado {estado}, {_codigo(datos)}")
    estado, datos, _ = http("GET", f"{base}/users?limit=1", cabeceras=admin)
    informe.comprobar("rol correcto: administrador en usuarios", estado == 200 and "items" in (datos or {}),
                      f"estado {estado}")

    # 5. Predicción real, sin persistencia: normal, con aviso y rechazada.
    estado, datos, segundos = http("POST", f"{base}/predict", ENTRADA_NORMAL, admin)
    d = datos or {}
    informe.comprobar(
        "predicción normal",
        estado == 200 and d.get("risk_level") in {"high", "mid", "low"} and d.get("extrapolation_warnings") == []
        and bool(d.get("clinical_disclaimer")),
        f"estado {estado}, riesgo {d.get('risk_level')}, {segundos * 1000:.0f} ms",
    )
    estado, datos, _ = http("POST", f"{base}/predict", ENTRADA_EXTRAPOLADA, admin)
    d = datos or {}
    avisos = sorted(a.get("field") for a in d.get("extrapolation_warnings") or [])
    informe.comprobar(
        "predicción con aviso de extrapolación",
        estado == 200 and avisos == ["bmi_kg_m2", "hba1c_percent"] and bool(d.get("clinical_disclaimer")),
        f"estado {estado}, riesgo {d.get('risk_level')}, avisos {avisos}",
    )
    estado, datos, _ = http("POST", f"{base}/predict", ENTRADA_IMPOSIBLE, admin)
    detalles = [(x.get("loc"), x.get("type")) for x in (datos or {}).get("error", {}).get("details", [])] \
        if isinstance((datos or {}).get("error"), dict) else []
    informe.comprobar(
        "valor imposible rechazado",
        estado == 422 and (["body", "temperature_c"], "less_than_equal") in detalles,
        f"estado {estado}, {_codigo(datos)}",
    )

    # 6. Errores sin detalles internos.
    for metodo, ruta, esperado, codigo in (("GET", "/no-existe", 404, "not_found"),
                                           ("PUT", "/health", 405, "method_not_allowed")):
        estado, datos, _ = http(metodo, f"{base}{ruta}")
        texto = json.dumps(datos or {})
        informe.comprobar(
            f"error {esperado} uniforme y sin detalles internos",
            estado == esperado and _codigo(datos) == codigo and set(datos or {}) == {"error"}
            and set(datos["error"]) == {"code", "message", "request_id"}
            and not any(f in texto for f in FUGAS_EN_ERRORES),
            f"estado {estado}, {_codigo(datos)}",
        )

    # 7. Latencia medida desde aquí (la del servidor, en `duration_ms` de sus logs).
    for ruta, cabeceras in (("/health", None), ("/health/ready", admin), ("/me", admin)):
        tiempos, estados = [], []
        for _ in range(repeticiones):
            estado, _, segundos = http("GET", f"{base}{ruta}", cabeceras=cabeceras)
            estados.append(estado)
            tiempos.append(segundos * 1000)
        informe.comprobar(
            f"Latencia {PREFIJO}{ruta}",
            all(e == 200 for e in estados),
            f"mediana {statistics.median(tiempos):.0f} ms, mín {min(tiempos):.0f}, máx {max(tiempos):.0f} (n={repeticiones})",
        )

    print(f"\n{informe.fallos} fallos.", flush=True)
    return 0 if informe.fallos == 0 else 1


def main(argv: Sequence[str] | None = None, http: Http | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ops.verificar_despliegue",
                                     description="Verifica la API desplegada sin crear datos clínicos.")
    parser.add_argument("--url", required=True, help="URL pública del servicio: https://<servicio>.onrender.com")
    parser.add_argument("--env-file", type=Path, help="lee las variables de este archivo en vez del entorno")
    parser.add_argument("--repeticiones", type=int, default=10, help="peticiones por ruta al medir la latencia")
    args = parser.parse_args(argv)

    if not _url_valida(args.url):
        sys.stderr.write("La URL debe ser https://<host>, sin ruta.\n")
        return 1
    variables = _leer_variables(args.env_file)
    faltan = [nombre for nombre, valor in variables.items() if not valor]
    if faltan:
        sys.stderr.write(f"Faltan variables: {', '.join(faltan)}.\n")
        return 1
    if not _url_valida(variables["GYNFEM_SUPABASE_URL"]):
        # La contraseña del administrador solo viaja por https.
        sys.stderr.write("GYNFEM_SUPABASE_URL debe ser https://<project-ref>.supabase.co, sin ruta.\n")
        return 1
    return verificar(args.url, variables, http or http_real, max(args.repeticiones, 1))


if __name__ == "__main__":
    raise SystemExit(main())
