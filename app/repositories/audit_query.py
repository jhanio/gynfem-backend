"""Lectura de `gynfem.audit_log`. Solo consulta: la escritura vive en `audit.py`.

SQL explícito y parametrizado. Las condiciones salen de una lista cerrada de
filtros; los valores viajan siempre como parámetros. El id numérico interno
ordena, pero nunca se devuelve.
"""

from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg.rows import dict_row

COLUMNAS_PUBLICAS = "created_at, actor_user_id, action, entity_type, entity_id, request_id, outcome, changed_fields"

#: Filtro → condición. `from` es inclusivo y `to` exclusivo: dos intervalos
#: consecutivos no comparten ninguna fila.
_CONDICIONES = {
    "action": "action = %s",
    "entity_type": "entity_type = %s",
    "entity_id": "entity_id = %s",
    "actor_user_id": "actor_user_id = %s",
    "created_from": "created_at >= %s",
    "created_to": "created_at < %s",
}


def list_page(
    conexion: psycopg.Connection, filtros: Mapping[str, Any], limit: int, offset: int
) -> list[dict[str, Any]]:
    """De la fila más reciente a la más antigua. Las filas de una misma transacción
    comparten `created_at`: desempata el id, de modo que la paginación es estable."""
    condiciones = [_CONDICIONES[nombre] for nombre in filtros]
    donde = f"WHERE {' AND '.join(condiciones)} " if condiciones else ""
    with conexion.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            f"SELECT {COLUMNAS_PUBLICAS} FROM gynfem.audit_log {donde}"
            "ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
            [*filtros.values(), limit, offset],
        ).fetchall()
