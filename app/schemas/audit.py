"""Entrada y salida de la consulta de la auditoría.

Los filtros son un esquema cerrado: un parámetro que no existe da 422, igual
que un valor inválido, y el 422 nunca repite el valor recibido
(`docs/API_SPEC.md` §2.5).
"""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from app.schemas.pagination import LIMITE_MAXIMO, LIMITE_POR_DEFECTO

#: Las entidades que admite `audit_log.entity_type` (migraciones 0005, 0008 y 0009).
EntityType = Literal["patient", "clinical_measurement", "prediction", "user", "system_setting"]
Outcome = Literal["success", "denied", "error"]

#: El formato que impone la base a `audit_log.action`.
FORMATO_DE_ACCION = r"^[a-z_]+\.[a-z_]+$"
ACCION_MAX = 100


class AuditLogQuery(BaseModel):
    """Paginación y filtros, todos opcionales y combinables."""

    model_config = ConfigDict(extra="forbid")

    #: Fijo en 20 por defecto: el parámetro `history_default_page_size` es solo del historial.
    limit: int = Field(default=LIMITE_POR_DEFECTO, ge=1, le=LIMITE_MAXIMO)
    offset: int = Field(default=0, ge=0)
    action: Annotated[str, Field(pattern=FORMATO_DE_ACCION, max_length=ACCION_MAX)] | None = None
    entity_type: EntityType | None = None
    entity_id: UUID | None = None
    actor_user_id: UUID | None = None
    #: Inclusivo. Con zona horaria.
    created_from: AwareDatetime | None = Field(default=None, alias="from")
    #: Exclusivo. Con zona horaria.
    created_to: AwareDatetime | None = Field(default=None, alias="to")

    @model_validator(mode="after")
    def _intervalo_no_invertido(self) -> "AuditLogQuery":
        # Un intervalo invertido es un error de quien llama: responder una página
        # vacía lo ocultaría. `from` igual a `to` sí es válido: un intervalo vacío.
        if self.created_from is not None and self.created_to is not None and self.created_from > self.created_to:
            raise PydanticCustomError("date_range_inverted", "La fecha inicial no puede ser posterior a la final.")
        return self

    def filtros(self) -> dict[str, Any]:
        """Solo los filtros indicados, por el nombre que entiende el repositorio."""
        return self.model_dump(exclude={"limit", "offset"}, exclude_none=True)


class AuditEntryOut(BaseModel):
    """Quién hizo qué, sobre qué y cuándo. Sin valores y sin el id numérico interno."""

    created_at: datetime
    actor_user_id: UUID | None
    action: str
    entity_type: EntityType
    #: Id opaco: el administrador no puede resolverlo, porque recibe 403 en lo clínico.
    entity_id: UUID | None
    request_id: str | None
    outcome: Outcome
    #: Solo nombres de campo o de parámetro, nunca valores.
    changed_fields: list[str] | None
