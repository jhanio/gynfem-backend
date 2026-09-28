"""`render.yaml`: el servicio de Render como código (Fase 12).

El archivo es público y define cómo arranca la API en producción. Estos tests
fijan lo que no puede cambiar sin una decisión: ningún secreto versionado, el
health check que no reinicia en cadena, ninguna migración automática, una sola
rama que despliega y la versión exacta de Python que validó el modelo.
"""

import platform
import shlex

import pytest
import yaml

from .api_constantes import REPO_ROOT

RENDER_YAML = REPO_ROOT / "render.yaml"

#: Variables con secretos o datos del proyecto: solo su nombre en el repositorio.
SIN_VALOR_EN_EL_REPO = {
    "GYNFEM_DATABASE_URL",
    "GYNFEM_SUPABASE_SECRET_KEY",
    "GYNFEM_SUPABASE_URL",
    "GYNFEM_CORS_ORIGINS",
}


@pytest.fixture(scope="module")
def servicio() -> dict:
    datos = yaml.safe_load(RENDER_YAML.read_text(encoding="utf-8"))
    [servicio] = datos["services"]
    return servicio


def variables(servicio: dict) -> dict[str, dict]:
    return {v["key"]: v for v in servicio["envVars"]}


def argumentos_de_arranque(servicio: dict) -> list[str]:
    return shlex.split(servicio["startCommand"])


def test_servicio_web_gratuito_en_oregon_desde_main(servicio):
    assert servicio["type"] == "web"
    assert servicio["runtime"] == "python"
    assert servicio["plan"] == "free"
    assert servicio["region"] == "oregon"
    assert servicio["branch"] == "main"
    assert servicio["autoDeployTrigger"] == "commit"


def test_health_check_publico_y_sin_base(servicio):
    """Nunca /health/ready: exige administrador (401 sin token) y consulta la base,
    así que Render reiniciaría el servicio en bucle o ante una caída de Supabase."""
    assert servicio["healthCheckPath"] == "/api/v1/health"


def test_el_health_check_es_la_ruta_publica_de_la_aplicacion():
    """La ruta del health check existe y es la única pública de la matriz (Fase 11)."""
    from app.api.v1 import health

    rutas = {r.path for r in health.router.routes}
    assert "/health" in rutas


def test_python_fijado_a_la_version_que_valido_el_modelo(servicio):
    assert variables(servicio)["PYTHON_VERSION"]["value"] == "3.12.10"
    assert platform.python_version() == "3.12.10", "el entorno local también debe ser 3.12.10"


def test_produccion_declarada(servicio):
    assert variables(servicio)["GYNFEM_ENVIRONMENT"]["value"] == "production"


def test_ningun_secreto_ni_dato_del_proyecto_versionado(servicio):
    declaradas = variables(servicio)
    for nombre in SIN_VALOR_EN_EL_REPO:
        assert declaradas[nombre] == {"key": nombre, "sync": False}, f"{nombre} no debe llevar valor"


def test_toda_variable_con_valor_es_publica(servicio):
    con_valor = {k for k, v in variables(servicio).items() if "value" in v}
    assert con_valor <= {"PYTHON_VERSION", "GYNFEM_ENVIRONMENT", "GYNFEM_LOG_LEVEL"}


def test_declara_las_variables_obligatorias_de_la_aplicacion(servicio):
    """Si falta una obligatoria en Render, la API no arranca (Fase 7): mejor declararlas todas."""
    from app.core.config import Settings

    obligatorias = {f"GYNFEM_{n.upper()}" for n, c in Settings.model_fields.items() if c.is_required()}
    assert obligatorias <= set(variables(servicio))


def test_la_url_de_migraciones_no_llega_a_render(servicio):
    """Las migraciones se aplican desde la máquina de quien migra, nunca desde el servicio."""
    assert "GYNFEM_MIGRATIONS_DATABASE_URL" not in variables(servicio)


def test_el_arranque_no_migra(servicio):
    for campo in ("buildCommand", "startCommand", "preDeployCommand"):
        assert "migrate" not in servicio.get(campo, ""), campo
    assert "preDeployCommand" not in servicio


def test_build_solo_con_las_dependencias_de_produccion(servicio):
    assert servicio["buildCommand"] == "pip install -r requirements.txt"


def test_arranque_con_uvicorn_un_proceso_y_sin_log_de_acceso(servicio):
    argumentos = argumentos_de_arranque(servicio)

    assert argumentos[:2] == ["uvicorn", "app.main:app"]
    assert argumentos[argumentos.index("--host") + 1] == "0.0.0.0"
    assert argumentos[argumentos.index("--port") + 1] == "$PORT"
    assert argumentos[argumentos.index("--workers") + 1] == "1"
    for bandera in ("--no-access-log", "--no-server-header", "--proxy-headers"):
        assert bandera in argumentos
    for prohibida in ("--reload", "--env-file"):
        assert prohibida not in argumentos


def test_la_configuracion_de_produccion_de_ejemplo_arranca(configurar, modelo_real):
    """Con los valores que se configuran en Render (ficticios aquí), la aplicación arranca:
    CORS con el origen reservado `.invalid` pasa la validación de production."""
    from app.factory import create_app

    configurar(
        environment="production",
        cors_origins="https://gynfem-frontend.invalid",
        database_url="postgresql://usuario@127.0.0.1:1/postgres?sslmode=require",
        supabase_url="https://abcdefghijklmnopqrst.supabase.co",
    )
    app = create_app(model=modelo_real)
    assert app.state.settings.cors_origins == ("https://gynfem-frontend.invalid",)
