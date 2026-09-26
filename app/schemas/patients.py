"""Entrada y salida de pacientes (HU003, HU004).

Identidad mínima (`docs/ERD.md`, decisión A de la Fase 10): tipo y número de
documento, nombres y apellidos. Esquema estricto: sin campos extra, solo texto.
Los mensajes de error nunca repiten el valor recibido (`docs/API_SPEC.md` §2.5).
"""

import re
import unicodedata
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.schemas.pagination import LIMITE_MAXIMO, LIMITE_POR_DEFECTO
from app.services.patients import normalizar_para_busqueda

DocumentType = Literal["DNI", "CE", "PASAPORTE"]

#: DNI: 8 dígitos (RENIEC). CE y pasaporte: regla provisional, pendiente de confirmar con GynFem.
FORMATO_DOCUMENTO = {
    "DNI": re.compile(r"^[0-9]{8}$"),
    "CE": re.compile(r"^[A-Z0-9]{4,20}$"),
    "PASAPORTE": re.compile(r"^[A-Z0-9]{4,20}$"),
}
NOMBRE_MAX = 100
#: Letras (con tildes y ñ), espacios, guion y apóstrofo.
_NOMBRE = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$")

Texto = Annotated[str, StringConstraints(strict=True)]


def _normalizar_nombre(valor: str) -> str:
    # NFC: «José» escrito con una tilde combinante (NFD) es el mismo nombre.
    limpio = " ".join(unicodedata.normalize("NFC", valor).split())
    if not limpio or len(limpio) > NOMBRE_MAX or not _NOMBRE.match(limpio):
        raise PydanticCustomError(
            "name_format", "Solo letras, espacios, guion o apóstrofo; de 1 a 100 caracteres."
        )
    return limpio


def normalizar_documento(numero: str, tipo: str | None) -> str:
    """Sin espacios en los extremos y en mayúsculas; valida el formato de su tipo."""
    limpio = numero.strip().upper()
    formato = FORMATO_DOCUMENTO.get(tipo or "")
    if formato is not None and not formato.match(limpio):
        raise PydanticCustomError("document_number_format", "El número no tiene el formato de su tipo de documento.")
    return limpio


class PatientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType
    document_number: Texto
    given_names: Texto
    family_names: Texto

    @field_validator("given_names", "family_names")
    @classmethod
    def _nombres(cls, valor: str) -> str:
        return _normalizar_nombre(valor)

    @field_validator("document_number")
    @classmethod
    def _documento(cls, valor: str, info) -> str:
        return normalizar_documento(valor, info.data.get("document_type"))


class PatientUpdate(BaseModel):
    """Actualización parcial. El documento se cambia con tipo y número juntos."""

    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType | None = None
    document_number: Texto | None = None
    given_names: Texto | None = None
    family_names: Texto | None = None

    @field_validator("given_names", "family_names")
    @classmethod
    def _nombres(cls, valor: str | None) -> str | None:
        return None if valor is None else _normalizar_nombre(valor)

    @field_validator("document_number")
    @classmethod
    def _documento(cls, valor: str | None, info) -> str | None:
        return None if valor is None else normalizar_documento(valor, info.data.get("document_type"))

    @model_validator(mode="after")
    def _coherente(self) -> "PatientUpdate":
        cambios = self.model_dump(exclude_unset=True)
        if not cambios:
            raise PydanticCustomError("empty_update", "Indique al menos un campo.")
        if any(v is None for v in cambios.values()):
            raise PydanticCustomError("null_field", "Un campo no puede ser nulo.")
        if ("document_type" in cambios) != ("document_number" in cambios):
            raise PydanticCustomError(
                "document_pair_required", "El tipo y el número de documento se cambian juntos."
            )
        return self


class PatientOut(BaseModel):
    id: UUID
    document_type: DocumentType
    document_number: str
    given_names: str
    family_names: str
    created_at: datetime
    updated_at: datetime


class PatientSummary(BaseModel):
    """Resultado de búsqueda: el documento va enmascarado (minimización)."""

    id: UUID
    document_type: DocumentType
    document_number_masked: str
    given_names: str
    family_names: str


#: Mínimo de letras o dígitos de una búsqueda por nombre, contados **después** de
#: normalizarla: evita búsquedas amplias (tildes sueltas o signos no cuentan).
NOMBRE_BUSQUEDA_MIN = 3


class PatientSearch(BaseModel):
    """Criterio de búsqueda (HU004), **en el cuerpo** de `POST /patients/search`.

    Nunca en la URL: el documento o el nombre quedarían en proxies, CDN o el
    historial del navegador (hallazgo 5 de la autorrevisión de PR #9). Un solo
    criterio: el documento (tipo y número, coincidencia exacta) o el nombre (al
    menos `NOMBRE_BUSQUEDA_MIN` letras o dígitos tras normalizar). No hay
    listado abierto de pacientes.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    document_type: DocumentType | None = None
    document_number: Annotated[Texto, Field(max_length=20)] | None = None
    name: Annotated[Texto, Field(max_length=NOMBRE_MAX)] | None = None
    limit: int = Field(default=LIMITE_POR_DEFECTO, ge=1, le=LIMITE_MAXIMO)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _un_criterio_acotado(self) -> "PatientSearch":
        por_documento = self.document_type is not None or self.document_number is not None
        if por_documento and self.name is not None:
            raise PydanticCustomError("single_search_criterion", "Use un solo criterio de búsqueda.")
        if por_documento:
            if self.document_type is None or self.document_number is None:
                raise PydanticCustomError(
                    "document_pair_required", "El tipo y el número de documento se buscan juntos."
                )
            self.document_number = normalizar_documento(self.document_number, self.document_type)
            return self
        # El mínimo se cuenta sobre el texto **normalizado**, que es el que se busca:
        # tres tildes combinantes sueltas quedarían en «» y coincidirían con todas.
        if self.name is None or sum(c.isalnum() for c in normalizar_para_busqueda(self.name)) < NOMBRE_BUSQUEDA_MIN:
            raise PydanticCustomError("search_criterion_required", "Indique un documento o un nombre más preciso.")
        return self
