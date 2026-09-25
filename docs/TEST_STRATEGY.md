# TEST_STRATEGY — Estrategia de pruebas

- **Alcance de este documento:** el estándar de pruebas que ya aplica el
  repositorio, el inventario actual de la suite, los casos reales de
  verificación por mutación y los niveles de prueba previstos con su fase. Qué
  cifras del modelo recalcula la suite y cuáles no lo detalla
  `reports/ml/training_report.md`, Sección 13; aquí se cita. Los comandos que
  preparan el entorno están en `docs/DEPLOYMENT.md`.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  en la Fase 7 (esqueleto de la API), PR #6.
- **Convención:** lo que aún no existe se marca
  **PENDIENTE (Fase N) — se documentará al implementarse**.

---

## 1. Principios que ya rigen

### 1.1 Tests antes del código

El test se escribe primero, se ve fallar y luego se implementa. La historia de
Git lo muestra de forma explícita en PR #2: `47e5533` («tests de limpieza
reproducible del dataset (RED)») es anterior a `658126a`, que implementa el
pipeline. En PR #4 los tests y el código entraron en el mismo commit
(`a6e2778`), así que el orden no se puede demostrar desde Git en esa fase. En
PR #6 los tests de la API tienen su propio commit, anterior al de la
aplicación.

### 1.2 Un test vale si falla cuando el código se altera

Que la suite esté en verde no basta. Desde PR #3, el código se altera a
propósito (mutación) y se exige que algún test falle. Si ninguno falla, el test no protegía
nada y se reescribe. Casos reales en la Sección 4.

### 1.3 Los tests no reescriben artefactos versionados

`tests/conftest.py` ejecuta cada script **una sola vez por sesión y siempre
sobre un directorio temporal** (`tmp_path_factory`). Los artefactos commiteados
—`data/processed/`, `models/` y `reports/ml/`— se leen como referencia, nunca
se escriben. Lo fijan dos tests:

- `test_la_suite_no_reescribe_los_artefactos_commiteados`, que existe en
  `tests/test_prepare_dataset.py` y en `tests/test_train_model.py`
- `test_el_entrenamiento_no_escribe_en_data` (`tests/test_train_model.py`)

La suite de la API no escribe archivos. Su único test que usa disco
(`test_arranque_real_falla_sin_variable_obligatoria`) ejecuta el subproceso con
`cwd=tmp_path`.

### 1.6 Dos suites, un solo comando

| | Suite de ML | Suite de la API |
| --- | --- | --- |
| Ubicación | `tests/*.py` | `tests/api/` (paquete, con su propio `conftest.py`) |
| Fixtures | `tests/conftest.py`: pipeline y entrenamiento en `tmp_path_factory` | `tests/api/conftest.py`: una aplicación por test con `create_app()` |
| Solo esta suite | `pytest tests --ignore=tests\api` | `pytest tests\api` |

`python -m pytest` ejecuta las dos. Cómo se mantienen aisladas:

- **Sin fixtures cruzadas.** `tests/conftest.py` también se carga para
  `tests/api/`, pero sus fixtures son perezosas y la suite de la API no pide
  ninguna, así que nunca ejecuta el pipeline ni el entrenamiento.
- **`tests/api/` es un paquete.** Su `conftest.py` se registra como
  `api.conftest` y no reemplaza al módulo `conftest` que los tests de ML
  importan por nombre (`from conftest import …`). Sin el `__init__.py`, la
  colección de la suite completa falla con `ImportError`. Sus constantes
  están en `tests/api/api_constantes.py`.
- **Sin entorno heredado.** Una fixture `autouse` borra toda variable
  `GYNFEM_*` antes de cada test de la API. La aplicación no lee `.env`, así
  que un `.env` local tampoco influye.
- **Sin aplicación global.** Cada test construye la suya. Las rutas que
  provocan errores a propósito (`/api/v1/_test/…`) se añaden en la fixture y
  no existen en `app/`.
### 1.4 Integridad por hash

Todo dato de entrada se identifica por su SHA-256. `prepare_dataset.py` y
`train_model.py` abortan antes de escribir si no coincide; `profile_dataset.py`
solo registra el hash del RAW (`docs/SECURITY.md`, Sección 2). Los tests comprueban
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

- **Toda llamada a `train_model.main()` en un test pasa una rejilla reducida
  explícita**: `TINY_PARAM_GRID`, o `REDUCED_PARAM_GRID` en el test lento
  (`tests/conftest.py`). Sin ella, el test cae en la rejilla completa de 72 configuraciones, que tardó 13993 s
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

Recuento de `pytest --collect-only -q` en la rama de PR #6 (2026-09-24):
**189 casos**: 127 de ML y 62 de la API.

| Archivo | Funciones de test | Casos | Cubre |
| --- | --- | --- | --- |
| `tests/test_raw_integrity.py` | 1 | 1 | SHA-256 del RAW frente a `data/raw/README.md` |
| `tests/test_prepare_dataset.py` | 24 | 45 | Limpieza: integridad, reglas y umbrales, columnas, `Name`, determinismo, fin de línea (`data_cleaning_report.md`, Sección 6) |
| `tests/test_train_model.py` | 51 | 81 | Entrenamiento: contrato del artefacto, rangos, split, reproducibilidad, Decisión D, higiene, versiones |
| `tests/api/test_api_config.py` | 16 | 27 | Variables obligatorias, arranque real en subproceso, CORS por entorno, mensajes sin valores, `.env.example` |
| `tests/api/test_api_health.py` | 8 | 10 | Esquema de `/health`, versión, hora UTC, sin información interna, prefijo, documentación interactiva |
| `tests/api/test_api_errors.py` | 8 | 13 | Formato uniforme (404, 405, 422, 500), sin traza ni valores, CORS en el 500, `X-Request-ID` |
| `tests/api/test_api_cors.py` | 5 | 5 | Origen configurado aceptado, no configurado rechazado, sin comodín ni credenciales |
| `tests/api/test_api_logging.py` | 7 | 7 | Línea JSON de acceso, correlación, plantilla de ruta, sin valores clínicos |

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

### 4.2 PR #4 — dieciocho mutaciones, todas detectadas

Cada mutación se aplicó sola y se revirtió antes de la siguiente. La serie M
ataca el código y los artefactos; la serie N, las cifras publicadas y la regla
de decisión.

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

| # | Mutación | Detectada por |
| --- | --- | --- |
| N1 | El desempate prefiere **más** errores `high → low` | Test unitario del desempate |
| N2 | Ramas D2 y D3 intercambiadas | Tests unitarios de las ramas D |
| N3 | Cifra de ML_SPEC editada a mano | `test_las_cifras_de_ml_spec_coinciden_con_el_json` |
| N4 | f1 del test de `paper` editado en el JSON y re-renderizado | Reproducción `[paper]`, banda de coherencia y ML_SPEC |
| N5 | f1 del Dummy de `paper` editado en el JSON | `test_los_modelos_de_referencia_publicados_se_reproducen[paper]` |
| N6 | Un fold de la CV de selección editado | `test_los_folds_de_la_cv_de_seleccion_se_reproducen[clean]` |
| N7 | Razón de la Decisión D editada en el JSON | Test que reaplica la regla de la Decisión D sobre el JSON (`tests/test_train_model.py`) |

**N1–N6 pasaban la suite anterior a la autorrevisión de PR #4, y N7 solo se
detectaba a medias**: la suite se reforzó en ese mismo PR hasta detectarlas.

M3 solo la detecta un test, y M8 colgaba la suite antes de introducir
`TINY_PARAM_GRID` en los tests de aborto (Sección 2).

### 4.3 PR #6 — veintitrés mutaciones de la API, todas detectadas

Cada mutación se aplicó sola sobre `app/` y se ejecutó `pytest tests/api` con
un límite de 300 s. Después se restauró `app/` y se comprobó byte a byte contra
una copia prístina. Ninguna mutación toca los tests.

| # | Mutación | Detectada por |
| --- | --- | --- |
| M1a | `cors_origins` con valor por defecto (deja de ser obligatoria) | Variable faltante al crear la app y arranque real en subproceso (2) |
| M1b | Sin validación de orígenes | Comodín, malformados, reglas por entorno, mensaje sin valor (12) |
| M1c | `load_settings()` ignora los errores de validación | Toda la validación de configuración (17) |
| M1d | Sin la regla de solo localhost en `development` y `test` | Origen no local en desarrollo, mensaje sin valor (2) |
| M1e | Sin la regla de `https` y no localhost en `production` | Los 3 casos de producción |
| M1f | Sin el rechazo explícito del comodín | Los 2 casos de comodín (exigen un mensaje claro) |
| M2 | `CORSMiddleware(allow_origins=["*"])` | Los 5 tests de CORS del preflight, del GET y del 500 |
| M3a | El 500 devuelve `traceback.format_exc()` | `test_excepcion_no_controlada_no_filtra_traza` |
| M3b | Sin captura propia del 500 y `FastAPI(debug=True)` | Sin traza y CORS en el 500 (2) |
| M4a | El log de acceso incluye la query string | Sin valores clínicos y claves del log de acceso (2) |
| M4b | El log de error incluye el mensaje de la excepción | Sin valores clínicos y error sin su mensaje (2) |
| M4c | El log registra el path real en vez de la plantilla | Plantilla de ruta, ruta sin coincidencia y sin valores clínicos (3) |
| M5 | Prefijo `/api/v1` → `/api/v2` | `/health`, documentación interactiva, 405, CORS y log de acceso (9) |
| M6 | El 422 devuelve el valor recibido | `test_error_de_validacion_no_refleja_el_valor` |
| M7 | `/health` añade el entorno | Esquema exacto y sin información interna (2) |
| M8 | Se acepta cualquier `X-Request-ID` | Los 6 casos de `test_request_id_malicioso_se_reemplaza` |
| M9a | `/health` devuelve `"1.0.0"` escrito a mano (la versión del modelo) | `test_health_version_es_la_de_la_app` |
| M9b | Se sube `__version__` sin actualizar el ejemplo de `API_SPEC.md` | `test_version_del_ejemplo_de_api_spec_coincide` |
| M10 | Sin manejador de `HTTPException` (404 por defecto de Starlette) | 404, 405 y rutas fuera del prefijo (6) |
| M11 | Documentación interactiva habilitada en `production` | `test_docs_deshabilitadas_en_produccion` |
| M12 | Middleware de contexto fuera de CORS | `test_error_500_conserva_cabeceras_cors` |
| M13 | El 422 omite `details` | `test_error_de_validacion_no_refleja_el_valor` |
| M14 | `app/main.py` deja pasar la excepción de configuración con traza | `test_arranque_real_falla_sin_variable_obligatoria` |

M1f se identificó al diseñar el ejercicio, antes de ejecutarlo: la validación
de formato también rechaza `*`, así que la primera versión de
`test_comodin_se_rechaza`, que solo exigía un error, no habría distinguido la
mutación. Se reforzó para exigir el mensaje que nombra el comodín.

## 5. Niveles previstos

| Nivel | Fase | Alcance previsto |
| --- | --- | --- |
| Unitarias de la conversión de unidades | PENDIENTE (Fase 8) | Casos conocidos y ida y vuelta que fija `ML_SPEC.md`, Sección 4 |
| Integración de la API | **Iniciada en la Fase 7** (`tests/api/`, pytest con `fastapi.testclient.TestClient` sobre `httpx2`). Contra el modelo: PENDIENTE (Fase 8). Contra la base de datos: PENDIENTE (Fase 10) | Endpoints contra el modelo y la base de datos |
| RBAC | PENDIENTE (Fase 11) | Cada rol accede solo a lo que le corresponde |
| Extremo a extremo | PENDIENTE (Fase 15) | Frontend ↔ backend ↔ base de datos |
| Validación integral: unitarias, integración, RBAC, seguridad, E2E y regresión | PENDIENTE (Fase 17) | Campaña completa antes del cierre |

Las herramientas de cada nivel se documentarán al implementarse.
