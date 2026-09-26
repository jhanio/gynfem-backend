"""Consultas de `gynfem.predictions`: la trazabilidad completa de `docs/ML_SPEC.md` §6.

El vector llega como un mapeo ordenado `feature → valor`, en el orden del
contrato del modelo, y se guarda en las columnas `model_<feature>`; al releerlo
se reconstruye en el orden que indica quien llama (el mismo contrato).
"""

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.repositories.measurements import CAMPOS_CLINICOS

NIVELES = ("high", "mid", "low")
#: Los nombres de feature forman nombres de columna: solo identificadores simples.
_IDENTIFICADOR = re.compile(r"^[a-z][a-z0-9_]*$")


def _columnas_del_modelo(features: Sequence[str]) -> list[str]:
    for feature in features:
        if not _IDENTIFICADOR.match(feature):
            raise ValueError("nombre de feature inválido")
    return [f"model_{f}" for f in features]


def insert_prediction(
    conexion: psycopg.Connection,
    measurement_id: UUID,
    *,
    clinical_input: Mapping[str, float],
    model_input: Mapping[str, float],
    risk_level: str,
    probabilities: Mapping[str, float],
    extrapolation_warnings: Sequence[Mapping[str, Any]],
    model_version: str,
    conversion_schema_version: str,
    predicted_at: datetime,
    actor: UUID | None,
) -> UUID:
    columnas = [
        "measurement_id",
        *(f"input_{c}" for c in CAMPOS_CLINICOS),
        *_columnas_del_modelo(list(model_input)),
        "risk_level", *(f"prob_{n}" for n in NIVELES),
        "extrapolation_warnings", "model_version", "conversion_schema_version", "predicted_at",
        "created_by", "updated_by",
    ]
    valores = [
        measurement_id,
        *(clinical_input[c] for c in CAMPOS_CLINICOS),
        *model_input.values(),
        risk_level, *(probabilities[n] for n in NIVELES),
        Jsonb([dict(a) for a in extrapolation_warnings]),
        model_version, conversion_schema_version, predicted_at,
        actor, actor,
    ]
    return conexion.execute(
        f"INSERT INTO gynfem.predictions ({', '.join(columnas)}) "
        f"VALUES ({', '.join(['%s'] * len(columnas))}) RETURNING id",
        valores,
    ).fetchone()[0]


def get_active(conexion: psycopg.Connection, prediction_id: UUID, feature_order: Sequence[str]) -> dict[str, Any] | None:
    """La predicción vigente con su trazabilidad; `model_input` en el orden `feature_order`."""
    columnas_modelo = _columnas_del_modelo(feature_order)
    columnas = [
        "id", "measurement_id", "risk_level", *(f"prob_{n}" for n in NIVELES),
        "extrapolation_warnings", "model_version", "conversion_schema_version", "predicted_at",
        *(f"input_{c}" for c in CAMPOS_CLINICOS),
        *columnas_modelo,
    ]
    with conexion.cursor(row_factory=dict_row) as cursor:
        fila = cursor.execute(
            f"SELECT {', '.join(columnas)} FROM gynfem.predictions WHERE id = %s AND deleted_at IS NULL",
            [prediction_id],
        ).fetchone()
    if fila is None:
        return None
    return {
        "id": fila["id"],
        "measurement_id": fila["measurement_id"],
        "risk_level": fila["risk_level"],
        "probabilities": {n: fila[f"prob_{n}"] for n in NIVELES},
        "extrapolation_warnings": fila["extrapolation_warnings"],
        "model_version": fila["model_version"],
        "conversion_schema_version": fila["conversion_schema_version"],
        "predicted_at": fila["predicted_at"],
        "input": {c: fila[f"input_{c}"] for c in CAMPOS_CLINICOS},
        "model_input": {f: fila[c] for f, c in zip(feature_order, columnas_modelo, strict=True)},
    }
