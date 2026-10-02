"""Configuración de parámetros básicos (HU011): solo el administrador.

- `GET /settings`: cada parámetro del catálogo con su valor vigente, su valor
  por defecto y quién y cuándo lo cambió por última vez.
- `PATCH /settings`: cambia uno o más. Un valor igual al vigente no escribe
  nada y responde 200 con el estado vigente, igual que un cambio.

Ningún parámetro es clínico (`app/services/settings_catalog.py`).
"""

import time

from fastapi import APIRouter, Depends, Request

from app.api.access import requiere
from app.api.deps import Actor, get_actor
from app.api.v1.comun import ERRORES, registrar
from app.auth.roles import Role
from app.core.logging import request_id_var
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.services.system_settings import SystemSettingsService

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[requiere(Role.ADMINISTRADOR)])


def _servicio(request: Request) -> SystemSettingsService:
    return request.app.state.system_settings_service


@router.get("", response_model=SettingsOut, responses=ERRORES)
def get_settings(request: Request) -> SettingsOut:
    return SettingsOut.model_validate(_servicio(request).get_all())


@router.patch("", response_model=SettingsOut, responses=ERRORES)
def update_settings(cambios: SettingsUpdate, request: Request, actor: Actor = Depends(get_actor)) -> SettingsOut:
    inicio = time.perf_counter()
    estado, cambiadas = _servicio(request).update(cambios.model_dump(exclude_unset=True), actor, request_id_var.get())
    if cambiadas:
        # Solo la acción y la latencia: ni la clave ni el valor.
        registrar("system_setting.update", inicio)
    return SettingsOut.model_validate(estado)
