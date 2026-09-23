# Reporte de limpieza — Mathernal Risk (PR #2)

- **Fecha de generación:** 2026-09-22 (correcciones de revisión: 2026-09-22,
  rama `fix/dataset-cleaning-review`)
- **Estado:** PR #2 mergeado en `main` (commit `39c8741`)
- **Script:** `scripts/prepare_dataset.py`
- **Python:** 3.12.10 — **pandas:** 3.0.6
- **Comando para regenerar:** `.venv\Scripts\python.exe scripts\prepare_dataset.py`
- **Fuente de verdad:** `data/raw/Mathernal_Risk.csv` y
  `reports/ml/dataset_profile.md`. Ninguna cifra de este documento se inventa:
  todas provienen del RAW o del profiling. Pero **no todas las emite el
  script**, y conviene saber cuáles:

| Origen | Cifras |
| --- | --- |
| **Emitidas por `prepare_dataset.py`** en cada ejecución (`main()`, salida de consola) | SHA-256 del RAW; filas del RAW; filas eliminadas por deduplicación; y por variante: ruta, filas, distribución de clases y SHA-256 |
| **Fijadas por los tests** (fallan si dejan de cuadrar) | Filas y distribución de ambas variantes; los dos SHA-256 de la Sección 3, leídos de este documento; conteo por regla del paper (1 / 43 / 1, unión 45); las 3 filas imposibles de la variante principal; las 42 filas de 93.0–94.9 °F; los umbrales, mediante filas sintéticas en su límite exacto |
| **Verificadas por código *ad hoc* durante la revisión externa**, no regeneradas por el repositorio | Correlación de Pearson de `Patient ID` (§2.1); `Patient ID` del par duplicado (§2.3); porcentajes de clase (§3); tasa base de 33.28% y 2.04% (§4, §5b); escenario contrafactual de 6057 filas (§5a); hash CRLF `9b26421b…` (§6); barrido de tokens de `Name` (encabezado) |

  Las de la tercera fila se recalcularon una a una en la revisión de este PR y
  reprodujeron exactamente, salvo las dos correcciones que registra este
  documento. No hay código commiteado que las regenere.

> **Política sobre `Name`:** la columna se descarta en el primer paso del
> pipeline. Su contenido no se lee, imprime ni registra en ningún punto de
> este reporte, del script ni de los tests.
>
> Verificado por código a nivel de token contra los **5794** valores distintos
> de `Name` (`raw["Name"].nunique()`, idéntico tras `.str.strip()` y tras
> `.str.lower()`): **0 coincidencias** en `maternal_risk_clean.csv`,
> `maternal_risk_paper.csv`, `scripts/prepare_dataset.py` y
> `tests/test_prepare_dataset.py`.
>
> **Criterio de matching:** tokens alfabéticos de ≥2 caracteres
> (`[A-Za-z']{2,}`), **sensible a mayúsculas**, sobre el contenido completo de
> cada archivo. El criterio importa: con matching *insensible* a mayúsculas
> aparecen 3 coincidencias en este reporte (`para`, `rama`, `viva`) y 1 en el
> script (`para`), todas palabras españolas corrientes que por casualidad
> también son valores de la columna `Name`.
>
> Bajo el criterio sensible a mayúsculas hay **1** coincidencia en este
> documento: la palabra «Rama» que encabezaba la versión anterior (el término
> español para *branch*). Se conserva la nota porque el patrón se repite: un
> `grep` ingenuo sobre los nombres produce falsos positivos léxicos, no fugas.
>
> Desde las correcciones de revisión, el barrido sobre las dos variantes de
> `data/processed/` **es un test**
> (`test_ningun_valor_de_name_aparece_en_el_cuerpo_de_la_salida`), que usa el
> criterio más estricto de los dos: insensible a mayúsculas. El barrido sobre
> reportes y código sigue siendo manual.

---

## 1. Entrada

| Campo | Valor |
| --- | --- |
| Archivo | `data/raw/Mathernal_Risk.csv` |
| SHA-256 | `2d5b35af3c401329ce3dfd8ef0fb48057f66570e7bae24f6f40c970cb012ae0b` |
| Filas | 6103 |
| Columnas | 11 |

`data/raw/` es inmutable: el pipeline solo lee de ahí y escribe exclusivamente
en `data/processed/`. Dos controles lo sostienen:

- **En el script:** `verify_raw_integrity()` compara el SHA-256 del RAW con el
  registrado en `data/raw/README.md` **antes de leer o escribir nada**, y
  aborta con `RawIntegrityError` si no coinciden. Un RAW alterado no llega a
  producir archivos de salida.
- **En los tests:** `test_raw_sha256_no_cambia_tras_ejecutar_el_pipeline`
  vuelve a calcular el SHA-256 después de ejecutar el pipeline y lo compara
  con el registrado.

---

## 2. Transformaciones

### 2.1 Descartar `Name` y `Patient ID`

**Filas afectadas:** 0 — **Columnas afectadas:** 2 (11 → 9)

- **`Name`:** dato personal identificable. Se descarta en el primer paso del
  pipeline, antes de cualquier otra operación (`ML_SPEC.md` §3;
  `data/raw/README.md`).
- **`Patient ID`:** secuencia estrictamente consecutiva (+1, sin huecos),
  equivalente al orden de fila. Correlación de Pearson con `Status` (low=0,
  mid=1, high=2) = **-0.0030**: sin evidencia de leakage, pero se excluye por
  no ser una variable clínica y por riesgo de overfitting si producción asigna
  IDs en otro orden (profiling §9).

### 2.2 Renombrar a snake_case con la unidad real

**Filas afectadas:** 0 — **Columnas afectadas:** 9

Normaliza los nombres (incluido el espacio sobrante de `'Body Temperature(F) '`,
profiling §11.2) y hace explícita la unidad **real**, no la declarada:

| Columna original | Columna nueva | Nota sobre la unidad |
| --- | --- | --- |
| `Age` | `age_years` | años |
| `Body Temperature(F) ` | `temperature_f` | °F; el nombre original lleva un espacio final |
| `Heart rate(bpm)` | `heart_rate_bpm` | lpm |
| `Systolic Blood Pressure(mm Hg)` | `systolic_bp_mmhg` | mmHg |
| `Diastolic Blood Pressure(mm Hg)` | `diastolic_bp_mmhg` | mmHg |
| `BMI(kg/m 2)` | `bmi_kg_m2` | kg/m² |
| `Blood Glucose(HbA1c)` | `hba1c_mmol_mol` | **mmol/mol (IFCC)**, no % — profiling §6 |
| `Blood Glucose(Fasting hour-mg/dl)` | `fasting_glucose_mmol_l` | **mmol/L**, pese a que el header dice mg/dl — profiling §6 |
| `Status` | `risk_level` | `low risk` / `mid risk` / `high risk` |

**No se convierte ningún valor.** `data/processed/` conserva las unidades del
dataset (°F, mmol/mol, mmol/L) para poder comparar directamente con las cifras
del paper. La conversión desde unidades clínicas peruanas vive en el backend
(`ML_SPEC.md` §4).

### 2.3 Deduplicación — solo la variante principal

**Filas afectadas:** −1 (de 6103 a 6102)

Existe **1 grupo** de 2 filas con las 8 variables clínicas idénticas
(`Patient ID` 3543 y 3638), ambas `low risk`. El profiling (§2) reporta **0
conflictos de etiqueta**, así que conservar la primera no descarta información
de `risk_level`.

Esta transformación se aplica **únicamente a la variante principal**. La razón
está en el Hallazgo (a) de la Sección 5.

### 2.4 Eliminación de outliers — dos variantes

Ambas variantes las genera el **mismo script**, en la misma ejecución.

#### Variante PRINCIPAL — `data/processed/maternal_risk_clean.csv`

Elimina solo los valores **fisiológicamente imposibles**, sobre el conjunto ya
deduplicado (6102 filas):

| Regla | Umbral | Origen del umbral | Filas eliminadas |
| --- | --- | --- | --- |
| Edad imposible | `age_years > 100` | Regla del paper (profiling §7) — captura el único valor de 250 | 1 |
| Temperatura imposible | `temperature_f < 70` | Profiling §7: 39.6 °F es «valor imposible en °F (por debajo de 70°F)» | 1 |
| Diastólica imposible | `diastolic_bp_mmhg < 50` | Regla del paper (profiling §7) — captura el único valor de 9 | 1 |
| **Unión** | | | **3** |

**Conserva** las 42 filas con temperatura de 93.0–94.9 °F (ver Sección 4).

`6103 − 1 (dedup) − 3 (imposibles) = 6099 filas`

#### Variante COMPARACIÓN — `data/processed/maternal_risk_paper.csv`

Aplica las reglas de outliers del paper sobre el RAW **sin deduplicar**:

| Regla | Filas marcadas |
| --- | --- |
| `age_years > 100` | 1 |
| `temperature_f` fuera de 95–105 °F | 43 |
| `diastolic_bp_mmhg < 50` | 1 |
| **Unión (cualquier regla)** | **45** |

`6103 − 45 = 6058 filas`

---

## 3. Salidas

| Variante | Archivo | Filas | SHA-256 |
| --- | --- | --- | --- |
| PRINCIPAL | `data/processed/maternal_risk_clean.csv` | 6099 | `abc61dfc78210eb1fa394264942bb33acb69cce0927c0d73ec0025f14cad7abd` |
| COMPARACIÓN | `data/processed/maternal_risk_paper.csv` | 6058 | `98be1dbe8283deaab48688b72c6a0130863d1697313c065e8382bf0b0b92b20e` |

Ambas tienen las mismas 9 columnas, en el mismo orden, sin nulos.

### Distribución de clases final

**PRINCIPAL (6099 filas):**

| Clase | Conteo | Porcentaje |
| --- | --- | --- |
| `high risk` | 2058 | 33.74% |
| `mid risk` | 2043 | 33.50% |
| `low risk` | 1998 | 32.76% |

**COMPARACIÓN (6058 filas):**

| Clase | Conteo | Porcentaje |
| --- | --- | --- |
| `high risk` | 2016 | 33.28% |
| `mid risk` | 2043 | 33.72% |
| `low risk` | 1999 | 33.00% |

La variante de comparación coincide **exactamente** con lo reportado en el
paper: 45 filas eliminadas, 6058 restantes, 2016 high / 2043 mid / 1999 low.

### Comparación de ambas variantes

| Aspecto | PRINCIPAL | COMPARACIÓN |
| --- | --- | --- |
| Filas | 6099 | 6058 |
| Deduplicación | Sí (−1) | No |
| Regla de edad | `> 100` | `> 100` |
| Regla de diastólica | `< 50` | `< 50` |
| Regla de temperatura | `< 70 °F` (solo lo imposible) | fuera de 95–105 °F (regla del paper) |
| Filas de 93.0–94.9 °F | 42 conservadas | 42 eliminadas |
| Duplicados de las 8 variables | 0 | 1 grupo (intencional) |
| Diferencia neta en `high risk` | — | −42 respecto a la principal |

La única diferencia sustantiva entre ambas es la **regla de temperatura**: las
42 filas `high risk` de 93.0–94.9 °F. Las reglas de edad y diastólica son
idénticas en las dos variantes, porque los valores que marcan (250 años,
9 mmHg) son fisiológicamente imposibles bajo cualquier criterio.

---

## 4. Por qué la variante principal se aparta del paper en la regla de temperatura

**La decisión:** la variante principal elimina la temperatura de 39.6 °F pero
**conserva** las 42 filas de 93.0–94.9 °F, en lugar de aplicar el corte de
95–105 °F del paper.

**La evidencia (profiling §7, «Desglose de la regla de temperatura»):** de las
43 filas que la regla del paper marca por temperatura, los dos extremos no son
el mismo fenómeno.

- **1 fila, 39.6 °F (`low risk`), ≈4.2 °C.** Es un valor **imposible en °F**:
  está por debajo de 70 °F, incompatible con una persona viva. El profiling lo
  atribuye a un probable registro en °C. Se elimina en ambas variantes.
- **42 filas, 93.0–94.9 °F (todas `high risk`), ≈33.9–34.9 °C.** Este rango es
  un valor **fisiológicamente posible**, no un error de captura evidente. La
  regla del paper las descarta junto con el valor imposible, sin distinguir
  entre ambos casos.

| Valor (°F) | Clase | Conteo | ≈°C |
| --- | --- | --- | --- |
| 39.6 | `low risk` | 1 | 4.2 |
| 93.0–94.9 | `high risk` | 42 | 33.9–34.9 |

**El razonamiento:** aplicar el corte completo del paper eliminaría 42 de los
2058 casos `high risk` de la variante principal (**2.04%** de la clase) por una
regla que no distingue entre un valor imposible y uno posible. El criterio de
la variante principal es más estrecho y más defendible: elimina solo lo que el
propio profiling califica de imposible, y usa para ello el umbral que el
profiling ya enuncia («por debajo de 70°F»), no un número inventado.

Esto no cierra la pregunta clínica sobre esas 42 filas — ver Hallazgo (b).

---

## 5. Hallazgos

### (a) El paper no deduplicó

**Verificado por código.** Existe 1 par de filas con las 8 variables clínicas
idénticas (`Patient ID` 3543 y 3638), ambas `low risk`, con
`age_years = 24`, `temperature_f = 98.6` y `diastolic_bp_mmhg = 90`.

Ninguna de las tres reglas del paper alcanza a ese par:

| Regla del paper | Filas del par marcadas |
| --- | --- |
| `age_years > 100` | 0 |
| `temperature_f` fuera de 95–105 °F | 0 |
| `diastolic_bp_mmhg < 50` | 0 |
| **Cualquier regla** | **0** |

Si el paper hubiera deduplicado, su resultado sería 6057 filas con 1998
`low risk`. Reporta 6058 con 1999. Por lo tanto, **el paper no aplicó
deduplicación**: sus 6058 filas son el RAW menos las 45 filas de outliers, sin
más.

**Consecuencia para este pipeline:** la variante de comparación se genera
**sin deduplicar**, que es la única forma de reproducir exactamente la cifra
publicada, y por eso conserva 1 grupo duplicado. La variante principal **sí**
deduplica, porque entrenar sobre una fila repetida no aporta información y sí
sesga levemente el peso de ese punto. El test
`test_variante_paper_no_deduplica_y_conserva_el_grupo_duplicado` fija esta
asimetría como comportamiento esperado, para que no se «corrija» por error más
adelante.

### (b) Las 42 filas de 93.0–94.9 °F son todas `high risk` (concordancia 100%)

**Verificado por código antes de escribir esta afirmación.** En el RAW completo,
las 42 filas cuya `temperature_f` cae en 93.0–94.9 °F son `high risk` **sin una
sola excepción**:

| Métrica | Valor |
| --- | --- |
| Filas en la banda 93.0–94.9 °F | 42 |
| De ellas, `high risk` | 42 |
| De ellas, **no** `high risk` | **0** |
| Concordancia | **100.0000%** |
| Proporción de `high risk` en el resto del dataset (6061 filas) | 33.28% |

Una concordancia perfecta de 42/42, frente a una tasa base de 33.28%, es un
patrón demasiado limpio para ser clínico.

**Interpretación:** esto sugiere un **artefacto de sensor o de captura** más que
hipotermia real. Una gestante con 33.9–34.9 °C está en hipotermia moderada y no
estaría en una consulta prenatal ambulatoria; estaría en urgencias. El
acoplamiento perfecto con la etiqueta apunta a que esos registros provienen de
una misma fuente o procedimiento defectuoso, no a que la hipotermia esté
prediciendo el riesgo.

> Esto matiza la lectura del profiling (§7), que describe el rango como
> «hipotermia clínicamente plausible». El rango de temperatura *es* plausible
> en aislamiento; lo que no es plausible es la concordancia perfecta con la
> etiqueta.

**Riesgo si el artefacto es real:** el modelo aprendería «93–95 °F ⇒ high risk»,
una regla que no se sostendría en producción y que además infla artificialmente
las métricas de la clase `high risk`.

**Decisión: no se resuelve en PR #2.** Las 42 filas **se conservan** en la
variante principal y la decisión se toma en **PR #3 mediante análisis de
sensibilidad**: entrenar con ambas variantes y comparar métricas. Si el
rendimiento de la variante principal depende de forma desproporcionada de esas
42 filas, se tratará como artefacto y se eliminarán. Esta es exactamente la
comparación para la que existe la variante de comparación.

---

## 6. Reproducibilidad

El pipeline es determinista: no usa aleatoriedad, muestreo ni ningún orden
dependiente del sistema de archivos. El salto de línea se fija explícitamente a
`\n` (`to_csv` usaría `os.linesep`, lo que haría los bytes dependientes del
sistema operativo).

Verificado por `test_dos_ejecuciones_producen_archivos_byte_identicos`:
dos ejecuciones consecutivas producen archivos byte-idénticos.

### `.gitattributes`: los SHA-256 de arriba solo valen si git no toca los bytes

Este repositorio tiene `core.autocrlf=true`. Sin una regla explícita, git
reescribe los CSV a CRLF **al hacer checkout**, de modo que un `git clone`
entregaría archivos con un SHA-256 distinto del documentado en la Sección 3, y
`git status` mostraría los datasets como modificados en cuanto alguien
regenerara los datos. Comprobado: tras un checkout sin la regla, el archivo
principal pasaba a `9b26421b…` en lugar de `abc61dfc…`.

Por eso `data/processed/*.csv` se marca como `binary` en `.gitattributes`,
igual que `data/raw/*.csv`. El test
`test_gitattributes_protege_los_csv_generados_de_la_conversion_de_eol` fija
esta regla para que no se pierda.

### Tests

`tests/test_prepare_dataset.py` — **24 funciones de test, 45 casos** una vez
expandida la parametrización (`pytest --collect-only -q`). Con
`tests/test_raw_integrity.py`, la suite completa son **46 casos**.

> La suite **no escribe nunca en `data/processed/`**: `tests/conftest.py`
> ejecuta el pipeline una sola vez por sesión sobre un `tmp_path`. Los
> artefactos commiteados se leen como referencia, no se reescriben.

| Verificación | Test |
| --- | --- |
| El RAW no se modifica (SHA-256 intacto) | `test_raw_sha256_no_cambia_tras_ejecutar_el_pipeline` |
| El pipeline aborta si el RAW no coincide con su SHA registrado | `test_el_pipeline_aborta_si_el_raw_no_coincide_con_el_readme` |
| El pipeline aborta si el README no registra ningún SHA | `test_el_pipeline_aborta_si_el_readme_no_registra_ningun_sha` |
| Regenerar reproduce los SHA-256 de la Sección 3 | `test_regenerar_reproduce_el_sha256_publicado_en_el_reporte` |
| El artefacto commiteado sigue coincidiendo con la Sección 3 | `test_el_artefacto_commiteado_coincide_con_el_reporte` |
| La suite escribe fuera de `data/processed/` | `test_la_suite_no_reescribe_los_artefactos_commiteados` |
| Ningún valor de `Name` en el cuerpo de las salidas | `test_ningun_valor_de_name_aparece_en_el_cuerpo_de_la_salida` |
| Conteo exacto por regla del paper (1 / 43 / 1, unión 45) | `test_reglas_del_paper_marcan_el_numero_exacto_de_filas_de_cada_regla` |
| Principal: elimina exactamente 3 filas imposibles | `test_variante_principal_elimina_exactamente_las_tres_filas_imposibles` |
| Umbral de temperatura de la principal, en su límite | `test_umbral_de_temperatura_de_la_variante_principal_es_vinculante` |
| Umbrales del paper, en ambos extremos | `test_umbrales_del_paper_son_vinculantes_en_ambos_extremos` |
| 9 columnas con los nombres exactos, en orden | `test_salida_tiene_las_nueve_columnas_en_orden` |
| `Name` y `Patient ID` no existen | `test_salida_no_contiene_name_ni_patient_id` |
| Sin fuga de texto libre en las features | `test_las_ocho_variables_clinicas_son_numericas` |
| `risk_level` solo tiene las 3 etiquetas | `test_risk_level_solo_tiene_las_tres_etiquetas` |
| Sin nulos | `test_salida_sin_nulos` |
| Sin duplicados de las 8 variables (principal) | `test_variante_principal_sin_duplicados_de_las_ocho_variables` |
| Principal: 6099 filas y distribución | `test_variante_principal_tiene_las_filas_y_distribucion_esperadas` |
| Principal: conserva las 42 filas de 93.0–94.9 °F | `test_variante_principal_conserva_la_hipotermia_de_93_a_94_9_f` |
| Paper: 6058 filas y distribución | `test_variante_paper_tiene_las_filas_y_distribucion_esperadas` |
| Paper: conserva el grupo duplicado (Hallazgo a) | `test_variante_paper_no_deduplica_y_conserva_el_grupo_duplicado` |
| Las salidas usan solo LF | `test_salida_usa_solo_lf` |
| `.gitattributes` protege los CSV de la conversión de EOL | `test_gitattributes_protege_los_csv_generados_de_la_conversion_de_eol` |
| Dos ejecuciones → archivos byte-idénticos | `test_dos_ejecuciones_producen_archivos_byte_identicos` |

---

## 7. Qué queda pendiente

- **PR #3 — análisis de sensibilidad de las 42 filas de 93.0–94.9 °F**
  (Hallazgo b): entrenar con ambas variantes y comparar métricas.
- **PR #3 — `models/feature_ranges.json`:** el rango de entrenamiento se
  generará automáticamente desde `data/processed/` al entrenar, nunca a mano
  (`ML_SPEC.md` §5).
- **Módulo de conversión de unidades del backend** y sus tests
  (`ML_SPEC.md` §4).
