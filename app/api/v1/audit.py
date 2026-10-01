"""Consulta de la auditoría: solo el administrador y solo lectura.

`GET /audit-log`: quién hizo qué acción, sobre qué entidad y cuándo, de lo más
reciente a lo más antiguo, paginado y sin total. Filtros combinables: `action`,
`entity_type`, `entity_id`, `actor_user_id`, `from` (inclusivo) y `to`
(exclusivo).

- **No hay ruta de escritura**: la auditoría no se crea, no se modifica y no se
  borra por la API. Cada registro lo escribe la operación que audita.
- **Sin datos clínicos en claro**: la tabla no tiene columnas donde quepan
  (`docs/SECURITY.md`). `entity_id` es un id opaco: el administrador no puede
  resolverlo, porque recibe 403 en todo lo clínico.
- Consultar la auditoría no se audita ni deja los filtros en los logs.
- La respuesta lleva `Cache-Control: no-store`.
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.api.access import requiere
from app.api.v1.comun import ERRORES
from app.auth.roles import Role
from app.schemas.audit import AuditEntryOut, AuditLogQuery
from app.schemas.pagination import Page
from app.services.audit_query import AuditQueryService

router = APIRouter(tags=["audit"], dependencies=[requiere(Role.ADMINISTRADOR)])


def _servicio(request: Request) -> AuditQueryService:
    return request.app.state.audit_query_service


@router.get("/audit-log", response_model=Page[AuditEntryOut], responses=ERRORES)
def list_audit_log(
    consulta: Annotated[AuditLogQuery, Query()], request: Request, response: Response
) -> Page[AuditEntryOut]:
    items, mas = _servicio(request).list_page(consulta.filtros(), consulta.limit, consulta.offset)
    response.headers["Cache-Control"] = "no-store"
    return Page[AuditEntryOut](items=items, limit=consulta.limit, offset=consulta.offset, has_more=mas)
