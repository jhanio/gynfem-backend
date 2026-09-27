"""Entrada y salida de la gestión de usuarios (HU002) y de `GET /me` (HU001).

Esquemas estrictos, sin campos extra: ni el rol ni el estado de quien llama se
pueden declarar en un cuerpo. La contraseña es `SecretStr`: se reenvía a
Supabase Auth y nunca se guarda, se registra ni se devuelve.
"""

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.schemas.patients import Texto, _normalizar_nombre

RoleName = Literal["medico", "administrador"]

#: Longitud de la contraseña temporal. 72: límite de bytes de bcrypt, que usa
#: Supabase Auth. 12: por encima del mínimo de 8 de NIST SP 800-63B (§3.1.1.2)
#: para una contraseña elegida por una persona; decisión de ingeniería.
CONTRASENA_MIN = 12
CONTRASENA_MAX = 72
#: Forma mínima de un correo; la validación completa la hace Supabase Auth.
_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CORREO_MAX = 254


def validar_contrasena(valor: str) -> None:
    if not CONTRASENA_MIN <= len(valor.encode()) <= CONTRASENA_MAX:
        raise PydanticCustomError(
            "password_length", f"La contraseña debe tener de {CONTRASENA_MIN} a {CONTRASENA_MAX} bytes."
        )


def normalizar_correo(valor: str) -> str:
    limpio = valor.strip().lower()
    if len(limpio) > CORREO_MAX or not _CORREO.match(limpio):
        raise PydanticCustomError("email_format", "El correo no tiene un formato válido.")
    return limpio


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Texto
    password: SecretStr
    full_name: Texto
    role: RoleName

    @field_validator("email")
    @classmethod
    def _correo(cls, valor: str) -> str:
        return normalizar_correo(valor)

    @field_validator("password")
    @classmethod
    def _contrasena(cls, valor: SecretStr) -> SecretStr:
        validar_contrasena(valor.get_secret_value())
        return valor

    @field_validator("full_name")
    @classmethod
    def _nombre(cls, valor: str) -> str:
        return _normalizar_nombre(valor)


class UserUpdate(BaseModel):
    """Modificar el nombre o asignar el rol. Activar y desactivar son acciones aparte."""

    model_config = ConfigDict(extra="forbid")

    full_name: Texto | None = None
    role: RoleName | None = None

    @field_validator("full_name")
    @classmethod
    def _nombre(cls, valor: str | None) -> str | None:
        return None if valor is None else _normalizar_nombre(valor)

    @model_validator(mode="after")
    def _al_menos_un_campo(self) -> "UserUpdate":
        if not self.model_fields_set or all(getattr(self, c) is None for c in self.model_fields_set):
            raise PydanticCustomError("empty_update", "Indique al menos un campo.")
        return self


class UserOut(BaseModel):
    id: UUID
    email: str | None
    full_name: str
    role: RoleName
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MeOut(BaseModel):
    """Solo lo que el frontend necesita para decidir qué mostrar."""

    id: UUID
    role: RoleName
