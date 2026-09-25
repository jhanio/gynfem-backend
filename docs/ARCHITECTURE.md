# ARCHITECTURE — Arquitectura

- **Alcance de este documento:** qué componentes existen hoy, cómo fluyen los
  datos entre ellos, la estructura real de carpetas y los componentes previstos
  con su fase. No describe el modelo por dentro (dueño: `docs/ML_SPEC.md`), las
  entidades de datos (`docs/ERD.md`), el contrato HTTP (`docs/API_SPEC.md`) ni
  cómo reproducir o desplegar (`docs/DEPLOYMENT.md`).
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  en la Fase 7 (esqueleto de la API), PR #6, y en la Fase 8 (predicción sin
  persistencia), PR #7.
- **Convención:** lo que aún no existe se marca
  **PENDIENTE (Fase N) — se documentará al implementarse**.

---

## 1. Estado

| Componente | Estado | Evidencia |
| --- | --- | --- |
| Dataset RAW inmutable con verificación SHA-256 | **Construido** (PR #1) | `data/raw/`, `tests/test_raw_integrity.py` |
| Perfilado reproducible | **Construido** (PR #1) | `scripts/profile_dataset.py`, `reports/ml/dataset_profile.md` |
| Limpieza reproducible, dos variantes | **Construido** (PR #2, PR #3) | `scripts/prepare_dataset.py`, `reports/ml/data_cleaning_report.md` |
| Entrenamiento y artefactos del modelo | **Construido** (PR #4) | `scripts/train_model.py`, `models/`, `reports/ml/training_report.md` |
| Esqueleto del backend FastAPI: configuración, `/health`, CORS, logs y errores | **Construido** (PR #6) | `app/`, `tests/api/` |
| Predicción sin persistencia: conversión de unidades, carga validada del modelo, validación en tres niveles, `/predict` y `/prediction/schema` | **Construido** (PR #7) | `app/services/`, `app/api/v1/prediction.py`, `tests/api/` |
| Base de datos Supabase | PENDIENTE (Fases 9 y 10) | — |
| Autenticación y autorización | PENDIENTE (Fase 11) | — |
| Despliegue del backend en Render | PENDIENTE (Fase 12) | — |
| Frontend y su despliegue en Vercel | PENDIENTE (Fases 13 y 14) | Existe el repositorio `gynfem-frontend`, con solo su commit inicial |

## 2. Lo construido: pipeline de datos y ML

Tres scripts, cada uno lee la salida verificada del anterior y escribe solo en
su destino. Ningún script escribe en `data/raw/`.

| Script | Lee | Escribe | Control de integridad |
| --- | --- | --- | --- |
| `scripts/profile_dataset.py` | `data/raw/Mathernal_Risk.csv` | `reports/ml/dataset_profile.md`, `reports/ml/figures/hist_*.png` y `box_*.png` | Registra el SHA-256 del RAW en el reporte |
| `scripts/prepare_dataset.py` | RAW | `data/processed/maternal_risk_clean.csv` y `maternal_risk_paper.csv` | Aborta antes de leer o escribir si el SHA-256 del RAW no coincide con `data/raw/README.md` (`data_cleaning_report.md`, Sección 6) |
| `scripts/train_model.py` | Ambas variantes de `data/processed/` | `models/*`, `reports/ml/training_metrics.json`, `reports/ml/training_report.md`, `reports/ml/figures/training_*.png` | Aborta si el SHA-256 del dataset no coincide con el registrado en `data_cleaning_report.md` (tests `test_el_entrenamiento_aborta_si…`) |

`scripts/training_report.py` no se ejecuta por separado: es el módulo que
`train_model.py` usa al renderizar el reporte desde el JSON de métricas, sin
calcular nada.

**Qué hace cada etapa** — detalle y cifras en su documento dueño:

- **Limpieza:** descarta `Name` y `Patient ID`, renombra a nombres con la unidad
  real, y genera dos variantes que difieren en la regla de temperatura
  (`ML_SPEC.md`, Secciones 2.2, 3 y 7).
- **Entrenamiento:** entrena con ambas variantes bajo el mismo protocolo, elige
  la de producción con una regla codificada y serializa un solo modelo
  (`ML_SPEC.md`, Secciones 8 y 9).

### 2.1 Artefactos del modelo

| Artefacto | Rol |
| --- | --- |
| `models/maternal_risk_rf_v1.0.0.joblib` | Modelo entregado (versión `1.0.0`) |
| `models/model_metadata.json` | Orden y unidad de las variables, orden de clases, versiones, SHA-256 del dataset |
| `models/feature_ranges.json` | Rango de entrenamiento por variable, generado |

El contrato que el backend deberá respetar al cargarlos es el de
`ML_SPEC.md`, Sección 9.6. Este documento no lo repite.

### 2.2 Backend FastAPI (Fases 7 y 8)

Aplicación FastAPI en `app/`, servida por uvicorn. Endpoints:
`GET /api/v1/health` (Fase 7), `POST /api/v1/predict` y
`GET /api/v1/prediction/schema` (Fase 8) (`docs/API_SPEC.md`, Sección 3).

**Capas.** Tres capas, con dependencias en un solo sentido
(`api → services → repositories`, nunca al revés):

| Capa | Carpeta | Responsabilidad | Estado |
| --- | --- | --- | --- |
| Entrada HTTP | `app/api/` | Rutas, validación de la petición, forma de la respuesta. No accede a recursos externos: llama a un servicio | `v1/health.py`, `v1/prediction.py` |
| Lógica de negocio | `app/services/` | Reglas del dominio. No conoce HTTP | `unit_conversion.py`, `clinical_limits.py`, `model_loader.py`, `prediction.py` (Fase 8) |
| Acceso a recursos externos | `app/repositories/` | Base de datos y otros servicios externos | Vacía; la llenan las Fases 9 y 10 (Supabase) |

Las piezas transversales están en `app/core/`, y los modelos Pydantic de
respuesta en `app/schemas/`.

**Recorrido de una petición.** Cada capa envuelve a la siguiente:

```text
ServerErrorMiddleware (Starlette)
  └─ CORSMiddleware                orígenes de GYNFEM_CORS_ORIGINS
      └─ RequestContextMiddleware  X-Request-ID, log de acceso, 500 uniforme
          └─ ExceptionMiddleware   404 / 405 / 422 → formato uniforme
              └─ AsyncExitStackMiddleware (FastAPI)
                  └─ router /api/v1 → endpoint
```

`RequestContextMiddleware` va **dentro** de CORS a fin de que el 500 que
genera conserve las cabeceras CORS.

**Arranque.** `app/main.py` llama a `create_app()` (`app/factory.py`) al ser
importado por uvicorn. `create_app()`:

1. valida la configuración (`app/core/config.py`) antes de construir nada;
2. carga el modelo **una sola vez** desde `GYNFEM_MODEL_DIR` y valida su
   contrato (`app/services/model_loader.py`; `ML_SPEC.md`, Sección 9.9);
3. crea el `PredictionService` y lo guarda en `app.state`, de donde lo toman
   las rutas.

Si la configuración o el contrato del modelo no se verifican, el proceso
termina con código 1 y un mensaje que nombra la variable o la parte del
contrato que falla, sin traza (`docs/DEPLOYMENT.md`, Secciones 5.3 y 5.4).

### 2.3 Flujo de una predicción (Fase 8)

```text
POST /api/v1/predict  {8 variables en unidad clínica}
  │
  ├─ PredictionRequest (app/schemas/prediction.py)          nivel a
  │    límites fisiológicos de clinical_limits.py, esquema estricto,
  │    diastólica < sistólica ──── falla ──► 422 uniforme; el modelo no se llama
  │
  ▼
PredictionService.predict (app/services/prediction.py)      sin HTTP
  ├─ to_model_units (unit_conversion.py)       °C→°F, %→mmol/mol, mg/dl→mmol/L
  ├─ DataFrame con las columnas en el orden de model_metadata.json
  ├─ pipeline.predict_proba ─► probabilidades asignadas por nombre de clase
  └─ nivel b: entrada clínica frente al rango de entrenamiento convertido
             ─► un aviso por variable fuera del rango
  │
  ▼
200 {risk_level, probabilities, extrapolation_warnings, clinical_disclaimer,
     input, model_input, model_version, conversion_schema_version, predicted_at}
  + una línea de log con request_id, latencia y resultado agregado
```

Nada se guarda: la respuesta se devuelve y se descarta. La persistencia llega
en la Fase 10, y la respuesta ya lleva los cuatro elementos de trazabilidad
que guardará (`ML_SPEC.md`, Sección 6). `GET /api/v1/prediction/schema` sale
del mismo `PredictionService`, así que publica exactamente los límites que
aplica la validación.

## 3. Lo previsto

Una o dos frases por componente. El detalle se documentará al implementarse.

- **Base de datos — PENDIENTE (Fases 9 y 10).** Supabase como almacenamiento
  (Fase 9) y persistencia clínica con trazabilidad de cada predicción
  (Fase 10; `docs/ERD.md`).
- **Autenticación y autorización — PENDIENTE (Fase 11).** Supabase Auth emite
  el JWT, FastAPI lo valida y aplica RBAC (HU001, `docs/PRD.md`).
- **Despliegue del backend — PENDIENTE (Fase 12).** Render.
- **Frontend — PENDIENTE (Fases 13 y 14).** Interfaz en el repositorio
  `gynfem-frontend` (Fase 13), desplegada en Vercel (Fase 14).

## 4. Flujo completo previsto

```text
 ┌──────────────────────── CONSTRUIDO (PR #1–#4) ──────────────────────────────────┐
 │                                                                                 │
 │  data/raw/Mathernal_Risk.csv ──(SHA-256)──► prepare_dataset.py                  │
 │          │                                        │                             │
 │          └─► profile_dataset.py                   ▼                             │
 │                    │                 data/processed/*.csv ──(SHA-256)──►        │
 │                    ▼                                        train_model.py      │
 │          dataset_profile.md                                     │               │
 │                                          ┌──────────────────────┤               │
 │                                          ▼                      ▼               │
 │                          models/*.joblib + *.json     reports/ml/training_*     │
 └──────────────────────────────────────────┬──────────────────────────────────────┘
                                            │ carga del artefacto (ML_SPEC §9.6)
 ┌──────────────────────────── PENDIENTE (Fases 8–14) ─────────────────────────────┐
 │                                          ▼                                      │
 │  Frontend (13) ──────► FastAPI /api/v1 (7) ──► validación + conversión ──►      │
 │  en Vercel (14)             │   en Render (12)        predicción (8)            │
 │                             │                                                   │
 │                             ├──► Supabase Auth: JWT + RBAC (11)                 │
 │                             └──► Supabase: pacientes, evaluaciones,             │
 │                                  trazabilidad (9, 10)                           │
 └─────────────────────────────────────────────────────────────────────────────────┘
```

Todo lo que está sobre la línea `carga del artefacto` existe. Lo cubren tests
salvo el perfilado: `profile_dataset.py` no tiene tests
(`docs/TEST_STRATEGY.md`, Sección 3). De lo que está debajo existen
`FastAPI /api/v1 (7)` y `validación + conversión + predicción (8)`
(Secciones 2.2 y 2.3). El resto es PENDIENTE y no tiene código en este
repositorio.

## 5. Estructura real de carpetas

Solo archivos versionados (`git ls-files`); se omiten las figuras una a una.

```text
gynfem-backend/
├── .env.example              variables de entorno de la API, con valores locales de ejemplo
├── CLAUDE.md                 reglas permanentes del repositorio
├── README.md                 solo el título
├── requirements.txt          dependencias fijadas con ==
├── app/                      backend FastAPI (Sección 2.2)
│   ├── __init__.py           __version__, única fuente de la versión de la aplicación
│   ├── main.py               objeto `app` que arranca uvicorn
│   ├── factory.py            create_app(): configuración, middleware, errores y rutas
│   ├── core/                 config, logging, middleware, errors
│   ├── api/                  router.py (prefijo /api/v1), v1/health.py y v1/prediction.py
│   ├── schemas/              modelos Pydantic (health, error, prediction)
│   ├── services/             conversión de unidades, límites fisiológicos, carga del modelo y predicción
│   └── repositories/         vacía: acceso a recursos externos (Fases 9 y 10)
├── data/
│   ├── raw/                  RAW inmutable + README con su SHA-256
│   ├── interim/              vacía (.gitkeep); ningún script la usa hoy
│   └── processed/            las dos variantes generadas
├── docs/                     especificaciones (ML_SPEC.md es la del modelo)
├── models/                   modelo serializado, metadata y rangos
├── reports/ml/               reportes generados, métricas JSON y figuras
├── scripts/                  profile_dataset, prepare_dataset, train_model, training_report
└── tests/                    conftest + tests de integridad, limpieza y entrenamiento
    └── api/                  suite de la API, con su propio conftest (docs/TEST_STRATEGY.md)
```
