"""RBAC sobre todas las rutas (HU001, decisiones aprobadas 4–9).

La matriz rol × endpoint vive en `docs/API_SPEC.md` y en el código. Estos tests
recorren la **lista real de rutas** de la aplicación: una ruta nueva sin
decisión de acceso, o una que no coincide con la matriz documentada, hace fallar
la suite. El rol y el estado salen del directorio en memoria (`auth_claves.py`);
la suite de base de datos repite lo esencial contra PostgreSQL.
"""

import logging
import re
import time

import pytest
from fastapi import Depends

from .api_constantes import ENTRADA_NORMAL, ORIGEN_LOCAL, REPO_ROOT
from .auth_claves import (
    ADMIN_ID,
    ADMIN_INACTIVO_ID,
    ADMINISTRADOR,
    MEDICO,
    MEDICO_ID,
    MEDICO_INACTIVO_ID,
    ROLES,
    SIN_PERFIL_ID,
    USUARIO_DE,
    cabecera,
)

API_SPEC = REPO_ROOT / "docs" / "API_SPEC.md"
UUID_DE_EJEMPLO = "00000000-0000-4000-8000-000000000000"
PARAMETRO = re.compile(r"\{\w+\}")
PERMITIDO = "✔"


# --- La matriz documentada y la efectiva ---------------------------------------------


def matriz_documentada() -> dict[tuple[str, str], frozenset[str] | None]:
    """(método, ruta) → roles permitidos, o `None` si es pública. Tabla entre los marcadores de API_SPEC."""
    texto = API_SPEC.read_text(encoding="utf-8")
    bloque = texto.split("<!-- matriz-rbac:inicio -->")[1].split("<!-- matriz-rbac:fin -->")[0]
    matriz = {}
    for linea in bloque.strip().splitlines()[2:]:
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        metodo, ruta, anonimo, medico, administrador = (c.strip("`") for c in celdas[:5])
        if anonimo == PERMITIDO:
            assert medico == administrador == PERMITIDO, f"{metodo} {ruta}: una pública admite a todos"
            matriz[(metodo, ruta)] = None
        else:
            matriz[(metodo, ruta)] = frozenset(
                rol for rol, celda in ((MEDICO, medico), (ADMINISTRADOR, administrador)) if celda == PERMITIDO
            )
    return matriz


def rutas_de(app) -> list:
    """Todas las rutas, también las incluidas con `include_router` (FastAPI ≥ 0.141)."""
    rutas = []
    for ruta in app.routes:
        contextos = getattr(ruta, "effective_route_contexts", None)
        if contextos is not None:
            rutas.extend(contextos() if callable(contextos) else contextos)
        else:
            rutas.append(ruta)
    return rutas


def declaraciones(dependant) -> list:
    from app.api.access import Publica, Requiere

    encontradas = [dependant.call] if isinstance(dependant.call, (Publica, Requiere)) else []
    for sub in dependant.dependencies:
        encontradas.extend(declaraciones(sub))
    return encontradas


def matriz_efectiva(app) -> dict[tuple[str, str], frozenset[str] | None]:
    from app.api.access import RUTAS_DE_DOCUMENTACION, Publica

    matriz = {}
    for ruta in rutas_de(app):
        if hasattr(ruta, "dependant"):
            decl = declaraciones(ruta.dependant)
            assert len(decl) == 1, f"{sorted(ruta.methods)} {ruta.path}: {len(decl)} decisiones de acceso, se exige una"
            politica = None if isinstance(decl[0], Publica) else frozenset(decl[0].roles)
            for metodo in ruta.methods:
                matriz[(metodo, ruta.path)] = politica
        else:
            assert ruta.path in RUTAS_DE_DOCUMENTACION, f"{ruta.path}: ruta sin decisión de acceso"
            for metodo in set(getattr(ruta, "methods", None) or {"GET"}) - {"HEAD"}:
                matriz[(metodo, ruta.path)] = None
    return matriz


@pytest.fixture
def app_de(configurar, modelo_real, verificador, directorio):
    from app.factory import create_app

    def _crear(environment: str):
        origen = ORIGEN_LOCAL if environment != "production" else "https://gynfem.example"
        configurar(environment=environment, cors_origins=origen)
        app = create_app(model=modelo_real, token_verifier=verificador, user_directory=directorio)
        logging.getLogger("gynfem").handlers.clear()
        return app

    return _crear


@pytest.mark.parametrize("entorno", ["development", "production"])
def test_toda_ruta_tiene_una_sola_decision_de_acceso(entorno, app_de):
    """Recorre la lista real de rutas: una ruta nueva sin decisión hace fallar la suite."""
    assert len(matriz_efectiva(app_de(entorno))) >= 20


def test_matriz_de_api_spec_coincide_con_las_rutas_reales(app_de):
    assert matriz_efectiva(app_de("development")) == matriz_documentada()


def test_en_produccion_solo_falta_la_documentacion_interactiva(app_de):
    documentada = matriz_documentada()
    efectiva = matriz_efectiva(app_de("production"))

    assert set(documentada) - set(efectiva) == {("GET", "/api/v1/openapi.json"), ("GET", "/api/v1/docs")}
    assert all(documentada[clave] == politica for clave, politica in efectiva.items())


def test_las_publicas_son_exactamente_las_aprobadas_y_tienen_motivo(app_de):
    from app.api.access import RUTAS_DE_DOCUMENTACION

    publicas = {clave for clave, politica in matriz_efectiva(app_de("development")).items() if politica is None}
    assert publicas == {("GET", "/api/v1/health"), ("GET", "/api/v1/openapi.json"), ("GET", "/api/v1/docs")}
    for ruta in rutas_de(app_de("development")):
        if hasattr(ruta, "dependant") and ruta.path == "/api/v1/health":
            assert declaraciones(ruta.dependant)[0].motivo.strip()
    assert all(motivo.strip() for motivo in RUTAS_DE_DOCUMENTACION.values())


def rutas_protegidas() -> list[tuple[str, str, frozenset[str]]]:
    return sorted(
        (metodo, ruta, roles) for (metodo, ruta), roles in matriz_documentada().items() if roles is not None
    )


def pedir(cliente, metodo: str, ruta: str, **kwargs):
    url = PARAMETRO.sub(UUID_DE_EJEMPLO, ruta)
    if metodo in ("POST", "PATCH"):
        kwargs.setdefault("json", {})
    return cliente.request(metodo, url, **kwargs)


# --- 401: sin credenciales o con credenciales inválidas --------------------------------


def test_sin_token_401_en_toda_ruta_protegida(crear_cliente):
    cliente = crear_cliente(rol=None)
    for metodo, ruta, _ in rutas_protegidas():
        respuesta = pedir(cliente, metodo, ruta)
        assert respuesta.status_code == 401, f"{metodo} {ruta}"
        assert respuesta.json()["error"]["code"] == "not_authenticated", f"{metodo} {ruta}"
        assert respuesta.headers["www-authenticate"] == "Bearer", f"{metodo} {ruta}"


@pytest.mark.parametrize("valor", ["Basic dXN1YXJpbzpjbGF2ZQ==", "Bearer", "Bearer ", "Token abc", "abc"])
def test_cabecera_malformada_401(valor, crear_cliente):
    respuesta = crear_cliente(rol=None).post("/api/v1/predict", json=ENTRADA_NORMAL, headers={"Authorization": valor})

    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] in {"not_authenticated", "invalid_token"}


def test_token_invalido_401_invalid_token(crear_cliente, emisor):
    token = emisor.token(MEDICO_ID, iss="https://otro-proyecto.supabase.co/auth/v1")
    respuesta = crear_cliente(rol=None).post("/api/v1/predict", json=ENTRADA_NORMAL, headers=cabecera(token))

    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "invalid_token"
    assert respuesta.headers["www-authenticate"] == "Bearer"


def test_token_caducado_401_token_expired(crear_cliente, emisor):
    ahora = int(time.time())
    token = emisor.token(MEDICO_ID, iat=ahora - 3720, exp=ahora - 120)
    respuesta = crear_cliente(rol=None).post("/api/v1/predict", json=ENTRADA_NORMAL, headers=cabecera(token))

    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "token_expired"


def test_401_antes_que_422(crear_cliente):
    """Sin credenciales no se valida el cuerpo: la respuesta no dice nada del esquema."""
    cliente = crear_cliente(rol=None)

    assert cliente.post("/api/v1/predict", json={"campo": "inválido"}).status_code == 401
    assert cliente.post("/api/v1/patients", json={}).status_code == 401


def test_jwks_inaccesible_503_auth_unavailable(crear_cliente, emisor):
    from app.auth.tokens import JwksKeySource, TokenVerifier
    from .auth_claves import EMISOR_FICTICIO

    verificador = TokenVerifier(JwksKeySource("http://127.0.0.1:1", timeout_s=1), EMISOR_FICTICIO)
    respuesta = crear_cliente(token_verifier=verificador).post("/api/v1/predict", json=ENTRADA_NORMAL)

    assert respuesta.status_code == 503
    assert respuesta.json()["error"]["code"] == "auth_unavailable"


# --- 403: autenticado sin permiso -----------------------------------------------------


def test_rol_insuficiente_403_en_toda_ruta(crear_cliente):
    clientes = {rol: crear_cliente(rol=rol) for rol in ROLES}
    for metodo, ruta, roles in rutas_protegidas():
        for rol in set(ROLES) - roles:
            respuesta = pedir(clientes[rol], metodo, ruta)
            assert respuesta.status_code == 403, f"{rol} en {metodo} {ruta}"
            assert respuesta.json()["error"]["code"] == "forbidden", f"{rol} en {metodo} {ruta}"


def test_rol_permitido_supera_la_autorizacion_en_toda_ruta(crear_cliente):
    """Lo que responda después (422, 404, 503…) es de la ruta, no de la autorización."""
    clientes = {rol: crear_cliente(rol=rol) for rol in ROLES}
    for metodo, ruta, roles in rutas_protegidas():
        for rol in roles:
            assert pedir(clientes[rol], metodo, ruta).status_code not in (401, 403), f"{rol} en {metodo} {ruta}"


@pytest.mark.parametrize("usuario", [MEDICO_INACTIVO_ID, ADMIN_INACTIVO_ID, SIN_PERFIL_ID])
def test_usuario_desactivado_o_sin_perfil_con_token_valido_403(usuario, crear_cliente, emisor):
    cliente = crear_cliente(rol=None)
    cliente.headers.update(cabecera(emisor.token(usuario)))
    for metodo, ruta in (("POST", "/api/v1/predict"), ("GET", "/api/v1/users"), ("GET", "/api/v1/me")):
        respuesta = pedir(cliente, metodo, ruta)
        assert respuesta.status_code == 403, f"{metodo} {ruta}"
        assert respuesta.json()["error"]["code"] == "account_disabled"


def test_desactivacion_efectiva_en_la_siguiente_peticion(crear_cliente, directorio):
    """El estado se consulta en cada petición: el mismo token deja de servir al instante."""
    cliente = crear_cliente(rol=MEDICO)
    assert cliente.post("/api/v1/predict", json=ENTRADA_NORMAL).status_code == 200

    directorio.usuarios[MEDICO_ID].is_active = False
    assert cliente.post("/api/v1/predict", json=ENTRADA_NORMAL).status_code == 403

    directorio.usuarios[MEDICO_ID].is_active = True
    assert cliente.post("/api/v1/predict", json=ENTRADA_NORMAL).status_code == 200


def test_cambio_de_rol_efectivo_en_la_siguiente_peticion(crear_cliente, directorio):
    cliente = crear_cliente(rol=MEDICO)
    assert cliente.get("/api/v1/users").status_code == 403

    directorio.usuarios[MEDICO_ID].role = ADMINISTRADOR
    assert cliente.get("/api/v1/users").status_code not in (401, 403)


def test_rol_declarado_en_el_token_se_ignora(crear_cliente, emisor):
    """El rol sale de la base, nunca del token, aunque el token lo declare en cualquier claim."""
    token = emisor.token(
        MEDICO_ID,
        role=ADMINISTRADOR,
        app_metadata={"role": ADMINISTRADOR},
        user_metadata={"role": ADMINISTRADOR},
        user_role=ADMINISTRADOR,
    )
    cliente = crear_cliente(rol=None)
    cliente.headers.update(cabecera(token))

    assert cliente.get("/api/v1/users").status_code == 403
    assert cliente.get("/api/v1/me").json()["role"] == MEDICO


def test_rol_o_identidad_en_el_cuerpo_o_en_cabeceras_no_eleva(crear_cliente):
    cliente = crear_cliente(rol=MEDICO)
    suplantacion = {"X-User-Role": ADMINISTRADOR, "X-User-Id": str(ADMIN_ID), "X-Role": ADMINISTRADOR}

    assert cliente.get("/api/v1/users", headers=suplantacion).status_code == 403
    assert cliente.get("/api/v1/users", params={"role": ADMINISTRADOR, "user_id": str(ADMIN_ID)}).status_code == 403
    respuesta = cliente.post("/api/v1/predict", json={**ENTRADA_NORMAL, "role": ADMINISTRADOR})
    assert respuesta.status_code == 422
    assert {"loc": ["body", "role"], "type": "extra_forbidden"} in respuesta.json()["error"]["details"]
    assert cliente.get("/api/v1/me", headers=suplantacion).json()["id"] == str(MEDICO_ID)


# --- Públicas y cierre por defecto ------------------------------------------------------


def test_health_no_exige_ni_valida_token(crear_cliente):
    cliente = crear_cliente(rol=None)

    assert cliente.get("/api/v1/health").status_code == 200
    assert cliente.get("/api/v1/health", headers={"Authorization": "Bearer basura"}).status_code == 200


def test_ruta_que_pide_el_actor_sin_decision_de_acceso_falla_cerrada(crear_cliente):
    """Si una ruta futura olvida su decisión pero usa el actor, no se sirve."""
    from app.api.deps import Actor, get_actor

    cliente = crear_cliente(rol=MEDICO)

    @cliente.app.get("/api/v1/_test/sin-decision")
    def sin_decision(actor: Actor = Depends(get_actor)):
        return {"ok": True}

    respuesta = cliente.get("/api/v1/_test/sin-decision")
    assert respuesta.status_code == 500
    assert respuesta.json()["error"]["code"] == "internal_error"


def test_me_devuelve_el_usuario_del_token_y_su_rol_de_la_base(crear_cliente, directorio):
    """Solo id y rol: un usuario que llega a responder está, por definición, activo."""
    for rol in ROLES:
        cliente = crear_cliente(rol=rol)
        assert cliente.get("/api/v1/me").json() == {"id": str(USUARIO_DE[rol]), "role": rol}
        assert directorio.consultas[-1] == USUARIO_DE[rol]


def test_openapi_declara_el_esquema_bearer(crear_cliente):
    esquema = crear_cliente(rol=None).get("/api/v1/openapi.json").json()

    assert any(s.get("scheme") == "bearer" for s in esquema["components"]["securitySchemes"].values())
