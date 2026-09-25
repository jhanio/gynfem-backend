"""Punto de entrada de uvicorn: `uvicorn app.main:app`.

La configuración se valida al importar este módulo, es decir, al arrancar el
servidor. Si es inválida, el proceso termina con código 1 y un mensaje que
nombra la variable, sin traza.
"""

import sys

from app.core.config import ConfigurationError
from app.factory import create_app

try:
    app = create_app()
except ConfigurationError as exc:
    sys.stderr.write(f"{exc}\n")
    raise SystemExit(1) from None
