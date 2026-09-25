"""Límites fisiológicos del nivel a: un valor fuera de ellos se rechaza con 422.

**PROVISIONALES.** No hay todavía una fuente clínica aprobada
(`docs/ML_SPEC.md`, Sección 5). Son una propuesta técnica pendiente de
validación con el equipo médico de GynFem, aprobada como provisional en la
Fase 8.

Criterio: atrapar errores de unidad y de tecleo, no juzgar la clínica. Por eso
son amplios y siempre contienen el rango de entrenamiento (la carga del modelo
lo comprueba y la aplicación no arranca si no se cumple).

Para sustituirlos tras la validación médica: editar este diccionario (cambiar
`min`/`max`, poner `status="validated"` y citar la fuente en `rationale`) y la
tabla de `docs/ML_SPEC.md`, Sección 5.1, que los transcribe; un test exige que
coincidan. La validación de entrada, `/prediction/schema` y los tests leen de
aquí; ningún otro archivo de código o de tests repite estos números.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PhysiologicalLimit:
    min: float
    max: float
    status: Literal["provisional", "validated"]
    rationale: str


_PENDIENTE = "Provisional, pendiente de validación clínica con GynFem."

#: Por campo de entrada clínico, en unidad clínica. Límites inclusivos.
PHYSIOLOGICAL_LIMITS: dict[str, PhysiologicalLimit] = {
    "age_years": PhysiologicalLimit(
        10, 60, "provisional", f"{_PENDIENTE} Contiene el rango de entrenamiento con margen amplio."
    ),
    "temperature_c": PhysiologicalLimit(
        30,
        43,
        "provisional",
        f"{_PENDIENTE} Contiene el rango de entrenamiento; rechaza una temperatura escrita en °F.",
    ),
    "heart_rate_bpm": PhysiologicalLimit(
        30, 220, "provisional", f"{_PENDIENTE} Contiene el rango de entrenamiento."
    ),
    "systolic_bp_mmhg": PhysiologicalLimit(
        60, 250, "provisional", f"{_PENDIENTE} Contiene el rango de entrenamiento."
    ),
    "diastolic_bp_mmhg": PhysiologicalLimit(
        30, 150, "provisional", f"{_PENDIENTE} Contiene el rango de entrenamiento."
    ),
    "bmi_kg_m2": PhysiologicalLimit(
        12,
        70,
        "provisional",
        f"{_PENDIENTE} Contiene el rango de entrenamiento y la obesidad, que se predice con "
        "aviso de extrapolación en vez de rechazarse.",
    ),
    "hba1c_percent": PhysiologicalLimit(
        3,
        20,
        "provisional",
        f"{_PENDIENTE} Contiene el rango de entrenamiento; rechaza una HbA1c escrita en mmol/mol.",
    ),
    "fasting_glucose_mg_dl": PhysiologicalLimit(
        20,
        600,
        "provisional",
        f"{_PENDIENTE} Contiene el rango de entrenamiento; rechaza una glucosa escrita en mmol/L.",
    ),
}
