"""Limpieza reproducible del dataset Mathernal Risk.

Lee `data/raw/Mathernal_Risk.csv` (inmutable) y escribe dos variantes en
`data/processed/`:

- `maternal_risk_clean.csv`  (PRINCIPAL)   — deduplica y elimina solo los
  valores fisiologicamente imposibles.
- `maternal_risk_paper.csv`  (COMPARACION) — aplica las reglas de outliers
  del paper (Hossain et al., 2026) sin deduplicar, para reproducir
  exactamente las 6058 filas publicadas.

Antes de leer nada, verifica que el RAW coincide con el SHA-256 registrado en
`data/raw/README.md` y aborta con `RawIntegrityError` si no.

El proceso es determinista: no usa aleatoriedad, muestreo ni orden dependiente
del sistema de archivos. Dos ejecuciones producen archivos byte-identicos.

La columna `Name` se descarta en el primer paso y su contenido nunca se lee,
imprime ni registra.

Regenerar:  .venv\\Scripts\\python.exe scripts\\prepare_dataset.py
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_CSV = REPO_ROOT / "data" / "raw" / "Mathernal_Risk.csv"
RAW_README = REPO_ROOT / "data" / "raw" / "README.md"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
CLEAN_CSV = PROCESSED_DIR / "maternal_risk_clean.csv"
PAPER_CSV = PROCESSED_DIR / "maternal_risk_paper.csv"

#: Columnas del RAW que se descartan antes de cualquier otro paso.
#: `Name` es dato personal identificable; `Patient ID` es un identificador
#: secuencial sin significado clinico (ver ML_SPEC.md, Seccion 3).
DROPPED_COLUMNS = ("Name", "Patient ID")

#: Nombre original en el CSV -> nombre snake_case con la unidad real.
#: Las unidades son las verificadas en reports/ml/dataset_profile.md (Seccion 6):
#: HbA1c esta en mmol/mol y la glucosa en ayunas en mmol/L, pese al header.
COLUMN_RENAMES = {
    "Age": "age_years",
    "Body Temperature(F) ": "temperature_f",  # el nombre original lleva un espacio final
    "Heart rate(bpm)": "heart_rate_bpm",
    "Systolic Blood Pressure(mm Hg)": "systolic_bp_mmhg",
    "Diastolic Blood Pressure(mm Hg)": "diastolic_bp_mmhg",
    "BMI(kg/m 2)": "bmi_kg_m2",
    "Blood Glucose(HbA1c)": "hba1c_mmol_mol",
    "Blood Glucose(Fasting hour-mg/dl)": "fasting_glucose_mmol_l",
    "Status": "risk_level",
}

OUTPUT_COLUMNS = tuple(COLUMN_RENAMES.values())
CLINICAL_COLUMNS = OUTPUT_COLUMNS[:-1]
TARGET_COLUMN = OUTPUT_COLUMNS[-1]

# --- Umbrales -------------------------------------------------------------
# Todos provienen del paper o del profiling; ninguno se fija a mano.

#: Reglas de outliers del paper (dataset_profile.md, Seccion 7).
PAPER_MAX_AGE_YEARS = 100
PAPER_TEMPERATURE_RANGE_F = (95.0, 105.0)
PAPER_MIN_DIASTOLIC_MMHG = 50

#: Umbral de temperatura de la variante principal. El profiling (Seccion 7,
#: "Desglose de la regla de temperatura") califica 39.6 F como "valor imposible
#: en F (por debajo de 70F)". Se usa ese mismo umbral para eliminar unicamente
#: ese registro y conservar la hipotermia plausible de 93.0-94.9 F.
IMPOSSIBLE_MIN_TEMPERATURE_F = 70.0

#: Salto de linea fijo: `to_csv` usaria os.linesep, lo que haria los bytes
#: dependientes del sistema operativo.
LINE_TERMINATOR = "\n"


def sha256_of_file(path: Path) -> str:
    """Devuelve el SHA-256 hexadecimal del archivo."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    """Ruta relativa al repo cuando aplica; absoluta si esta fuera de el."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


class RawIntegrityError(RuntimeError):
    """El RAW no coincide con el SHA-256 registrado en `data/raw/README.md`."""


def recorded_raw_sha256() -> str:
    """SHA-256 del RAW tal como lo registra `data/raw/README.md`."""
    texto = RAW_README.read_text(encoding="utf-8")
    match = re.search(r"SHA-256:\*\*\s*`([0-9a-f]{64})`", texto)
    if match is None:
        raise RawIntegrityError(
            f"No se encontro el SHA-256 registrado en {_display_path(RAW_README)}. "
            "El RAW no puede procesarse sin una referencia de integridad."
        )
    return match.group(1)


def verify_raw_integrity() -> str:
    """Aborta si el RAW cambio. Devuelve el SHA-256 verificado.

    `data/raw/` es inmutable por contrato. Procesar un RAW alterado produciria
    variantes nuevas en silencio, con SHA-256 distintos de los publicados en
    reports/ml/data_cleaning_report.md.
    """
    actual = sha256_of_file(RAW_CSV)
    registrado = recorded_raw_sha256()
    if actual != registrado:
        raise RawIntegrityError(
            f"El RAW no coincide con el SHA-256 registrado.\n"
            f"  archivo:    {_display_path(RAW_CSV)}\n"
            f"  registrado: {registrado}  ({_display_path(RAW_README)})\n"
            f"  calculado:  {actual}\n"
            "data/raw/ es inmutable: restaura el archivo original en vez de "
            "actualizar el README."
        )
    return actual


def load_raw() -> pd.DataFrame:
    """Lee el RAW, descarta `Name` y `Patient ID`, y renombra a snake_case."""
    raw = pd.read_csv(RAW_CSV)
    sin_identificadores = raw.drop(columns=list(DROPPED_COLUMNS))
    renombrado = sin_identificadores.rename(columns=COLUMN_RENAMES)
    return renombrado[list(OUTPUT_COLUMNS)]


def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """Conserva la primera fila de cada grupo con las 8 variables identicas.

    El profiling (Seccion 2) confirma 0 conflictos de etiqueta, asi que quedarse
    con la primera no descarta informacion de `risk_level`.

    Se aplica solo a la variante PRINCIPAL: ninguna regla del paper alcanza al
    grupo duplicado, de modo que deduplicar la variante de comparacion la
    alejaria de las 6058 filas publicadas.
    """
    return df.drop_duplicates(subset=list(CLINICAL_COLUMNS), keep="first")


def drop_physiologically_impossible(df: pd.DataFrame) -> pd.DataFrame:
    """Variante PRINCIPAL: elimina solo lo fisiologicamente imposible.

    Edad 250 anios, temperatura 39.6 F (~4.2 C) y diastolica 9 mmHg. Conserva
    los 42 casos `high risk` de 93.0-94.9 F, que el profiling documenta como
    hipotermia clinicamente plausible.
    """
    imposibles = (
        (df["age_years"] > PAPER_MAX_AGE_YEARS)
        | (df["temperature_f"] < IMPOSSIBLE_MIN_TEMPERATURE_F)
        | (df["diastolic_bp_mmhg"] < PAPER_MIN_DIASTOLIC_MMHG)
    )
    return df.loc[~imposibles]


def drop_paper_outliers(df: pd.DataFrame) -> pd.DataFrame:
    """Variante COMPARACION: reglas de outliers del paper, sin deduplicar."""
    temperatura_min, temperatura_max = PAPER_TEMPERATURE_RANGE_F
    marcadas = (
        (df["age_years"] > PAPER_MAX_AGE_YEARS)
        | (~df["temperature_f"].between(temperatura_min, temperatura_max))
        | (df["diastolic_bp_mmhg"] < PAPER_MIN_DIASTOLIC_MMHG)
    )
    return df.loc[~marcadas]


def write_variant(df: pd.DataFrame, path: Path) -> str:
    """Escribe la variante y devuelve el SHA-256 del archivo resultante."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, lineterminator=LINE_TERMINATOR)
    return sha256_of_file(path)


def _describe(df: pd.DataFrame) -> dict[str, int]:
    """Distribucion de clases en orden fijo (determinista para el log)."""
    conteos = df[TARGET_COLUMN].value_counts()
    return {etiqueta: int(conteos[etiqueta]) for etiqueta in sorted(conteos.index)}


def main(out_dir: Path | None = None) -> dict[str, dict[str, object]]:
    """Genera ambas variantes y devuelve un resumen de cada una.

    `out_dir` permite escribir fuera de `data/processed/`. Los tests lo apuntan
    a un `tmp_path` para no reescribir nunca los artefactos commiteados.
    """
    destino = PROCESSED_DIR if out_dir is None else Path(out_dir)
    raw_sha = verify_raw_integrity()
    sin_identificadores = load_raw()
    deduplicado = deduplicate(sin_identificadores)

    variantes = {
        # PRINCIPAL: deduplicada, solo se eliminan los valores imposibles.
        "clean": (drop_physiologically_impossible(deduplicado), destino / CLEAN_CSV.name),
        # COMPARACION: reglas del paper sobre el RAW completo, sin deduplicar,
        # para reproducir exactamente las 6058 filas publicadas.
        "paper": (drop_paper_outliers(sin_identificadores), destino / PAPER_CSV.name),
    }

    resumen: dict[str, dict[str, object]] = {}
    for nombre, (df, path) in variantes.items():
        sha = write_variant(df, path)
        resumen[nombre] = {
            "path": _display_path(path),
            "rows": len(df),
            "distribution": _describe(df),
            "sha256": sha,
        }

    print(f"RAW: {RAW_CSV.relative_to(REPO_ROOT)}")
    print(f"  filas: {len(sin_identificadores)}  SHA-256 verificado: {raw_sha}")
    eliminadas = len(sin_identificadores) - len(deduplicado)
    print(f"Deduplicacion (solo variante principal): {eliminadas} fila(s) eliminada(s)")
    for nombre, datos in resumen.items():
        print(f"{nombre}: {datos['path']}")
        print(f"  filas: {datos['rows']}  distribucion: {datos['distribution']}")
        print(f"  SHA-256: {datos['sha256']}")

    return resumen


if __name__ == "__main__":
    main()
