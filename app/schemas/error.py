"""Formato de error uniforme (`docs/API_SPEC.md`, Sección 2.5)."""

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    """Qué campo falló y por qué tipo de regla. Nunca el valor recibido."""

    loc: list[str | int]
    type: str


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
