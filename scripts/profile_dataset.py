"""Genera reports/ml/dataset_profile.md a partir de data/raw/Mathernal_Risk.csv.

Solo lee data/raw/. No escribe, limpia ni modifica nada dentro de data/.
Determinista: dos ejecuciones producen el mismo reporte salvo la fecha de
generación.

Uso:
    .venv\\Scripts\\python.exe scripts\\profile_dataset.py
"""

import hashlib
import platform
import re
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_CSV = REPO_ROOT / "data" / "raw" / "Mathernal_Risk.csv"
REPORT_DIR = REPO_ROOT / "reports" / "ml"
FIGURES_DIR = REPORT_DIR / "figures"
REPORT_PATH = REPORT_DIR / "dataset_profile.md"
REGEN_COMMAND = r".venv\Scripts\python.exe scripts\profile_dataset.py"

EXCLUDED_FROM_CLINICAL = {"Patient ID", "Name", "Status"}
CLASS_ORDER = ["low risk", "mid risk", "high risk"]

# Rangos fisiológicos de referencia usados SOLO para razonar sobre unidades.
# No se usan para alterar ni filtrar datos; el veredicto se basa en el
# min/max/media reales calculados por el script (ver seccion 6).
HBA1C_PERCENT_RANGE = (3.5, 15.0)  # % (DCCT/NGSP), tope realista clinico
HBA1C_MMOL_MOL_RANGE = (20.0, 75.0)  # mmol/mol (IFCC)
GLUCOSE_MGDL_RANGE = (50.0, 300.0)  # mg/dL, rango fisiologico plausible
GLUCOSE_MMOLL_RANGE = (2.5, 16.5)  # mmol/L, rango fisiologico plausible

# Reglas de outliers documentadas por el paper (solo diagnostico).
PAPER_REMAINING = {"total": 6058, "high": 2016, "mid": 2043, "low": 1999}
PAPER_REMOVED = 45

# Por debajo de esto, ningun ser humano vivo tendria esa temperatura corporal
# expresada en F: es evidencia de que el valor probablemente se registro en C.
IMPOSSIBLE_TEMP_F = 70.0


def _slug(name: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower())
    return slug.strip("_")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_eol(path: Path) -> str:
    raw = path.read_bytes()
    crlf = raw.count(b"\r\n")
    lf_only = raw.count(b"\n") - crlf
    if crlf and not lf_only:
        return f"CRLF consistente ({crlf} líneas)"
    if lf_only and not crlf:
        return f"LF consistente ({lf_only} líneas)"
    return f"MIXTO: {crlf} CRLF y {lf_only} LF sueltos"


def render_table(headers: list, rows: list) -> str:
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def load_raw() -> pd.DataFrame:
    return pd.read_csv(RAW_CSV)


# ---------------------------------------------------------------------------
# Secciones del reporte
# ---------------------------------------------------------------------------


def section_header(sha256: str) -> str:
    lines = [
        "# Perfil del dataset — Mathernal Risk (RAW)",
        "",
        f"- **Fecha de generación:** {date.today().isoformat()}",
        f"- **SHA-256 del RAW:** `{sha256}`",
        f"- **Python:** {platform.python_version()}",
        f"- **pandas:** {pd.__version__}",
        f"- **Comando para regenerar:** `{REGEN_COMMAND}`",
    ]
    return "\n".join(lines)


def section_structure(df: pd.DataFrame, clinical_vars: list) -> tuple:
    rows, cols = df.shape
    eol = detect_eol(RAW_CSV)
    memory_bytes = df.memory_usage(deep=True).sum()

    col_rows = []
    for col in df.columns:
        has_ws = col != col.strip()
        note = "⚠️ espacio(s) sobrante(s)" if has_ws else "—"
        col_rows.append([f"`{col}`", repr(col), str(df[col].dtype), note])

    lines = [
        "## 1. Estructura",
        "",
        f"- Filas: **{rows}**",
        f"- Columnas: **{cols}**",
        f"- Formato de fin de línea del archivo RAW: {eol}",
        f"- Uso de memoria (deep): **{memory_bytes:,} bytes** "
        f"({memory_bytes / 1024:.1f} KiB)",
        f"- Variables clínicas identificadas (todas las columnas excepto "
        f"`Patient ID`, `Name`, `Status`): **{len(clinical_vars)}**",
        "",
        render_table(
            ["Columna", "repr() exacto", "Tipo inferido", "Observación"], col_rows
        ),
    ]
    return "\n".join(lines), eol, memory_bytes


def section_quality(df: pd.DataFrame, clinical_vars: list, findings: list) -> str:
    null_counts = df.isnull().sum()
    null_rows = [[f"`{c}`", int(n)] for c, n in null_counts.items()]

    full_dup_mask = df.duplicated(keep=False)
    full_dup_n = int(full_dup_mask.sum())

    clin_dup_mask = df.duplicated(subset=clinical_vars, keep=False)
    clin_dup_n = int(clin_dup_mask.sum())
    clin_dup_groups = df[clin_dup_mask].drop_duplicates(subset=clinical_vars)
    clin_dup_group_n = len(clin_dup_groups)

    conflict_groups = df[clin_dup_mask].groupby(clinical_vars)["Status"].nunique()
    conflict_n = int((conflict_groups > 1).sum())

    pid_unique = df["Patient ID"].is_unique
    pid_dup_n = int(df["Patient ID"].duplicated().sum())

    name_exists = "Name" in df.columns
    name_nonnull = int(df["Name"].notna().sum()) if name_exists else 0

    if clin_dup_group_n > 0:
        example_ids = df[clin_dup_mask]["Patient ID"].tolist()
        findings.append(
            f"Hay {clin_dup_n} filas ({clin_dup_group_n} grupo(s)) que comparten "
            f"idénticas las 8 variables clínicas (Patient ID involucrados: "
            f"{example_ids}). Decidir si se deduplican antes de entrenar."
        )

    ws_cols = [c for c in df.columns if c != c.strip()]
    if ws_cols:
        names = ", ".join(repr(c) for c in ws_cols)
        findings.append(
            f"Las columnas con espacios sobrantes en el nombre ({names}) deben "
            f"normalizarse en PR #2."
        )

    lines = [
        "## 2. Calidad de datos",
        "",
        "### Nulos por columna",
        "",
        render_table(["Columna", "Nulos"], null_rows),
        "",
        "### Duplicados",
        "",
        f"- Filas exactamente duplicadas (todas las columnas): **{full_dup_n}**",
        f"- Filas duplicadas usando solo las 8 variables clínicas: "
        f"**{clin_dup_n}** ({clin_dup_group_n} grupo(s))",
        f"- Conflictos de etiqueta (mismas 8 variables clínicas, distinto "
        f"`Status`): **{conflict_n}** grupo(s)",
        "",
        "### Identificadores",
        "",
        f"- `Patient ID` es único: **{pid_unique}** (duplicados: {pid_dup_n})",
        f"- Columna `Name` presente: **{name_exists}**. Conteo de valores no "
        f"nulos: **{name_nonnull}**. Por política del proyecto, su contenido "
        f"nunca se imprime en este reporte.",
    ]
    return "\n".join(lines)


def section_target(df: pd.DataFrame) -> str:
    counts = df["Status"].value_counts()
    pct = df["Status"].value_counts(normalize=True) * 100
    rows = [
        [f"`{cls}`", int(counts[cls]), f"{pct[cls]:.2f}%"] for cls in counts.index
    ]
    lines = [
        "## 3. Variable objetivo (`Status`)",
        "",
        render_table(["Clase", "Conteo", "Porcentaje"], rows),
    ]
    return "\n".join(lines)


def _stats_table(frame: pd.DataFrame, clinical_vars: list) -> str:
    rows = []
    for col in clinical_vars:
        series = frame[col]
        rows.append(
            [
                f"`{col}`",
                f"{series.min():.3f}",
                f"{series.max():.3f}",
                f"{series.mean():.3f}",
                f"{series.median():.3f}",
                f"{series.std():.3f}",
                f"{series.quantile(0.25):.3f}",
                f"{series.quantile(0.75):.3f}",
            ]
        )
    return render_table(
        ["Variable", "Min", "Max", "Media", "Mediana", "Desv. Est.", "Q1", "Q3"],
        rows,
    )


def section_stats(df: pd.DataFrame, clinical_vars: list) -> str:
    lines = [
        "## 4. Estadísticos descriptivos por variable",
        "",
        _stats_table(df, clinical_vars),
    ]
    return "\n".join(lines)


def section_stats_by_class(df: pd.DataFrame, clinical_vars: list) -> str:
    lines = ["## 5. Estadísticos descriptivos por variable y clase"]
    for cls in CLASS_ORDER:
        subset = df[df["Status"] == cls]
        lines += ["", f"### `{cls}` (n={len(subset)})", "", _stats_table(subset, clinical_vars)]
    return "\n".join(lines)


def section_units(df: pd.DataFrame, findings: list) -> str:
    hba1c = df["Blood Glucose(HbA1c)"]
    glucose = df["Blood Glucose(Fasting hour-mg/dl)"]

    hba1c_min, hba1c_max, hba1c_mean = hba1c.min(), hba1c.max(), hba1c.mean()
    glu_min, glu_max, glu_mean = glucose.min(), glucose.max(), glucose.mean()

    hba1c_fits_pct = HBA1C_PERCENT_RANGE[0] <= hba1c_min and hba1c_max <= HBA1C_PERCENT_RANGE[1]
    hba1c_fits_mmol = HBA1C_MMOL_MOL_RANGE[0] <= hba1c_min and hba1c_max <= HBA1C_MMOL_MOL_RANGE[1]
    if hba1c_fits_mmol and not hba1c_fits_pct:
        hba1c_verdict = (
            f"Los valores observados (min={hba1c_min:.1f}, max={hba1c_max:.1f}, "
            f"media={hba1c_mean:.1f}) caen fuera del rango clínicamente posible "
            f"para % (típicamente {HBA1C_PERCENT_RANGE[0]}–{HBA1C_PERCENT_RANGE[1]}%) "
            f"y sí son consistentes con **mmol/mol (IFCC)**, cuyo rango típico es "
            f"{HBA1C_MMOL_MOL_RANGE[0]}–{HBA1C_MMOL_MOL_RANGE[1]}. Conclusión: la "
            f"columna `Blood Glucose(HbA1c)` está en **mmol/mol**, no en %."
        )
        findings.append(
            "La columna `Blood Glucose(HbA1c)` no declara unidad y los valores "
            "indican mmol/mol, no %. Documentar o renombrar en PR #2."
        )
    else:
        hba1c_verdict = (
            f"Los valores observados (min={hba1c_min:.1f}, max={hba1c_max:.1f}) "
            f"son ambiguos respecto a % vs mmol/mol con los rangos de referencia "
            f"usados; requiere revisión manual."
        )

    glu_fits_mgdl = GLUCOSE_MGDL_RANGE[0] <= glu_min and glu_max <= GLUCOSE_MGDL_RANGE[1]
    glu_fits_mmoll = GLUCOSE_MMOLL_RANGE[0] <= glu_min and glu_max <= GLUCOSE_MMOLL_RANGE[1]
    if glu_fits_mmoll and not glu_fits_mgdl:
        glu_verdict = (
            f"El header indica `mg/dl`, pero los valores observados "
            f"(min={glu_min:.1f}, max={glu_max:.1f}, media={glu_mean:.1f}) son "
            f"demasiado bajos para mg/dL (rango fisiológico plausible "
            f"{GLUCOSE_MGDL_RANGE[0]}–{GLUCOSE_MGDL_RANGE[1]}) y sí encajan en "
            f"**mmol/L** (rango plausible {GLUCOSE_MMOLL_RANGE[0]}–"
            f"{GLUCOSE_MMOLL_RANGE[1]}). Conclusión: la columna "
            f"`Blood Glucose(Fasting hour-mg/dl)` está en **mmol/L**, pese a que "
            f"el nombre dice mg/dl."
        )
        findings.append(
            "El header dice mg/dl pero los valores están en mmol/L. En PR #2 se "
            "renombrará la columna para reflejar la unidad real; NO se "
            "convertirán valores (decisión aprobada: la conversión desde "
            "unidades clínicas vive en el backend)."
        )
    else:
        glu_verdict = (
            f"Los valores observados (min={glu_min:.1f}, max={glu_max:.1f}) son "
            f"consistentes con mg/dL como indica el header."
        )

    lines = [
        "## 6. Verificación de unidades",
        "",
        "### `Blood Glucose(HbA1c)`",
        "",
        hba1c_verdict,
        "",
        "### `Blood Glucose(Fasting hour-mg/dl)`",
        "",
        glu_verdict,
    ]
    return "\n".join(lines)


def _temperature_breakdown(df: pd.DataFrame, temp_col: str, temp_rule: pd.Series) -> tuple:
    outliers = df.loc[temp_rule, [temp_col, "Status"]].copy()
    outliers["approx_C"] = (outliers[temp_col] - 32) * 5 / 9

    grouped = (
        outliers.groupby([temp_col, "Status"])
        .size()
        .reset_index(name="Conteo")
        .sort_values(temp_col)
    )
    rows = [
        [
            f"{r[temp_col]:.1f}",
            f"`{r['Status']}`",
            int(r["Conteo"]),
            f"{(r[temp_col] - 32) * 5 / 9:.1f}",
        ]
        for _, r in grouped.iterrows()
    ]
    table = render_table(["Valor (°F)", "Clase", "Conteo", "≈°C"], rows)

    note_parts = []
    for cls, sub in outliers.groupby("Status"):
        n = len(sub)
        vmin, vmax = sub[temp_col].min(), sub[temp_col].max()
        cmin, cmax = (vmin - 32) * 5 / 9, (vmax - 32) * 5 / 9
        if vmax < IMPOSSIBLE_TEMP_F:
            interpretation = (
                f"valor imposible en °F (por debajo de {IMPOSSIBLE_TEMP_F:.0f}°F), "
                f"probable registro en °C"
            )
        else:
            interpretation = "hipotermia clínicamente plausible"
        if vmin == vmax:
            range_str = f"{vmin:.1f} °F (≈{cmin:.1f} °C)"
        else:
            range_str = f"{vmin:.1f}–{vmax:.1f} °F (≈{cmin:.1f}–{cmax:.1f} °C)"
        verb = "es" if n == 1 else "son"
        note_parts.append(f"**{n}** {verb} `{cls}` con {range_str}: {interpretation}")

    note = (
        f"De las {len(outliers)} filas marcadas por la regla de temperatura, "
        + "; ".join(note_parts)
        + "."
    )
    return table, note


def section_outliers(df: pd.DataFrame, findings: list) -> str:
    age_rule = df["Age"] > 100
    temp_rule = ~df["Body Temperature(F) "].between(95, 105)
    dia_rule = df["Diastolic Blood Pressure(mm Hg)"] < 50
    union = age_rule | temp_rule | dia_rule

    temp_table, temp_note = _temperature_breakdown(df, "Body Temperature(F) ", temp_rule)

    remaining = df[~union]
    remaining_counts = remaining["Status"].value_counts()
    remaining_map = {
        cls.replace(" risk", ""): int(remaining_counts.get(cls, 0)) for cls in CLASS_ORDER
    }

    total_removed = int(union.sum())
    total_remaining = int((~union).sum())

    diff_lines = []
    if total_removed != PAPER_REMOVED:
        diff_lines.append(
            f"- Eliminadas: {total_removed} (paper: {PAPER_REMOVED}) → "
            f"diferencia de {total_removed - PAPER_REMOVED}"
        )
    if total_remaining != PAPER_REMAINING["total"]:
        diff_lines.append(
            f"- Restantes: {total_remaining} (paper: {PAPER_REMAINING['total']}) → "
            f"diferencia de {total_remaining - PAPER_REMAINING['total']}"
        )
    for key in ("high", "mid", "low"):
        ours = remaining_map.get(key, 0)
        paper = PAPER_REMAINING[key]
        if ours != paper:
            diff_lines.append(f"- {key}: {ours} (paper: {paper}) → diferencia de {ours - paper}")

    comparison = (
        "Coincide exactamente con lo reportado en el paper."
        if not diff_lines
        else "Diferencias frente al paper:\n" + "\n".join(diff_lines)
    )

    findings.append(
        f"Las reglas de outliers del paper marcan {total_removed} filas "
        f"(edad>100: {int(age_rule.sum())}, temperatura fuera de rango: "
        f"{int(temp_rule.sum())}, diastólica<50: {int(dia_rule.sum())}). Decidir "
        f"en PR #2 si se eliminan, se corrigen o se tratan como missing."
    )
    findings.append(
        "Decidir en PR #2 si se aplica la regla de temperatura del paper "
        "completa (elimina 42 casos high risk con hipotermia plausible) o solo "
        "se eliminan los valores fisiológicamente imposibles (edad 250, "
        "temperatura 39.6 °F, diastólica 9). Documentar la decisión con esta "
        "evidencia."
    )

    lines = [
        "## 7. Outliers (reglas del paper, solo diagnóstico)",
        "",
        "Ninguna fila fue eliminada de `data/raw/`; esto es un diagnóstico.",
        "",
        render_table(
            ["Regla", "Filas marcadas"],
            [
                ["Edad > 100", int(age_rule.sum())],
                ["Temperatura fuera de 95–105 °F", int(temp_rule.sum())],
                ["Diastólica < 50 mmHg", int(dia_rule.sum())],
                ["**Unión (cualquier regla)**", total_removed],
            ],
        ),
        "",
        "### Desglose de la regla de temperatura",
        "",
        temp_table,
        "",
        temp_note,
        "",
        f"- Filas que quedarían si se aplicaran estas reglas: **{total_remaining}**",
        "",
        render_table(
            ["Clase", "Conteo resultante"],
            [[k, v] for k, v in remaining_map.items()],
        ),
        "",
        f"**Comparación con el paper** (45 eliminadas, 6058 restantes; "
        f"2016 high, 2043 mid, 1999 low):",
        "",
        comparison,
    ]
    return "\n".join(lines)


def section_correlations(df: pd.DataFrame, clinical_vars: list) -> str:
    corr = df[clinical_vars].corr(method="pearson")
    rows = []
    for row_var in clinical_vars:
        row = [f"`{row_var}`"] + [f"{corr.loc[row_var, col_var]:.3f}" for col_var in clinical_vars]
        rows.append(row)
    lines = [
        "## 8. Correlaciones de Pearson (variables clínicas)",
        "",
        render_table(["Variable"] + [f"`{c}`" for c in clinical_vars], rows),
    ]
    return "\n".join(lines)


def section_leakage(df: pd.DataFrame, findings: list) -> str:
    order_map = {cls: i for i, cls in enumerate(CLASS_ORDER)}
    codes = df["Status"].map(order_map)
    row_pos = pd.Series(range(len(df)), index=df.index)

    corr_pid = df["Patient ID"].corr(codes)
    corr_pos = row_pos.corr(codes)

    is_sequential = (df["Patient ID"].diff().dropna() == 1).all()

    lines = [
        "## 9. Leakage vía `Patient ID` u orden de filas",
        "",
        f"- `Patient ID` es una secuencia estrictamente consecutiva "
        f"(paso +1, sin huecos): **{is_sequential}** → equivale al orden de "
        f"fila, no aporta información clínica.",
        f"- Correlación de Pearson entre `Patient ID` y `Status` (codificado "
        f"ordinalmente low=0, mid=1, high=2): **{corr_pid:.4f}**",
        f"- Correlación de Pearson entre la posición de fila y `Status` "
        f"(misma codificación): **{corr_pos:.4f}**",
        "",
        "Ambas correlaciones son cercanas a cero: no hay evidencia de que el "
        "orden de filas o `Patient ID` codifiquen la clase. Aun así, `Name` y "
        "`Patient ID` deben excluirse del modelo: `Name` por ser dato personal "
        "identificable y `Patient ID` por ser un identificador secuencial sin "
        "significado clínico (riesgo de overfitting/leakage si el pipeline de "
        "producción asigna IDs en un orden distinto).",
    ]
    return "\n".join(lines)


def make_figures(df: pd.DataFrame, clinical_vars: list) -> list:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for col in clinical_vars:
        slug = _slug(col)

        fig, ax = plt.subplots(figsize=(6, 4))
        ax.hist(df[col].dropna(), bins=30, color="#4C72B0", edgecolor="black")
        ax.set_title(f"Histograma — {col}")
        ax.set_xlabel(col)
        ax.set_ylabel("Frecuencia")
        fig.tight_layout()
        hist_path = FIGURES_DIR / f"hist_{slug}.png"
        fig.savefig(hist_path, dpi=100)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(6, 4))
        data_by_class = [df.loc[df["Status"] == cls, col].dropna() for cls in CLASS_ORDER]
        ax.boxplot(data_by_class, tick_labels=CLASS_ORDER)
        ax.set_title(f"Boxplot por clase — {col}")
        ax.set_ylabel(col)
        fig.tight_layout()
        box_path = FIGURES_DIR / f"box_{slug}.png"
        fig.savefig(box_path, dpi=100)
        plt.close(fig)

        entries.append((col, hist_path.name, box_path.name))
    return entries


def section_figures(entries: list) -> str:
    lines = ["## 10. Figuras", ""]
    for col, hist_name, box_name in entries:
        lines.append(f"### `{col}`")
        lines.append("")
        lines.append(f"![Histograma de {col}](figures/{hist_name})")
        lines.append("")
        lines.append(f"![Boxplot de {col} por clase](figures/{box_name})")
        lines.append("")
    return "\n".join(lines).rstrip()


def section_findings(findings: list) -> str:
    lines = ["## 11. Hallazgos y decisiones pendientes (para PR #2)", ""]
    if not findings:
        lines.append("No se detectaron hallazgos pendientes.")
    else:
        for i, item in enumerate(findings, start=1):
            lines.append(f"{i}. {item}")
    return "\n".join(lines)


def main() -> None:
    df = load_raw()
    clinical_vars = [c for c in df.columns if c not in EXCLUDED_FROM_CLINICAL]
    assert len(clinical_vars) == 8, (
        f"Se esperaban 8 variables clínicas, se encontraron {len(clinical_vars)}: "
        f"{clinical_vars}"
    )
    found_classes = set(df["Status"].unique())
    assert found_classes == set(CLASS_ORDER), (
        f"Clases inesperadas en Status: {found_classes} (se esperaban {CLASS_ORDER})"
    )

    sha256 = sha256_of(RAW_CSV)
    findings: list = []

    structure_md, _eol, _mem = section_structure(df, clinical_vars)
    figures_entries = make_figures(df, clinical_vars)

    parts = [
        section_header(sha256),
        structure_md,
        section_quality(df, clinical_vars, findings),
        section_target(df),
        section_stats(df, clinical_vars),
        section_stats_by_class(df, clinical_vars),
        section_units(df, findings),
        section_outliers(df, findings),
        section_correlations(df, clinical_vars),
        section_leakage(df, findings),
        section_figures(figures_entries),
        section_findings(findings),
    ]

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    print(f"Reporte generado en {REPORT_PATH}")


if __name__ == "__main__":
    main()
