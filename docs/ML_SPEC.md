# ML_SPEC — Especificación técnica del modelo de riesgo gestacional

- **Estado:** v4 — incorpora la conversión de unidades, la validación de
  entrada y la carga del modelo en el backend (Fase 8, rama
  `feat/prediction-endpoint`)
- **Fecha:** 2026-09-25 (v3: 2026-09-23, v2: 2026-09-22, v1: 2026-09-21)
- **Fuente de verdad:** `reports/ml/dataset_profile.md` (generado 2026-09-21,
  commit `cf4d0fc`), `reports/ml/data_cleaning_report.md` (generado 2026-09-22),
  `reports/ml/training_report.md` (generado 2026-09-23) y `data/raw/README.md`.
  Todo número de este documento proviene de esos archivos o cita directamente
  el paper de origen. La tesis **no** es fuente técnica para este documento.
- **Convención:** todo lo aún no decidido o no ejecutado se marca como
  **PENDIENTE (Fase N)**, con la fase de `docs/TASK_BREAKDOWN.md`, Sección 1.

> **Nota sobre la numeración.** Hasta la v3 este documento se refería a números
> de PR, y dos veces quedaron desfasados: la v2 marcaba el modelado como
> «PENDIENTE (PR #3)», número que acabó ocupando la corrección de la limpieza,
> y la v3 marcaba el backend como «PENDIENTE (PR #5)», que acabó siendo el
> baseline documental. Desde la v4 las referencias son **fases**. La
> correspondencia con los PR está en `docs/TASK_BREAKDOWN.md`, Sección 1: la
> limpieza es la Fase 5 (PR #2 y #3), el entrenamiento la Fase 6 (PR #4) y el
> servicio de predicción la Fase 8 (PR #7).

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

### 2.2 Dataset procesado (Fase 5)

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

### Nombres finales en el dataset procesado (Fase 5)

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
  la Fase 5:** `prepare_dataset.py` descarta la columna antes de cualquier otra
  transformación.

  **Lo que los tests verifican exactamente** (`tests/test_prepare_dataset.py`),
  sobre las dos variantes de `data/processed/` y solo sobre ellas:

  - `test_salida_no_contiene_name_ni_patient_id`: ninguna columna se llama
    `Name`, `Patient ID` ni `patient_id`.
  - `test_ningun_valor_de_name_aparece_en_el_cuerpo_de_la_salida`: ningún
    valor distinto de la columna `Name` del RAW aparece como token en el
    **contenido completo** del archivo, no solo en la cabecera. El matching
    es insensible a mayúsculas.
  - `test_las_ocho_variables_clinicas_son_numericas`: las 8 features son
    numéricas, lo que descarta texto libre en ellas.

  Fuera del alcance de los tests: reportes, logs y salida de consola. Que
  `Name` no se imprima ahí es una propiedad del código (el script nunca lee
  la columna después de descartarla), no algo que un test compruebe.
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
  **CONSTRUIDO en la Fase 8:** `app/services/unit_conversion.py`, única fuente
  de las fórmulas y de sus inversas en todo el código. No depende de FastAPI.
  Tests: `tests/api/test_unit_conversion.py`, que además comprueba que ningún
  otro archivo de `app/` contiene las constantes de las fórmulas.
- **Versión del esquema de conversión:** `CONVERSION_SCHEMA_VERSION = "1.0.0"`,
  en el mismo módulo. Identifica el conjunto de campos, unidades y fórmulas de
  esta tabla, viaja en cada respuesta de predicción (Sección 6) y se sube si
  cambia cualquiera de ellos.
- **Ningún valor se redondea (decisión A de la Fase 8).** La HbA1c del dataset
  es entera, pero la convertida se envía con todos sus decimales. En un Random
  Forest cada corte es un umbral: los que aprendió para HbA1c son puntos medios
  entre valores enteros observados. Redondear no acerca la entrada a nada que
  el modelo haya visto; solo descarta resolución real (el laboratorio informa
  la HbA1c con 0.1 %, ≈1.09 mmol/mol) y añade una transformación oculta entre
  lo que se registra y lo que entra al modelo. El test del caso 5.7 % exige
  el valor sin redondear.
- El dataset **no se convierte**: `data/processed` conserva las unidades
  originales del RAW (°F, mmol/mol, mmol/L) para poder comparar directamente
  con las cifras del paper. La conversión ocurre únicamente sobre la entrada
  clínica en tiempo de inferencia.

## 5. Validación de entrada

Tres niveles (`docs/API_SPEC.md`, Sección 2.3): imposible → 422 sin predecir;
fuera del rango de entrenamiento → se predice con aviso; dentro → sin aviso.

### 5.1 Nivel a — límites fisiológicos (rechazo)

**PROVISIONALES, pendientes de validación clínica con GynFem.** No hay aún una
fuente clínica aprobada. Se implementaron en la Fase 8 como propuesta técnica,
aprobada como provisional, con un criterio explícito: **atrapar errores de
unidad y de tecleo, no juzgar la clínica**. Por eso son amplios y siempre
contienen el rango de entrenamiento.

Única fuente: `PHYSIOLOGICAL_LIMITS` en `app/services/clinical_limits.py`. De
ahí los leen la validación de la petición, `/api/v1/prediction/schema` y los
tests. Valores vigentes, en unidad clínica y con los extremos incluidos:

| Campo | Mínimo | Máximo | Error de unidad que atrapa |
| --- | --- | --- | --- |
| `age_years` | 10 | 60 | — |
| `temperature_c` | 30 | 43 | Temperatura escrita en °F |
| `heart_rate_bpm` | 30 | 220 | — |
| `systolic_bp_mmhg` | 60 | 250 | — |
| `diastolic_bp_mmhg` | 30 | 150 | — |
| `bmi_kg_m2` | 12 | 70 | — (la obesidad se predice con aviso, no se rechaza) |
| `hba1c_percent` | 3 | 20 | HbA1c escrita en mmol/mol |
| `fasting_glucose_mg_dl` | 20 | 600 | Glucosa escrita en mmol/L |

Además, la diastólica debe ser **menor** que la sistólica: es una condición
lógica, sin ningún número.

**Esta regla rechaza un patrón que el modelo sí vio.** El dataset procesado
tiene **19 filas** con la diastólica mayor o igual que la sistólica, 5 de ellas con los dos valores iguales,
y todas son `high risk`. La limpieza (Fase 5) no las trata. Una presión
diferencial nula o negativa no es fisiológica, así que lo más probable es que
sean errores de captura, pero el modelo las aprendió como alto riesgo. La API
las rechaza con 422 en lugar de predecir. Las cifras las recalcula desde
`data/processed/maternal_risk_clean.csv` el test
`test_ml_spec_documenta_las_filas_del_entrenamiento_que_la_regla_cruzada_rechaza`.

**Decisión (Fase 8): la regla se mantiene.** Es un rechazo por
**imposibilidad fisiológica**, no una limitación del rango de entrenamiento.
Es distinto de la banda de hipotermia (93–95 °F, Fase 6, Sección 7.2), que sí
es fisiológicamente posible y por eso se conservó. Una diastólica mayor o igual
que la sistólica no tiene lectura clínica válida bajo ninguna circunstancia.
Es, por tanto, exactamente el tipo de error de captura que
`app/services/clinical_limits.py` existe para atrapar en el umbral, sin
predecir sobre un dato imposible.

La tabla de arriba transcribe `PHYSIOLOGICAL_LIMITS`, y
`test_la_tabla_de_ml_spec_repite_exactamente_los_limites_fisiologicos` exige
que coincidan.

**Cómo se sustituyen tras la validación médica:** se edita ese diccionario
(`min`, `max`, `status="validated"` y la fuente en `rationale`) y esta tabla.
Ningún test repite los números: los leen del diccionario, y uno exige que la
tabla coincida con él. Si un límite nuevo quedara dentro del rango de
entrenamiento, la carga del modelo falla y la aplicación no arranca
(Sección 9.9).

### 5.2 Nivel b — rango de entrenamiento (aviso de extrapolación, no bloqueo)

- **Origen del rango:** **RESUELTO en la Fase 6.** `models/feature_ranges.json` lo genera
  `scripts/train_model.py` a partir del **split de entrenamiento** de la
  variante de producción —el rango que el modelo vio de verdad—, nunca a mano.
  Tres tests lo respaldan: se recalcula desde el CSV procesado con la semilla
  registrada y debe coincidir exactamente; cubre las 8 variables en el orden
  del metadata; y cada mínimo y cada máximo publicados deben **existir** en su
  columna, lo que delata cualquier valor redondo escrito a mano.

  Rangos vigentes (`training_report.md`, Sección 11.1):

  | Variable | Mínimo | Máximo | Unidad |
  | --- | --- | --- | --- |
  | `age_years` | 15.0 | 47.0 | años |
  | `temperature_f` | 93.0 | 104.0 | °F |
  | `heart_rate_bpm` | 45.0 | 150.0 | lpm |
  | `systolic_bp_mmhg` | 90.0 | 169.0 | mmHg |
  | `diastolic_bp_mmhg` | 57.0 | 125.0 | mmHg |
  | `bmi_kg_m2` | 14.9 | **27.9** | kg/m² |
  | `hba1c_mmol_mol` | 30.0 | 50.0 | mmol/mol |
  | `fasting_glucose_mmol_l` | 3.5 | 8.2 | mmol/L |

  **El IMC máximo es 27.9.** El umbral de obesidad es 30, de modo que el modelo
  **nunca ha visto una gestante con obesidad**, que es justamente un grupo de
  riesgo elevado. Una paciente real con IMC 32 recibe una predicción
  extrapolada. El backend debe advertirlo de forma visible.
- **Consumo del archivo por el backend:** **CONSTRUIDO en la Fase 8.** El
  backend lee `feature_ranges.json` al arrancar y convierte cada extremo a
  unidad clínica con el módulo de conversión. Nunca los escribe a mano: un
  test altera el archivo en una copia temporal y exige que el aviso lo siga.
- **La comparación se hace en unidad clínica**, contra los extremos ya
  convertidos, que son exactamente los que publica
  `/api/v1/prediction/schema`. Comparar tras convertir la entrada daría avisos
  falsos en el propio extremo por el error de coma flotante de la ida y vuelta:
  el mínimo de HbA1c, 30 mmol/mol, se publica como 4.896990392533626 %, que al
  volver a convertirse da 29.999999999999996. Un test exige que los extremos
  publicados no generen aviso y que el siguiente número representable, sí.
- **Un aviso por variable afectada**, con dirección (`below`/`above`), unidad,
  el rango de entrenamiento en unidad clínica y un mensaje fijo.

### 5.3 Decisiones de la Fase 8 sobre la salida

- **C — el aviso no gradúa el alejamiento.** Todos los cortes del Random
  Forest caen dentro del rango de entrenamiento, así que cualquier valor más
  allá del máximo recibe la misma predicción que el máximo (y lo mismo por
  debajo del mínimo). Un IMC de 45 se predice igual que uno de 27.9, y un test
  lo fija. Graduar el aviso («leve», «grave») exigiría umbrales inventados y
  sugeriría una degradación gradual que el modelo no tiene. El mensaje lo dice
  tal cual: «la predicción no refleja cuánto se aleja».
- **D — sin umbral de «resultado no concluyente».** Las probabilidades del
  Random Forest son fracciones de votos sin calibrar, y no hay en el
  repositorio un estudio de calibración que respalde un umbral. Tampoco serían
  un indicador de fiabilidad: en extrapolación, que es el caso peligroso, el
  modelo puede responder con alta confianza. La señal de «sin respaldo
  empírico» es el aviso del nivel b. Ocultar la clase tras un «no concluyente»
  podría esconder una señal de alto riesgo. La respuesta publica siempre la
  clase y las tres probabilidades. Un umbral de confianza, igual que el ajuste
  por asimetría de coste (Sección 9.4, Decisión B), queda **PENDIENTE (fase
  por confirmar)**: ambos exigen validación clínica y datos de calibración.
- **Clase publicada y empates.** La clase es el argmax de `predict_proba` en
  el orden de `classes_`, igual que `predict`, de modo que coincide con las
  métricas publicadas. Un empate exacto se resuelve a favor de la clase que
  aparece antes en ese orden (`high risk`, `low risk`, `mid risk`).

## 6. Trazabilidad de predicciones

Cada predicción debe guardar:

1. Las 8 variables clínicas ingresadas (unidades clínicas peruanas, Sección 4).
2. El vector convertido que efectivamente entró al modelo (unidades del
   dataset, Sección 3).
3. La versión del modelo utilizada.
4. La versión del esquema de unidades/conversión (Sección 4).

**Estado:** los cuatro elementos **viajan en cada respuesta** de
`POST /api/v1/predict` desde la Fase 8 (`input`, `model_input`,
`model_version` y `conversion_schema_version`; `docs/API_SPEC.md`, Sección 3),
de modo que la persistencia puede guardarlos tal cual. Su **almacenamiento**:
**Construido en la Fase 10 (PR #9)**: `gynfem.predictions`; ver
`docs/ERD.md` §3 y `docs/API_SPEC.md` §3.5.

La versión del modelo es `model_metadata.json → model_version` (actualmente
`1.0.0`), y el archivo que le corresponde es
`models/maternal_risk_rf_v1.0.0.joblib`. La del esquema de conversión es
`CONVERSION_SCHEMA_VERSION` (Sección 4).

## 7. Decisiones de limpieza (Fase 5 — resueltas)

Las seis decisiones que la Sección 11 de `reports/ml/dataset_profile.md` dejó
abiertas quedan resueltas así. El detalle completo, con el número de filas que
afecta cada transformación, está en `reports/ml/data_cleaning_report.md`.

| # | Decisión pendiente en el profiling | Resolución en la Fase 5 |
| --- | --- | --- |
| 1 | ¿Deduplicar el grupo de 2 filas con las 8 variables idénticas (`Patient ID` 3543, 3638)? | **Sí, en la variante principal** (−1 fila). La de comparación **no** se deduplica, para reproducir las 6058 filas del paper. |
| 2 | Normalizar los nombres con espacios sobrantes | Hecho: `'Body Temperature(F) '` → `temperature_f` (Sección 3). |
| 3 | `Blood Glucose(HbA1c)` no declara unidad y está en mmol/mol | Renombrada a `hba1c_mmol_mol`. Valores **sin convertir**. |
| 4 | El header dice mg/dl pero los valores están en mmol/L | Renombrada a `fasting_glucose_mmol_l`. Valores **sin convertir**. |
| 5 | ¿Qué hacer con las 45 filas que marcan las reglas del paper? | **Eliminar**, no imputar. Con dos criterios distintos, uno por variante (Sección 2.2). |
| 6 | ¿Regla de temperatura del paper completa o solo lo imposible? | **Decisión A**, abajo. |

### 7.1 Decisión A — las 42 filas de 93.0–94.9 °F: se adopta **A3**

**La decisión (v2):** las 42 filas **se conservan** en la variante principal, y
la decisión final **se toma en la Fase 6 mediante análisis de sensibilidad**,
entrenando con ambas variantes y comparando métricas.

> **RESUELTO en la Fase 6: las 42 filas se conservan.** El análisis de sensibilidad
> se ejecutó y la sospecha de artefacto **no se sostiene**. Ver la Sección 7.2.

**La evidencia** (`data_cleaning_report.md`, Sección 5, Hallazgo b — verificada
por código sobre el RAW):

| Métrica | Valor |
| --- | --- |
| Filas con `temperature_f` en 93.0–94.9 °F | 42 |
| De ellas, `high risk` | **42 (100%)** |
| De ellas, **no** `high risk` | **0** |
| Tasa base de `high risk` en el resto del dataset (6061 filas) | **33.28%** |

**Por qué esto no se cierra en la Fase 5:** una concordancia de 42/42 frente a una
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

### 7.2 Resultado del análisis de sensibilidad (Fase 6)

Todas las cifras de esta subsección provienen de `reports/ml/training_report.md`
(Secciones 7.5 y 9), generadas por `scripts/train_model.py`.

La comparación se hizo sobre la **CV anidada del conjunto de entrenamiento**,
no sobre el conjunto de prueba, de modo que la elección de variante no consulta
el test de ninguna de las dos.

| Medida | Valor |
| --- | --- |
| CV anidada, variante PRINCIPAL | 0.990614 ± 0.004388 |
| CV anidada, variante COMPARACIÓN | 0.990546 ± 0.002926 |
| `delta` (PRINCIPAL − COMPARACIÓN) | **+0.000068** |
| Umbral (1σ de la CV anidada de la ganadora) | 0.004388 |
| CV anidada de PRINCIPAL sin las filas de hipotermia del entrenamiento | 0.990525 ± 0.003938 |
| Caída atribuible a esas filas | 0.000090 |

**Interpretación:** el `delta` entre variantes (0.000068) es unas **65 veces
menor** que el umbral de ruido del propio procedimiento (0.004388). Quitar del
entrenamiento las 36 filas de hipotermia que cayeron allí mueve la métrica
0.000090, otra cantidad de nivel de ruido.

**Conclusión:** el **rendimiento agregado** no depende de las 42 filas: ni lo
aportan ni lo sostienen. Como eliminarlas descartaría 42 de 2058 casos
`high risk` (2.04% de la clase) sin ganancia medible a cambio, **se conservan**.

**Lo que esto no demuestra:**

- **Que el modelo no haya aprendido la regla «93–95 °F ⇒ alto riesgo».** La
  ablación retira esas filas del entrenamiento y, con ello, de la validación de
  la CV anidada, así que nunca evalúa filas de la banda. Contrastar esa
  hipótesis exigiría predecir sobre la banda con un modelo entrenado sin ella.
  No se hizo en la Fase 6 y queda como verificación pendiente.
- **Que las 42 filas sean clínicamente válidas.** La concordancia 42/42 con
  `high risk` frente a una tasa base del 33.28% sigue siendo anómala, y sigue
  siendo más compatible con un artefacto de captura que con hipotermia real en
  consulta ambulatoria. Lo que el análisis descarta es que el **rendimiento
  medido dependa de ellas**. Si el equipo clínico de GynFem llega a confirmar
  que son un error de instrumentación, eliminarlas costaría del orden de
  0.000090 de `f1_macro` en la CV anidada; aplicarlo exigiría reentrenar y
  volver a serializar el modelo.

## 8. Plan de modelado

**EJECUTADO en la Fase 6.** Ver Sección 9 y `reports/ml/training_report.md`.

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

Ambas tablas de métricas se publican en el reporte de la Fase 6, con
independencia de cuál se elija.

**RESUELTO en la Fase 6: la variante de producción es `maternal_risk_clean.csv`**
(la PRINCIPAL), por el caso `D1` de la regla de la Sección 9.4. Las dos tablas
de métricas están publicadas en `reports/ml/training_report.md`, Sección 5.

---

## 9. Modelo entrenado (Fase 6)

Todas las cifras de esta sección provienen de `reports/ml/training_metrics.json`,
emitido por `scripts/train_model.py`, y se publican en
`reports/ml/training_report.md`. Aquí se **transcriben**, y por eso las ata un
test: `test_las_cifras_de_ml_spec_coinciden_con_el_json` exige que las tablas de
esta sección y de la 7.2, y las cifras derivadas del texto, coincidan con el
JSON formateado. Qué cifras del JSON recalcula la suite a partir del código, y
cuáles no, lo detalla `training_report.md`, Sección 13.

### 9.1 Hiperparámetros finales

Salen de una búsqueda con `GridSearchCV` sobre **72 configuraciones**, con
validación cruzada estratificada de 10 folds sobre el entrenamiento y métrica
`f1_macro`. No se copiaron del paper.

| Hiperparámetro | Valor | Explorados |
| --- | --- | --- |
| `n_estimators` | 200 | 200, 500 |
| `max_depth` | 20 | None, 10, 20 |
| `min_samples_leaf` | 1 | 1, 2, 5 |
| `max_features` | `sqrt` | `sqrt`, None |
| `class_weight` | None | None, `balanced` |
| `criterion` | `gini` | fijo, no buscado |

Semilla `42`, `random_state` fijo. Ambas variantes eligieron la misma
configuración de forma independiente.

### 9.2 Métricas reales

El protocolo distingue **tres cifras que no son intercambiables** (Decisión E,
Sección 9.4). La cifra de rendimiento es la del conjunto de prueba apartado.

| Cifra | PRINCIPAL (producción) | COMPARACIÓN |
| --- | --- | --- |
| Puntaje de **selección** (sesgado al alza, **no es rendimiento**) | 0.991839 | 0.991367 |
| CV anidada (estimación insesgada del procedimiento) | 0.990614 ± 0.004388 | 0.990546 ± 0.002926 |
| **Test apartado — `f1_macro`** | **0.987766** | 0.993414 |
| Test apartado — accuracy | 0.987705 | 0.993399 |
| Test apartado — precisión macro | 0.987912 | 0.993423 |
| Test apartado — recall macro | 0.987714 | 0.993407 |
| Errores `high risk` → `low risk` | **0** | 1 |

**Matriz de confusión de la variante de producción** (1220 filas de prueba;
orden de clases `high risk`, `low risk`, `mid risk`):

| Real \ Predicho | `high risk` | `low risk` | `mid risk` |
| --- | --- | --- | --- |
| `high risk` | 405 | 0 | 7 |
| `low risk` | 1 | 394 | 4 |
| `mid risk` | 2 | 1 | 406 |

**Modelos de referencia**, mismo protocolo, mismo conjunto de prueba:

| Modelo | Accuracy | `f1_macro` |
| --- | --- | --- |
| `DummyClassifier(most_frequent)` | 0.3377 | 0.1683 |
| `DecisionTreeClassifier` | 0.9762 | 0.9764 |
| **Random Forest** | **0.9877** | **0.9878** |

**Importancia de variables** (reducción media de impureza; descriptiva, no
causal):

| Variable | Importancia |
| --- | --- |
| `systolic_bp_mmhg` | 0.2260 |
| `heart_rate_bpm` | 0.1647 |
| `temperature_f` | 0.1440 |
| `diastolic_bp_mmhg` | 0.1158 |
| `fasting_glucose_mmol_l` | 0.1092 |
| `hba1c_mmol_mol` | 0.0892 |
| `age_years` | 0.0869 |
| `bmi_kg_m2` | 0.0642 |

### 9.3 Comparación con el paper

El paper (Hossain et al., 2026) reporta **99.34%** de accuracy con Random
Forest. Nuestra variante de producción obtiene **98.77%** sobre su conjunto de
prueba apartado: **−0.57 pp**. La cifra del paper se cita como referencia
externa; no es una meta y no se ha verificado de forma independiente aquí.

> La variante de COMPARACIÓN obtiene 99.34%, exactamente la cifra publicada al
> redondear a dos decimales. **Es una casualidad aritmética**, no una réplica:
> sale de 1204 aciertos sobre 1212 filas, y un acierto más o menos la habría
> movido. `training_report.md` Sección 12 lo deja dicho de forma explícita, y
> nada de este trabajo se orientó a reproducir esa cifra.

### 9.4 Decisiones A–F

| # | Decisión | Resolución |
| --- | --- | --- |
| **A** | ¿Escalado de features? | **No.** Un árbol parte por umbrales, y una transformación afín por columna preserva el orden de los valores, así que el conjunto de particiones alcanzables es idéntico. Medido, no asumido: con y sin `StandardScaler` la CV da **exactamente lo mismo** en la variante de producción (diferencia 0.000000). El `Pipeline` se conserva con un solo paso, y un test verifica que el artefacto no contiene escalador. |
| **B** | ¿Qué métrica decide? | **`f1_macro`**, con la cuenta de errores `high risk` → `low risk` publicada siempre aparte, porque ninguna métrica agregada la distingue del error inverso. `class_weight` se **buscó** en vez de fijarse: con las clases al 33% ganó `None`. La asimetría de coste se trata en inferencia, ajustando el umbral sobre `predict_proba` — **PENDIENTE (fase por confirmar)**: la Fase 8 no lo implementa porque exige validación clínica y un estudio de calibración que no existen (Sección 5.3, decisión D). |
| **C** | ¿Cómo se descarta el sobreajuste? | Seis comprobaciones, todas generadas. **Etiquetas permutadas:** con `risk_level` barajado el puntaje cae de 0.9918 a **0.3337** (azar ≈ 0.3374), p = 0.0099 — no hay fuga. **Solapamiento exacto train/test: 0.** **Banda de coherencia de dos lados** entre test y CV anidada: dentro. **Curva de aprendizaje:** brecha final 0.0080. **Varianza de partición** con `RepeatedStratifiedKFold` solo sobre entrenamiento. **Ablación de hipotermia** (Sección 7.2). |
| **D** | ¿Cómo se comparan las variantes? | Mismo protocolo para las dos, y una regla de cuatro casos. El `delta` se calcula sobre la CV anidada (solo entrenamiento) para que la elección no consulte el test. El repositorio no demuestra que esa base se fijara antes de medir, y la primera redacción del plan usaba el test (Sección 9.5). Se activó el caso **`D1`** (`\|delta\| ≤ umbral`): producción = **`clean`**. Se serializa **un solo modelo**. |
| **E** | ¿Cómo se evita el sesgo de selección en la CV? | Tres cifras separadas y etiquetadas (tabla de 9.2). El puntaje de `GridSearchCV` es de **selección** y está sesgado al alza; la **CV anidada** (externa 10 × interna 5) estima el procedimiento sin ese sesgo; el **test apartado** estima el modelo entregado y es la cifra titular. La diferencia entre selección (0.991839) y CV anidada (0.990614) mide el sesgo: **0.001224** (calculada con las cifras sin redondear). |
| **F** | ¿Versiones fijadas? | `requirements.txt` fija `scikit-learn==1.9.1` y `joblib==1.6.0` con `==`. `model_metadata.json` registra las versiones de Python, scikit-learn, joblib, numpy y pandas leídas en ejecución. **Tres tests**: la versión instalada de scikit-learn frente a la del metadata, la de Python, y que `requirements.txt` las fije de forma exacta. |

### 9.5 Reglas de la Decisión D

Codificadas en `choose_production_variant()`. El umbral es 1σ de la CV anidada
de la variante ganadora.

**Sobre cuándo se fijó la base del `delta`, sin adornos.** El repositorio no
permite demostrar que la regla se fijara antes de la primera medición. Antes de
la Fase 6 esta especificación solo recogía la regla cualitativa (Sección 8.1), y el
umbral y la base entraron en la misma fase que los resultados. La primera
redacción del plan de la Fase 6, que no está versionada, definía el `delta` sobre el
**conjunto de prueba**. Con esa base el `delta` sería **−0.005648**, con un
umbral de 0.002926 (1σ de la CV anidada de `paper`, la ganadora con esa base), y
el caso activado habría sido **`D4`**: producción = **`paper`**.

La base actual, la CV anidada, es preferible porque no consulta el test
(`training_report.md`, Sección 9.1), pero es un cambio respecto de esa primera
redacción y se declara como tal. La elección entre `clean` y `paper` queda
abierta a revisión con esta información a la vista.

| Caso | Condición | Variante |
| --- | --- | --- |
| `D1` | `\|delta\| ≤ umbral` | `clean` |
| `D2` | `delta > umbral` **y** la ablación explica ≥50% de la ventaja | `paper` (artefacto) |
| `D3` | `delta > umbral` **sin** que la ablación la explique | `clean` |
| `D4` | `delta < −umbral` | `paper` |

### 9.6 Contrato del artefacto del modelo

El backend debe poder cargar el modelo sin ambigüedad. Ese es el contrato:

| Artefacto | Qué contiene |
| --- | --- |
| `models/maternal_risk_rf_v1.0.0.joblib` | `Pipeline` de un solo paso con el `RandomForestClassifier` ajustado |
| `models/model_metadata.json` | Orden y unidad de las 8 variables, orden de clases, hiperparámetros, semilla, versiones, SHA-256 del dataset, resumen de métricas, fecha |
| `models/feature_ranges.json` | Mínimo y máximo por variable, generados (Sección 5) |

**Orden de las 8 variables — es contrato, no documentación.** El backend debe
enviar el vector exactamente en este orden y en estas unidades:

| # | Variable | Unidad |
| --- | --- | --- |
| 0 | `age_years` | años |
| 1 | `temperature_f` | °F |
| 2 | `heart_rate_bpm` | lpm |
| 3 | `systolic_bp_mmhg` | mmHg |
| 4 | `diastolic_bp_mmhg` | mmHg |
| 5 | `bmi_kg_m2` | kg/m² |
| 6 | `hba1c_mmol_mol` | mmol/mol (IFCC) |
| 7 | `fasting_glucose_mmol_l` | mmol/L |

Un test comprueba que intercambiar dos variables **cambia** las predicciones:
el orden importa de verdad, no es una lista decorativa.

**Orden de las clases:** `predict_proba` devuelve las columnas en el orden
`["high risk", "low risk", "mid risk"]`, que es el de `classes_` del modelo
serializado y el que registra `model_metadata.json`. **No es el orden de
severidad**; el backend no debe asumirlo.

**El modelo se ajustó solo con el 80% de entrenamiento** (4879 filas de 6099),
no se reajustó sobre el dataset completo. Así la métrica publicada es la de
este artefacto y no la de otro parecido.

**Versión de scikit-learn:** cargar el `.joblib` con una versión distinta de
`1.9.1` puede cambiar el comportamiento en silencio. Un test lo compara y falla
si difieren.

### 9.7 Reproducibilidad: qué se verificó y una desviación declarada

El entrenamiento es determinista: misma semilla, mismas métricas. Entre dos
ejecuciones solo cambian tres valores de reloj (`generated_at`, `created_at`,
`elapsed_seconds`); incluso los PNG son byte-idénticos.

**La desviación:** la rejilla completa de 72 configuraciones se ejecutó **una
sola vez** (13993 s ≈ 3 h 53 min). El determinismo de todos los caminos lo
comprueba un test que compara **dos ejecuciones independientes de rejilla
reducida pero con todas las comprobaciones caras activadas** —CV anidada,
etiquetas permutadas, curva de aprendizaje, varianza de partición y ambas
ablaciones—, en lugar de repetir dos veces la rejilla completa. Ese test no
corre en la suite por defecto y el script no emite su resultado, así que ni
este documento ni el reporte lo publican.

**Por qué es evidencia al menos igual de fuerte:** el tamaño de la rejilla
cambia cuántas veces se llama a `fit`, no qué código se ejecuta. Repetir la
rejilla completa recorrería el mismo camino una segunda vez; la verificación
elegida recorre **todas las ramas** donde podría esconderse una fuente de
aleatoriedad.

**Lo que no cubre:** la rejilla reducida (`REDUCED_PARAM_GRID` en
`tests/conftest.py`) no explora todos los valores de la rejilla completa. Ese
hueco lo cierran `test_las_metricas_publicadas_se_reproducen_al_reentrenar` y
`test_los_folds_de_la_cv_de_seleccion_se_reproducen`, que sí corren en la suite
por defecto y reajustan el modelo con **los hiperparámetros ganadores
concretos**, exigiendo que el test apartado y los folds de la CV se reproduzcan
exactamente, en ambas variantes.

La verificación completa está commiteada como test, no como una nota: se
ejecuta con `GYNFEM_SLOW_TESTS=1 pytest tests/ -k todas_las_comprobaciones`.
Ver `training_report.md`, Sección 14.

### 9.8 Qué queda fuera de la Fase 6

- El servicio de predicción y la conversión de unidades: **construidos en la
  Fase 8** (Secciones 4, 5 y 9.9). El almacenamiento de la trazabilidad:
  **Construido en la Fase 10 (PR #9)** (Sección 6).
- El ajuste del umbral de decisión sobre `predict_proba` para tratar la
  asimetría de coste clínico: **PENDIENTE (fase por confirmar)** (Sección 5.3,
  decisión D).
- Los límites fisiológicos duros de validación de entrada: implementados en la
  Fase 8 como **provisionales**, pendientes de validación clínica con GynFem
  (Sección 5.1).
- Validación externa con datos de otra institución o periodo: no planificada.

### 9.9 Contrato de carga en el backend (Fase 8)

`app/services/model_loader.py` carga el modelo **una sola vez**, al construir
la aplicación, y valida el contrato de la Sección 9.6 contra
`model_metadata.json`. Si algo no coincide lanza `ModelContractError`, y la
aplicación termina con código 1 y un mensaje que nombra la parte del contrato
que falla, sin traza. Nunca se predice con un modelo cuyo contrato no se
comprobó.

| Comprobación | Si falla |
| --- | --- |
| `model_metadata.json` y `feature_ranges.json` existen y son JSON válido | No arranca |
| `model_version` declarado | No arranca |
| La versión de scikit-learn instalada es la del metadata | No arranca |
| Las posiciones de las features son 0..7 sin huecos y sus nombres son las 8 del módulo de conversión | No arranca |
| El orden de features del metadata es exactamente `feature_names_in_` del modelo | No arranca |
| Las clases del metadata son `classes_` del modelo, en el mismo orden, y son las tres conocidas | No arranca |
| `feature_ranges.json` cubre las 8 features con `min < max` | No arranca |
| Cada límite fisiológico (Sección 5.1) contiene el rango de entrenamiento convertido | No arranca |

El vector se envía como `DataFrame` con las columnas en el orden del contrato.
El modelo conserva los nombres con los que se ajustó, así que un reordenamiento
de columnas hace fallar a scikit-learn en vez de producir una predicción
equivocada. Las probabilidades se asignan a su clase **por nombre**, nunca por
posición.

El directorio del modelo es `GYNFEM_MODEL_DIR` (por defecto `models/`;
`docs/DEPLOYMENT.md`, Sección 5.1). `joblib.load` des-serializa un pickle, así
que solo se lee de ese directorio, que controla el operador
(`docs/SECURITY.md`).

Tests: `tests/api/test_model_contract.py`.

**Nota sobre `disclaimer`.** `model_metadata.json` lleva un campo `disclaimer`,
escrito por el entrenamiento. La API no lo usa: la advertencia clínica de las
respuestas vive en `CLINICAL_DISCLAIMER` (`app/services/prediction.py`), su
única fuente en el código.
