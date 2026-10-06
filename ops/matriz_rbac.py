"""Matriz RBAC contra la API desplegada (Fase 17): cada ruta × anónimo, médica y administradora.

    .venv\\Scripts\\python.exe -m ops.matriz_rbac --url https://<servicio>.onrender.com --env-file .env

La lista de rutas y lo permitido salen de la tabla de `docs/API_SPEC.md` §3.6
(entre los marcadores `matriz-rbac`); que esa tabla coincide con las rutas del
código lo vigila `test_matriz_de_api_spec_coincide_con_las_rutas_reales`, y el
guion se detiene si la versión desplegada no es la del código local.

**No escribe nada.** Una celda permitida se demuestra con una respuesta que solo
llega **después** de pasar la autorización y sin escribir: un 200 de lectura, un
404 sobre un UUID aleatorio de esta corrida o un 422 de un cuerpo inválido (la
API decide el 401 y el 403 antes que el 422: `test_401_antes_que_422`). Que
ninguna tabla cambia se prueba contra la base embebida en
`tests/database/test_matriz_rbac.py`.

Las credenciales se leen por **nombre**, como en `ops.verificar_despliegue`. La
salida y la evidencia (una línea JSON por celda, en `reports/fase17/`, ignorada
por git) llevan solo métodos, rutas, estados, códigos y `request_id`: nunca un
token, un correo ni una clave. Sale con código 1 si alguna celda falla.
"""

import argparse
import json
import re
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import __version__
from ops.verificar_despliegue import (
    ENTRADA_NORMAL,
    PREFIJO,
    REPO_ROOT,
    Http,
    _codigo,
    _iniciar_sesion,
    _leer_variables,
    _objeto,
    _seguro,
    _url_valida,
    http_real,
)

API_SPEC = REPO_ROOT / "docs" / "API_SPEC.md"
CARPETA_DE_EVIDENCIAS = REPO_ROOT / "reports" / "fase17"
IDENTIDADES = ("anonimo", "medico", "administrador")
PERMITIDO = "✔"
#: En production no existen: `create_app` no las registra (API_SPEC §3.6).
DOCUMENTACION = {("GET", "/api/v1/openapi.json"), ("GET", "/api/v1/docs")}
PARAMETRO = re.compile(r"\{\w+\}")


@dataclass(frozen=True)
class Fila:
    metodo: str
    ruta: str
    celdas: dict[str, str]


@dataclass(frozen=True)
class Sonda:
    """Lo que se envía a una ruta protegida y lo que responde quien **sí** tiene permiso, sin escribir."""

    estado: int
    codigo: str | None = None
    cuerpo: dict | None = None
    consulta: str = ""


_PACIENTE = "/api/v1/patients/{patient_id}"
#: Una por ruta protegida. 404: UUID aleatorio de la corrida. 422: cuerpo que el esquema rechaza.
SONDAS: dict[tuple[str, str], Sonda] = {
    ("GET", "/api/v1/health/ready"): Sonda(200),
    ("POST", "/api/v1/predict"): Sonda(200, cuerpo=ENTRADA_NORMAL),
    ("GET", "/api/v1/prediction/schema"): Sonda(200),
    ("GET", "/api/v1/model/metrics"): Sonda(200),
    ("POST", "/api/v1/patients"): Sonda(422, "validation_error", {}),
    ("POST", "/api/v1/patients/search"): Sonda(422, "validation_error", {}),
    ("GET", _PACIENTE): Sonda(404, "patient_not_found"),
    ("PATCH", _PACIENTE): Sonda(404, "patient_not_found", {"given_names": "Paciente Ficticia"}),
    ("DELETE", _PACIENTE): Sonda(404, "patient_not_found"),
    ("POST", f"{_PACIENTE}/measurements"): Sonda(404, "patient_not_found", ENTRADA_NORMAL),
    ("GET", f"{_PACIENTE}/measurements"): Sonda(404, "patient_not_found"),
    ("GET", f"{_PACIENTE}/evaluations"): Sonda(404, "patient_not_found"),
    ("POST", "/api/v1/measurements/{measurement_id}/corrections"): Sonda(404, "measurement_not_found", ENTRADA_NORMAL),
    ("GET", "/api/v1/predictions/{prediction_id}"): Sonda(404, "prediction_not_found"),
    ("POST", "/api/v1/predictions/{prediction_id}/report"): Sonda(404, "prediction_not_found"),
    ("GET", "/api/v1/me"): Sonda(200),
    ("POST", "/api/v1/users"): Sonda(422, "validation_error", {}),
    ("GET", "/api/v1/users"): Sonda(200, consulta="?limit=1"),
    ("GET", "/api/v1/users/{user_id}"): Sonda(404, "user_not_found"),
    ("PATCH", "/api/v1/users/{user_id}"): Sonda(404, "user_not_found", {"full_name": "Usuario Ficticio"}),
    ("POST", "/api/v1/users/{user_id}/deactivate"): Sonda(404, "user_not_found"),
    ("POST", "/api/v1/users/{user_id}/activate"): Sonda(404, "user_not_found"),
    ("GET", "/api/v1/settings"): Sonda(200),
    ("PATCH", "/api/v1/settings"): Sonda(422, "validation_error", {}),
    ("GET", "/api/v1/audit-log"): Sonda(200, consulta="?limit=1"),
}


def leer_matriz(path: Path = API_SPEC) -> list[Fila]:
    """Las filas de la tabla entre los marcadores `matriz-rbac` de API_SPEC, en su orden."""
    texto = path.read_text(encoding="utf-8")
    bloque = texto.split("<!-- matriz-rbac:inicio -->")[1].split("<!-- matriz-rbac:fin -->")[0]
    filas = []
    for linea in bloque.strip().splitlines()[2:]:
        celdas = [c.strip().strip("`") for c in linea.strip().strip("|").split("|")]
        filas.append(Fila(celdas[0], celdas[1], dict(zip(IDENTIDADES, celdas[2:5], strict=True))))
    return filas


def esperado_de(fila: Fila, identidad: str) -> tuple[int, str | None]:
    """(estado, `code` del error o None) que la API desplegada debe dar en esta celda."""
    if (fila.metodo, fila.ruta) in DOCUMENTACION:
        return 404, "not_found"
    celda = fila.celdas[identidad]
    if celda == "401":
        return 401, "not_authenticated"
    if celda == "403":
        return 403, "forbidden"
    if fila.celdas["anonimo"] == PERMITIDO:
        return 200, None
    sonda = SONDAS[(fila.metodo, fila.ruta)]
    return sonda.estado, sonda.codigo


def ruta_concreta(ruta: str) -> str:
    """La ruta con un UUID aleatorio en cada parámetro: no existe, y no coincide entre corridas."""
    return PARAMETRO.sub(lambda _: str(uuid.uuid4()), ruta)


def _request_id(datos: Any) -> str | None:
    error = _objeto(datos).get("error")
    return _seguro(error.get("request_id")) if isinstance(error, dict) and "request_id" in error else None


def _probar(http: Http, api: str, fila: Fila, identidad: str, cabeceras: dict) -> dict:
    sonda = SONDAS.get((fila.metodo, fila.ruta), Sonda(200))
    url = api + ruta_concreta(fila.ruta) + sonda.consulta
    estado, datos, _ = http(fila.metodo, url, sonda.cuerpo, cabeceras)
    esperado_estado, esperado_codigo = esperado_de(fila, identidad)
    codigo = _codigo(datos)
    ok = estado == esperado_estado and (esperado_codigo is None or codigo == esperado_codigo)
    return {
        "metodo": fila.metodo, "ruta": fila.ruta, "identidad": identidad,
        "esperado_estado": esperado_estado, "esperado_codigo": esperado_codigo,
        "estado": estado, "codigo": codigo, "request_id": _request_id(datos), "ok": ok,
    }


def _detenido(motivo: str) -> int:
    print(f"DETENIDO — {motivo}. No se probó ninguna celda.", flush=True)
    return 1


def _identidades(http: Http, api: str, variables: dict[str, str]) -> dict[str, dict] | str:
    """Cabeceras por identidad, tras comprobar con `/me` que cada cuenta tiene el rol que dice; o el motivo."""
    cabeceras: dict[str, dict] = {"anonimo": {}}
    for identidad, cuenta in (("medico", "MEDICO"), ("administrador", "ADMIN")):
        token, estado = _iniciar_sesion(http, variables, cuenta)
        if token is None:
            return f"inicio de sesión de la cuenta {identidad}: estado {estado}"
        cabeceras[identidad] = {"Authorization": f"Bearer {token}"}
        estado, datos, _ = http("GET", f"{api}{PREFIJO}/me", None, cabeceras[identidad])
        rol = _objeto(datos).get("role")
        if estado != 200 or rol != identidad:
            return f"la cuenta {identidad} no tiene ese rol (estado {estado}, rol {_seguro(rol)})"
    return cabeceras


def ejecutar(api: str, variables: dict[str, str], http: Http, salida: Path) -> int:
    api = api.rstrip("/")
    filas = leer_matriz()
    if {(f.metodo, f.ruta) for f in filas if f.celdas["anonimo"] != PERMITIDO} != set(SONDAS):
        return _detenido("las sondas no cubren exactamente la matriz de API_SPEC")

    # Despierta el servicio (hasta 120 s) y confirma que el código desplegado es el local.
    estado, datos, segundos = http("GET", f"{api}{PREFIJO}/health")
    version = _objeto(datos).get("version")
    print(f"salud: estado {estado} en {segundos:.1f} s, versión {_seguro(version)}", flush=True)
    if estado != 200 or version != __version__:
        return _detenido(f"la versión desplegada no es la local ({__version__})")

    cabeceras = _identidades(http, api, variables)
    if isinstance(cabeceras, str):
        return _detenido(cabeceras)

    salida.parent.mkdir(parents=True, exist_ok=True)
    fallos = 0
    with salida.open("w", encoding="utf-8") as evidencia:
        for fila in filas:
            for identidad in IDENTIDADES:
                r = _probar(http, api, fila, identidad, cabeceras[identidad])
                fallos += not r["ok"]
                evidencia.write(json.dumps(r, ensure_ascii=False) + "\n")
                print(
                    f"{'OK   ' if r['ok'] else 'FALLA'} {r['metodo']} {r['ruta']} · {identidad} — "
                    f"esperado {r['esperado_estado']} {r['esperado_codigo'] or ''}, "
                    f"real {r['estado']} {r['codigo']}",
                    flush=True,
                )
    print(f"\n{len(filas) * len(IDENTIDADES)} celdas, {fallos} fallos. Evidencia: {salida.name}", flush=True)
    return 0 if fallos == 0 else 1


def main(argv: Sequence[str] | None = None, http: Http | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ops.matriz_rbac",
        description="Matriz RBAC contra la API desplegada. No escribe nada.",
    )
    parser.add_argument("--url", required=True, help="URL pública del servicio: https://<servicio>.onrender.com")
    parser.add_argument("--env-file", type=Path, help="lee las variables de este archivo en vez del entorno")
    parser.add_argument("--salida", type=Path, help="evidencia JSONL (por defecto, en reports/fase17/)")
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
        sys.stderr.write("GYNFEM_SUPABASE_URL debe ser https://<project-ref>.supabase.co, sin ruta.\n")
        return 1
    marca = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    salida = args.salida or CARPETA_DE_EVIDENCIAS / f"matriz_rbac_{marca}.jsonl"
    try:
        return ejecutar(args.url, variables, http or http_real, salida)
    except Exception as exc:  # noqa: BLE001 — el mensaje de una excepción puede llevar una credencial
        print(f"FALLA error inesperado — {type(exc).__name__}; la matriz no terminó.", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
