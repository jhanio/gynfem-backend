"""Constantes compartidas de la suite de la API.

Viven aquí y no en `conftest.py` porque los tests no importan un conftest por
nombre: `tests/` y `tests/api/` tienen cada uno el suyo.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

ORIGEN_LOCAL = "http://localhost:5173"
ORIGEN_NO_CONFIGURADO = "http://evil.example"

#: Base de datos ficticia en loopback (puerto 1, cerrado), válida en todo entorno
#: (lleva `sslmode=require`, que se exige en production). La aplicación arranca
#: sin conectarse: solo el ciclo de vida (`with TestClient(...)`) abre el pool.
URL_BD_FICTICIA = "postgresql://gynfem@127.0.0.1:1/gynfem?sslmode=require"

#: Valor clínico ficticio. Si aparece en un log o en una respuesta de error,
#: algo está filtrando lo que envió el cliente.
CENTINELA = "4242.4242"

#: Ruta del sistema ficticia incluida en el mensaje de la excepción de prueba.
RUTA_SECRETA = r"C:\gynfem\ruta\secreta.py"

#: Artefactos del modelo commiteados. Los tests solo los leen.
MODELS_DIR = REPO_ROOT / "models"
METADATA_JSON = MODELS_DIR / "model_metadata.json"
FEATURE_RANGES_JSON = MODELS_DIR / "feature_ranges.json"
DATASET_CLEAN = REPO_ROOT / "data" / "processed" / "maternal_risk_clean.csv"

#: Entrada clínica dentro del rango de entrenamiento en las 8 variables.
ENTRADA_NORMAL = {
    "age_years": 28,
    "temperature_c": 36.8,
    "heart_rate_bpm": 80,
    "systolic_bp_mmhg": 118,
    "diastolic_bp_mmhg": 76,
    "bmi_kg_m2": 22.5,
    "hba1c_percent": 5.2,
    "fasting_glucose_mg_dl": 85,
}

#: IMC 32 (obesidad, fuera del máximo entrenado) y HbA1c 7.2 %.
ENTRADA_EXTRAPOLADA = {
    "age_years": 34,
    "temperature_c": 37.0,
    "heart_rate_bpm": 88,
    "systolic_bp_mmhg": 132,
    "diastolic_bp_mmhg": 86,
    "bmi_kg_m2": 32.0,
    "hba1c_percent": 7.2,
    "fasting_glucose_mg_dl": 110,
}

#: Campos de entrada aprobados, en el orden del contrato del modelo.
CAMPOS_CLINICOS = list(ENTRADA_NORMAL)
