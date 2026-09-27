"""Roles funcionales de `docs/PRD.md` §3. Un usuario tiene exactamente uno.

El valor es el que guarda `gynfem.user_profiles.role` (migración 0008).
"""

from enum import StrEnum


class Role(StrEnum):
    MEDICO = "medico"
    ADMINISTRADOR = "administrador"
