"""Configuración: solo variables de entorno, validadas al arrancar."""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from .api_constantes import ORIGEN_LOCAL, REPO_ROOT, URL_BD_FICTICIA

ENV_EXAMPLE = REPO_ROOT / ".env.example"


def test_configuracion_valida_se_carga(configurar):
    from app.core.config import load_settings

    configurar(environment="development", cors_origins=ORIGEN_LOCAL)
    settings = load_settings()

    assert settings.environment == "development"
    assert list(settings.cors_origins) == [ORIGEN_LOCAL]
    assert settings.log_level == "INFO"


def test_varios_origenes_separados_por_comas(configurar):
    from app.core.config import load_settings

    configurar(environment="development", cors_origins="http://localhost:5173, http://127.0.0.1:3000")

    assert list(load_settings().cors_origins) == ["http://localhost:5173", "http://127.0.0.1:3000"]


CONFIGURACION_COMPLETA = {
    "GYNFEM_ENVIRONMENT": "development",
    "GYNFEM_CORS_ORIGINS": ORIGEN_LOCAL,
    "GYNFEM_DATABASE_URL": URL_BD_FICTICIA,
}


@pytest.mark.parametrize("faltante", list(CONFIGURACION_COMPLETA))
def test_falta_variable_obligatoria_falla_al_crear_la_app(faltante, monkeypatch):
    from app.core.config import ConfigurationError
    from app.factory import create_app

    completas = CONFIGURACION_COMPLETA
    for clave, valor in completas.items():
        if clave != faltante:
            monkeypatch.setenv(clave, valor)

    with pytest.raises(ConfigurationError) as error:
        create_app()
    assert faltante in str(error.value)


def _importar_main(env_extra: dict[str, str], cwd: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GYNFEM_")}
    env.update(env_extra)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("faltante", ["GYNFEM_CORS_ORIGINS", "GYNFEM_DATABASE_URL"])
def test_arranque_real_falla_sin_variable_obligatoria(faltante, tmp_path):
    """Lo que ejecuta uvicorn al arrancar: importar `app.main` sin configuración completa."""
    incompleta = {k: v for k, v in CONFIGURACION_COMPLETA.items() if k != faltante}
    resultado = _importar_main(incompleta, tmp_path)

    assert resultado.returncode == 1
    assert faltante in resultado.stderr
    assert "Traceback" not in resultado.stderr


def test_arranque_real_funciona_con_configuracion_completa(tmp_path):
    """Importar la aplicación no conecta con la base: el pool se abre en el ciclo de vida."""
    resultado = _importar_main(CONFIGURACION_COMPLETA, tmp_path)

    assert resultado.returncode == 0, resultado.stderr


@pytest.mark.parametrize("origenes", ["*", "http://localhost:5173,*"])
def test_comodin_se_rechaza(origenes, configurar):
    from app.core.config import ConfigurationError, load_settings

    configurar(environment="development", cors_origins=origenes)
    with pytest.raises(ConfigurationError) as error:
        load_settings()
    assert "GYNFEM_CORS_ORIGINS" in str(error.value)
    assert "comodín" in str(error.value), "el rechazo del comodín debe decirlo con claridad"


@pytest.mark.parametrize("origen", ["https://*.vercel.app", "https://*"])
def test_comodin_en_el_host_se_rechaza_en_produccion(origen, configurar):
    """CORSMiddleware compararía `*.vercel.app` literalmente: nunca coincidiría,
    pero quien lo escribe cree haber abierto las previews de Vercel."""
    from app.core.config import ConfigurationError, load_settings

    configurar(environment="production", cors_origins=origen)
    with pytest.raises(ConfigurationError) as error:
        load_settings()
    assert "comodín" in str(error.value)


def test_en_desarrollo_se_rechaza_un_origen_que_no_es_localhost(configurar):
    from app.core.config import ConfigurationError, load_settings

    configurar(environment="development", cors_origins="https://gynfem.vercel.app")
    with pytest.raises(ConfigurationError):
        load_settings()


@pytest.mark.parametrize(
    "origen", ["http://localhost", "http://localhost:5173", "http://127.0.0.1:8000"]
)
def test_en_desarrollo_se_admite_localhost_con_cualquier_puerto(origen, configurar):
    from app.core.config import load_settings

    configurar(environment="development", cors_origins=origen)
    assert list(load_settings().cors_origins) == [origen]


@pytest.mark.parametrize(
    "origen", ["http://gynfem.vercel.app", "https://localhost:5173", "http://localhost:5173"]
)
def test_en_produccion_se_exige_https_y_no_localhost(origen, configurar):
    from app.core.config import ConfigurationError, load_settings

    configurar(environment="production", cors_origins=origen)
    with pytest.raises(ConfigurationError):
        load_settings()


def test_en_produccion_se_admite_un_origen_https(configurar):
    from app.core.config import load_settings

    configurar(environment="production", cors_origins="https://gynfem.vercel.app")
    assert list(load_settings().cors_origins) == ["https://gynfem.vercel.app"]


@pytest.mark.parametrize(
    "origen",
    [
        "localhost:5173",
        "http://localhost:5173/app",
        "http://localhost:5173/",
        "null",
        "ftp://localhost",
        "http://localhost:5173?x=1",
        "",
        "http://LOCALHOST:5173",
        "http://@localhost",
        "http://usuario:clave@localhost",
        "http://localhost:abc",
        "http://localhost:99999",
        "http://[::1]:5173",
        "http://localhost.evil.com",
    ],
)
def test_origen_malformado_se_rechaza(origen, configurar):
    from app.core.config import ConfigurationError, load_settings

    configurar(environment="development", cors_origins=origen)
    with pytest.raises(ConfigurationError):
        load_settings()


def test_entorno_invalido_se_rechaza(configurar):
    from app.core.config import ConfigurationError, load_settings

    configurar(environment="prod", cors_origins=ORIGEN_LOCAL)
    with pytest.raises(ConfigurationError) as error:
        load_settings()
    assert "GYNFEM_ENVIRONMENT" in str(error.value)


def test_mensaje_de_configuracion_no_repite_el_valor(configurar):
    """Hoy ninguna variable es secreta; desde la Fase 9 alguna lo será."""
    from app.core.config import ConfigurationError, load_settings

    valor = "https://valor-que-no-debe-repetirse.example"
    configurar(environment="development", cors_origins=valor)
    with pytest.raises(ConfigurationError) as error:
        load_settings()
    assert "GYNFEM_CORS_ORIGINS" in str(error.value)
    assert "valor-que-no-debe-repetirse" not in str(error.value)


def _leer_env_example() -> dict[str, str]:
    variables = {}
    for linea in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        clave, _, valor = linea.partition("=")
        variables[clave.strip()] = valor.strip()
    return variables


def test_env_example_declara_exactamente_las_variables_de_settings():
    """Las de la aplicación y la del runner de migraciones, que la aplicación no lee."""
    from app.core.config import Settings
    from app.db.migrate import MIGRATIONS_ENV_VAR

    esperadas = {f"GYNFEM_{campo.upper()}" for campo in Settings.model_fields}
    assert set(_leer_env_example()) == esperadas | {MIGRATIONS_ENV_VAR}


def test_env_example_es_una_configuracion_valida_y_solo_local(monkeypatch):
    from app.core.config import load_settings

    variables = _leer_env_example()
    for clave, valor in variables.items():
        monkeypatch.setenv(clave, valor)
    settings = load_settings()

    locales = {"localhost", "127.0.0.1"}
    assert settings.environment == "development"
    assert all(urlsplit(o).hostname in locales for o in settings.cors_origins)
    assert urlsplit(settings.database_url.get_secret_value()).hostname in locales
    assert urlsplit(variables["GYNFEM_MIGRATIONS_DATABASE_URL"]).hostname in locales


def test_env_example_comenta_cada_variable():
    lineas = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    for i, linea in enumerate(lineas):
        if linea.strip() and not linea.lstrip().startswith("#"):
            assert i > 0 and lineas[i - 1].lstrip().startswith("#"), (
                f"la variable de la línea {i + 1} no tiene comentario encima"
            )
