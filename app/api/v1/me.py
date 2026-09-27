"""`GET /api/v1/me` (HU001): quién es el usuario del token y con qué rol.

El frontend lo usa tras iniciar sesión para decidir qué mostrar. El rol es el
de la base, no el del token. Solo id y rol: si responde, el usuario está activo.
"""

from fastapi import APIRouter, Depends

from app.api.access import requiere
from app.api.deps import Actor, get_actor
from app.auth.roles import Role
from app.schemas.users import MeOut

router = APIRouter(tags=["auth"], dependencies=[requiere(Role.MEDICO, Role.ADMINISTRADOR)])


@router.get("/me", response_model=MeOut)
def me(actor: Actor = Depends(get_actor)) -> MeOut:
    return MeOut(id=actor.user_id, role=actor.role)
