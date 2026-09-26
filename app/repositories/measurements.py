"""Consultas de `gynfem.clinical_measurements`. SQL explícito y parametrizado.

Guardan las unidades clínicas tal como las recibe la API: la conversión es solo
de `app/services/unit_conversion.py`. `CAMPOS_CLINICOS` son las columnas de la
tabla; un test exige que coincidan con los campos de `PredictionRequest`.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

CAMPOS_CLINICOS = (
    "age_years",
    "temperature_c",
    "heart_rate_bpm",
    "systolic_bp_mmhg",
    "diastolic_bp_mmhg",
    "bmi_kg_m2",
    "hba1c_percent",
    "fasting_glucose_mg_dl",
)
COLUMNAS_PUBLICAS = "m.id, m.patient_id, m.measured_at, " + ", ".join(f"m.{c}" for c in CAMPOS_CLINICOS)


def insert_measurement(
    conexion: psycopg.Connection,
    patient_id: UUID,
    measured_at: datetime | None,
    valores: Mapping[str, float],
    actor: UUID | None,
    replaces: UUID | None = None,
) -> dict[str, Any]:
    columnas = ", ".join(CAMPOS_CLINICOS)
    marcas = ", ".join(["%s"] * len(CAMPOS_CLINICOS))
    with conexion.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            "INSERT INTO gynfem.clinical_measurements AS m "
            f"(patient_id, measured_at, {columnas}, replaces_measurement_id, created_by, updated_by) "
            f"VALUES (%s, coalesce(%s, now()), {marcas}, %s, %s, %s) RETURNING {COLUMNAS_PUBLICAS}",
            [patient_id, measured_at, *(valores[c] for c in CAMPOS_CLINICOS), replaces, actor, actor],
        ).fetchone()


def get_active(conexion: psycopg.Connection, measurement_id: UUID, *, for_update: bool = False) -> dict[str, Any] | None:
    """Medición vigente de una paciente activa."""
    bloqueo = " FOR UPDATE OF m" if for_update else ""
    with conexion.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            f"SELECT {COLUMNAS_PUBLICAS} FROM gynfem.clinical_measurements m "
            "JOIN gynfem.patients p ON p.id = m.patient_id "
            f"WHERE m.id = %s AND m.deleted_at IS NULL AND p.deleted_at IS NULL{bloqueo}",
            [measurement_id],
        ).fetchone()


def is_corrected(conexion: psycopg.Connection, measurement_id: UUID) -> bool:
    """¿Alguna medición la corrige? Sin filtrar bajas: una corrección da de baja la original."""
    return conexion.execute(
        "SELECT EXISTS (SELECT 1 FROM gynfem.clinical_measurements WHERE replaces_measurement_id = %s)",
        [measurement_id],
    ).fetchone()[0]


def deactivate_measurement(conexion: psycopg.Connection, measurement_id: UUID, actor: UUID | None) -> None:
    """Baja **lógica** de la medición corregida; su predicción se conserva intacta."""
    conexion.execute(
        "UPDATE gynfem.clinical_measurements SET deleted_at = now(), deleted_by = %s, updated_by = %s "
        "WHERE id = %s AND deleted_at IS NULL",
        [actor, actor, measurement_id],
    )


def list_for_patient(conexion: psycopg.Connection, patient_id: UUID, limit: int, offset: int) -> list[dict[str, Any]]:
    """Mediciones vigentes, de la más reciente a la más antigua, con su predicción vigente."""
    with conexion.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            f"SELECT {COLUMNAS_PUBLICAS}, "
            "(SELECT pr.id FROM gynfem.predictions pr WHERE pr.measurement_id = m.id AND pr.deleted_at IS NULL "
            " ORDER BY pr.predicted_at DESC LIMIT 1) AS prediction_id "
            "FROM gynfem.clinical_measurements m "
            "WHERE m.patient_id = %s AND m.deleted_at IS NULL "
            "ORDER BY m.measured_at DESC, m.created_at DESC, m.id LIMIT %s OFFSET %s",
            [patient_id, limit, offset],
        ).fetchall()
