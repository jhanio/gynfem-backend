"""Gestión de usuarios y roles (HU002): solo el administrador.

- `POST /users`: crea la cuenta en Supabase Auth y su perfil con el rol.
- `GET /users`, `GET /users/{id}`: consultar, paginado y sin total.
- `PATCH /users/{id}`: modificar el nombre o asignar el rol.
- `POST /users/{id}/deactivate` y `/activate`: rigen desde la petición
  siguiente del usuario afectado, aunque conserve un token válido.

El rol de un cuerpo es el del usuario **gestionado**, nunca el de quien llama:
ese sale del token y de la base (`app/api/access.py`).
"""

import time
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.access import requiere
from app.api.deps import Actor, get_actor
from app.api.v1.comun import ERRORES, registrar
from app.auth.roles import Role
from app.core.logging import request_id_var
from app.schemas.pagination import LIMITE_POR_DEFECTO, Limit, Offset, Page
from app.schemas.users import UserCreate, UserOut, UserUpdate
from app.services.users import UserService

router = APIRouter(prefix="/users", tags=["users"], dependencies=[requiere(Role.ADMINISTRADOR)])


def _servicio(request: Request) -> UserService:
    return request.app.state.user_service


@router.post("", status_code=201, response_model=UserOut, responses=ERRORES)
def create_user(datos: UserCreate, request: Request, actor: Actor = Depends(get_actor)) -> UserOut:
    inicio = time.perf_counter()
    usuario = _servicio(request).create(
        datos.email, datos.password.get_secret_value(), datos.full_name, datos.role, actor, request_id_var.get()
    )
    registrar("user.create", inicio)
    return UserOut.model_validate(usuario)


@router.get("", response_model=Page[UserOut], responses=ERRORES)
def list_users(request: Request, limit: Limit = LIMITE_POR_DEFECTO, offset: Offset = 0) -> Page[UserOut]:
    items, mas = _servicio(request).list_page(limit, offset)
    return Page[UserOut](items=items, limit=limit, offset=offset, has_more=mas)


@router.get("/{user_id}", response_model=UserOut, responses=ERRORES)
def get_user(user_id: UUID, request: Request) -> UserOut:
    return UserOut.model_validate(_servicio(request).get(user_id))


@router.patch("/{user_id}", response_model=UserOut, responses=ERRORES)
def update_user(user_id: UUID, cambios: UserUpdate, request: Request, actor: Actor = Depends(get_actor)) -> UserOut:
    inicio = time.perf_counter()
    usuario = _servicio(request).update(user_id, cambios.model_dump(exclude_none=True), actor, request_id_var.get())
    registrar("user.update", inicio)
    return UserOut.model_validate(usuario)


@router.post("/{user_id}/deactivate", response_model=UserOut, responses=ERRORES)
def deactivate_user(user_id: UUID, request: Request, actor: Actor = Depends(get_actor)) -> UserOut:
    inicio = time.perf_counter()
    usuario = _servicio(request).set_active(user_id, False, actor, request_id_var.get())
    registrar("user.deactivate", inicio)
    return UserOut.model_validate(usuario)


@router.post("/{user_id}/activate", response_model=UserOut, responses=ERRORES)
def activate_user(user_id: UUID, request: Request, actor: Actor = Depends(get_actor)) -> UserOut:
    inicio = time.perf_counter()
    usuario = _servicio(request).set_active(user_id, True, actor, request_id_var.get())
    registrar("user.activate", inicio)
    return UserOut.model_validate(usuario)
