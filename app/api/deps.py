"""Dependencias compartidas de las rutas.

**`get_actor`: punto de enganche de la autenticación (Fase 11).** Hoy devuelve
un actor anónimo explícito: los endpoints clínicos **no tienen autenticación
por diseño y de forma temporal** (`docs/SECURITY.md`, deuda con cierre en el
PR #10). La Fase 11 solo cambia el cuerpo de esta función —validar el JWT de
Supabase y resolver el rol— sin tocar servicios ni repositorios: ya reciben el
`Actor` y escriben su `user_id` en `created_by`/`updated_by`/`deleted_by` y en
`audit_log.actor_user_id`. Un test exige que toda ruta clínica dependa de ella.
"""

from app.services.actor import ANONIMO, Actor

__all__ = ["Actor", "get_actor"]


def get_actor() -> Actor:
    return ANONIMO
