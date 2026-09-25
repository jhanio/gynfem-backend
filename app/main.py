"""Punto de entrada de uvicorn: `uvicorn app.main:app`.

La configuración, el contrato del modelo y la serie de migraciones se validan
al importar este módulo, es decir, al arrancar el servidor. Si alguno es
inválido, el proceso termina con código 1 y un mensaje claro (la variable, la
parte del contrato o la migración que falla), sin traza. La conexión con la
base **no** se comprueba aquí: se abre después, sin bloquear el arranque.
"""

import sys

from app.core.config import ConfigurationError
from app.db.migrate import MigrationError
from app.factory import create_app
from app.services.model_loader import ModelContractError

try:
    app = create_app()
except (ConfigurationError, ModelContractError, MigrationError) as exc:
    sys.stderr.write(f"{exc}\n")
    raise SystemExit(1) from None
