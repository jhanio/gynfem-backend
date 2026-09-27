"""Dependencias compartidas de las rutas.

**`get_actor`** devuelve el usuario autenticado y autorizado de la petición, que
resolvió la decisión de acceso de la ruta (`app/api/access.py`, Fase 11). Los
servicios reciben ese `Actor` y escriben su `user_id` en
`created_by`/`updated_by`/`deleted_by` y en `audit_log.actor_user_id`.

Falla cerrada: si una ruta pide el actor sin haber declarado `requiere(...)`,
no hay actor y la petición termina en 500, nunca con un actor anónimo.
"""

from fastapi import Request

from app.services.actor import Actor

__all__ = ["Actor", "get_actor"]


class SinDecisionDeAcceso(RuntimeError):
    """Una ruta usa el actor sin declarar `requiere(...)`: error de programación."""


def get_actor(request: Request) -> Actor:
    actor = getattr(request.state, "actor", None)
    if not isinstance(actor, Actor) or actor.user_id is None:
        raise SinDecisionDeAcceso()
    return actor
