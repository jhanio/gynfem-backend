"""Configuración de la base de datos: obligatoria, validada y nunca repetida.

`GYNFEM_DATABASE_URL` lleva la contraseña de la base: ningún mensaje, `repr`
ni volcado de la configuración puede contenerla.
"""

import pytest

from .api_constantes import ORIGEN_LOCAL

CLAVE_CENTINELA = "clave-centinela-9f3a"
URL_CON_CLAVE = f"postgresql://postgres:{CLAVE_CENTINELA}@localhost:5432/gynfem"


def _cargar(configurar, **variables):
    from app.core.config import load_settings

    configurar(**{"environment": "development", "cors_origins": ORIGEN_LOCAL, **variables})
    return load_settings()


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:5432/gynfem",
        "mysql://localhost:5432/gynfem",
        "postgresql:///gynfem",
        "postgresql://localhost:5432",
        "postgresql://localhost:5432/",
        "localhost:5432/gynfem",
        "",
        "postgresql://localhost:abc/gynfem",
    ],
)
def test_database_url_invalida_se_rechaza(url, configurar):
    from app.core.config import ConfigurationError

    with pytest.raises(ConfigurationError) as error:
        _cargar(configurar, database_url=url)
    assert "GYNFEM_DATABASE_URL" in str(error.value)


@pytest.mark.parametrize("esquema", ["postgresql", "postgres"])
def test_database_url_valida_se_acepta(esquema, configurar):
    settings = _cargar(configurar, database_url=f"{esquema}://u:p@localhost:6543/postgres")
    assert settings.database_url.get_secret_value() == f"{esquema}://u:p@localhost:6543/postgres"


@pytest.mark.parametrize(
    "url",
    [
        f"mysql://postgres:{CLAVE_CENTINELA}@localhost:5432/gynfem",
        f"postgresql://postgres:{CLAVE_CENTINELA}@localhost:5432",
        f"postgresql://postgres:{CLAVE_CENTINELA}@localhost:xyz/gynfem",
    ],
)
def test_mensaje_no_repite_la_database_url(url, configurar):
    from app.core.config import ConfigurationError

    with pytest.raises(ConfigurationError) as error:
        _cargar(configurar, database_url=url)
    assert "GYNFEM_DATABASE_URL" in str(error.value)
    assert CLAVE_CENTINELA not in str(error.value)
    assert "localhost" not in str(error.value)


@pytest.mark.parametrize("sufijo", ["", "?sslmode=disable", "?sslmode=prefer", "?sslmode=allow"])
def test_en_produccion_se_exige_ssl(sufijo, configurar):
    from app.core.config import ConfigurationError, load_settings

    configurar(
        environment="production",
        cors_origins="https://gynfem.vercel.app",
        database_url=f"{URL_CON_CLAVE}{sufijo}",
    )
    with pytest.raises(ConfigurationError) as error:
        load_settings()
    assert "GYNFEM_DATABASE_URL" in str(error.value)
    assert "sslmode" in str(error.value)
    assert CLAVE_CENTINELA not in str(error.value)


@pytest.mark.parametrize("modo", ["require", "verify-ca", "verify-full"])
def test_en_produccion_se_admite_ssl(modo, configurar):
    from app.core.config import load_settings

    configurar(
        environment="production",
        cors_origins="https://gynfem.vercel.app",
        database_url=f"{URL_CON_CLAVE}?sslmode={modo}",
    )
    assert load_settings().environment == "production"


def test_settings_no_expone_la_url(configurar):
    settings = _cargar(configurar, database_url=URL_CON_CLAVE)

    for volcado in (repr(settings), str(settings), settings.model_dump_json(), str(settings.model_dump())):
        assert CLAVE_CENTINELA not in volcado
    assert settings.database_url.get_secret_value() == URL_CON_CLAVE


def test_opcionales_del_pool_tienen_valores_por_defecto(configurar):
    settings = _cargar(configurar)

    assert settings.db_pool_min_size == 1
    assert settings.db_pool_max_size == 5
    assert settings.db_connect_timeout_s == 5
    assert settings.db_pool_timeout_s == 5.0
    assert settings.db_statement_timeout_ms == 5000


@pytest.mark.parametrize(
    "variable, valor",
    [
        ("db_pool_min_size", "0"),
        ("db_pool_max_size", "0"),
        ("db_pool_max_size", "abc"),
        ("db_connect_timeout_s", "1"),
        ("db_connect_timeout_s", "-5"),
        ("db_pool_timeout_s", "0"),
        ("db_statement_timeout_ms", "0"),
        ("db_statement_timeout_ms", "-1"),
    ],
)
def test_opcional_del_pool_invalido_se_rechaza(variable, valor, configurar):
    from app.core.config import ConfigurationError

    with pytest.raises(ConfigurationError) as error:
        _cargar(configurar, **{variable: valor})
    assert f"GYNFEM_{variable.upper()}" in str(error.value)


def test_minimo_del_pool_no_supera_al_maximo(configurar):
    from app.core.config import ConfigurationError

    with pytest.raises(ConfigurationError) as error:
        _cargar(configurar, db_pool_min_size="6", db_pool_max_size="5")
    assert "GYNFEM_DB_POOL_MAX_SIZE" in str(error.value)


def test_pgserver_solo_en_las_dependencias_de_desarrollo():
    """El PostgreSQL embebido de los tests no se instala en el despliegue."""
    from .api_constantes import REPO_ROOT

    produccion = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    desarrollo = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8").lower()

    assert "pgserver" not in produccion
    assert "pgserver==" in desarrollo
    assert "-r requirements.txt" in desarrollo
    assert "psycopg[binary]==" in produccion and "psycopg-pool==" in produccion
