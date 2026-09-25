"""Punto de entrada de uvicorn: `uvicorn app.main:app`.

La configuración y el contrato del modelo se validan al importar este módulo,
es decir, al arrancar el servidor. Si alguno es inválido, el proceso termina
con código 1 y un mensaje claro (la variable o la parte del contrato que
falla), sin traza.
"""

import sys

from app.core.config import ConfigurationError
from app.factory import create_app
from app.services.model_loader import ModelContractError

try:
    app = create_app()
except (ConfigurationError, ModelContractError) as exc:
    sys.stderr.write(f"{exc}\n")
    raise SystemExit(1) from None
