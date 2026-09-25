"""Conversión de unidades clínicas peruanas a las unidades del dataset.

Única fuente de las fórmulas en todo el código (`docs/ML_SPEC.md`, Sección 4).
Dominio puro: no depende de FastAPI ni de pandas.

Ningún valor se redondea: el modelo recibe el resultado exacto de la fórmula
(decisión A de la Fase 8, `docs/ML_SPEC.md`, Sección 4).

`CONVERSION_SCHEMA_VERSION` identifica este conjunto de campos, unidades y
fórmulas. Viaja en cada respuesta de predicción y se sube si cambia cualquiera
de ellos.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

CONVERSION_SCHEMA_VERSION = "1.0.0"

# Constantes de la ecuación maestra NGSP–IFCC: mmol/mol = (% − 2.152) × 10.929.
_HBA1C_PENDIENTE = 10.929
_HBA1C_INTERCEPTO = 2.152
#: mg/dl por mmol/L de glucosa.
_GLUCOSA_MG_DL_POR_MMOL_L = 18


def celsius_to_fahrenheit(celsius: float) -> float:
    return celsius * 9 / 5 + 32


def fahrenheit_to_celsius(fahrenheit: float) -> float:
    return (fahrenheit - 32) * 5 / 9


def hba1c_percent_to_mmol_mol(percent: float) -> float:
    return (percent - _HBA1C_INTERCEPTO) * _HBA1C_PENDIENTE


def hba1c_mmol_mol_to_percent(mmol_mol: float) -> float:
    return mmol_mol / _HBA1C_PENDIENTE + _HBA1C_INTERCEPTO


def glucose_mg_dl_to_mmol_l(mg_dl: float) -> float:
    return mg_dl / _GLUCOSA_MG_DL_POR_MMOL_L


def glucose_mmol_l_to_mg_dl(mmol_l: float) -> float:
    return mmol_l * _GLUCOSA_MG_DL_POR_MMOL_L


def _identidad(valor: float) -> float:
    return valor


@dataclass(frozen=True)
class ClinicalField:
    """Un campo de entrada clínico y la feature del dataset a la que se convierte.

    Todas las conversiones son crecientes: el mínimo de un rango convertido
    sigue siendo el mínimo.
    """

    name: str
    unit: str
    model_feature: str
    model_unit: str
    to_model: Callable[[float], float]
    to_clinical: Callable[[float], float]


#: Los 8 campos aprobados, en el orden del contrato del modelo.
CLINICAL_FIELDS: tuple[ClinicalField, ...] = (
    ClinicalField("age_years", "años", "age_years", "años", _identidad, _identidad),
    ClinicalField(
        "temperature_c", "°C", "temperature_f", "°F", celsius_to_fahrenheit, fahrenheit_to_celsius
    ),
    ClinicalField("heart_rate_bpm", "lpm", "heart_rate_bpm", "lpm", _identidad, _identidad),
    ClinicalField("systolic_bp_mmhg", "mmHg", "systolic_bp_mmhg", "mmHg", _identidad, _identidad),
    ClinicalField("diastolic_bp_mmhg", "mmHg", "diastolic_bp_mmhg", "mmHg", _identidad, _identidad),
    ClinicalField("bmi_kg_m2", "kg/m²", "bmi_kg_m2", "kg/m²", _identidad, _identidad),
    ClinicalField(
        "hba1c_percent",
        "%",
        "hba1c_mmol_mol",
        "mmol/mol",
        hba1c_percent_to_mmol_mol,
        hba1c_mmol_mol_to_percent,
    ),
    ClinicalField(
        "fasting_glucose_mg_dl",
        "mg/dl",
        "fasting_glucose_mmol_l",
        "mmol/L",
        glucose_mg_dl_to_mmol_l,
        glucose_mmol_l_to_mg_dl,
    ),
)

_POR_FEATURE = {campo.model_feature: campo for campo in CLINICAL_FIELDS}


def to_model_units(clinical: Mapping[str, float]) -> dict[str, float]:
    """Entrada clínica → valores en unidades del dataset, con claves de feature."""
    return {campo.model_feature: campo.to_model(clinical[campo.name]) for campo in CLINICAL_FIELDS}


def model_to_clinical(model_feature: str, value: float) -> float:
    """Un valor en unidades del dataset → la unidad clínica de su campo."""
    return _POR_FEATURE[model_feature].to_clinical(value)
