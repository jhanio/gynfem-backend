"""Quién hace una operación. Lo resuelve la capa HTTP (`app/api/access.py`) a
partir del token verificado y del perfil en la base, y lo reciben los servicios,
que escriben su `user_id` en `*_by` y en la auditoría."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Actor:
    """`user_id` es el `sub` del JWT de Supabase; `role`, el de `gynfem.user_profiles`.

    Desde la Fase 11 una ruta protegida nunca llega al servicio sin actor. Los
    `None` solo los usa la CLI del primer administrador, que no tiene actor.
    """

    user_id: UUID | None
    role: str | None
