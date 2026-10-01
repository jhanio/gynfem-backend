"""Catálogo cerrado de los parámetros del sistema (HU011).

**Ninguno es clínico.** Los umbrales de riesgo, los límites fisiológicos, los
rangos de entrenamiento y el texto de la advertencia clínica no son parámetros:
cambiarlos alteraría el comportamiento clínico sin la trazabilidad de un cambio
de código (`docs/SECURITY.md`). Añadir una clave es un cambio de código, con su
validación en `app/schemas/settings.py`; los **valores** viven en
`gynfem.system_settings` y se cambian sin desplegar.

Sin fila guardada para una clave, rige su valor por defecto.
"""

from collections.abc import Mapping
from types import MappingProxyType

from app.schemas.pagination import LIMITE_MAXIMO, LIMITE_POR_DEFECTO

#: Nombre de la institución en el encabezado del reporte (HU009).
INSTITUTION_NAME = "institution_name"
#: Tamaño de página del historial (HU008) cuando el cliente no indica `limit`.
HISTORY_DEFAULT_PAGE_SIZE = "history_default_page_size"

INSTITUTION_NAME_MAX = 100
HISTORY_PAGE_SIZE_MIN = 1
HISTORY_PAGE_SIZE_MAX = LIMITE_MAXIMO

VALORES_POR_DEFECTO: Mapping[str, str | int] = MappingProxyType(
    {
        INSTITUTION_NAME: "GynFem",
        HISTORY_DEFAULT_PAGE_SIZE: LIMITE_POR_DEFECTO,
    }
)

#: La tabla guarda texto: cómo se relee el valor de cada clave.
_DE_TEXTO = MappingProxyType({INSTITUTION_NAME: str, HISTORY_DEFAULT_PAGE_SIZE: int})


def a_texto(valor: str | int) -> str:
    return str(valor)


def de_texto(clave: str, texto: str) -> str | int:
    return _DE_TEXTO[clave](texto)
