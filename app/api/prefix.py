"""Prefijo de versión de todas las rutas (`docs/API_SPEC.md`, Sección 2.1).

Módulo propio para que `app/api/access.py` lo use sin importar el router raíz,
que a su vez importa los routers que dependen de `access`.
"""

API_V1_PREFIX = "/api/v1"
