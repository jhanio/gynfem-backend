"""Paginación de los listados: límite obligatorio desde el principio (decisión 8).

Sin el total de filas: en una búsqueda de pacientes revelaría cuántas hay.
"""

from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

LIMITE_POR_DEFECTO = 20
LIMITE_MAXIMO = 50

T = TypeVar("T")

Limit = Annotated[int, Query(ge=1, le=LIMITE_MAXIMO)]
Offset = Annotated[int, Query(ge=0)]


class Page(BaseModel, Generic[T]):
    items: list[T]
    limit: int
    offset: int
    has_more: bool
