"""Capa de entrada HTTP: rutas, validación de la petición y forma de la respuesta.

Regla de dependencias: `api → services → repositories`, nunca al revés. Un
router no accede a recursos externos directamente: llama a un servicio.
"""
