"""Datos de prueba **sintéticos e inventados**, para los tests de persistencia clínica.

Ningún dato pertenece a una paciente real (`CLAUDE.md`, regla 3). Los nombres
dicen «Sintética» y «Prueba» a propósito, y los documentos son secuencias
`0000000N` que no se parecen a un registro real.
"""

PACIENTE = {
    "document_type": "DNI",
    "document_number": "00000001",
    "given_names": "Sintética",
    "family_names": "Prueba Uno",
}

PACIENTE_DOS = {
    "document_type": "PASAPORTE",
    "document_number": "PRUEBA0002",
    "given_names": "Ficticia",
    "family_names": "Pérez Ensayo",
}

#: Claves que expone la API de una paciente; nada interno de la base.
CLAVES_PACIENTE = {"id", "document_type", "document_number", "given_names", "family_names", "created_at", "updated_at"}
CLAVES_RESUMEN = {"id", "document_type", "document_number_masked", "given_names", "family_names"}
CLAVES_PAGINA = {"items", "limit", "offset", "has_more"}
CLAVES_MEDICION = {
    "id", "patient_id", "measured_at",
    "age_years", "temperature_c", "heart_rate_bpm", "systolic_bp_mmhg",
    "diastolic_bp_mmhg", "bmi_kg_m2", "hba1c_percent", "fasting_glucose_mg_dl",
}
CLAVES_PREDICCION = {
    "id", "risk_level", "probabilities", "extrapolation_warnings", "clinical_disclaimer",
    "model_version", "conversion_schema_version", "predicted_at",
}
CLAVES_PREDICCION_DETALLE = CLAVES_PREDICCION | {"measurement_id", "input", "model_input"}

#: Nunca deben salir en una respuesta.
CAMPOS_INTERNOS = ("deleted_at", "created_by", "updated_by", "deleted_by", "search_key", "replaces_measurement_id")


#: Búsqueda de pacientes: POST con el criterio en el cuerpo, nunca en la URL
#: (hallazgo 5 de la autorrevisión de PR #9).
BUSQUEDA = "/api/v1/patients/search"


def buscar(cliente, criterio: dict):
    """`POST /patients/search` con el criterio (y la paginación) en el cuerpo."""
    return cliente.post(BUSQUEDA, json=criterio)


def documento(n: int) -> str:
    """DNI sintético número `n`: 00000001, 00000002…"""
    return f"{n:08d}"
