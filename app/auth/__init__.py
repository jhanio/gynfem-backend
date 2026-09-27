"""Autenticación con Supabase Auth (Fase 11, HU001).

Supabase Auth emite el JWT; el backend solo lo verifica (`tokens.py`) y resuelve
el rol y el estado del usuario en la base en cada petición (`directory.py`).
Nunca emite tokens ni guarda contraseñas.
"""
