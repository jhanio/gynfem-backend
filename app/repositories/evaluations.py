"""Evaluaciones para el historial (HU008) y el reporte (HU009). SQL explícito y parametrizado.

Una evaluación es una medición con su predicción. **Una sola consulta** trae la
página entera del historial: la medición, su predicción y si fue corregida.
Incluye las mediciones corregidas (dadas de baja al corregirlas), porque el
médico pudo decidir con ellas; nunca las de una paciente dada de baja.
"""

from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.repositories.measurements import CAMPOS_CLINICOS
from app.repositories.predictions import NIVELES

_COLUMNAS_DE_LA_PREDICCION = (
    "id", "risk_level", *(f"prob_{n}" for n in NIVELES),
    "extrapolation_warnings", "model_version", "conversion_schema_version", "predicted_at",
)
_SELECT = ", ".join(
    [
        "m.id AS measurement_id", "m.patient_id", "m.measured_at",
        *(f"m.{c}" for c in CAMPOS_CLINICOS),
        *(f"pr.{c} AS prediction_{c}" for c in _COLUMNAS_DE_LA_PREDICCION),
        # Una medición se corrige una sola vez (`UNIQUE`): el join no duplica filas.
        "(correccion.id IS NOT NULL) AS corrected",
    ]
)


def list_for_patient(conexion: psycopg.Connection, patient_id: UUID, limit: int, offset: int) -> list[dict[str, Any]]:
    """Evaluaciones de una paciente **activa**, de la medición más reciente a la más antigua.

    Orden estable: `measured_at`, luego el registro (`created_at`) y luego el id,
    de modo que la paginación no repite ni pierde filas aunque las horas coincidan.
    Los dos últimos criterios solo cuentan si una medición tuviera varias predicciones.
    """
    with conexion.cursor(row_factory=dict_row) as cursor:
        filas = cursor.execute(
            f"SELECT {_SELECT} FROM gynfem.predictions pr "
            "JOIN gynfem.clinical_measurements m ON m.id = pr.measurement_id "
            "JOIN gynfem.patients p ON p.id = m.patient_id "
            "LEFT JOIN gynfem.clinical_measurements correccion ON correccion.replaces_measurement_id = m.id "
            "WHERE m.patient_id = %s AND p.deleted_at IS NULL AND pr.deleted_at IS NULL "
            "ORDER BY m.measured_at DESC, m.created_at DESC, m.id, pr.predicted_at DESC, pr.id "
            "LIMIT %s OFFSET %s",
            [patient_id, limit, offset],
        ).fetchall()
    return [_evaluacion(fila) for fila in filas]


_COLUMNAS_DE_LA_PACIENTE = ("id", "document_type", "document_number", "given_names", "family_names")
_SELECT_CON_PACIENTE = _SELECT + ", " + ", ".join(f"p.{c} AS patient_{c}" for c in _COLUMNAS_DE_LA_PACIENTE)


def get_with_patient(conexion: psycopg.Connection, prediction_id: UUID) -> dict[str, Any] | None:
    """Una evaluación con la identidad de su paciente **activa**, para el reporte.

    La predicción de una paciente dada de baja no existe aquí. La de una medición
    corregida sí: sale marcada como corregida.
    """
    with conexion.cursor(row_factory=dict_row) as cursor:
        fila = cursor.execute(
            f"SELECT {_SELECT_CON_PACIENTE} FROM gynfem.predictions pr "
            "JOIN gynfem.clinical_measurements m ON m.id = pr.measurement_id "
            "JOIN gynfem.patients p ON p.id = m.patient_id "
            "LEFT JOIN gynfem.clinical_measurements correccion ON correccion.replaces_measurement_id = m.id "
            "WHERE pr.id = %s AND p.deleted_at IS NULL AND pr.deleted_at IS NULL",
            [prediction_id],
        ).fetchone()
    if fila is None:
        return None
    return {**_evaluacion(fila), "patient": {c: fila[f"patient_{c}"] for c in _COLUMNAS_DE_LA_PACIENTE}}


def _evaluacion(fila: dict[str, Any]) -> dict[str, Any]:
    return {
        "measurement": {
            "id": fila["measurement_id"],
            "patient_id": fila["patient_id"],
            "measured_at": fila["measured_at"],
            **{c: fila[c] for c in CAMPOS_CLINICOS},
        },
        "prediction": {
            "id": fila["prediction_id"],
            "risk_level": fila["prediction_risk_level"],
            "probabilities": {n: fila[f"prediction_prob_{n}"] for n in NIVELES},
            "extrapolation_warnings": fila["prediction_extrapolation_warnings"],
            "model_version": fila["prediction_model_version"],
            "conversion_schema_version": fila["prediction_conversion_schema_version"],
            "predicted_at": fila["prediction_predicted_at"],
        },
        "corrected": fila["corrected"],
    }
