"""Verificación repetible de la API desplegada (Fase 12, decisión D; ampliada en la Fase 16).

    .venv\\Scripts\\python.exe -m ops.verificar_despliegue --url https://<servicio>.onrender.com --env-file .env

Comprueba salud, documentación cerrada, autenticación, autorización, las tres
clases de predicción, el formato de los errores y la latencia. Desde la Fase 16,
también las métricas del modelo contra los artefactos locales, la configuración
y la auditoría con el administrador, y sus negativos: el médico no ve la
configuración ni la auditoría, y el administrador no ve el historial ni el
reporte.

**Sin indicadores no escribe nada**: se puede ejecutar tras cada despliegue,
también con datos reales en la base. Dos indicadores opcionales sí escriben, y
lo que escriben **no se borra nunca** (la base no admite borrados físicos):

- `--flujo-clinico`: con la cuenta de médico, crea una paciente
  inequívocamente ficticia (PASAPORTE FICTICIOF16), registra dos mediciones y
  una corrección, consulta el historial, genera el reporte y da de baja lógica
  a la paciente. Quedan, dadas de baja, la paciente, sus tres mediciones y sus
  tres predicciones, con su auditoría.
- `--cambio-de-parametro`: con el administrador, cambia `institution_name` y lo
  restaura al valor que tenía. Quedan **2 filas permanentes** en
  `system_settings` y 2 en `audit_log`, porque ambas tablas son de solo
  inserción.

El guion **no aplica migraciones** ni lee la credencial de la base: solo habla
con la API pública y con Supabase Auth. Si `/health/ready` responde
`schema_outdated`, lo informa y se detiene sin ejecutar el resto.

Las credenciales se leen por **nombre** de `--env-file` (o del entorno): la URL
del proyecto, la clave publicable (para iniciar sesión, como hace el frontend) y
el correo y la contraseña de una cuenta de administrador y de una de médico,
dedicadas a la verificación. Nunca se imprime un token, una contraseña, un
correo ni una clave: solo estados y códigos, y de un error inesperado, solo su
tipo. Sale con código 1 si alguna comprobación falla.
"""

import argparse
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dotenv import dotenv_values

from app import __version__

#: Variables que solo usa este guion (la URL del proyecto es de la aplicación).
VARIABLES_DEL_GUION = (
    "GYNFEM_SUPABASE_PUBLISHABLE_KEY",
    "GYNFEM_SMOKE_ADMIN_EMAIL",
    "GYNFEM_SMOKE_ADMIN_PASSWORD",
    "GYNFEM_SMOKE_MEDICO_EMAIL",
    "GYNFEM_SMOKE_MEDICO_PASSWORD",
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

# --- Fase 16 ---
#: Los artefactos locales con los que se comparan las métricas desplegadas.
REPO_ROOT = Path(__file__).resolve().parents[1]
METADATA_LOCAL = REPO_ROOT / "models" / "model_metadata.json"
METRICAS_LOCALES = REPO_ROOT / "reports" / "ml" / "training_metrics.json"
RESUMEN = ("accuracy", "f1_macro", "precision_macro", "recall_macro", "high_to_low_errors")
#: Las limitaciones que acompañan siempre a las métricas, en su orden.
LIMITACIONES = (
    "metrics_scope", "accuracy_meaning", "high_risk_errors", "narrow_training_range", "dataset_not_local",
    "labels_not_verified", "variant_selection", "low_temperature_band", "clinical_disclaimer",
)
PARAMETROS = {"institution_name", "history_default_page_size"}
#: Un id que no existe: el 403 del rol va antes que cualquier consulta del recurso.
UUID_INEXISTENTE = "00000000-0000-4000-8000-000000000000"
#: Paciente inequívocamente ficticia: ningún dato pertenece a una persona real.
PACIENTE_FICTICIA = {
    "document_type": "PASAPORTE", "document_number": "FICTICIOF16",
    "given_names": "Paciente Ficticia", "family_names": "Sintetica Fdieciseis",
}
INSTITUCION_DE_VERIFICACION = "Verificacion Fase Dieciseis"

#: Lo único de una respuesta que se imprime: identificadores cortos y sin datos.
_IMPRIMIBLE = re.compile(r"^[A-Za-z0-9_.\-]{1,40}$")

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


def _seguro(valor: Any) -> str:
    """Un valor de una respuesta, para imprimirlo: solo si es un identificador corto.

    Lo que devuelve un servicio no se copia a la salida sin más: un cuerpo
    inesperado podría repetir una credencial o un dato.
    """
    texto = str(valor)
    return texto if _IMPRIMIBLE.match(texto) else "?"


def _objeto(datos: Any) -> dict:
    return datos if isinstance(datos, dict) else {}


def _codigo(datos: dict | None) -> str:
    error = _objeto(datos).get("error")
    return _seguro(error.get("code", "?")) if isinstance(error, dict) else "-"


def _leer_variables(env_file: Path | None) -> dict[str, str]:
    fuente = dotenv_values(env_file) if env_file is not None else os.environ
    return {nombre: fuente.get(nombre) or "" for nombre in NECESARIAS}


def _url_valida(url: str) -> bool:
    partes = urlsplit(url)
    return partes.scheme == "https" and bool(partes.hostname) and partes.path in ("", "/") and not partes.query


def _iniciar_sesion(http: Http, variables: dict[str, str], cuenta: str) -> tuple[str | None, int]:
    """Como el frontend: contra Supabase Auth, con la clave publicable. `cuenta`: ADMIN o MEDICO."""
    estado, datos, _ = http(
        "POST", f"{variables['GYNFEM_SUPABASE_URL'].rstrip('/')}/auth/v1/token?grant_type=password",
        {"email": variables[f"GYNFEM_SMOKE_{cuenta}_EMAIL"], "password": variables[f"GYNFEM_SMOKE_{cuenta}_PASSWORD"]},
        {"apikey": variables["GYNFEM_SUPABASE_PUBLISHABLE_KEY"]},
    )
    token = _objeto(datos).get("access_token") if estado == 200 else None
    return (token if isinstance(token, str) and token else None), estado


def _prohibido(informe: Informe, http: Http, nombre: str, metodo: str, url: str, cabeceras: dict) -> None:
    estado, datos, _ = http(metodo, url, None, cabeceras)
    informe.comprobar(nombre, estado == 403 and _codigo(datos) == "forbidden", f"estado {estado}, {_codigo(datos)}")


def _verificar_metricas(informe: Informe, http: Http, base: str, admin: dict) -> None:
    """Las métricas desplegadas son las de los artefactos locales, con todas sus limitaciones."""
    local = json.loads(METADATA_LOCAL.read_text(encoding="utf-8"))
    prueba = json.loads(METRICAS_LOCALES.read_text(encoding="utf-8"))["variants"][local["variant"]]["held_out_test"]
    estado, datos, _ = http("GET", f"{base}/model/metrics", cabeceras=admin)
    d = _objeto(datos)
    esperadas = {clave: local["metrics_summary"][clave] for clave in RESUMEN}
    version = _objeto(d.get("model")).get("model_version")
    informe.comprobar(
        "métricas del modelo: iguales al artefacto local",
        estado == 200 and d.get("metrics") == esperadas and version == local["model_version"],
        f"estado {estado}, versión {_seguro(version)}, {len(esperadas)} cifras comparadas",
    )
    limitaciones = d.get("limitations") if isinstance(d.get("limitations"), list) else []
    codigos = [_objeto(limitacion).get("code") for limitacion in limitaciones]
    informe.comprobar(
        "métricas del modelo: limitaciones completas",
        codigos == list(LIMITACIONES) and all(_objeto(limitacion).get("message") for limitacion in limitaciones),
        f"{len(codigos)} de {len(LIMITACIONES)}",
    )
    detalle = _objeto(d.get("detail"))
    informe.comprobar(
        "métricas del modelo: detalle desplegado",
        detalle.get("labels") == prueba["labels"] and detalle.get("confusion_matrix") == prueba["confusion_matrix"],
        f"motivo de ausencia: {_seguro(d.get('detail_unavailable_reason'))}",
    )


def _verificar_administracion(informe: Informe, http: Http, base: str, admin: dict) -> None:
    """Configuración y auditoría para el administrador; historial y reporte, prohibidos."""
    estado, datos, _ = http("GET", f"{base}/settings", cabeceras=admin)
    informe.comprobar("rol correcto: administrador en configuración",
                      estado == 200 and set(_objeto(datos)) == PARAMETROS, f"estado {estado}")
    estado, datos, _ = http("GET", f"{base}/audit-log?limit=1", cabeceras=admin)
    informe.comprobar("rol correcto: administrador en auditoría",
                      estado == 200 and isinstance(_objeto(datos).get("items"), list), f"estado {estado}")
    _prohibido(informe, http, "rol insuficiente: administrador en el historial",
               "GET", f"{base}/patients/{UUID_INEXISTENTE}/evaluations", admin)
    _prohibido(informe, http, "rol insuficiente: administrador en el reporte",
               "POST", f"{base}/predictions/{UUID_INEXISTENTE}/report", admin)


def _verificar_medico(informe: Informe, http: Http, base: str, medico: dict) -> None:
    estado, datos, _ = http("GET", f"{base}/me", cabeceras=medico)
    rol = _objeto(datos).get("role")
    informe.comprobar("cuenta de médico: rol de la base", estado == 200 and rol == "medico",
                      f"estado {estado}, rol {_seguro(rol)}")
    _prohibido(informe, http, "rol insuficiente: médico en configuración", "GET", f"{base}/settings", medico)
    _prohibido(informe, http, "rol insuficiente: médico en auditoría", "GET", f"{base}/audit-log", medico)


def _valor_de_institucion(datos: Any) -> Any:
    return _objeto(_objeto(datos).get("institution_name")).get("value")


def _cambio_de_parametro(informe: Informe, http: Http, base: str, admin: dict) -> None:
    """Cambia `institution_name` y lo restaura. Deja 2 filas permanentes en `system_settings`
    y 2 en `audit_log`: las dos tablas son de solo inserción. El valor nunca se imprime."""
    estado, datos, _ = http("GET", f"{base}/settings", cabeceras=admin)
    anterior = _valor_de_institucion(datos)
    if not informe.comprobar("parámetro: valor vigente leído", estado == 200 and isinstance(anterior, str),
                             f"estado {estado}"):
        return
    nuevo = INSTITUCION_DE_VERIFICACION if anterior != INSTITUCION_DE_VERIFICACION else f"{INSTITUCION_DE_VERIFICACION} Dos"
    estado, datos, _ = http("PATCH", f"{base}/settings", {"institution_name": nuevo}, admin)
    aplicado = estado == 200 and _valor_de_institucion(datos) == nuevo
    informe.comprobar("parámetro: cambio aplicado", aplicado, f"estado {estado}, {_codigo(datos)}")
    if aplicado:
        estado, datos, _ = http("GET", f"{base}/audit-log?action=system_setting.update&limit=1", cabeceras=admin)
        items = _objeto(datos).get("items")
        ultimo = _objeto(items[0]) if isinstance(items, list) and items else {}
        informe.comprobar(
            "parámetro: cambio auditado con solo el nombre de la clave",
            estado == 200 and ultimo.get("changed_fields") == ["institution_name"] and ultimo.get("entity_id") is None,
            f"estado {estado}",
        )
    # La restauración se intenta siempre, también si algo de lo anterior falló.
    estado, datos, _ = http("PATCH", f"{base}/settings", {"institution_name": anterior}, admin)
    informe.comprobar("parámetro: valor anterior restaurado", estado == 200 and _valor_de_institucion(datos) == anterior,
                      f"estado {estado}, {_codigo(datos)}; quedan 2 filas permanentes en system_settings y 2 en audit_log")


def _evaluar_y_consultar(informe: Informe, http: Http, base: str, medico: dict, admin: dict, paciente: str) -> str | None:
    """Dos mediciones, una corrección, el historial y el reporte. Devuelve la predicción reportada."""
    mediciones = f"{base}/patients/{paciente}/measurements"
    estado_1, primera, _ = http("POST", mediciones, ENTRADA_NORMAL, medico)
    estado_2, segunda, _ = http("POST", mediciones, ENTRADA_EXTRAPOLADA, medico)
    original = _objeto(_objeto(primera).get("measurement")).get("id")
    prediccion = _objeto(_objeto(segunda).get("prediction")).get("id")
    if not informe.comprobar("flujo clínico: dos mediciones registradas con su predicción",
                             estado_1 == estado_2 == 201 and bool(original) and bool(prediccion),
                             f"estados {estado_1} y {estado_2}"):
        return None

    estado, correccion, _ = http("POST", f"{base}/measurements/{original}/corrections",
                                 {**ENTRADA_NORMAL, "heart_rate_bpm": 82}, medico)
    corregida = _objeto(_objeto(correccion).get("prediction")).get("id")
    if informe.comprobar("flujo clínico: corrección registrada", estado == 201 and bool(corregida),
                         f"estado {estado}, {_codigo(correccion)}"):
        prediccion = corregida

    estado, datos, _ = http("GET", f"{base}/patients/{paciente}/evaluations", cabeceras=medico)
    d = _objeto(datos)
    items = d.get("items") if isinstance(d.get("items"), list) else []
    estados = {_objeto(_objeto(i).get("measurement")).get("id"): _objeto(i).get("status") for i in items}
    informe.comprobar(
        "flujo clínico: historial con las tres evaluaciones y la original marcada como corregida",
        estado == 200 and len(items) == 3 and estados.get(original) == "corrected"
        and sorted(map(str, estados.values())) == ["corrected", "current", "current"]
        and bool(d.get("clinical_disclaimer")),
        f"estado {estado}, {len(items)} evaluaciones",
    )

    estado, datos, _ = http("POST", f"{base}/predictions/{prediccion}/report", None, medico)
    d = _objeto(datos)
    informe.comprobar(
        "flujo clínico: reporte con la paciente, la medición y la advertencia clínica",
        estado == 200
        and _objeto(d.get("patient")).get("document_number") == PACIENTE_FICTICIA["document_number"]
        and bool(_objeto(d.get("measurement")).get("id")) and _objeto(d.get("prediction")).get("status") == "current"
        and bool(d.get("clinical_disclaimer")) and bool(d.get("institution_name")),
        f"estado {estado}, {_codigo(datos)}",
    )

    estado_h, datos_h, _ = http("GET", f"{base}/patients/{paciente}/evaluations", cabeceras=admin)
    estado_r, datos_r, _ = http("POST", f"{base}/predictions/{prediccion}/report", None, admin)
    informe.comprobar(
        "flujo clínico: el administrador no ve el historial ni el reporte",
        estado_h == estado_r == 403 and _codigo(datos_h) == _codigo(datos_r) == "forbidden",
        f"estados {estado_h} y {estado_r}",
    )
    return prediccion


def _flujo_clinico(informe: Informe, http: Http, base: str, medico: dict, admin: dict) -> None:
    """Paciente ficticia, evaluaciones, historial, reporte y baja lógica. Nada se borra: la
    paciente, sus mediciones y sus predicciones quedan en la base, dadas de baja."""
    documento = {clave: PACIENTE_FICTICIA[clave] for clave in ("document_type", "document_number")}
    _, datos, _ = http("POST", f"{base}/patients/search", documento, medico)
    previas = _objeto(datos).get("items")
    for previa in previas if isinstance(previas, list) else []:
        # Una corrida anterior se interrumpió antes de la baja: el documento seguiría ocupado.
        estado, _, _ = http("DELETE", f"{base}/patients/{_objeto(previa).get('id')}", None, medico)
        informe.comprobar("flujo clínico: baja de la paciente sintética de una corrida anterior", estado == 204,
                          f"estado {estado}")

    estado, datos, _ = http("POST", f"{base}/patients", PACIENTE_FICTICIA, medico)
    paciente = _objeto(datos).get("id")
    if not informe.comprobar("flujo clínico: paciente sintética creada", estado == 201 and bool(paciente),
                             f"estado {estado}, {_codigo(datos)}"):
        return
    prediccion = None
    try:
        prediccion = _evaluar_y_consultar(informe, http, base, medico, admin, paciente)
    finally:
        # La baja se intenta siempre: la paciente sintética no debe quedar activa.
        estado, _, _ = http("DELETE", f"{base}/patients/{paciente}", None, medico)
        informe.comprobar("flujo clínico: baja lógica de la paciente", estado == 204, f"estado {estado}")

    estado, datos, _ = http("GET", f"{base}/patients/{paciente}/evaluations", cabeceras=medico)
    informe.comprobar("flujo clínico: historial de la paciente dada de baja",
                      estado == 404 and _codigo(datos) == "patient_not_found", f"estado {estado}, {_codigo(datos)}")
    if prediccion is not None:
        estado, datos, _ = http("POST", f"{base}/predictions/{prediccion}/report", None, medico)
        informe.comprobar("flujo clínico: reporte de la paciente dada de baja",
                          estado == 404 and _codigo(datos) == "prediction_not_found",
                          f"estado {estado}, {_codigo(datos)}")


def verificar(
    api: str, variables: dict[str, str], http: Http, repeticiones: int,
    flujo_clinico: bool = False, cambio_de_parametro: bool = False,
) -> int:
    informe = Informe()
    base = api.rstrip("/") + PREFIJO

    # 1-2. Salud y superficie pública.
    estado, datos, segundos = http("GET", f"{base}/health")
    informe.comprobar("salud", estado == 200 and _objeto(datos).get("status") == "ok",
                      f"estado {estado}; primera respuesta en {segundos:.1f} s")
    informe.comprobar("versión desplegada", _objeto(datos).get("version") == __version__,
                      f"esperada {__version__}, recibida {_seguro(_objeto(datos).get('version'))}")
    for ruta in ("/docs", "/openapi.json"):
        estado, _, _ = http("GET", f"{base}{ruta}")
        informe.comprobar(f"sin documentación interactiva ({ruta})", estado == 404, f"estado {estado}")

    # 3. Autenticación sin token.
    estado, datos, _ = http("GET", f"{base}/me")
    informe.comprobar("sin token", estado == 401 and _codigo(datos) == "not_authenticated",
                      f"estado {estado}, {_codigo(datos)}")

    token, estado = _iniciar_sesion(http, variables, "ADMIN")
    if not informe.comprobar("inicio de sesión en Supabase", bool(token), f"estado {estado}"):
        return 1
    admin = {"Authorization": f"Bearer {token}"}

    estado, datos, _ = http("GET", f"{base}/me", cabeceras={"Authorization": f"Bearer {token[:-4]}AAAA"})
    informe.comprobar("token alterado", estado == 401 and _codigo(datos) == "invalid_token",
                      f"estado {estado}, {_codigo(datos)}")
    estado, datos, _ = http("GET", f"{base}/me", cabeceras=admin)
    informe.comprobar("token válido: rol de la base", estado == 200 and _objeto(datos).get("role") == "administrador",
                      f"estado {estado}, rol {_seguro(_objeto(datos).get('role'))}")

    # 4. Autorización.
    estado, datos, _ = http("GET", f"{base}/health/ready", cabeceras=admin)
    informe.comprobar("readiness (base y esquema)", estado == 200 and _objeto(datos).get("status") == "ready",
                      f"estado {estado}, {_seguro(_objeto(datos).get('status') or _codigo(datos))}")
    if estado == 503 and _codigo(datos) == "schema_outdated":
        # El código desplegado y las migraciones aplicadas no coinciden: nada de lo que
        # sigue sería fiable, y el guion no aplica migraciones.
        print("DETENIDO — schema_outdated: el esquema de la base no es el que espera el código desplegado. "
              "Aplique la migración pendiente o espere a que termine el despliegue (docs/DEPLOYMENT.md, "
              "Sección 7.5). No se ejecutó el resto de la verificación.", flush=True)
        return 1
    estado, datos, _ = http("POST", f"{base}/patients/search", {"name": "verificacion"}, admin)
    informe.comprobar("rol insuficiente: administrador en pacientes", estado == 403 and _codigo(datos) == "forbidden",
                      f"estado {estado}, {_codigo(datos)}")
    estado, datos, _ = http("GET", f"{base}/users?limit=1", cabeceras=admin)
    informe.comprobar("rol correcto: administrador en usuarios", estado == 200 and "items" in _objeto(datos),
                      f"estado {estado}")

    # 5. Predicción real, sin persistencia: normal, con aviso y rechazada.
    estado, datos, segundos = http("POST", f"{base}/predict", ENTRADA_NORMAL, admin)
    d = _objeto(datos)
    informe.comprobar(
        "predicción normal",
        estado == 200 and d.get("risk_level") in {"high", "mid", "low"} and d.get("extrapolation_warnings") == []
        and bool(d.get("clinical_disclaimer")),
        f"estado {estado}, riesgo {_seguro(d.get('risk_level'))}, {segundos * 1000:.0f} ms",
    )
    estado, datos, _ = http("POST", f"{base}/predict", ENTRADA_EXTRAPOLADA, admin)
    d = _objeto(datos)
    avisos = sorted(str(_objeto(a).get("field")) for a in d.get("extrapolation_warnings") or [])
    informe.comprobar(
        "predicción con aviso de extrapolación",
        estado == 200 and avisos == ["bmi_kg_m2", "hba1c_percent"] and bool(d.get("clinical_disclaimer")),
        f"estado {estado}, riesgo {_seguro(d.get('risk_level'))}, avisos {[_seguro(a) for a in avisos]}",
    )
    estado, datos, _ = http("POST", f"{base}/predict", ENTRADA_IMPOSIBLE, admin)
    error = _objeto(datos).get("error")
    detalles = [(_objeto(x).get("loc"), _objeto(x).get("type")) for x in _objeto(error).get("details") or []]
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
            estado == esperado and _codigo(datos) == codigo and set(_objeto(datos)) == {"error"}
            and set(_objeto(_objeto(datos).get("error"))) == {"code", "message", "request_id"}
            and not any(f in texto for f in FUGAS_EN_ERRORES),
            f"estado {estado}, {_codigo(datos)}",
        )

    # 7. Fase 16: métricas, configuración y auditoría, con sus negativos por rol.
    _verificar_metricas(informe, http, base, admin)
    _verificar_administracion(informe, http, base, admin)
    token_medico, estado = _iniciar_sesion(http, variables, "MEDICO")
    medico = {"Authorization": f"Bearer {token_medico}"} if token_medico else None
    if informe.comprobar("inicio de sesión de la cuenta de médico", medico is not None, f"estado {estado}"):
        _verificar_medico(informe, http, base, medico)

    # 8. Lo que escribe, solo si se pide (ver el encabezado: lo escrito no se borra).
    if cambio_de_parametro:
        _cambio_de_parametro(informe, http, base, admin)
    if flujo_clinico and medico is not None:
        _flujo_clinico(informe, http, base, medico, admin)

    # 9. Latencia medida desde aquí (la del servidor, en `duration_ms` de sus logs).
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
    parser = argparse.ArgumentParser(
        prog="python -m ops.verificar_despliegue",
        description="Verifica la API desplegada. Sin indicadores no escribe nada.",
    )
    parser.add_argument("--url", required=True, help="URL pública del servicio: https://<servicio>.onrender.com")
    parser.add_argument("--env-file", type=Path, help="lee las variables de este archivo en vez del entorno")
    parser.add_argument("--repeticiones", type=int, default=10, help="peticiones por ruta al medir la latencia")
    parser.add_argument("--flujo-clinico", action="store_true",
                        help="ESCRIBE: paciente ficticia con dos mediciones y una corrección, que quedan dadas de baja")
    parser.add_argument("--cambio-de-parametro", action="store_true",
                        help="ESCRIBE: cambia institution_name y lo restaura; deja 2 filas permanentes en "
                             "system_settings y 2 en audit_log")
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
        # Las contraseñas solo viajan por https.
        sys.stderr.write("GYNFEM_SUPABASE_URL debe ser https://<project-ref>.supabase.co, sin ruta.\n")
        return 1
    try:
        return verificar(args.url, variables, http or http_real, max(args.repeticiones, 1),
                         flujo_clinico=args.flujo_clinico, cambio_de_parametro=args.cambio_de_parametro)
    except Exception as exc:  # noqa: BLE001 — el mensaje de una excepción puede llevar una credencial
        # Solo el tipo: ni el mensaje ni la traza.
        print(f"FALLA error inesperado — {type(exc).__name__}; la verificación no terminó.", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
