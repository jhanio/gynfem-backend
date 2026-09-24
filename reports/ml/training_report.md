# Reporte de entrenamiento — Random Forest (PR #4)

- **Fecha de generación:** 2026-09-23T12:43:32Z
- **Script:** `scripts/train_model.py`
- **Renderizado por:** `scripts/training_report.py` desde `reports/ml/training_metrics.json`
- **Python:** 3.12.10 — **scikit-learn:** 1.9.1 — **joblib:** 1.6.0 — **numpy:** 2.5.3 — **pandas:** 3.0.6
- **Comando:** `.venv\Scripts\python.exe scripts\train_model.py`
- **Semilla:** `42`, fijada antes de la primera ejecución y no modificada después
- **Tiempo de ejecución:** 13993.4 s
- **Comprobaciones completas:** sí

> **Ninguna cifra de este documento se escribe a mano.** El script emite
> `reports/ml/training_metrics.json` y este documento se renderiza de ahí. La
> Sección 13 detalla la procedencia de cada grupo de cifras. Editar un número
> aquí hace fallar la suite.

> **Alcance clínico:** el modelo es apoyo a la decisión, no un diagnóstico. Su
> salida acompaña al juicio profesional del personal médico de GynFem; no lo
> sustituye.

---

## 1. Datos de entrada

El SHA-256 de cada variante se verifica **antes de leer una sola fila**, contra lo
publicado en `reports/ml/data_cleaning_report.md` (Sección 3). Si no coincide, el
script aborta con `DatasetIntegrityError` sin escribir nada.

| Variante | Archivo | Filas | SHA-256 verificado |
| --- | --- | --- | --- |
| PRINCIPAL (`clean`) | `data/processed/maternal_risk_clean.csv` | 6099 | `abc61dfc78210eb1fa394264942bb33acb69cce0927c0d73ec0025f14cad7abd` |
| COMPARACIÓN (`paper`) | `data/processed/maternal_risk_paper.csv` | 6058 | `98be1dbe8283deaab48688b72c6a0130863d1697313c065e8382bf0b0b92b20e` |

**Distribución de clases:**

| Variante | `high risk` | `low risk` | `mid risk` |
| --- | --- | --- | --- |
| PRINCIPAL (`clean`) | 2058 (33.74%) | 1998 (32.76%) | 2043 (33.50%) |
| COMPARACIÓN (`paper`) | 2016 (33.28%) | 1999 (33.00%) | 2043 (33.72%) |

Ambas variantes se entrenan bajo el **mismo protocolo** (ML_SPEC, Decisión D):
mismo split, misma semilla, misma rejilla, mismas métricas. Las dos tablas de
resultados se publican, se elija la que se elija.

---

## 2. Split

Split **80/20 estratificado** por `risk_level`, semilla
`42`. El conjunto de prueba se aparta al inicio y solo se toca en
`evaluate()`, **una vez por variante**. No interviene en el escalado, ni en la
búsqueda de hiperparámetros, ni en la elección de variante.

| Variante | Entrenamiento | Prueba | Solapamiento exacto train/test |
| --- | --- | --- | --- |
| PRINCIPAL (`clean`) | 4879 | 1220 | 0 |
| COMPARACIÓN (`paper`) | 4846 | 1212 | 0 |

El **solapamiento exacto** cuenta cuántas filas del conjunto de prueba tienen un
vector de 8 variables que también aparece en entrenamiento. Dos filas distintas
con las 8 variables idénticas serían una fuga aunque sus índices no se solapen.
La variante principal está deduplicada (PR #2), así que su cuenta es 0; la de
comparación conserva 1 grupo duplicado de forma deliberada, y el conteo de arriba
dice si ese grupo quedó repartido entre los dos lados.

---

## 3. Búsqueda de hiperparámetros

`GridSearchCV` con validación cruzada estratificada de **10
folds sobre el entrenamiento**, métrica `f1_macro`. La
rejilla tiene **72 configuraciones**.

| Hiperparámetro | Valores explorados |
| --- | --- |
| `n_estimators` | `200`, `500` |
| `max_depth` | `None`, `10`, `20` |
| `min_samples_leaf` | `1`, `2`, `5` |
| `max_features` | `sqrt`, `None` |
| `class_weight` | `None`, `balanced` |

**Fijos, no buscados:** `criterion=gini`, `random_state=42`.

`criterion` queda fijo en `gini` porque duplicaría la rejilla y su efecto dentro
de un bosque es marginal. `max_features` explora `sqrt` y `None`: con solo 8
variables, quedarse con 2 por división puede ser demasiado agresivo. `log2` se
omite por redundante, ya que log2(8)=3 casi coincide con sqrt(8)≈2.8.

**Regla de desempate, declarada antes de medir:** entre las configuraciones que
caen a menos de 1 desviación del mejor puntaje, gana la que menos errores
`high risk` → `low risk` comete; si el empate persiste, la más simple (menos
árboles, menos profundidad, hojas más grandes); y en último término, la primera.

| Variante | Ganadora | Configuraciones a <1σ | Desempate aplicado | Tasa `high`→`low` en CV |
| --- | --- | --- | --- | --- |
| PRINCIPAL (`clean`) | `class_weight=None`, `max_depth=20`, `max_features=sqrt`, `min_samples_leaf=1`, `n_estimators=200` | 38 | sí | 0.0004 |
| COMPARACIÓN (`paper`) | `class_weight=None`, `max_depth=20`, `max_features=sqrt`, `min_samples_leaf=1`, `n_estimators=200` | 16 | sí | 0.0002 |

---

## 4. Las tres estimaciones, y cuál es cuál

Esta sección existe por la Decisión E. Usar la misma validación cruzada con el fin
de elegir hiperparámetros y después reportar su puntaje como rendimiento produce
una cifra optimista por selección. El script produce **tres números distintos** y
este documento los mantiene separados.

| Cifra | Cómo se obtiene | Qué es | Qué **no** es |
| --- | --- | --- | --- |
| **Puntaje de selección** | `GridSearchCV.best_score_`, CV de 10 folds sobre entrenamiento | El puntaje con el que se eligieron los hiperparámetros | **No es una estimación de rendimiento**: está sesgado al alza por haber elegido el máximo de la rejilla |
| **CV anidada** | Externa 10 × interna 5, sobre entrenamiento | Estimación insesgada del **procedimiento** completo (buscar + ajustar) | No es el rendimiento del modelo final concreto |
| **Test apartado** | El 20% separado al inicio, evaluado una sola vez | **La estimación de rendimiento del modelo que se entrega** | — |

| Variante | Puntaje de selección | CV anidada | Test apartado |
| --- | --- | --- | --- |
| PRINCIPAL (`clean`) | 0.9918 ± 0.0043 | 0.9906 ± 0.0044 | 0.9878 |
| COMPARACIÓN (`paper`) | 0.9914 ± 0.0026 | 0.9905 ± 0.0029 | 0.9934 |

Todas las cifras de la tabla son `f1_macro`.
**La cifra titular de este trabajo es la del test apartado**, no la de selección.

---

## 5. Métricas sobre el conjunto de prueba apartado

| Variante | Accuracy | Precisión macro | Recall macro | F1 macro | `high`→`low` |
| --- | --- | --- | --- | --- | --- |
| PRINCIPAL (`clean`) | 0.9877 | 0.9879 | 0.9877 | 0.9878 | 0 |
| COMPARACIÓN (`paper`) | 0.9934 | 0.9934 | 0.9934 | 0.9934 | 1 |

La última columna es el número de gestantes de **alto riesgo clasificadas como
bajo riesgo**. Es el error clínicamente grave, y ninguna métrica agregada lo
distingue del error inverso: por eso se publica aparte (Decisión B).

### 5.1 PRINCIPAL (`clean`)

**Por clase:**

| Clase | Precisión | Recall | F1 | Soporte |
| --- | --- | --- | --- | --- |
| `high risk` | 0.9926 | 0.9830 | 0.9878 | 412 |
| `low risk` | 0.9975 | 0.9875 | 0.9924 | 399 |
| `mid risk` | 0.9736 | 0.9927 | 0.9831 | 409 |
| **macro** | 0.9879 | 0.9877 | 0.9878 | 1220 |

**Matriz de confusión:**

| Real \ Predicho | `high risk` | `low risk` | `mid risk` |
| --- | --- | --- | --- |
| `high risk` | 405 | 0 | 7 |
| `low risk` | 1 | 394 | 4 |
| `mid risk` | 2 | 1 | 406 |

Accuracy de entrenamiento: 0.9992. En un bosque con
`max_depth=None` este número roza 1.0 por diseño (cada árbol crece hasta hojas
puras) y **no** es por sí mismo evidencia de sobreajuste; lo informativo son
las comprobaciones de la Sección 7.

Figura: `reports/ml/figures/training_confusion_matrix_clean.png`

### 5.2 COMPARACIÓN (`paper`)

**Por clase:**

| Clase | Precisión | Recall | F1 | Soporte |
| --- | --- | --- | --- | --- |
| `high risk` | 0.9950 | 0.9926 | 0.9938 | 403 |
| `low risk` | 0.9950 | 0.9950 | 0.9950 | 400 |
| `mid risk` | 0.9902 | 0.9927 | 0.9915 | 409 |
| **macro** | 0.9934 | 0.9934 | 0.9934 | 1212 |

**Matriz de confusión:**

| Real \ Predicho | `high risk` | `low risk` | `mid risk` |
| --- | --- | --- | --- |
| `high risk` | 400 | 1 | 2 |
| `low risk` | 0 | 398 | 2 |
| `mid risk` | 2 | 1 | 406 |

Accuracy de entrenamiento: 0.9994. En un bosque con
`max_depth=None` este número roza 1.0 por diseño (cada árbol crece hasta hojas
puras) y **no** es por sí mismo evidencia de sobreajuste; lo informativo son
las comprobaciones de la Sección 7.

Figura: `reports/ml/figures/training_confusion_matrix_paper.png`

---

## 6. Modelos de referencia

Un 98% de accuracy no significa nada sin saber qué consigue el modelo que ignora
las variables y el que usa un solo árbol. Ambos se ajustan sobre el mismo
entrenamiento y se evalúan sobre el mismo conjunto de prueba.

| Variante | Modelo | Accuracy | F1 macro | `high`→`low` |
| --- | --- | --- | --- | --- |
| PRINCIPAL (`clean`) | `DummyClassifier(most_frequent)` | 0.3377 | 0.1683 | 0 |
| PRINCIPAL (`clean`) | `DecisionTreeClassifier` | 0.9762 | 0.9764 | 0 |
| PRINCIPAL (`clean`) | **Random Forest** | 0.9877 | 0.9878 | 0 |
| COMPARACIÓN (`paper`) | `DummyClassifier(most_frequent)` | 0.3375 | 0.1682 | 0 |
| COMPARACIÓN (`paper`) | `DecisionTreeClassifier` | 0.9818 | 0.9819 | 0 |
| COMPARACIÓN (`paper`) | **Random Forest** | 0.9934 | 0.9934 | 1 |

El clasificador trivial fija el suelo: su accuracy es exactamente la proporción de
la clase mayoritaria en el conjunto de prueba. El árbol simple mide cuánto aporta
el promediado del bosque frente a una sola partición del espacio.

---

## 7. Comprobaciones de sobreajuste (Decisión C)

Una accuracy muy alta obliga a demostrar que es señal y no memorización. Estas
comprobaciones existen con ese fin.

### 7.1 Etiquetas permutadas (C1)

Se baraja `risk_level` y se reentrena. Si el modelo siguiera acertando, habría
fuga en el split o en el pipeline y la accuracy real no significaría nada.

| Variante | Puntaje real | Con etiquetas barajadas | Máximo barajado | Azar | p |
| --- | --- | --- | --- | --- | --- |
| PRINCIPAL (`clean`) | 0.9918 | 0.3337 ± 0.0076 | 0.3470 | 0.3374 | 0.0099 |
| COMPARACIÓN (`paper`) | 0.9913 | 0.3329 ± 0.0083 | 0.3611 | 0.3372 | 0.0099 |

Con 100 permutaciones, el p
mínimo alcanzable es 1/(n+1). El puntaje con etiquetas barajadas cae al nivel
de azar: el modelo no puede aprender de etiquetas aleatorias, que es justo lo
que se espera de un procedimiento sin fuga.

### 7.2 Coherencia entre el test apartado y la CV anidada (C4)

Banda de **dos lados**: `|test − CV anidada| ≤ 3σ`. Una sola cota detectaría solo
una de las dos anomalías posibles.

- **Por debajo de la banda:** el conjunto de prueba salió desfavorable, o el split
  es degenerado.
- **Por encima de la banda:** partición afortunada, o una fuga que la CV anidada no
  alcanza a ver.

| Variante | Test | CV anidada | Diferencia | Límite 3σ | Lado | Dentro |
| --- | --- | --- | --- | --- | --- | --- |
| PRINCIPAL (`clean`) | 0.9878 | 0.9906 | 0.002848 | 0.013165 | por debajo | sí |
| COMPARACIÓN (`paper`) | 0.9934 | 0.9905 | 0.002867 | 0.008779 | por encima | sí |

### 7.3 Varianza de partición (C5)

`RepeatedStratifiedKFold` **solo sobre el entrenamiento**. Volver a partir el
conjunto de prueba con otras semillas lo expondría, y el contrato dice que se
toca una sola vez; repetir la partición del entrenamiento responde la misma
pregunta sin gastarlo.

| Variante | Repeticiones | Media | Desviación | Mínimo | Máximo |
| --- | --- | --- | --- | --- | --- |
| PRINCIPAL (`clean`) | 5×5 | 0.9910 | 0.0036 | 0.9836 | 0.9980 |
| COMPARACIÓN (`paper`) | 5×5 | 0.9905 | 0.0031 | 0.9856 | 0.9969 |

### 7.4 Curva de aprendizaje (C2)

Variante `clean`, métrica `f1_macro`.

| Filas de entrenamiento | Entrenamiento | Validación (CV) |
| --- | --- | --- |
| 439 | 1.0000 | 0.9267 |
| 1097 | 1.0000 | 0.9704 |
| 1756 | 1.0000 | 0.9820 |
| 2415 | 1.0000 | 0.9874 |
| 3073 | 0.9999 | 0.9892 |
| 3732 | 0.9998 | 0.9910 |
| 4391 | 0.9997 | 0.9916 |

Brecha final entrenamiento − validación: 0.0080. Lo
informativo no es que la curva de entrenamiento roce 1.0 —eso lo impone
`max_depth=None`— sino si la de validación converge hacia ella al crecer la
muestra. Figura: `reports/ml/figures/training_learning_curve.png`

### 7.5 Ablación de las filas de hipotermia (C6)

ML_SPEC Sección 7.1 documenta que las 42 filas de
93.0–94.9 °F del dataset son `high risk`
al 100%, frente a una tasa base del 33.28%. Si al quitarlas el rendimiento se
desplomara, el modelo habría aprendido «93–95 °F ⇒ alto riesgo», que es un
artefacto de captura y no se sostendría en producción.

La ablación opera **sobre el split de entrenamiento**, donde cayeron
36 de esas 42; las restantes están en el conjunto de
prueba y no intervienen aquí.

| Medida | Valor |
| --- | --- |
| Filas retiradas del entrenamiento | 36 |
| Filas de entrenamiento restantes | 4843 |
| CV anidada sin esas filas | 0.9905 ± 0.0039 |
| CV anidada con todas las filas | 0.9906 |
| Caída atribuible a esas filas | 0.000090 |

---

## 8. Importancia de variables

Reducción media de impureza. Es una medida **descriptiva del modelo ajustado**, no
una afirmación causal: variables correlacionadas se reparten la importancia y el
criterio favorece a las de mayor cardinalidad.

| Variable | PRINCIPAL (`clean`) | COMPARACIÓN (`paper`) |
| --- | --- | --- |
| `systolic_bp_mmhg` | 0.2260 | 0.2223 |
| `heart_rate_bpm` | 0.1647 | 0.1630 |
| `temperature_f` | 0.1440 | 0.1402 |
| `diastolic_bp_mmhg` | 0.1158 | 0.1143 |
| `fasting_glucose_mmol_l` | 0.1092 | 0.1110 |
| `hba1c_mmol_mol` | 0.0892 | 0.0962 |
| `age_years` | 0.0869 | 0.0883 |
| `bmi_kg_m2` | 0.0642 | 0.0648 |

Figuras: `reports/ml/figures/training_feature_importance_{clean,paper}.png` y
`reports/ml/figures/training_cv_scores_{clean,paper}.png`.

---

## 9. Decisión D — variante de producción

La regla se escribió en `choose_production_variant()` **antes** de la primera
medición, con sus cuatro casos. El `delta` se calcula sobre la **CV anidada**
(solo entrenamiento), no sobre el conjunto de prueba: así la elección de
variante no consulta el test de ninguna de las dos.

| Caso | Condición | Variante |
| --- | --- | --- |
| `D1` | `\|delta\| ≤ umbral` | `clean` |
| `D2` | `delta > umbral` y la ablación explica la ventaja | `paper` |
| `D3` | `delta > umbral` sin que la ablación la explique | `clean` |
| `D4` | `delta < −umbral` | `paper` |

«La ablación explica la ventaja» significa que al retirar del entrenamiento
las 36 filas de hipotermia se pierde al menos el 50% del `delta`.

| Magnitud | Valor |
| --- | --- |
| `delta` (CV anidada, `clean` − `paper`) | 0.000068 |
| Umbral (1σ de la CV anidada de la ganadora) | 0.004388 |
| La ablación explica la ventaja | no aplica (el caso activado no depende de la ablación) |
| **Caso activado** | **`D1`** |
| **Variante de producción** | **`clean`** |

Las dos variantes rinden igual dentro del ruido del procedimiento: la sospecha de artefacto sobre las 42 filas de hipotermia no se sostiene, y conservarlas preserva casos `high risk` reales.

### 9.1 El test y la CV anidada no dicen lo mismo, y eso se explica

Sobre el conjunto de prueba la diferencia entre variantes es -0.005648
`f1_macro`, 83 veces mayor que el `delta` de
0.000068 con el que se decide. Conviene decir por qué no es
una contradicción:

- **No son conjuntos comparables.** Cada variante tiene su propio conjunto de
  prueba, de extensión y composición distintas, porque parten de datasets con
  distinto número de filas (6099 y 6058). No es una
  comparación pareada: comparar esas dos cifras entre sí mide, en buena parte,
  qué conjunto de prueba salió más fácil.
- **La magnitud cabe en el ruido.** 0.005648 es del mismo orden
  que la desviación de la CV anidada (0.004388). Con 1220
  filas de prueba, un solo acierto mueve la métrica 0.000820, así
  que esa diferencia equivale al orden de 7 aciertos.
- **La CV anidada promedia 10 particiones; el test es una sola.** Por eso es la
  base de la decisión: elegir por el test sería elegir por una partición.

El modelo serializado corresponde **solo** a la variante de producción. La otra
se entrena y se mide bajo el mismo protocolo, y sus métricas se publican en
este documento, pero no se empaqueta: dos `.joblib` con el mismo contrato de
metadatos serían una ambigüedad que el backend podría resolver mal.

---

## 10. Decisión A — escalado de variables

**No se escala.** Un árbol parte por umbrales `x ≤ t`; una transformación afín por
columna preserva el orden de los valores de esa columna, luego el conjunto de
particiones alcanzables es idéntico. Lo mismo vale al árbol simple, y el
clasificador trivial ignora las variables por completo. Ninguno de los tres
modelos del alcance puede beneficiarse.

El `Pipeline` se conserva de todos modos: garantiza que cualquier preprocesamiento
futuro se ajuste dentro de cada fold, y el backend carga un solo objeto.

La afirmación se mide, no se asume. Validación cruzada sobre el entrenamiento
(el conjunto de prueba no se gasta en diagnósticos):

| Variante | Sin escalador | Con `StandardScaler` | Diferencia |
| --- | --- | --- | --- |
| PRINCIPAL (`clean`) | 0.9918 | 0.9918 | 0.000000 |
| COMPARACIÓN (`paper`) | 0.9914 | 0.9916 | 0.000205 |

Cualquier diferencia residual procede de desempates en punto flotante, no de un
cambio en el espacio de particiones alcanzables.

---

## 11. Limitaciones

### 11.1 El rango de entrenamiento es estrecho

Estos son los valores que el modelo vio de verdad. Fuera de ellos, cualquier
predicción es extrapolación.

Origen: split de entrenamiento (80%), semilla 42.

| Variable | Mínimo | Máximo | Unidad |
| --- | --- | --- | --- |
| `age_years` | 15.0 | 47.0 | años |
| `temperature_f` | 93.0 | 104.0 | °F |
| `heart_rate_bpm` | 45.0 | 150.0 | lpm |
| `systolic_bp_mmhg` | 90.0 | 169.0 | mmHg |
| `diastolic_bp_mmhg` | 57.0 | 125.0 | mmHg |
| `bmi_kg_m2` | 14.9 | 27.9 | kg/m² |
| `hba1c_mmol_mol` | 30.0 | 50.0 | mmol/mol |
| `fasting_glucose_mmol_l` | 3.5 | 8.2 | mmol/L |

Tres consecuencias concretas, y ninguna es menor:

- **IMC máximo 27.9 kg/m².** El umbral de obesidad es 30. El modelo
  **nunca ha visto una gestante con obesidad**, que es precisamente un grupo de
  riesgo elevado. Una paciente real con IMC 32 recibiría una predicción
  extrapolada, fuera de todo respaldo empírico.
- **HbA1c hasta 50.0 mmol/mol** (≈6.7%). El umbral diagnóstico de diabetes es
  48 mmol/mol, así que el rango diabético está apenas representado.
- **Edad entre 15.0 y 47.0 años.** Las gestantes fuera de ese
  intervalo quedan sin respaldo.

`models/feature_ranges.json` se genera de estos mismos datos, nunca se escribe a
mano, y el backend debe usarlo emitiendo una **advertencia de extrapolación**, no
un bloqueo (ML_SPEC, Sección 5).

### 11.2 Otras limitaciones

- **El dataset no es de GynFem.** Procede de la publicación de origen; su
  población, su instrumentación y sus criterios de etiquetado no son los del
  contexto peruano donde se desplegará.
- **Las etiquetas son la variable objetivo del dataset original**, no un
  diagnóstico verificado de forma independiente. El modelo reproduce ese criterio,
  con sus sesgos.
- **La elección de variante es una selección entre dos opciones.** Aunque el
  `delta` se mide sobre la CV anidada y no sobre el test, elegir el mejor de dos
  introduce una dosis pequeña de sesgo de selección. Es mucho menor que elegir
  entre las configuraciones de la rejilla, pero no es cero, y conviene decirlo.
- **La importancia por impureza es descriptiva**, no causal.
- **No hay validación externa**: ningún conjunto de otra institución o periodo.

---

## 12. Comparación con el paper de origen

Hossain et al., *BMC Medical Informatics and Decision Making*, 2026, 26:79 reporta **99.34%** de accuracy con Random
Forest. Esa cifra se cita **solo como referencia externa**. No es una meta de
este proyecto, no se ha verificado de forma independiente en este repositorio,
y el paper no publica su protocolo con el detalle necesario a fin de
replicarlo.

| Origen | Accuracy | Procedencia |
| --- | --- | --- |
| Paper de origen | 99.34% | Citada, no verificada |
| Este trabajo (`clean`, test apartado) | 98.77% | Medida por `scripts/train_model.py` |
| Diferencia | -0.57 pp | — |

> **Coincidencia, no réplica.** La variante `paper` obtiene exactamente
> 99.34% sobre su conjunto de prueba, la misma
> cifra que publica el paper al redondear a dos decimales. Es una casualidad
> aritmética: sale de 1204 aciertos sobre 1212 filas. Un acierto más o
> menos la habría movido, y nada de este trabajo se orientó a reproducirla. No
> debe leerse como una replicación del resultado publicado.

**Por qué no son directamente comparables**, aunque las cifras se parezcan:

- El paper no declara semilla ni proporción de split, así que su cifra podría
  proceder de una partición distinta.
- No queda claro si su accuracy sale de un conjunto apartado o de validación
  cruzada; si fuera el puntaje con el que eligió hiperparámetros, estaría
  sesgado al alza igual que nuestro puntaje de selección (Sección 4).
- Nuestra variante `clean` conserva 42 filas que el paper elimina, y deduplica
  un grupo que el paper conserva (PR #2).

Nuestra cifra es la que es. No se ajustó nada con el objeto de acercarla a la
publicada, y si difiere, la explicación está arriba y no en el modelo.

---

## 13. Procedencia de las cifras

| Origen | Cifras |
| --- | --- |
| **Emitidas por `scripts/train_model.py`** en cada ejecución, vía `reports/ml/training_metrics.json` | Absolutamente todas las de este documento: SHA-256, filas, distribuciones, split, rejilla y ganadora, las tres estimaciones, métricas por clase y macro, matrices de confusión, modelos de referencia, comprobaciones de sobreajuste, importancias, rangos de variables y el caso activado de la Decisión D |
| **Fijadas por los tests** (fallan si dejan de cuadrar) | El reporte completo se regenera byte a byte desde el JSON; las métricas del test apartado se reproducen reentrenando con los hiperparámetros registrados; los rangos se recalculan desde el split; el solapamiento train/test; el puntaje con etiquetas barajadas; la banda de coherencia; el caso de la Decisión D reaplicando la regla; las versiones de Python y scikit-learn |
| **Citadas de una fuente externa** | La accuracy del paper de origen (Sección 12) y los umbrales clínicos de las limitaciones (obesidad IMC 30, diabetes 48 mmol/mol) |
| **Verificadas por código ad hoc**, no regeneradas | Ninguna |

La tercera fila es la única que este repositorio no produce. La cuarta está
vacía a propósito: en PR #3 hubo cifras verificadas a mano que ningún código
regeneraba, y ese hueco no se repite aquí.

---

## 14. Reproducibilidad y su verificación

### 14.1 De dónde sale el determinismo

Semilla `42` fija en el `random_state` del bosque, en el split
estratificado, en cada `StratifiedKFold`, en la prueba de etiquetas permutadas,
en la curva de aprendizaje y en la varianza de partición. `n_jobs` reparte el
trabajo entre núcleos pero no altera el resultado: el estado aleatorio de cada
árbol queda fijado por la semilla, no por el orden en que se ajustan.

Las figuras también son byte-idénticas entre ejecuciones: `savefig` recibe
`metadata={"Software": None}` porque matplotlib escribiría su propia versión en
el PNG y los bytes cambiarían con cada actualización de la librería.

Entre dos ejecuciones solo cambian tres valores, todos de reloj:
`generated_at`, `created_at` y `elapsed_seconds`.

### 14.2 Cómo se verificó, y una desviación declarada

**La desviación:** la rejilla completa de
72 configuraciones se ejecutó **una sola vez**
(13993 s). El determinismo se verificó con **dos
ejecuciones independientes de rejilla reducida pero con todas las
comprobaciones activadas**, no repitiendo dos veces la rejilla completa.

**Por qué esta evidencia es al menos tan fuerte.** El número de configuraciones
cambia *cuántas veces* se llama a `fit`, no *qué código se ejecuta*. Repetir la
rejilla completa una segunda vez recorrería el mismo camino otra vez, y a un
coste de horas. La verificación elegida recorre en cambio **todas las ramas**
donde podría esconderse una fuente de aleatoriedad, que es donde está el riesgo
real:

| Camino de código | ¿Lo cubre la verificación? |
| --- | --- |
| Split estratificado y búsqueda con CV de 10 folds | sí |
| CV anidada (externa 10 × interna 5) | sí |
| Prueba de etiquetas permutadas | sí |
| Curva de aprendizaje | sí |
| Varianza de partición (`RepeatedStratifiedKFold`) | sí |
| Ablación del escalador | sí |
| Ablación de las filas de hipotermia | sí |
| Evaluación, modelos de referencia y escritura de artefactos | sí |

Resultado: **métricas idénticas** entre las dos ejecuciones.

**Qué no cubre, dicho sin adornos.** La rejilla reducida no explora
`class_weight="balanced"`, `max_features=None`, `min_samples_leaf` distinto de
1 ni `max_depth=20`. Si existiera una no-determinación que solo apareciese con
alguno de esos valores, esta verificación no la vería.

Ese hueco lo cierra otro test, y este sí corre en la suite por defecto:
`test_las_metricas_publicadas_se_reproducen_al_reentrenar` reajusta el modelo
con **los hiperparámetros ganadores concretos** que publica este reporte y exige
que las métricas del conjunto de prueba se reproduzcan exactamente. Es decir: la
configuración que de verdad se entrega está fijada por un test que corre siempre.

### 14.3 Cómo repetir cada verificación

| Verificación | Comando | En la suite por defecto |
| --- | --- | --- |
| Métricas publicadas reproducibles al reentrenar | `pytest tests/ -k metricas_publicadas` | sí |
| Dos ejecuciones idénticas (camino rápido) | `pytest tests/ -k dos_ejecuciones_con_la_misma` | sí |
| Dos ejecuciones idénticas (**todos** los caminos) | `GYNFEM_SLOW_TESTS=1 pytest tests/ -k todas_las_comprobaciones` | no, ~80 min |
| Reporte regenerado byte a byte desde el JSON | `pytest tests/ -k regenera_identico` | sí |
| Regenerar todo desde cero | `.venv\Scripts\python.exe scripts\train_model.py` | no, 13993 s |

---

## 15. Contrato del artefacto

- **Modelo:** `models/maternal_risk_rf_v1.0.0.joblib`
- **Versión:** `1.0.0`
- **Metadatos:** `models/model_metadata.json`
- **Rangos de variables:** `models/feature_ranges.json`

El modelo entregado se ajusta **solo con el 80% de entrenamiento**, no se
reajusta sobre el dataset completo. Reajustar daría un modelo marginalmente
mejor, pero la métrica publicada dejaría de ser la de este artefacto: lo medido
y lo entregado son el mismo objeto.

`model_metadata.json` registra el orden exacto de las 8 variables con su
unidad, el orden de las clases tal como lo expone el modelo serializado, los
hiperparámetros finales, la semilla, las versiones de Python y scikit-learn, el
SHA-256 del dataset de entrenamiento y el resumen de métricas. Cargar el modelo
con una versión de scikit-learn distinta de la registrada puede cambiar su
comportamiento en silencio; un test compara ambas y falla si difieren.
