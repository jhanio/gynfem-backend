"""Respuestas de `GET /api/v1/health` y `GET /api/v1/health/ready`."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    timestamp: datetime


class ReadyChecks(BaseModel):
    """Solo el resultado de cada comprobación: nunca detalles de la conexión."""

    model_config = ConfigDict(populate_by_name=True)

    database: Literal["ok"]
    # `schema` es un atributo heredado de `BaseModel`: se publica con alias.
    schema_: Literal["ok"] = Field(alias="schema")


class ReadyResponse(BaseModel):
    status: Literal["ready"]
    checks: ReadyChecks
