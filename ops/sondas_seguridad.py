"""Sondas de seguridad dirigidas contra la API desplegada (Fase 17).

    .venv\\Scripts\\python.exe -m ops.sondas_seguridad --url https://<servicio>.onrender.com --env-file .env

Casos aprobados (plan de la Fase 17, Sección 3):

- **S1** sin `Authorization` o con otro esquema: 401 y `WWW-Authenticate: Bearer`.
- **S2** token real con la carga alterada o la firma truncada: 401 `invalid_token`.
- **S3** token HS256 firmado con una clave inventada, o con `alg: none`: 401 `invalid_token`.
- **S5** el rol declarado en cabeceras, en la consulta o en el cuerpo no eleva: 403.
- **S6** la administradora recibe 403 en recursos clínicos, sin que el error repita el id;
  la médica, 404 en el mismo UUID (control).
- **S8** un id que no es UUID: 422 que no repite el valor recibido.
- **S9** inyección en texto: la búsqueda trata `'`, `%` y `_` como literales (200 sin
  resultados), y un nombre con SQL o HTML se rechaza (422) sin repetirlo.
- **S11** errores uniformes (404, 405, JSON mal formado, cuerpo enorme): sin trazas,
  rutas ni módulos, y con el mismo `request_id` en el cuerpo y en `X-Request-ID`.
- **S12** CORS: un origen ajeno no recibe `Access-Control-Allow-Origin`.

**No escribe nada.** Las rutas con id usan un UUID aleatorio de esta corrida; las
modificaciones van a pacientes que no existen o con cuerpos que el esquema
rechaza; las búsquedas no se auditan. Que ninguna tabla cambia se prueba contra
la base embebida en `tests/database/test_sondas_seguridad.py`.

Los tokens manipulados se construyen aquí, en local. La salida y la evidencia
(JSONL en `reports/fase17/`, ignorada por git) llevan solo caso, nombre, método,
estado, código y `request_id`: nunca un token, un correo, una clave ni un cuerpo.
Sale con código 1 si alguna sonda falla.
"""

import argparse
import base64
import hashlib
import hmac
import json
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import __version__
from ops.verificar_despliegue import ENTRADA_NORMAL, PREFIJO, REPO_ROOT, TIMEOUT_S, _leer_variables, _seguro, _url_valida

CARPETA_DE_EVIDENCIAS = REPO_ROOT / "reports" / "fase17"
ORIGEN_AJENO = "https://evil.example"
CLAVES_DE_ERROR = {"code", "message", "request_id", "details"}
#: Del cuerpo de una respuesta que no es de la API, solo esto, y tachado (ver `diagnostico`).
LARGO_DEL_FRAGMENTO = 80
CABECERAS_DE_DIAGNOSTICO = ("server", "cf-ray", "content-type")
_CORREO = re.compile(r"[^\s@]+@[^\s@]+")
_JWT = re.compile(r"eyJ[\w-]*(?:\.[\w-]*){0,2}")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_FUGAS = re.compile(r"Traceback|File \"|site-packages|/opt/render|psycopg|sqlalchemy|\b[\w/]+\.py\b")


@dataclass(frozen=True)
class Respuesta:
    estado: int
    cabeceras: dict[str, str]
    texto: str

    def json(self) -> Any:
        try:
            return json.loads(self.texto)
        except ValueError:
            return None


Http = Callable[..., Respuesta]


@dataclass(frozen=True)
class Contexto:
    base: str
    supabase_url: str
    medico: dict[str, str]
    admin: dict[str, str]


@dataclass(frozen=True)
class Sonda:
    caso: str
    nombre: str
    metodo: str
    ruta: str
    evaluar: Callable[[Respuesta], bool]
    cuerpo: bytes | None = None
    cabeceras: dict[str, str] = field(default_factory=dict)


# --- HTTP ------------------------------------------------------------------------------------


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_SinRedirecciones)


def http_real(metodo: str, url: str, cuerpo: bytes | None = None, cabeceras: dict | None = None) -> Respuesta:
    """Sin seguir redirecciones (el token no sale del servicio). Inalcanzable o agotado: estado 0."""
    peticion = urllib.request.Request(url, data=cuerpo, method=metodo, headers=cabeceras or {})
    try:
        with _opener.open(peticion, timeout=TIMEOUT_S) as r:
            estado, cab, contenido = r.status, r.headers, r.read()
    except urllib.error.HTTPError as error:
        estado, cab, contenido = error.code, error.headers, error.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return Respuesta(0, {}, "")
    return Respuesta(estado, {k.lower(): v for k, v in cab.items()}, contenido.decode("utf-8", "replace"))


# --- Tokens manipulados, construidos en local -----------------------------------------------


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def _carga(token: str) -> dict:
    parte = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(parte + "=" * (-len(parte) % 4)))


def token_alterado(token: str) -> str:
    """La misma cabecera y la misma firma, con otro `sub` y un rol declarado: la firma ya no cuadra."""
    cabecera, _, firma = token.split(".")
    carga = {**_carga(token), "sub": str(uuid.uuid4()), "user_role": "administrador"}
    return f"{cabecera}.{_b64(json.dumps(carga).encode())}.{firma}"


def token_firma_truncada(token: str) -> str:
    cabecera, carga, firma = token.split(".")
    return f"{cabecera}.{carga}.{firma[: len(firma) // 2]}"


def _claims(supabase_url: str) -> dict:
    ahora = int(time.time())
    return {"iss": f"{supabase_url.rstrip('/')}/auth/v1", "aud": "authenticated", "sub": str(uuid.uuid4()),
            "role": "authenticated", "iat": ahora, "exp": ahora + 600}


def token_hs256(supabase_url: str) -> str:
    """Confusión de algoritmo: HS256 con una clave aleatoria que nadie más conoce."""
    base = f"{_b64(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())}.{_b64(json.dumps(_claims(supabase_url)).encode())}"
    firma = hmac.new(secrets.token_bytes(32), base.encode(), hashlib.sha256).digest()
    return f"{base}.{_b64(firma)}"


def token_alg_none(supabase_url: str) -> str:
    return f"{_b64(json.dumps({'alg': 'none', 'typ': 'JWT'}).encode())}.{_b64(json.dumps(_claims(supabase_url)).encode())}."


# --- Diagnóstico de respuestas que no son de la API -------------------------------------------


def diagnostico(r: Respuesta) -> dict | None:
    """Quién respondió, cuando el cuerpo **no es JSON**: un error uniforme o un 200 de la API no se guarda nunca.

    Un 403 sin el formato de API_SPEC §2.5 (S8 y S9 en producción, 2026-10-06) no lo emitió el manejador
    de errores de la API. Las cabeceras `server`, `cf-ray` y `content-type` y el comienzo del cuerpo dicen
    quién fue. Del cuerpo, solo los primeros caracteres, en una línea y con correos y JWT tachados.
    """
    if r.json() is not None:
        return None
    texto = _JWT.sub("[token]", _CORREO.sub("[correo]", " ".join(r.texto.split())))
    return {**{nombre: r.cabeceras.get(nombre) for nombre in CABECERAS_DE_DIAGNOSTICO},
            "cuerpo": texto[:LARGO_DEL_FRAGMENTO]}


# --- Evaluación ------------------------------------------------------------------------------


def tiene_fuga(texto: str) -> bool:
    """Una traza, una ruta del servidor, un módulo de Python o el driver de la base."""
    return bool(_FUGAS.search(texto))


def _error_uniforme(r: Respuesta, estado: int, codigos: set[str], no_repetir: Sequence[str] = ()) -> bool:
    """El formato de API_SPEC §2.5, sin fugas, sin ids y sin repetir lo recibido."""
    cuerpo = r.json()
    if r.estado != estado or not isinstance(cuerpo, dict) or set(cuerpo) != {"error"}:
        return False
    error = cuerpo["error"]
    if not isinstance(error, dict) or not set(error) <= CLAVES_DE_ERROR or error.get("code") not in codigos:
        return False
    detalles = error.get("details") or []
    visible = json.dumps([error.get("message"), detalles], ensure_ascii=False)
    return (
        bool(error.get("request_id")) and r.cabeceras.get("x-request-id") == error["request_id"]
        and all(isinstance(d, dict) and set(d) <= {"loc", "type"} for d in detalles)
        and not tiene_fuga(r.texto) and not _UUID.search(visible)
        and not any(valor in r.texto for valor in no_repetir)
    )


def _no_autenticado(codigos: set[str]) -> Callable[[Respuesta], bool]:
    return lambda r: _error_uniforme(r, 401, codigos) and r.cabeceras.get("www-authenticate") == "Bearer"


def _prohibido(r: Respuesta) -> bool:
    return _error_uniforme(r, 403, {"forbidden"})


def _busqueda_vacia(r: Respuesta) -> bool:
    cuerpo = r.json()
    return r.estado == 200 and isinstance(cuerpo, dict) and cuerpo.get("items") == [] and not tiene_fuga(r.texto)


def _sin_cors_ajeno(estado: int) -> Callable[[Respuesta], bool]:
    def evaluar(r: Respuesta) -> bool:
        return r.estado == estado and "access-control-allow-origin" not in r.cabeceras and not tiene_fuga(r.texto)

    return evaluar


# --- Las sondas ------------------------------------------------------------------------------


def _json(datos: Any) -> bytes:
    return json.dumps(datos).encode()


JSON = {"Content-Type": "application/json"}


def _autenticacion(ctx: Contexto) -> list[Sonda]:
    token_medico = ctx.medico["Authorization"].removeprefix("Bearer ")
    sin = {"not_authenticated"}
    invalido = {"invalid_token"}
    s1 = [
        Sonda("S1", "S1 sin Authorization", "GET", "/me", _no_autenticado(sin)),
        Sonda("S1", "S1 esquema Basic", "GET", "/me", _no_autenticado(sin),
              cabeceras={"Authorization": "Basic dXN1YXJpbzpjbGF2ZQ=="}),
        Sonda("S1", "S1 esquema Token", "GET", "/me", _no_autenticado(sin), cabeceras={"Authorization": "Token abc"}),
        Sonda("S1", "S1 esquema correcto sin token", "GET", "/me", _no_autenticado(sin | invalido),
              cabeceras={"Authorization": "Bearer "}),
        Sonda("S1", "S1 sin token en POST /predict", "POST", "/predict", _no_autenticado(sin),
              _json(ENTRADA_NORMAL), JSON),
    ]
    s2 = [
        Sonda("S2", "S2 carga alterada", "GET", "/me", _no_autenticado(invalido),
              cabeceras={"Authorization": f"Bearer {token_alterado(token_medico)}"}),
        Sonda("S2", "S2 firma truncada", "GET", "/me", _no_autenticado(invalido),
              cabeceras={"Authorization": f"Bearer {token_firma_truncada(token_medico)}"}),
    ]
    s3 = [
        Sonda("S3", "S3 alg HS256 con clave inventada", "GET", "/me", _no_autenticado(invalido),
              cabeceras={"Authorization": f"Bearer {token_hs256(ctx.supabase_url)}"}),
        Sonda("S3", "S3 alg none", "GET", "/me", _no_autenticado(invalido),
              cabeceras={"Authorization": f"Bearer {token_alg_none(ctx.supabase_url)}"}),
    ]
    return s1 + s2 + s3


def _autorizacion(ctx: Contexto) -> list[Sonda]:
    m = ctx.medico
    elevar = {"X-Role": "administrador", "X-User-Role": "administrador", "X-Forwarded-User": "administrador"}
    s5 = [
        Sonda("S5", "S5 rol en cabeceras", "GET", "/users", _prohibido, cabeceras={**m, **elevar}),
        Sonda("S5", "S5 rol en la consulta", "GET", "/settings?role=administrador", _prohibido, cabeceras=m),
        Sonda("S5", "S5 rol en el cuerpo de PATCH /settings", "PATCH", "/settings", _prohibido,
              _json({"role": "administrador", "institution_name": "Sonda Ficticia"}), {**m, **JSON}),
        Sonda("S5", "S5 rol en el cuerpo de POST /users", "POST", "/users", _prohibido,
              _json({"role": "administrador", "full_name": "Usuario Ficticio"}), {**m, **JSON}),
    ]
    paciente, prediccion = uuid.uuid4(), uuid.uuid4()
    s6 = [
        Sonda("S6", "S6 administradora en paciente", "GET", f"/patients/{paciente}", _prohibido, cabeceras=ctx.admin),
        Sonda("S6", "S6 administradora en historial", "GET", f"/patients/{paciente}/evaluations", _prohibido,
              cabeceras=ctx.admin),
        Sonda("S6", "S6 administradora en predicción", "GET", f"/predictions/{prediccion}", _prohibido,
              cabeceras=ctx.admin),
        Sonda("S6", "S6 administradora en reporte", "POST", f"/predictions/{prediccion}/report", _prohibido,
              cabeceras=ctx.admin),
        Sonda("S6", "S6 control: médica en el mismo paciente", "GET", f"/patients/{paciente}",
              lambda r: _error_uniforme(r, 404, {"patient_not_found"}), cabeceras=m),
    ]
    return s5 + s6


def _entradas(ctx: Contexto) -> list[Sonda]:
    m = ctx.medico
    s8 = [
        Sonda("S8", f"S8 id no UUID: {nombre}", "GET", f"/patients/{valor}",
              lambda r, crudo=crudo: _error_uniforme(r, 422, {"validation_error"}, [crudo]), cabeceras=m)
        for nombre, valor, crudo in (
            ("texto", "abcdef", "abcdef"),
            ("SQL", "1%20OR%201%3D1", "1 OR 1=1"),
            ("comilla", "%27%3B--", "';--"),
            ("largo", "z" * 200, "z" * 200),
        )
    ]
    sql = "Robert'); DROP TABLE gynfem.patients;--"
    html = "<img src=x onerror=alert(1)>"
    s9 = [
        Sonda("S9", f"S9 búsqueda literal: {nombre}", "POST", "/patients/search", _busqueda_vacia,
              _json({"name": valor}), {**m, **JSON})
        for nombre, valor in (("comilla", "O'Brienzq'--"), ("comodín %", "zq%x%w"), ("comodín _", "zq_x_w"))
    ] + [
        Sonda("S9", f"S9 nombre con {nombre} rechazado", "PATCH", f"/patients/{uuid.uuid4()}",
              lambda r, valor=valor: _error_uniforme(r, 422, {"validation_error"}, [valor]),
              _json({"given_names": valor}), {**m, **JSON})
        for nombre, valor in (("SQL", sql), ("HTML", html))
    ]
    return s8 + s9


def _errores(ctx: Contexto) -> list[Sonda]:
    m = ctx.medico
    enorme = _json({**ENTRADA_NORMAL, "age_years": "9" * 200_000})
    s11 = [
        Sonda("S11", "S11 ruta inexistente", "GET", "/no-existe", lambda r: _error_uniforme(r, 404, {"not_found"})),
        Sonda("S11", "S11 método no admitido", "PUT", "/health",
              lambda r: _error_uniforme(r, 405, {"method_not_allowed"})),
        Sonda("S11", "S11 JSON mal formado", "POST", "/predict",
              lambda r: _error_uniforme(r, 422, {"validation_error"}), b'{"age_years": 28,', {**m, **JSON}),
        Sonda("S11", "S11 cuerpo enorme", "POST", "/predict",
              lambda r: _error_uniforme(r, 422, {"validation_error"}, ["9" * 64]), enorme, {**m, **JSON}),
        Sonda("S11", "S11 tipo de contenido ajeno", "POST", "/predict",
              lambda r: _error_uniforme(r, 422, {"validation_error"}), b"<xml/>", {**m, "Content-Type": "text/xml"}),
    ]
    s12 = [
        Sonda("S12", "S12 preflight desde un origen ajeno", "OPTIONS", "/me", _sin_cors_ajeno(400),
              cabeceras={"Origin": ORIGEN_AJENO, "Access-Control-Request-Method": "GET",
                         "Access-Control-Request-Headers": "authorization"}),
        Sonda("S12", "S12 GET desde un origen ajeno", "GET", "/health", _sin_cors_ajeno(200),
              cabeceras={"Origin": ORIGEN_AJENO}),
    ]
    return s11 + s12


def construir_sondas(ctx: Contexto) -> list[Sonda]:
    return _autenticacion(ctx) + _autorizacion(ctx) + _entradas(ctx) + _errores(ctx)


# --- Ejecución -------------------------------------------------------------------------------


def _detenido(motivo: str) -> int:
    print(f"DETENIDO — {motivo}. No se envió ninguna sonda.", flush=True)
    return 1


def _iniciar_sesion(http: Http, variables: dict[str, str], cuenta: str) -> tuple[str | None, int]:
    r = http(
        "POST", f"{variables['GYNFEM_SUPABASE_URL'].rstrip('/')}/auth/v1/token?grant_type=password",
        _json({"email": variables[f"GYNFEM_SMOKE_{cuenta}_EMAIL"],
               "password": variables[f"GYNFEM_SMOKE_{cuenta}_PASSWORD"]}),
        {"apikey": variables["GYNFEM_SUPABASE_PUBLISHABLE_KEY"], **JSON},
    )
    token = (r.json() or {}).get("access_token") if r.estado == 200 else None
    return (token if isinstance(token, str) and token else None), r.estado


def _preparar(http: Http, api: str, variables: dict[str, str]) -> Contexto | str:
    """Despierta el servicio, comprueba la versión y que cada cuenta tiene su rol; o el motivo para no seguir."""
    base = api.rstrip("/") + PREFIJO
    r = http("GET", f"{base}/health")
    version = (r.json() or {}).get("version") if isinstance(r.json(), dict) else None
    print(f"salud: estado {r.estado}, versión {_seguro(version)}", flush=True)
    if r.estado != 200 or version != __version__:
        return f"la versión desplegada no es la local ({__version__})"
    cabeceras = {}
    for identidad, cuenta in (("medico", "MEDICO"), ("administrador", "ADMIN")):
        token, estado = _iniciar_sesion(http, variables, cuenta)
        if token is None:
            return f"inicio de sesión de la cuenta {identidad}: estado {estado}"
        cabeceras[identidad] = {"Authorization": f"Bearer {token}"}
        r = http("GET", f"{base}/me", None, cabeceras[identidad])
        rol = (r.json() or {}).get("role") if isinstance(r.json(), dict) else None
        if r.estado != 200 or rol != identidad:
            return f"la cuenta {identidad} no tiene ese rol (estado {r.estado}, rol {_seguro(rol)})"
    return Contexto(base=base, supabase_url=variables["GYNFEM_SUPABASE_URL"],
                    medico=cabeceras["medico"], admin=cabeceras["administrador"])


def _registro(sonda: Sonda, r: Respuesta, ok: bool) -> dict:
    cuerpo = r.json()
    error = cuerpo.get("error") if isinstance(cuerpo, dict) else None
    error = error if isinstance(error, dict) else {}
    return {
        "caso": sonda.caso, "nombre": sonda.nombre, "metodo": sonda.metodo, "estado": r.estado,
        "codigo": _seguro(error["code"]) if "code" in error else None,
        "request_id": _seguro(error["request_id"]) if "request_id" in error else None, "ok": ok,
        "diagnostico": diagnostico(r),
    }


def ejecutar(api: str, variables: dict[str, str], http: Http, salida: Path, solo: Sequence[str] = ()) -> int:
    """`solo`: los nombres de las sondas que se envían; vacío, todas."""
    ctx = _preparar(http, api, variables)
    if isinstance(ctx, str):
        return _detenido(ctx)
    sondas = construir_sondas(ctx)
    desconocidas = set(solo) - {s.nombre for s in sondas}
    if desconocidas:
        return _detenido(f"--solo nombra sondas que no existen: {', '.join(sorted(desconocidas))}")
    if solo:
        sondas = [s for s in sondas if s.nombre in solo]
    salida.parent.mkdir(parents=True, exist_ok=True)
    fallos = 0
    with salida.open("w", encoding="utf-8") as evidencia:
        for sonda in sondas:
            r = http(sonda.metodo, ctx.base + sonda.ruta, sonda.cuerpo, sonda.cabeceras)
            registro = _registro(sonda, r, sonda.evaluar(r))
            fallos += not registro["ok"]
            evidencia.write(json.dumps(registro, ensure_ascii=False) + "\n")
            print(f"{'OK   ' if registro['ok'] else 'FALLA'} {sonda.nombre} — "
                  f"estado {r.estado}, {registro['codigo'] or '-'}", flush=True)
    print(f"\n{len(sondas)} sondas, {fallos} fallos. Evidencia: {salida.name}", flush=True)
    return 0 if fallos == 0 else 1


def main(argv: Sequence[str] | None = None, http: Http | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ops.sondas_seguridad",
        description="Sondas de seguridad contra la API desplegada. No escribe nada.",
    )
    parser.add_argument("--url", required=True, help="URL pública del servicio: https://<servicio>.onrender.com")
    parser.add_argument("--env-file", type=Path, help="lee las variables de este archivo en vez del entorno")
    parser.add_argument("--salida", type=Path, help="evidencia JSONL (por defecto, en reports/fase17/)")
    parser.add_argument("--solo", action="append", default=[], metavar="NOMBRE",
                        help="envía solo la sonda con este nombre (repetible)")
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
    salida = args.salida or CARPETA_DE_EVIDENCIAS / f"sondas_seguridad_{marca}.jsonl"
    try:
        return ejecutar(args.url, variables, http or http_real, salida, args.solo)
    except Exception as exc:  # noqa: BLE001 — el mensaje de una excepción puede llevar una credencial
        print(f"FALLA error inesperado — {type(exc).__name__}; las sondas no terminaron.", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
