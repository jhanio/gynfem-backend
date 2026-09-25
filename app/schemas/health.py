"""Respuesta de `GET /api/v1/health`."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    timestamp: datetime
