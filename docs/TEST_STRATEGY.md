# TEST_STRATEGY — Estrategia de pruebas

- **Alcance de este documento:** el estándar de pruebas que ya aplica el
  repositorio, el inventario actual de la suite, los casos reales de
  verificación por mutación y los niveles de prueba previstos con su fase. Qué
  cifras del modelo recalcula la suite y cuáles no lo detalla
  `reports/ml/training_report.md`, Sección 13; aquí se cita. Los comandos que
  preparan el entorno están en `docs/DEPLOYMENT.md`.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5.
- **Convención:** lo que aún no existe se marca
  **PENDIENTE (Fase N) — se documentará al implementarse**.

---

## 1. Principios que ya rigen

### 1.1 Tests antes del código

El test se escribe primero, se ve fallar y luego se implementa. La historia de
Git lo muestra de forma explícita en PR #2: `47e5533` («tests de limpieza
reproducible del dataset (RED)») es anterior a `658126a`, que implementa el
pipeline. En PR #4 los tests y el código entraron en el mismo commit
(`a6e2778`), así que el orden no se puede demostrar desde Git en esa fase.

### 1.2 Un test vale si falla cuando el código se altera

Que la suite esté en verde no basta. Desde PR #3, el código se altera a
propósito (mutación) y se exige que algún test falle. Si ninguno falla, el test no protegía
nada y se reescribe. Casos reales en la Sección 4.

### 1.3 Los tests no reescriben artefactos versionados

`tests/conftest.py` ejecuta cada script **una sola vez por sesión y siempre
sobre un directorio temporal** (`tmp_path_factory`). Los artefactos commiteados
—`data/processed/`, `models/` y `reports/ml/`— se leen como referencia, nunca
se escriben. Lo fijan dos tests:

- `test_la_suite_no_reescribe_los_artefactos_commiteados`
- `test_el_entrenamiento_no_escribe_en_data`

### 1.4 Integridad por hash

Todo dato de entrada se identifica por su SHA-256, y los scripts abortan antes
de escribir si no coincide (`docs/SECURITY.md`, Sección 2). Los tests comprueban
tres cosas:

- el hash del RAW;
- que regenerar reproduce los hashes publicados;
- que los scripts abortan **antes** de escribir (`assert not (…).exists()`).

### 1.5 Las cifras se recalculan, no se copian

Una cifra publicada se ata al código que la produce:

- `training_report.md` se regenera byte a byte desde el JSON
  (`test_el_reporte_commiteado_se_regenera_identico_desde_el_json`).
- Las tablas de `ML_SPEC.md` se comparan con el JSON
  (`test_las_cifras_de_ml_spec_coinciden_con_el_json`).
- `feature_ranges.json` se recalcula desde el split y cada extremo debe existir
  en los datos (`test_ningun_valor_de_feature_ranges_es_inventado`).

## 2. Reglas operativas

- **Toda llamada a `train_model.main()` en un test pasa
  `param_grid=TINY_PARAM_GRID`** (`tests/conftest.py`). Sin ella, el test cae en
  la rejilla completa de 72 configuraciones, que tardó 13993 s
  (`training_report.md`). Bajo un mutante que se salte un aborto, ese test se
  colgaría en vez de fallar.
- **Tras revertir cada mutación se comprueba el árbol** con `git status` y
  `git diff --no-index` contra una copia prístina (descripción de PR #4).
- **Al mutar, `pytest` corre con un límite de tiempo.** Regla que adopta este
  baseline, a raíz del cuelgue que describe la primera regla; no consta en
  los PR anteriores.
- **Nunca se reentrena con la rejilla completa** al verificar: el
  determinismo de todos los caminos lo cubre el test lento con
  `REDUCED_PARAM_GRID` (`ML_SPEC.md`, Sección 9.7).
- **`BrokenProcessPool` / `WinError 6` en Windows** con la CPU saturada: fallo
  conocido de joblib/loky, ajeno al proyecto. Se repite la corrida con la
  máquina sin carga (`docs/KNOWN_ISSUES.md`).

## 3. Inventario actual

Recuento de `pytest --collect-only -q` sobre `main` (2026-09-24):
**127 casos**.

| Archivo | Funciones de test | Casos | Cubre |
| --- | --- | --- | --- |
| `tests/test_raw_integrity.py` | 1 | 1 | SHA-256 del RAW frente a `data/raw/README.md` |
| `tests/test_prepare_dataset.py` | 24 | 45 | Limpieza: integridad, reglas y umbrales, columnas, `Name`, determinismo, fin de línea (`data_cleaning_report.md`, Sección 6) |
| `tests/test_train_model.py` | 51 | 81 | Entrenamiento: contrato del artefacto, rangos, split, reproducibilidad, Decisión D, higiene, versiones |

Uno de los 81 casos, `test_dos_ejecuciones_con_todas_las_comprobaciones_dan_metricas_identicas`,
se omite salvo con `GYNFEM_SLOW_TESTS=1` (`training_report.md`, Sección 14.3).

**Sin cobertura de tests:** `scripts/profile_dataset.py`. Su reporte es
diagnóstico y ningún otro script lo consume.

**Deuda declarada:** la CV anidada, las etiquetas permutadas, la varianza de
partición, la curva de aprendizaje y las ablaciones las emite el script, pero
la suite por defecto no las recalcula (`training_report.md`, Sección 13).

## 4. Verificación por mutación: casos reales

Esta evidencia consta en las descripciones de los PR #3 y #4 en GitHub, no en
archivos del repositorio.

### 4.1 PR #3 — la suite de limpieza no detectaba alteraciones

La revisión de PR #2 demostró que la suite pasaba **23/23 con el script
alterado**. PR #3 reescribió los tests hasta que cada mutación fallara:

| Mutación | Antes | Después de PR #3 |
| --- | --- | --- |
| `IMPOSSIBLE_MIN_TEMPERATURE_F` 70.0 → 92.0 | 23/23 pasaban | Falla (2 tests) |
| `PAPER_TEMPERATURE_RANGE_F` (95, 105) → (95, 200) | 23/23 pasaban | Falla (1 test) |
| Reordenar filas antes de `to_csv` | 23/23 pasaban | Falla (2 tests de SHA) |
| No descartar la columna `Name` | — | Falla (8 tests) |

### 4.2 PR #4 — once mutaciones, todas detectadas

Cada mutación se aplicó sola y se revirtió antes de la siguiente.

| # | Mutación | Detectada por |
| --- | --- | --- |
| M1 | `RANDOM_SEED` 42 → 7 | 11 tests: rangos, reproducción de métricas, referencias y folds, modelo entregado |
| M2 | Orden de clases invertido en el metadata | Test de orden de clases |
| M3 | `modelo.fit(X, y)`: el test entra en el entrenamiento | `test_el_modelo_entregado_se_ajusto_solo_con_el_entrenamiento` |
| M4 | Accuracy sustituida por `0.99` | Dummy de clase más frecuente y reproducción de métricas y referencias (5) |
| M5 | IMC máximo 27.9 → 40.0 escrito a mano en `feature_ranges.json` | 2 tests de rangos |
| M6 | Dos variables intercambiadas en el metadata | Orden de variables y cobertura de rangos |
| M7 | Versión de scikit-learn `"1.5.0"` | Versión instalada y `requirements.txt` |
| M8 | Sin verificación de integridad del dataset | Los 2 tests `aborta_si…` |
| M9 | Cifra del reporte editada a mano | `test_el_reporte_commiteado_se_regenera_identico_desde_el_json` |
| M10 | `DummyClassifier(strategy="uniform")` | Dummy, referencias y determinismo (4) |
| M11 | `StandardScaler` añadido al pipeline | Pipeline sin escalador, modelo entregado, métricas y folds (4) |

M3 solo la detecta un test, y M8 colgaba la suite antes de introducir
`TINY_PARAM_GRID` en los tests de aborto (Sección 2).

## 5. Niveles previstos

| Nivel | Fase | Alcance previsto |
| --- | --- | --- |
| Unitarias de la conversión de unidades | PENDIENTE (Fase 8) | Casos conocidos y ida y vuelta que fija `ML_SPEC.md`, Sección 4 |
| Integración de la API | PENDIENTE (desde Fase 7) | Endpoints contra el modelo y la base de datos |
| RBAC | PENDIENTE (Fase 11) | Cada rol accede solo a lo que le corresponde |
| Extremo a extremo | PENDIENTE (Fase 15) | Frontend ↔ backend ↔ base de datos |
| Validación integral: unitarias, integración, RBAC, seguridad, E2E y regresión | PENDIENTE (Fase 17) | Campaña completa antes del cierre |

Las herramientas de cada nivel se documentarán al implementarse.
