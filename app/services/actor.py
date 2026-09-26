"""Quién hace una operación. Lo resuelve la capa HTTP (`app/api/deps.py`) y lo
reciben los servicios, que escriben su `user_id` en `*_by` y en la auditoría."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Actor:
    """`user_id` y `role` son `None` mientras no haya autenticación (Fase 11)."""

    user_id: UUID | None
    role: str | None


ANONIMO = Actor(user_id=None, role=None)
