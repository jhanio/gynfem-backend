"""Capa de lógica de negocio. Vacía hasta la Fase 8 (predicción).

Regla de dependencias: `api → services → repositories`, nunca al revés. Un
servicio no conoce HTTP (ni `Request` ni códigos de estado) y accede a recursos
externos solo a través de `repositories`.
"""
