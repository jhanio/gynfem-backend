"""Constantes compartidas de la suite de la API.

Viven aquí y no en `conftest.py` porque los tests no importan un conftest por
nombre: `tests/` y `tests/api/` tienen cada uno el suyo.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

ORIGEN_LOCAL = "http://localhost:5173"
ORIGEN_NO_CONFIGURADO = "http://evil.example"

#: Valor clínico ficticio. Si aparece en un log o en una respuesta de error,
#: algo está filtrando lo que envió el cliente.
CENTINELA = "4242.4242"

#: Ruta del sistema ficticia incluida en el mensaje de la excepción de prueba.
RUTA_SECRETA = r"C:\gynfem\ruta\secreta.py"
