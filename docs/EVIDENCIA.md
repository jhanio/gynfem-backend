# EVIDENCIA — Índice para la sustentación

- **Alcance de este documento:** un índice de la evidencia del proyecto. Cada
  fila dice qué se afirma y enlaza el archivo, PR, commit o informe que lo
  demuestra. **No es fuente de nada:** no repite el contenido de los documentos
  dueños (`CLAUDE.md`, Sección 6) y, si discrepa de uno de ellos, manda el
  documento dueño.
- **Fecha:** 2026-10-06 — Fase 18 (consolidación de evidencia), rama
  `docs/evidencia-fase18`.
- **Estado de partida:** `gynfem-backend` `main` = `f627bf0` (PR #18 fusionado),
  `__version__ = "0.6.0"` ([`app/__init__.py`](../app/__init__.py));
  `gynfem-frontend` `main` = `a0930c1` (PR #8 fusionado).
- **Convención:**
  - **Comprobado:** hay un archivo versionado, un PR o una salida de comando
    fechada que lo demuestra.
  - **PENDIENTE:** no se ejecutó o no hay evidencia. No cuenta como hecho.
  - **Fuera de alcance:** se decidió no hacerlo en este trabajo.
  - **Hipótesis:** se infiere sin comprobarse.
- **Cifras:** las del modelo salen de `reports/ml/` y `models/`, nunca del
  paper de origen (`CLAUDE.md`, reglas 4 y 5). Cada cifra cita el archivo que la
  produce.
- **Enlaces:** relativos dentro de este repositorio. Los de `gynfem-frontend`
  van fijados al commit `a0930c1` para que no cambien.

---

## 1. Preguntas previsibles del jurado

| Pregunta | Respuesta corta | Dónde |
| --- | --- | --- |
| **«Un 98,8 % parece sobreajuste. ¿Cómo lo descartan?»** | La cifra que se presenta es la del conjunto de prueba apartado (20 %, evaluado una sola vez), no la usada para elegir los hiperparámetros. Hay cinco comprobaciones: etiquetas permutadas, coherencia entre el test y la CV anidada, varianza de partición, curva de aprendizaje y ablación. La accuracy de entrenamiento (0.9992) roza 1.0 por cómo crecen los árboles y no es evidencia de sobreajuste por sí sola (`training_report.md`, Sección 5.1). Ninguna de estas comprobaciones sustituye una validación externa, que no existe | §3.2 |
| **«¿Qué pasa con una paciente con IMC fuera de rango?»** | Depende del tipo de «fuera». Un IMC imposible (fuera de 12–70 kg/m²) se rechaza con 422 y no se predice. Un IMC posible pero fuera de lo que el modelo vio (14.9–27.9 kg/m²) se predice **con un aviso de extrapolación visible**. Ese aviso dice que el modelo trata cualquier valor por encima del máximo como el máximo. El modelo nunca vio una gestante con obesidad (IMC ≥ 30) | §3.3 |
| **«¿Cómo se protege el acceso?»** | Supabase Auth emite el token y la API solo lo verifica (ES256 contra el JWKS). El rol se lee de la base en cada petición. Cada ruta declara su decisión de acceso, y un test compara la matriz con las rutas reales. Contra producción, 84 de 84 celdas de la matriz coinciden y 32 de 34 sondas de seguridad pasan. Las 2 restantes las bloqueó un intermediario antes de llegar a la API | §6 |
| **«¿Qué no está validado?»** | La regresión E2E de la Fase 17 no se ejecutó (el guion está redactado), no hay suite E2E automatizada ni cobertura medida, seis casos de seguridad (S4, S6 con un recurso real, S7, S10, S13 y S14) y `npm run verify:deployment` quedaron sin hacer contra producción, `FORCE ROW LEVEL SECURITY` es trabajo futuro y no hay validación clínica ni externa del modelo | §10 y §11 |

---

## 2. Datos

| Afirmación | Estado | Evidencia |
| --- | --- | --- |
| El RAW es inmutable y su SHA-256 se comprueba en cada corrida de la suite | Comprobado | [`data/raw/README.md`](../data/raw/README.md); [`tests/test_raw_integrity.py`](../tests/test_raw_integrity.py); commits `313a9bc` y `e5b2bc7` (PR #1) |
| El pipeline de limpieza aborta si el RAW no coincide con su SHA registrado | Comprobado | Commit `b3c6e25` (PR #3); [`scripts/prepare_dataset.py`](../scripts/prepare_dataset.py) |
| El perfilado del RAW es reproducible | Comprobado | [`reports/ml/dataset_profile.md`](../reports/ml/dataset_profile.md); [`scripts/profile_dataset.py`](../scripts/profile_dataset.py) (sin tests propios: `TEST_STRATEGY.md`, Sección 3) |
| Limpieza reproducible en dos variantes (`clean`, la de producción, y `paper`, de comparación) | Comprobado | [`reports/ml/data_cleaning_report.md`](../reports/ml/data_cleaning_report.md); [`docs/ML_SPEC.md`](ML_SPEC.md), Secciones 2.2 y 7; [`tests/test_prepare_dataset.py`](../tests/test_prepare_dataset.py); PR #2 y #3 |
| La columna `Name` nunca se expone en salidas derivadas, reportes ni logs | Comprobado | `CLAUDE.md`, regla 2; [`docs/SECURITY.md`](SECURITY.md), Sección 2.1; barrido en `tests/test_prepare_dataset.py` (commit `3db0995`) |
| Ningún dato real de pacientes de GynFem está en el repositorio ni en producción | Comprobado (por procedimiento) | `CLAUDE.md`, regla 3; `SECURITY.md`, Sección 2.2; [`docs/validation/FASE17.md`](validation/FASE17.md), Sección 1 |

PRs: [#1](https://github.com/jhanio/gynfem-backend/pull/1),
[#2](https://github.com/jhanio/gynfem-backend/pull/2),
[#3](https://github.com/jhanio/gynfem-backend/pull/3).

---

## 3. Modelo

Documento dueño: [`docs/ML_SPEC.md`](ML_SPEC.md). Evidencia numérica:
[`reports/ml/training_report.md`](../reports/ml/training_report.md), generado
desde [`reports/ml/training_metrics.json`](../reports/ml/training_metrics.json).
Artefacto: [`models/maternal_risk_rf_v1.0.0.joblib`](../models/maternal_risk_rf_v1.0.0.joblib)
con [`models/model_metadata.json`](../models/model_metadata.json) y
[`models/feature_ranges.json`](../models/feature_ranges.json). PR
[#4](https://github.com/jhanio/gynfem-backend/pull/4).

### 3.1 Resultado del modelo entregado

Random Forest v1.0.0, variante `clean`: 6099 filas, 4879 de entrenamiento y
1220 de prueba, semilla 42 (`model_metadata.json`; soporte en
`training_report.md`, Sección 5.1).

| Métrica (test apartado) | Valor | Fuente |
| --- | --- | --- |
| Accuracy | 0.9877 | `model_metadata.json` (`metrics_summary`); `training_report.md`, Sección 5 |
| F1 macro | 0.9878 | Idem |
| Precisión macro · recall macro | 0.9879 · 0.9877 | Idem |
| Alto riesgo clasificado como bajo riesgo | 0 | Idem (`high_to_low_errors`). Es el error clínicamente grave y se publica aparte (Decisión B) |
| Recall de `high risk` | 0.9830 (7 de 412 predichas como `mid risk`) | `training_report.md`, Sección 5.1 (matriz de confusión) |

- **Figuras:** [`training_confusion_matrix_clean.png`](../reports/ml/figures/training_confusion_matrix_clean.png),
  [`training_feature_importance_clean.png`](../reports/ml/figures/training_feature_importance_clean.png),
  [`training_cv_scores_clean.png`](../reports/ml/figures/training_cv_scores_clean.png).
- **Búsqueda:** 72 configuraciones, CV de 10 folds, métrica de selección
  `f1_macro` (`training_metrics.json`; `training_report.md`, Sección 3).
- **Variante de producción (Decisión D):** `clean`, caso `D1`. Las dos variantes
  rinden igual dentro del ruido de la CV anidada (`training_metrics.json`,
  bloque `production`; `training_report.md`, Sección 9). El mismo documento
  declara que el umbral y la base del `delta` entraron en el mismo PR que los
  resultados (Sección 9).

### 3.2 Sobreajuste: las cinco comprobaciones

Todas en `training_report.md`. Las cifras son `f1_macro` de la variante `clean`.

| Comprobación | Resultado | Sección |
| --- | --- | --- |
| Tres estimaciones separadas | Selección 0.9918 (sesgada al alza), CV anidada 0.9906, test apartado 0.9878. La cifra titular es la del test | 4 |
| Etiquetas permutadas (C1), 100 permutaciones | Con etiquetas barajadas, 0.3337 ± 0.0076, igual al azar (0.3374); p = 0.0099, el mínimo alcanzable | 7.1 |
| Test frente a CV anidada (C4) | Diferencia 0.002848, dentro de la banda de 3σ (0.013165) | 7.2 |
| Varianza de partición (C5), 5×5 solo sobre entrenamiento | 0.9910 ± 0.0036 (0.9836–0.9980) | 7.3 |
| Curva de aprendizaje (C2) | La validación sube de 0.9267 (439 filas) a 0.9916 (4391 filas); brecha final con entrenamiento, 0.0080 | 7.4; [`training_learning_curve.png`](../reports/ml/figures/training_learning_curve.png) |
| Ablación de las 36 filas de hipotermia del entrenamiento (C6) | Diferencia de la CV anidada, 0.000090. Mide el rendimiento agregado, **no** si el modelo aprendió la regla «93.0–94.9 °F ⇒ alto riesgo» | 7.5 |

**Límite de esta evidencia:** la CV anidada, las permutaciones, la varianza, la
curva y las ablaciones las emite `scripts/train_model.py`, pero la suite por
defecto **no las recalcula**; solo comprueba su coherencia interna
(`training_report.md`, Sección 13; `TEST_STRATEGY.md`, Sección 3). Las métricas
del test apartado sí se recalculan reentrenando.

### 3.3 Una paciente fuera del rango de entrenamiento

| Nivel | Qué ocurre | Evidencia |
| --- | --- | --- |
| a — imposible (IMC fuera de 12–70 kg/m², límites fisiológicos provisionales) | 422 sin predecir, sin repetir el valor | `ML_SPEC.md`, Sección 5.1; [`docs/API_SPEC.md`](API_SPEC.md), Sección 2.3; `test_valor_imposible_422_sin_predecir` y `test_el_422_no_repite_el_valor` ([`tests/api/test_api_prediction.py`](../tests/api/test_api_prediction.py)) |
| b — fuera del rango de entrenamiento (IMC 14.9–27.9 kg/m²) | Predice y añade un aviso por variable afectada (`extrapolation_warnings`), con dirección, unidad y rango | `ML_SPEC.md`, Sección 5.2; rango en `models/feature_ranges.json` y `training_report.md`, Sección 11.1; `test_fuera_del_rango_200_con_aviso` y `test_un_aviso_por_cada_variable_fuera_en_el_orden_del_contrato` |
| Ejemplo real | IMC 32 y HbA1c 7.2 %: `high`, con dos avisos | `API_SPEC.md`, Sección 3.2 (respuesta capturada de `/predict`) |
| El aviso no gradúa el alejamiento | Para un árbol, cualquier valor por encima del máximo equivale al máximo; el mensaje lo dice | `ML_SPEC.md`, Sección 5.2 (decisión C) |
| La interfaz lo muestra | Aviso no bloqueante en el formulario y en el resultado, con el texto de la API; también en el reporte | [`tests/flows/assessment.test.tsx`](https://github.com/jhanio/gynfem-frontend/blob/a0930c1ea622f6689b04fc2c310bb0c9fd29fa4e/tests/flows/assessment.test.tsx) y [`tests/flows/report.test.tsx`](https://github.com/jhanio/gynfem-frontend/blob/a0930c1ea622f6689b04fc2c310bb0c9fd29fa4e/tests/flows/report.test.tsx) (con MSW). **En producción, desde la interfaz: PENDIENTE** (paso 4 de [`E2E_GUION.md`](validation/E2E_GUION.md)) |

**Por qué importa:** el IMC máximo de entrenamiento es 27.9 y el umbral de
obesidad, 30; la HbA1c llega a 50 mmol/mol, apenas sobre el umbral de diabetes
(48). El modelo nunca vio una gestante con obesidad (`training_report.md`,
Sección 11.1).

### 3.4 Reproducibilidad

| Afirmación | Evidencia |
| --- | --- |
| Entorno fijado: Python 3.12.10, scikit-learn 1.9.1, joblib 1.6.0 | `model_metadata.json` (`environment`); [`requirements.txt`](../requirements.txt); commit `7413cf8` |
| Determinismo verificado, con una desviación declarada | `training_report.md`, Sección 14 |
| El reporte se recalcula byte a byte desde el JSON en cada corrida de la suite | `training_report.md`, Sección 13; [`tests/test_train_model.py`](../tests/test_train_model.py) |
| El entrenamiento completo tarda ≈3 h 53 min (13 993 s) | `training_metrics.json` (`elapsed_seconds`); `CLAUDE.md`, regla 13 |

### 3.5 Comparación con el paper de origen

Solo como referencia externa, nunca como meta (`CLAUDE.md`, regla 5). El paper
reporta 99.34 % de accuracy, citada y **no verificada**. Este trabajo obtiene
98.77 % (`clean`, test apartado). La variante `paper` da exactamente 99.34 %
(1204 de 1212), lo que el reporte declara **coincidencia, no réplica**.
Fuente única: `training_report.md`, Sección 12.

---

## 4. API e historias de usuario

La trazabilidad HU → fase → PR → tests → evidencia está en
[`docs/TASK_BREAKDOWN.md`](TASK_BREAKDOWN.md), Sección 2, y no se repite aquí.

| Tema | Evidencia | PR |
| --- | --- | --- |
| Producto, roles y HU001–HU011 | [`docs/PRD.md`](PRD.md), Sección 4 | [#5](https://github.com/jhanio/gynfem-backend/pull/5) |
| Esqueleto: configuración validada, `/health`, CORS, errores uniformes, logs | `API_SPEC.md`, Secciones 2 y 3.1 | [#6](https://github.com/jhanio/gynfem-backend/pull/6) |
| Predicción: conversión de unidades, tres niveles de validación, advertencia clínica (HU006, HU007) | `API_SPEC.md`, Secciones 3.2 y 3.3 | [#7](https://github.com/jhanio/gynfem-backend/pull/7) |
| Persistencia clínica: pacientes, mediciones, correcciones, auditoría (HU003–HU005) | `API_SPEC.md`, Sección 3.5 | [#9](https://github.com/jhanio/gynfem-backend/pull/9) |
| Autenticación, gestión de usuarios y roles (HU001, HU002) | `API_SPEC.md`, Sección 3.6 | [#10](https://github.com/jhanio/gynfem-backend/pull/10) |
| Administración: historial, reporte, métricas, parámetros, auditoría (HU008–HU011) | `API_SPEC.md`, Sección 3.7 | [#16](https://github.com/jhanio/gynfem-backend/pull/16) |
| Las métricas que publica la API (`/model/metrics`) salen de los artefactos, no de constantes, con sus limitaciones siempre en la respuesta | `ML_SPEC.md`, Sección 9.10; [`tests/api/test_api_model_metrics.py`](../tests/api/test_api_model_metrics.py) | #16 |

---

## 5. Base de datos

| Afirmación | Estado | Evidencia |
| --- | --- | --- |
| El esquema solo cambia con migraciones numeradas, cada una con su reversión (0001–0009) | Comprobado | [`migrations/`](../migrations/); [`docs/DEPLOYMENT.md`](DEPLOYMENT.md), Sección 6.2; [`tests/database/test_migrations.py`](../tests/database/test_migrations.py) |
| Tablas, claves foráneas, RLS en todas las tablas, `anon` y `authenticated` sin acceso | Comprobado | [`docs/ERD.md`](ERD.md); [`tests/database/test_schema.py`](../tests/database/test_schema.py) y [`test_auth_schema.py`](../tests/database/test_auth_schema.py) |
| Borrado físico prohibido, baja lógica, mediciones inmutables, auditoría de toda escritura | Comprobado | `ERD.md`; `SECURITY.md`, Sección 2.2; `test_schema.py` |
| La predicción guardada se reproduce bit a bit | Comprobado | `test_schema.py`; [`tests/database/test_api_measurements.py`](../tests/database/test_api_measurements.py) |
| La API se conecta con un rol de mínimo privilegio y `FORCE ROW LEVEL SECURITY` | **Fuera de alcance**: trabajo futuro | `SECURITY.md`, Sección 2.3; `FASE17.md`, Sección 7 |

PRs: [#8](https://github.com/jhanio/gynfem-backend/pull/8),
[#9](https://github.com/jhanio/gynfem-backend/pull/9),
[#10](https://github.com/jhanio/gynfem-backend/pull/10),
[#16](https://github.com/jhanio/gynfem-backend/pull/16).

---

## 6. Seguridad y control de acceso

Documento dueño: [`docs/SECURITY.md`](SECURITY.md). Informe de la validación
contra producción: [`docs/validation/FASE17.md`](validation/FASE17.md).

| Afirmación | Estado | Evidencia |
| --- | --- | --- |
| El backend no emite tokens ni guarda contraseñas: verifica un JWT ES256 contra el JWKS de Supabase; rechaza HS256 y `alg: none` | Comprobado (local y producción) | `SECURITY.md`, Sección 2.3; [`tests/api/test_auth_tokens.py`](../tests/api/test_auth_tokens.py); sondas S2 y S3 en `FASE17.md`, Sección 4 |
| El rol sale de la base en cada petición, no del token ni de cabeceras | Comprobado (local y producción) | `SECURITY.md`, Sección 2.3; [`tests/api/test_auth_rbac.py`](../tests/api/test_auth_rbac.py); sonda S5 |
| Cada ruta declara una decisión de acceso y la matriz coincide con las rutas reales | Comprobado | [`app/api/access.py`](../app/api/access.py); `API_SPEC.md`, Sección 3.6; `test_matriz_de_api_spec_coincide_con_las_rutas_reales` |
| **Matriz RBAC contra producción: 84 de 84 celdas** (28 rutas × sin sesión, médica, administradora), 2026-10-06 01:02 UTC | Comprobado | `FASE17.md`, Sección 3; [`ops/matriz_rbac.py`](../ops/matriz_rbac.py); [`tests/api/test_matriz_rbac.py`](../tests/api/test_matriz_rbac.py) y [`tests/database/test_matriz_rbac.py`](../tests/database/test_matriz_rbac.py) |
| **Sondas de seguridad contra producción: 32 de 34** (S1, S2, S3, S5, S6, S8, S9, S11, S12), 2026-10-06 13:24 UTC | Comprobado | `FASE17.md`, Sección 4; [`ops/sondas_seguridad.py`](../ops/sondas_seguridad.py); [`tests/api/test_sondas_seguridad.py`](../tests/api/test_sondas_seguridad.py) y [`tests/database/test_sondas_seguridad.py`](../tests/database/test_sondas_seguridad.py) |
| Las 2 sondas restantes (S8, S9) recibieron un 403 en HTML con `server: cloudflare`, no la respuesta de la API. En local, la API las rechaza con 422 | Comprobado lo observado; **quién emite el 403: hipótesis** (PENDIENTE de los logs de Render) | `FASE17.md`, Sección 5; [`docs/KNOWN_ISSUES.md`](KNOWN_ISSUES.md), sección de la Fase 17 |
| El BFF no deja pasar ese HTML al navegador: responde 502 uniforme | Comprobado en local | `FASE17.md`, Sección 6; [`tests/server/proxy-intermediary-html.test.ts`](https://github.com/jhanio/gynfem-frontend/blob/a0930c1ea622f6689b04fc2c310bb0c9fd29fa4e/tests/server/proxy-intermediary-html.test.ts); [`gynfem-frontend` #8](https://github.com/jhanio/gynfem-frontend/pull/8) |
| Postura de producción: sin `/docs` ni `/openapi.json`, CORS con un solo origen, errores sin trazas | Comprobado | `SECURITY.md`, Sección 2.4; `DEPLOYMENT.md`, Sección 7.3 (CORS); `FASE17.md`, Sección 3 y sondas S11 y S12 |
| Advertencia clínica obligatoria en cada predicción y reporte | Comprobado | `SECURITY.md`, Sección 4; `test_siempre_incluye_la_advertencia_clinica` |

**Evidencia en bruto de la Fase 17:** los JSONL de `reports/fase17/` están
ignorados por git (`.gitignore`) y **no se publican**. Su contenido está
transcrito en `FASE17.md`, que es la evidencia citable.

PRs: [#10](https://github.com/jhanio/gynfem-backend/pull/10),
[#11](https://github.com/jhanio/gynfem-backend/pull/11),
[#18](https://github.com/jhanio/gynfem-backend/pull/18) (commit `d6b1350`).

---

## 7. Pruebas

Documento dueño: [`docs/TEST_STRATEGY.md`](TEST_STRATEGY.md).

### 7.1 Ejecución de la suite completa (Fase 18)

| Qué | Resultado |
| --- | --- |
| Comando | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` |
| Código | `f627bf0` (`main`) con solo cambios de documentación sin confirmar, rama `docs/evidencia-fase18` |
| Entorno | Windows 11, Python 3.12.10, PostgreSQL embebido (`pgserver`), sin red hacia producción |
| Inicio · fin (UTC) | 2026-10-06 20:52:47 · 21:09:34 |
| Salida | `1306 passed, 1 skipped in 1003.20s (0:16:43)`, código de salida 0 |
| Omitido | `test_dos_ejecuciones_con_todas_las_comprobaciones_dan_metricas_identicas` (`tests/test_train_model.py`): «lento (todas las comprobaciones); se ejecuta bajo demanda con GYNFEM_SLOW_TESTS=1». Omitido por diseño (`TEST_STRATEGY.md`, Sección 3); **no se ejecutó** en esta corrida |
| `BrokenProcessPool` | No apareció ([`KNOWN_ISSUES.md`](KNOWN_ISSUES.md)) |

Los 1307 casos coinciden con el recuento de `TEST_STRATEGY.md`, Sección 3. La
salida se guardó fuera del repositorio; este cuadro es su transcripción.

### 7.2 Inventario y método

| Afirmación | Evidencia |
| --- | --- |
| Tres suites (ML, API, base de datos con PostgreSQL embebido, sin red), un solo comando | `TEST_STRATEGY.md`, Sección 1.6 |
| Inventario por archivo y qué cubre cada uno | `TEST_STRATEGY.md`, Sección 3 |
| Tests antes del código (commits RED, p. ej. `47e5533`, `a4dd1ec`, `11804bf`, `3226776`) | `TEST_STRATEGY.md`, Sección 1.1; historial de git |
| **Verificación por mutación** (cada mutación, detectada por algún test): PR #4, 18; PR #6, 32; PR #7, 23; PR #8, 28; PR #9, 20; PR #10, 27; PR #16, 19 | `TEST_STRATEGY.md`, Sección 4.2 a 4.8 |
| Caso en que la suite **no** detectaba alteraciones, y su corrección | `TEST_STRATEGY.md`, Sección 4.1 (PR #3) |
| Los tests no reescriben artefactos versionados | `TEST_STRATEGY.md`, Sección 1.3; commit `2458afd` |
| **CI:** solo en `gynfem-frontend`. Última ejecución en `main` (`a0930c1`), 2026-10-06 18:57 UTC: `success` | [Ejecución 37515346144](https://github.com/jhanio/gynfem-frontend/actions/runs/37515346144); [`ci.yml`](https://github.com/jhanio/gynfem-frontend/blob/a0930c1ea622f6689b04fc2c310bb0c9fd29fa4e/.github/workflows/ci.yml) |
| Suite del frontend en local: 37 archivos, 699 pruebas, en verde (2026-10-06) | `FASE17.md`, Sección 6 |

**Sin evidencia:** el backend no tiene CI ni mide cobertura (no hay
`pytest-cov` en [`requirements-dev.txt`](../requirements-dev.txt)), así que no
hay cifra de cobertura.

---

## 8. Despliegue

Documento dueño: [`docs/DEPLOYMENT.md`](DEPLOYMENT.md).

| Afirmación | Estado | Evidencia |
| --- | --- | --- |
| API en Render (plan Free, Oregon), configuración como código | Comprobado | [`render.yaml`](../render.yaml); `DEPLOYMENT.md`, Sección 7; [`tests/api/test_render_config.py`](../tests/api/test_render_config.py); PR [#11](https://github.com/jhanio/gynfem-backend/pull/11) |
| La versión desplegada era la 0.6.0 el 2026-10-05 23:36 UTC | Comprobado | `FASE17.md`, Sección 1 |
| Guion de verificación posterior al despliegue, sin crear datos clínicos por defecto | Comprobado | [`ops/verificar_despliegue.py`](../ops/verificar_despliegue.py); `DEPLOYMENT.md`, Secciones 7.7 y 7.11; [`tests/api/test_verificar_despliegue.py`](../tests/api/test_verificar_despliegue.py) |
| Latencia medida en el servidor: `/health` 1.24 ms de mediana; `/me` 879.8 ms (una transacción contra Supabase en São Paulo) | Comprobado | `DEPLOYMENT.md`, Sección 7.8 |
| Arranque en frío del plan Free: la primera respuesta tardó 62.5 s el 2026-10-06 | Comprobado | `FASE17.md`, Sección 3; impacto en la sustentación en `DEPLOYMENT.md`, Sección 7.10 |
| Incidentes de proceso y de despliegue, con su causa y su corrección | Comprobado | `TASK_BREAKDOWN.md`, notas de la Sección 1 |
| Frontend en Vercel (https://gynfem-frontend.vercel.app), con CSP y cabeceras de seguridad | Comprobado | `DEPLOYMENT.md`, Sección 6; [`DEPLOYMENT.md` de `gynfem-frontend`](https://github.com/jhanio/gynfem-frontend/blob/a0930c1ea622f6689b04fc2c310bb0c9fd29fa4e/docs/DEPLOYMENT.md); [`gynfem-frontend` #4](https://github.com/jhanio/gynfem-frontend/pull/4) |
| Integración Vercel ↔ Render ↔ Supabase verificada a mano el 2026-10-01, con el frontend **en local** contra la API de producción | Comprobado, con esa salvedad | Sección 12 del [`DEPLOYMENT.md` de `gynfem-frontend`](https://github.com/jhanio/gynfem-frontend/blob/a0930c1ea622f6689b04fc2c310bb0c9fd29fa4e/docs/DEPLOYMENT.md); [`gynfem-frontend` #6](https://github.com/jhanio/gynfem-frontend/pull/6) |
| Causa del fallo intermitente de arranque en Render | **PENDIENTE** (sin *Events* ni logs) | `FASE17.md`, Sección 7 |

---

## 9. Frontend (solo enlaces)

| PR | Qué aporta |
| --- | --- |
| [#2](https://github.com/jhanio/gynfem-frontend/pull/2), [#3](https://github.com/jhanio/gynfem-frontend/pull/3) | Revisión del código generado con v0 y CI obligatorio (Fase 13, modo simulado) |
| [#4](https://github.com/jhanio/gynfem-frontend/pull/4), [#5](https://github.com/jhanio/gynfem-frontend/pull/5) | Despliegue en Vercel y cabeceras de seguridad (Fase 14) |
| [#6](https://github.com/jhanio/gynfem-frontend/pull/6) | BFF con cookies httpOnly y conexión a la API (Fase 15) |
| [#7](https://github.com/jhanio/gynfem-frontend/pull/7) | Interfaz de administración (Fase 16); auditoría de la interfaz en [`AUDIT_INTERFACE.md`](https://github.com/jhanio/gynfem-frontend/blob/a0930c1ea622f6689b04fc2c310bb0c9fd29fa4e/docs/AUDIT_INTERFACE.md) |
| [#8](https://github.com/jhanio/gynfem-frontend/pull/8) | Prueba del BFF ante un 403 en HTML de un intermediario (Fase 17) |

---

## 10. Pendientes y límites conocidos

| Qué | Estado | Dónde |
| --- | --- | --- |
| Regresión E2E manual contra producción | **PENDIENTE**: guion redactado, **no ejecutado** | [`E2E_GUION.md`](validation/E2E_GUION.md); `FASE17.md`, Sección 7 |
| Suite E2E automatizada (Playwright) | **Fuera de alcance** | `FASE17.md`, Sección 7 |
| S4 (token caducado) en producción | **PENDIENTE** (evidencia local: `test_token_caducado_401_token_expired`) | `FASE17.md`, Sección 7 |
| S6 con un recurso que existe, S7 (recursos dados de baja), S14 (cookies `__Host-` en Vercel) | **PENDIENTE**: pasos 11, 13 y 1 del guion E2E | Idem |
| S10 (`institution_name` con HTML) | **PENDIENTE**, opcional: escribe en producción | Idem |
| S13 (logs sin datos clínicos) | **PENDIENTE** hasta recibir los logs de Render y Vercel | Idem |
| `npm run verify:deployment` contra producción | **PENDIENTE** | Idem; `TASK_BREAKDOWN.md`, Fase 15 |
| Quién emite el 403 en HTML de S8 y S9 | **PENDIENTE** (hipótesis: el proxy de Render) | `FASE17.md`, Sección 5.2 |
| Efectos del 502 del BFF: reintentos de lectura y «no sabemos si se guardó» en escrituras | Límite conocido, no corregido | `KNOWN_ISSUES.md`; `FASE17.md`, Sección 6 |
| Revisión visual de la impresión del reporte en Chrome y Firefox o Edge | **PENDIENTE** según `gynfem-frontend` #7 | `TASK_BREAKDOWN.md`, Fase 16 |
| Rol de mínimo privilegio con `FORCE ROW LEVEL SECURITY` | **Fuera de alcance**: trabajo futuro. Hasta entonces, ningún dato real de pacientes | `SECURITY.md`, Sección 2.3 |
| Límites de la Fase 16 (concurrencia de `PATCH /settings`, residuo de las verificaciones, métricas construidas al arrancar…) | Límites conocidos | `KNOWN_ISSUES.md` |
| Cifras del modelo que la suite no recalcula | Deuda declarada | `training_report.md`, Sección 13 |
| Cobertura de tests y CI del backend | **Sin evidencia**: no existen | §7 |
| Validación externa y clínica del modelo | **No existe** | `training_report.md`, Sección 11.2 |

---

## 11. Lo que este proyecto no afirma

- **Que la regresión E2E se haya ejecutado.** La única verificación de extremo a
  extremo es la manual de la Fase 15, con el frontend en local.
- **Que haya una suite E2E automatizada** ni una cifra de cobertura de tests.
- **Que la API use un rol de mínimo privilegio con `FORCE ROW LEVEL SECURITY`.**
  Es trabajo futuro.
- **Que una médica no vea las pacientes de otra.** No es un requisito: es una
  decisión de diseño para un consultorio único (`SECURITY.md`, Sección 2.3).
- **Que las 34 sondas pasen**, ni que el 403 en HTML lo emita Cloudflare con
  certeza.
- **Que el 99.34 % del paper sea una meta o se haya replicado.**
- **Que el modelo esté validado clínicamente** o en población peruana. El
  dataset no es de GynFem y sus etiquetas no son diagnósticos verificados
  (`training_report.md`, Sección 11.2).
- **Que el sistema diagnostique.** Es apoyo a la decisión clínica y la
  advertencia acompaña cada predicción.
- **Que la producción esté siempre disponible.** El plan Free suspende el
  servicio.
- **Que la producción contenga datos reales.** Solo tiene datos sintéticos.
