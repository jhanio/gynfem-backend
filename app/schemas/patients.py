"""Entrada y salida de pacientes (HU003, HU004).

Identidad mínima (`docs/ERD.md`, decisión A de la Fase 10): tipo y número de
documento, nombres y apellidos. Esquema estricto: sin campos extra, solo texto.
Los mensajes de error nunca repiten el valor recibido (`docs/API_SPEC.md` §2.5).
"""

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from pydantic_core import PydanticCustomError

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
    limpio = " ".join(valor.split())
    if not limpio or len(limpio) > NOMBRE_MAX or not _NOMBRE.match(limpio):
        raise PydanticCustomError(
            "name_format", "Solo letras, espacios, guion o apóstrofo; de 1 a 100 caracteres."
        )
    return limpio


def _normalizar_documento(numero: str, tipo: str | None) -> str:
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
        return _normalizar_documento(valor, info.data.get("document_type"))


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
        return None if valor is None else _normalizar_documento(valor, info.data.get("document_type"))

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


#: Mínimo de caracteres de una búsqueda por nombre: evita búsquedas amplias.
NOMBRE_BUSQUEDA_MIN = 3
BusquedaPorNombre = Annotated[str, Field(min_length=1, max_length=NOMBRE_MAX)]
