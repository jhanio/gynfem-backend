# ML_SPEC — Especificación técnica del modelo de riesgo gestacional

- **Estado:** v2 — incorpora las decisiones de limpieza de PR #2
  (rama `feat/dataset-cleaning`)
- **Fecha:** 2026-09-22 (v1: 2026-09-21)
- **Fuente de verdad:** `reports/ml/dataset_profile.md` (generado 2026-09-21,
  commit `cf4d0fc`), `reports/ml/data_cleaning_report.md` (generado 2026-09-22)
  y `data/raw/README.md`. Todo número de este documento proviene de esos
  archivos o cita directamente el paper de origen. La tesis **no** es fuente
  técnica para este documento.
- **Convención:** todo lo aún no decidido o no ejecutado se marca como
  **PENDIENTE (PR #3)**.

---

## 1. Objetivo del modelo

Clasificación **multiclase** del riesgo gestacional en tres categorías
(`low risk`, `mid risk`, `high risk`) como **apoyo a la decisión clínica**.

El modelo **no** constituye un diagnóstico. Su salida es una señal de apoyo
que el personal clínico de GynFem interpreta junto con su propio juicio
profesional; no reemplaza la evaluación médica.

## 2. Dataset

### 2.1 RAW (inmutable)

- **Fuente:** Hossain et al., *BMC Medical Informatics and Decision Making*,
  2026, 26:79.
- **DOI del paper:** 10.1186/s12911-026-03343-1
- **DOI del dataset:** 10.17632/ckhgtgdg4f
- **Licencia:** CC BY 4.0
- **SHA-256 del RAW:** `2d5b35af3c401329ce3dfd8ef0fb48057f66570e7bae24f6f40c970cb012ae0b`
  (`data/raw/README.md`)
- **Filas:** 6103 — **Columnas:** 11 (`reports/ml/dataset_profile.md`, Sección 1)

**Distribución de clases (RAW, sin filtrar)** — Sección 3 del profiling:

| Clase | Conteo | Porcentaje |
| --- | --- | --- |
| `high risk` | 2059 | 33.74% |
| `mid risk` | 2043 | 33.48% |
| `low risk` | 2001 | 32.79% |

### 2.2 Dataset procesado (PR #2)

Generado por `scripts/prepare_dataset.py`, que lee `data/raw/` y escribe solo
en `data/processed/`. El proceso es determinista: dos ejecuciones producen
archivos byte-idénticos. Todas las cifras de esta subsección provienen de
`reports/ml/data_cleaning_report.md` (Sección 3).

El script genera **dos variantes** en la misma ejecución:

| Variante | Archivo | Filas | SHA-256 |
| --- | --- | --- | --- |
| **PRINCIPAL** | `data/processed/maternal_risk_clean.csv` | 6099 | `abc61dfc78210eb1fa394264942bb33acb69cce0927c0d73ec0025f14cad7abd` |
| **COMPARACIÓN** | `data/processed/maternal_risk_paper.csv` | 6058 | `98be1dbe8283deaab48688b72c6a0130863d1697313c065e8382bf0b0b92b20e` |

**Distribución de clases — PRINCIPAL (6099 filas):**

| Clase | Conteo | Porcentaje |
| --- | --- | --- |
| `high risk` | 2058 | 33.74% |
| `mid risk` | 2043 | 33.50% |
| `low risk` | 1998 | 32.76% |

**Distribución de clases — COMPARACIÓN (6058 filas):**

| Clase | Conteo | Porcentaje |
| --- | --- | --- |
| `high risk` | 2016 | 33.28% |
| `mid risk` | 2043 | 33.72% |
| `low risk` | 1999 | 33.00% |

**En qué se diferencian:**

| Aspecto | PRINCIPAL | COMPARACIÓN |
| --- | --- | --- |
| Deduplicación por las 8 variables clínicas | Sí (−1 fila) | No |
| Regla de edad | `> 100` | `> 100` |
| Regla de diastólica | `< 50` | `< 50` |
| Regla de temperatura | `< 70 °F` (solo lo imposible) | fuera de 95–105 °F (regla del paper) |
| Filas de 93.0–94.9 °F | 42 conservadas | 42 eliminadas |

La única diferencia sustantiva es la **regla de temperatura** (ver Decisión A,
Sección 7.1). La variante de comparación reproduce **exactamente** lo reportado
en el paper: 45 filas eliminadas, 6058 restantes, 2016 high / 2043 mid /
1999 low.

La variante de comparación **no se deduplica** de forma deliberada: ninguna de
las tres reglas del paper alcanza al único grupo duplicado (`Patient ID` 3543 y
3638, ambos `low risk`), de modo que deduplicarla la alejaría de las 6058 filas
publicadas. Por eso conserva 1 grupo duplicado, y la variante principal no
(`data_cleaning_report.md`, Sección 5, Hallazgo a).

## 3. Variables

Las 8 variables clínicas son todas las columnas del RAW excepto `Patient ID`,
`Name` y `Status` (profiling, Sección 1).

| Columna original (CSV) | Unidad real del dataset | Rango observado (RAW) | Evidencia |
| --- | --- | --- | --- |
| `Age` | años (asumido; no verificada formalmente como HbA1c/glucosa) | 15.000–250.000 | Sección 4. Q1=22, Q3=30 consistente con edad materna en años; max=250 es fisiológicamente imposible y queda marcado por la regla "Edad > 100" (Sección 7: 1 fila). |
| `Body Temperature(F) ` (nota: nombre con espacio final) | °F | 39.600–104.000 | Declarada en el header. Sección 7 ("Desglose de la regla de temperatura"): 43 filas fuera de 95–105°F; 42 son `high risk` en 93.0–94.9°F (≈33.9–34.9°C, hipotermia clínicamente plausible) y 1 es `low risk` en 39.6°F (≈4.2°C, valor imposible en °F, probable registro en °C). |
| `Heart rate(bpm)` | lpm (bpm) | 45.000–150.000 | Declarada en el header; rango fisiológicamente plausible (reposo a taquicardia). No marcada por ninguna regla de outliers del paper (Sección 7). |
| `Systolic Blood Pressure(mm Hg)` | mmHg | 90.000–169.000 | Declarada en el header; rango fisiológicamente plausible. No marcada por ninguna regla de outliers del paper. |
| `Diastolic Blood Pressure(mm Hg)` | mmHg | 9.000–142.000 | Declarada en el header. min=9 es fisiológicamente imposible; capturado por la regla "Diastólica < 50 mmHg" (Sección 7: 1 fila). |
| `BMI(kg/m 2)` | kg/m² | 14.900–27.900 | Declarada en el header; rango fisiológicamente plausible (bajo peso a sobrepeso). No marcada por ninguna regla de outliers del paper. |
| `Blood Glucose(HbA1c)` | **mmol/mol (IFCC)**, pese a que el header no declara unidad | 30.000–50.000 | Sección 6 del profiling: valores fuera del rango posible para % (3.5–15.0%) y consistentes con mmol/mol (20.0–75.0). |
| `Blood Glucose(Fasting hour-mg/dl)` | **mmol/L**, pese a que el header dice "mg/dl" | 3.500–8.900 | Sección 6 del profiling: valores demasiado bajos para mg/dL (50–300) y consistentes con mmol/L (2.5–16.5). |

### Nombres finales en el dataset procesado (PR #2)

Ambas variantes tienen exactamente estas 9 columnas, en este orden. El nombre
declara la **unidad real** de la columna, no la del header original:

| Columna original (CSV) | Columna en `data/processed` | Unidad |
| --- | --- | --- |
| `Age` | `age_years` | años |
| `Body Temperature(F) ` | `temperature_f` | °F |
| `Heart rate(bpm)` | `heart_rate_bpm` | lpm |
| `Systolic Blood Pressure(mm Hg)` | `systolic_bp_mmhg` | mmHg |
| `Diastolic Blood Pressure(mm Hg)` | `diastolic_bp_mmhg` | mmHg |
| `BMI(kg/m 2)` | `bmi_kg_m2` | kg/m² |
| `Blood Glucose(HbA1c)` | `hba1c_mmol_mol` | **mmol/mol (IFCC)**, no % |
| `Blood Glucose(Fasting hour-mg/dl)` | `fasting_glucose_mmol_l` | **mmol/L**, pese a que el header dice mg/dl |
| `Status` | `risk_level` | `low risk` / `mid risk` / `high risk` |

El renombrado también normaliza el espacio sobrante de `'Body Temperature(F) '`
(profiling, Sección 11.2).

**El dataset procesado conserva las unidades del dataset original** (°F,
mmol/mol, mmol/L): `prepare_dataset.py` **no convierte ningún valor**. Esto
permite comparar directamente con las cifras del paper. La conversión desde las
unidades clínicas peruanas (°C, %, mg/dl) vive **solo en el backend**, en
tiempo de inferencia — ver Sección 4.

### `Name` y `Patient ID`: excluidos del modelo

- **`Name`:** dato personal identificable (profiling, Sección 2: columna
  presente, 6103 valores no nulos, contenido nunca impreso). Ver también
  `data/raw/README.md` — los nombres provienen de la publicación original
  (Mendeley Data, CC BY 4.0), no pertenecen a pacientes de GynFem, y el
  pipeline de limpieza los descarta en su primer paso. **Implementado en
  PR #2:** `prepare_dataset.py` descarta la columna antes de cualquier otra
  operación, y los tests verifican que no aparece en ninguna salida.
- **`Patient ID`:** es una secuencia estrictamente consecutiva (+1, sin
  huecos), equivalente al orden de fila; correlación de Pearson con `Status`
  (codificado ordinalmente low=0, mid=1, high=2) = **-0.0030**, sin evidencia
  de leakage, pero se excluye por no ser una variable clínica y por riesgo de
  overfitting si producción asigna IDs en otro orden (profiling, Sección 9).

## 4. Unidades de entrada y conversión (decisión aprobada)

El médico ingresa los datos en **unidades clínicas peruanas**:

- Edad en años
- Temperatura en °C
- Frecuencia cardiaca en lpm
- Presión arterial (sistólica/diastólica) en mmHg
- IMC en kg/m²
- HbA1c en %
- Glucosa en ayunas en mg/dl

El **backend convierte antes de invocar el modelo**, a las unidades reales
del dataset (Sección 3):

| Campo de entrada (backend) | Unidad clínica (Perú) | Conversión aplicada | Columna del dataset | Unidad del dataset |
| --- | --- | --- | --- | --- |
| `age_years` | años | sin conversión | `Age` | años |
| `temperature_c` | °C | `°F = °C × 9/5 + 32` | `Body Temperature(F) ` | °F |
| `heart_rate_bpm` | lpm | sin conversión | `Heart rate(bpm)` | lpm |
| `systolic_bp_mmhg` | mmHg | sin conversión | `Systolic Blood Pressure(mm Hg)` | mmHg |
| `diastolic_bp_mmhg` | mmHg | sin conversión | `Diastolic Blood Pressure(mm Hg)` | mmHg |
| `bmi_kg_m2` | kg/m² | sin conversión | `BMI(kg/m 2)` | kg/m² |
| `hba1c_percent` | % | `mmol/mol = (% − 2.152) × 10.929` (sin redondear) | `Blood Glucose(HbA1c)` | mmol/mol |
| `fasting_glucose_mg_dl` | mg/dl | `mmol/L = mg/dl ÷ 18` | `Blood Glucose(Fasting hour-mg/dl)` | mmol/L |

**Reglas de la conversión:**

- La conversión vive **solo en el backend**, en un módulo dedicado con tests
  de casos conocidos: 37 °C → 98.6 °F; 90 mg/dl → 5.0 mmol/L;
  5.7 % → ≈38.78 mmol/mol; ida y vuelta con tolerancia `1e-6`.
  **Estado: PENDIENTE (PR #3)** — el módulo y sus tests aún no existen en
  este repositorio.
- El dataset **no se convierte**: `data/processed` conserva las unidades
  originales del RAW (°F, mmol/mol, mmol/L) para poder comparar directamente
  con las cifras del paper. La conversión ocurre únicamente sobre la entrada
  clínica en tiempo de inferencia.

## 5. Validación de entrada

- **Límites fisiológicos duros (rechazo de la solicitud):** **PENDIENTE de
  validación clínica con GynFem**. No se fijan números sin una fuente clínica
  aprobada por el equipo médico.
- **Rango de entrenamiento (advertencia de extrapolación, no bloqueo):** se
  generará automáticamente a partir de `data/processed` en el momento de
  entrenar, y se guardará junto al modelo (por ejemplo,
  `models/feature_ranges.json`). Nunca se escribe a mano.
  **Estado: PENDIENTE (PR #3)** — `data/processed` ya está poblado (PR #2,
  Sección 2.2), pero no existe todavía un proceso de entrenamiento que genere
  ese archivo. Se generará a partir de la variante que elija la Decisión B
  (Sección 8.1).

## 6. Trazabilidad de predicciones

Cada predicción debe guardar:

1. Las 8 variables clínicas ingresadas (unidades clínicas peruanas, Sección 4).
2. El vector convertido que efectivamente entró al modelo (unidades del
   dataset, Sección 3).
3. La versión del modelo utilizada.
4. La versión del esquema de unidades/conversión (Sección 4).

**Estado: PENDIENTE (PR #3)** — este es el diseño del esquema de
trazabilidad; el servicio de predicción y su almacenamiento aún no están
implementados.

## 7. Decisiones de limpieza (PR #2 — resueltas)

Las seis decisiones que la Sección 11 de `reports/ml/dataset_profile.md` dejó
abiertas quedan resueltas así. El detalle completo, con el número de filas que
afecta cada transformación, está en `reports/ml/data_cleaning_report.md`.

| # | Decisión pendiente en el profiling | Resolución en PR #2 |
| --- | --- | --- |
| 1 | ¿Deduplicar el grupo de 2 filas con las 8 variables idénticas (`Patient ID` 3543, 3638)? | **Sí, en la variante principal** (−1 fila). La de comparación **no** se deduplica, para reproducir las 6058 filas del paper. |
| 2 | Normalizar los nombres con espacios sobrantes | Hecho: `'Body Temperature(F) '` → `temperature_f` (Sección 3). |
| 3 | `Blood Glucose(HbA1c)` no declara unidad y está en mmol/mol | Renombrada a `hba1c_mmol_mol`. Valores **sin convertir**. |
| 4 | El header dice mg/dl pero los valores están en mmol/L | Renombrada a `fasting_glucose_mmol_l`. Valores **sin convertir**. |
| 5 | ¿Qué hacer con las 45 filas que marcan las reglas del paper? | **Eliminar**, no imputar. Con dos criterios distintos, uno por variante (Sección 2.2). |
| 6 | ¿Regla de temperatura del paper completa o solo lo imposible? | **Decisión A**, abajo. |

### 7.1 Decisión A — las 42 filas de 93.0–94.9 °F: se adopta **A3**

**La decisión:** las 42 filas **se conservan** en la variante principal, y la
decisión final **se toma en PR #3 mediante análisis de sensibilidad**,
entrenando con ambas variantes y comparando métricas. No se resuelve aquí.

**La evidencia** (`data_cleaning_report.md`, Sección 5, Hallazgo b — verificada
por código sobre el RAW):

| Métrica | Valor |
| --- | --- |
| Filas con `temperature_f` en 93.0–94.9 °F | 42 |
| De ellas, `high risk` | **42 (100%)** |
| De ellas, **no** `high risk` | **0** |
| Tasa base de `high risk` en el resto del dataset (6061 filas) | **33.28%** |

**Por qué esto no se cierra en PR #2:** una concordancia de 42/42 frente a una
tasa base de 33.28% es un patrón demasiado limpio para ser clínico. Sugiere un
**artefacto de sensor o de captura** antes que hipotermia real: una gestante
con 33.9–34.9 °C está en hipotermia moderada y estaría en urgencias, no en una
consulta prenatal ambulatoria.

> Esto matiza la lectura del profiling (Sección 7), que describe el rango como
> «hipotermia clínicamente plausible». El rango de temperatura *es* plausible en
> aislamiento; lo que no es plausible es el acoplamiento perfecto con la
> etiqueta.

**El riesgo si el artefacto es real:** el modelo aprendería «93–95 °F ⇒ high
risk», una regla que no se sostendría en producción y que además inflaría
artificialmente las métricas de la clase `high risk`.

**Por qué se conservan mientras tanto:** eliminarlas ahora descartaría 42 de
2058 casos `high risk` (2.04% de la clase) por una sospecha todavía no medida.
La variante de comparación existe precisamente para medirla.

**Estado: PENDIENTE (PR #3)** — el análisis de sensibilidad no se ha ejecutado.

## 8. Plan de modelado

**Estado: PENDIENTE (PR #3)** — nada de esto está implementado todavía.

- Split estratificado por `risk_level` (train/test, y validación si aplica).
- Modelo baseline simple como referencia de comparación.
- Random Forest como modelo principal.
- Validación cruzada sobre el conjunto de entrenamiento.
- Métricas: accuracy, precision, recall, F1-macro, matriz de confusión,
  importancia de variables.
- El paper (Hossain et al., 2026) reporta ~99% de accuracy con Random Forest.
  Esa cifra es **referencia de comparación, nunca una meta** de este
  proyecto, y no ha sido verificada de forma independiente en este
  repositorio.

### 8.1 Decisión B — la Fase 6 entrena con **ambas** variantes

**La decisión:** la Fase 6 entrena con `maternal_risk_clean.csv` **y** con
`maternal_risk_paper.csv`, bajo el mismo protocolo (mismo split estratificado,
misma semilla, mismos modelos, mismas métricas), y **reporta las dos tablas de
métricas**, no una.

**El modelo de producción se elige con ese resultado, no antes.** Este
documento no designa una variante ganadora, y ni «principal» ni «comparación»
prejuzgan esa elección: son etiquetas de procedencia, no de calidad.

**Qué responde esa comparación:** es el análisis de sensibilidad de la
Decisión A (Sección 7.1). Las dos variantes difieren, en lo sustantivo, solo en
las 42 filas de 93.0–94.9 °F. Si el rendimiento de la variante principal
depende de forma desproporcionada de esas 42 filas, queda tratado como
artefacto y se eliminan; si ambas variantes rinden de forma equivalente, la
sospecha no se sostiene y conservarlas es lo correcto.

Ambas tablas de métricas se publican en el reporte de PR #3, con
independencia de cuál se elija.

**Estado: PENDIENTE (PR #3)** — no existe todavía ningún proceso de
entrenamiento ni métrica medida en este repositorio.
