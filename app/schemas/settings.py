"""Entrada y salida de la configuración de parámetros (HU011).

Esquema estricto y cerrado: solo las claves del catálogo
(`app/services/settings_catalog.py`), cada una con su tipo y su rango. Una clave
desconocida, un valor fuera de rango o un cuerpo vacío dan 422 sin escribir
nada. El 422 nunca repite el valor recibido (`docs/API_SPEC.md` §2.5).
"""

import unicodedata
from datetime import datetime
from typing import Annotated, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.schemas.patients import Texto
from app.services.settings_catalog import HISTORY_PAGE_SIZE_MAX, HISTORY_PAGE_SIZE_MIN, INSTITUTION_NAME_MAX

#: Separadores de línea y de párrafo: no son de control (`C*`), pero parten el texto.
_SEPARADORES_DE_LINEA = frozenset({"Zl", "Zp"})

T = TypeVar("T")


def _es_de_control(caracter: str) -> bool:
    """Control, formato (ancho cero, inversión de dirección), sustitutos, uso privado y sin asignar."""
    categoria = unicodedata.category(caracter)
    return categoria.startswith("C") or categoria in _SEPARADORES_DE_LINEA


def normalizar_nombre_de_institucion(valor: str) -> str:
    # NFC: «Clínica» con la tilde combinante (NFD) es el mismo nombre.
    normalizado = unicodedata.normalize("NFC", valor)
    # Antes de recortar: un salto de línea o un tabulador no se convierten en un espacio.
    if any(_es_de_control(c) for c in normalizado):
        raise PydanticCustomError("control_character", "El nombre no admite caracteres de control.")
    limpio = " ".join(normalizado.split())
    if not 1 <= len(limpio) <= INSTITUTION_NAME_MAX:
        raise PydanticCustomError(
            "institution_name_length", f"El nombre debe tener de 1 a {INSTITUTION_NAME_MAX} caracteres."
        )
    return limpio


class SettingsUpdate(BaseModel):
    """Cambio de uno o más parámetros. Solo las claves del catálogo."""

    model_config = ConfigDict(extra="forbid")

    institution_name: Texto | None = None
    history_default_page_size: (
        Annotated[int, Field(strict=True, ge=HISTORY_PAGE_SIZE_MIN, le=HISTORY_PAGE_SIZE_MAX)] | None
    ) = None

    @field_validator("institution_name")
    @classmethod
    def _nombre(cls, valor: str | None) -> str | None:
        return None if valor is None else normalizar_nombre_de_institucion(valor)

    @model_validator(mode="after")
    def _al_menos_una_clave(self) -> "SettingsUpdate":
        if not self.model_fields_set:
            raise PydanticCustomError("empty_update", "Indique al menos un parámetro.")
        if any(getattr(self, clave) is None for clave in self.model_fields_set):
            raise PydanticCustomError("null_field", "Un parámetro no puede ser nulo.")
        return self


class SettingOut(BaseModel, Generic[T]):
    value: T
    default: T
    #: Nulos mientras rige el valor por defecto: nadie lo ha cambiado.
    updated_at: datetime | None
    updated_by: UUID | None


class SettingsOut(BaseModel):
    institution_name: SettingOut[str]
    history_default_page_size: SettingOut[int]
