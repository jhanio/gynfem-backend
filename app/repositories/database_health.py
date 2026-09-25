"""Consultas de diagnóstico de la base de datos, sin datos clínicos."""

import psycopg

from app.db.migrate import CONTROL_TABLE


def applied_migration_versions(conexion: psycopg.Connection) -> frozenset[int]:
    """Versiones registradas por el runner; vacío si nunca se migró esta base."""
    if conexion.execute("SELECT to_regclass(%s)", [CONTROL_TABLE]).fetchone()[0] is None:
        return frozenset()
    filas = conexion.execute(f"SELECT version FROM {CONTROL_TABLE}").fetchall()
    return frozenset(version for (version,) in filas)
