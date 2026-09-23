# ML_SPEC — Especificación técnica del modelo de riesgo gestacional

- **Estado:** v1 inicial (rama `docs/technical-baseline`)
- **Fecha:** 2026-09-21
- **Fuente de verdad:** `reports/ml/dataset_profile.md` (generado 2026-09-21,
  commit `cf4d0fc`) y `data/raw/README.md`. Todo número de este documento
  proviene de esos dos archivos o cita directamente el paper de origen. La
  tesis **no** es fuente técnica para este documento.
- **Convención:** todo lo aún no decidido o no ejecutado se marca como
  **PENDIENTE (PR #2/#3)**.

---

## 1. Objetivo del modelo

Clasificación **multiclase** del riesgo gestacional en tres categorías
(`low risk`, `mid risk`, `high risk`) como **apoyo a la decisión clínica**.

El modelo **no** constituye un diagnóstico. Su salida es una señal de apoyo
que el personal clínico de GynFem interpreta junto con su propio juicio
profesional; no reemplaza la evaluación médica.

## 2. Dataset

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

### `Name` y `Patient ID`: excluidos del modelo

- **`Name`:** dato personal identificable (profiling, Sección 2: columna
  presente, 6103 valores no nulos, contenido nunca impreso). Ver también
  `data/raw/README.md` — los nombres provienen de la publicación original
  (Mendeley Data, CC BY 4.0), no pertenecen a pacientes de GynFem, y el
  pipeline de limpieza los descarta en su primer paso.
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
  **Estado: PENDIENTE (PR #2/#3)** — el módulo y sus tests aún no existen en
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
  **Estado: PENDIENTE (PR #3)** — no existe `data/processed` poblado ni un
  proceso de entrenamiento todavía.

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

## 7. Decisiones pendientes para PR #2 (limpieza)

Copiado literal de la Sección 11 de `reports/ml/dataset_profile.md`:

1. Hay 2 filas (1 grupo) que comparten idénticas las 8 variables clínicas
   (Patient ID involucrados: [3543, 3638]). Decidir si se deduplican antes de
   entrenar.
2. Las columnas con espacios sobrantes en el nombre (`'Body Temperature(F) '`)
   deben normalizarse en PR #2.
3. La columna `Blood Glucose(HbA1c)` no declara unidad y los valores indican
   mmol/mol, no %. Documentar o renombrar en PR #2.
4. El header dice mg/dl pero los valores están en mmol/L. En PR #2 se
   renombrará la columna para reflejar la unidad real; NO se convertirán
   valores (decisión aprobada: la conversión desde unidades clínicas vive en
   el backend, ver Sección 4).
5. Las reglas de outliers del paper marcan 45 filas (edad>100: 1, temperatura
   fuera de rango: 43, diastólica<50: 1). Decidir en PR #2 si se eliminan, se
   corrigen o se tratan como missing.
6. **Decidir en PR #2 si se aplica la regla de temperatura del paper completa
   (elimina 42 casos `high risk` con 93.0–94.9 °F, hipotermia clínicamente
   plausible) o solo se eliminan los valores fisiológicamente imposibles
   (edad 250, temperatura 39.6 °F, diastólica 9). Documentar la decisión con
   esta evidencia** (detalle completo en Sección 7 del profiling,
   "Desglose de la regla de temperatura").

## 8. Plan de modelado

**Estado: PENDIENTE (PR #3)** — nada de esto está implementado todavía.

- Split estratificado por `Status` (train/test, y validación si aplica).
- Modelo baseline simple como referencia de comparación.
- Random Forest como modelo principal.
- Validación cruzada sobre el conjunto de entrenamiento.
- Métricas: accuracy, precision, recall, F1-macro, matriz de confusión,
  importancia de variables.
- El paper (Hossain et al., 2026) reporta ~99% de accuracy con Random Forest.
  Esa cifra es **referencia de comparación, nunca una meta** de este
  proyecto, y no ha sido verificada de forma independiente en este
  repositorio.
