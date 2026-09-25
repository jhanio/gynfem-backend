"""Configuración de la aplicación, solo desde variables de entorno.

Se valida al arrancar: si falta una variable obligatoria o alguna es inválida,
`load_settings()` lanza `ConfigurationError` antes de atender ninguna petición.
El mensaje nombra la variable, nunca su valor: desde la Fase 9 alguna será un
secreto.

La aplicación no lee `.env`. En local lo carga uvicorn (`--env-file .env`).
"""

from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import ValidationError, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ENV_PREFIX = "GYNFEM_"

#: Raíz del repositorio: las rutas relativas de la configuración se resuelven
#: desde aquí, no desde el directorio de trabajo del proceso.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Hosts que cuentan como «solo localhost» en desarrollo y en test.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


class ConfigurationError(Exception):
    """La configuración del entorno falta o es inválida."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra="ignore", frozen=True)

    #: Sin valor por defecto: cualquiera sería peligroso en algún entorno.
    environment: Literal["development", "test", "production"]
    #: Lista explícita separada por comas. Nunca el comodín.
    cors_origins: Annotated[tuple[str, ...], NoDecode]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    #: Directorio con el `.joblib`, `model_metadata.json` y `feature_ranges.json`.
    model_dir: Path = REPO_ROOT / "models"

    @field_validator("model_dir")
    @classmethod
    def _resolver_desde_la_raiz(cls, valor: Path) -> Path:
        return valor if valor.is_absolute() else REPO_ROOT / valor

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _separar_por_comas(cls, valor: object) -> object:
        if isinstance(valor, str):
            return tuple(o.strip() for o in valor.split(",") if o.strip())
        return valor

    @field_validator("cors_origins")
    @classmethod
    def _validar_origenes(cls, origenes: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        if not origenes:
            raise ValueError("debe contener al menos un origen")
        entorno = info.data.get("environment")
        for origen in origenes:
            _validar_origen(origen, entorno)
        return origenes


def _validar_origen(origen: str, entorno: str | None) -> None:
    """Los mensajes no incluyen el origen: la regla de no repetir valores es general."""
    if "*" in origen:
        raise ValueError("el comodín '*' está prohibido, también dentro del host")
    partes = urlsplit(origen)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise ValueError("cada origen debe ser una URL http(s) con host")
    try:
        puerto = partes.port
    except ValueError:
        raise ValueError("el puerto de un origen debe ser un número entre 0 y 65535") from None
    # `hostname` sale en minúsculas y sin credenciales ni corchetes: si `netloc`
    # difiere, el origen nunca coincidiría con el `Origin` que envía un navegador.
    netloc_esperado = partes.hostname if puerto is None else f"{partes.hostname}:{puerto}"
    if partes.netloc != netloc_esperado or origen != f"{partes.scheme}://{partes.netloc}":
        raise ValueError(
            "un origen es esquema, host en minúsculas y puerto opcional, "
            "sin credenciales, ruta ni query"
        )
    es_local = partes.hostname in LOCAL_HOSTS
    if entorno in ("development", "test") and not es_local:
        raise ValueError("en development y test solo se admiten orígenes localhost")
    if entorno == "production" and (es_local or partes.scheme != "https"):
        raise ValueError("en production solo se admiten orígenes https que no sean localhost")


def load_settings() -> Settings:
    """Lee y valida el entorno. Lanza `ConfigurationError` con un mensaje legible."""
    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigurationError(_describir(exc)) from None


def _describir(exc: ValidationError) -> str:
    lineas = ["Configuración inválida:"]
    for error in exc.errors(include_input=False, include_url=False):
        campo = str(error["loc"][0]) if error["loc"] else "?"
        variable = f"{ENV_PREFIX}{campo.upper()}"
        if error["type"] == "missing":
            motivo = "falta la variable obligatoria"
        elif error["type"] == "value_error":
            motivo = str(error["ctx"]["error"])
        else:
            motivo = error["msg"]
        lineas.append(f"  - {variable}: {motivo}")
    return "\n".join(lineas)
