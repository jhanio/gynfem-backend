"""Backend de GynFem: API de apoyo a la decisión clínica.

`__version__` es la única fuente de la versión de la aplicación: la leen
`FastAPI(version=…)` y `GET /api/v1/health`. Se sube en cada PR que cambie la
API. Es independiente de la versión del modelo (`models/model_metadata.json`).
"""

__version__ = "0.1.0"
