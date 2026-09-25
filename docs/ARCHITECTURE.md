# ARCHITECTURE — Arquitectura

- **Alcance de este documento:** qué componentes existen hoy, cómo fluyen los
  datos entre ellos, la estructura real de carpetas y los componentes previstos
  con su fase. No describe el modelo por dentro (dueño: `docs/ML_SPEC.md`), las
  entidades de datos (`docs/ERD.md`), el contrato HTTP (`docs/API_SPEC.md`) ni
  cómo reproducir o desplegar (`docs/DEPLOYMENT.md`).
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  en la Fase 7 (esqueleto de la API), PR #6, en la Fase 8 (predicción sin
  persistencia), PR #7, y en la Fase 9 (base de datos), PR #8.
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
| Base de datos Supabase: esquema, migraciones versionadas, pool de conexiones y `/health/ready` | **Construido** (PR #8) | `migrations/`, `app/db/`, `tests/database/`, `docs/ERD.md` |
| Persistencia clínica (escritura en la base) | PENDIENTE (Fase 10) | — |
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
`GET /api/v1/prediction/schema` (Fase 8), y `GET /api/v1/health/ready`
(Fase 9) (`docs/API_SPEC.md`, Sección 3).

**Capas.** Tres capas, con dependencias en un solo sentido
(`api → services → repositories`, nunca al revés):

| Capa | Carpeta | Responsabilidad | Estado |
| --- | --- | --- | --- |
| Entrada HTTP | `app/api/` | Rutas, validación de la petición, forma de la respuesta. No accede a recursos externos: llama a un servicio | `v1/health.py`, `v1/prediction.py` |
| Lógica de negocio | `app/services/` | Reglas del dominio. No conoce HTTP | `unit_conversion.py`, `clinical_limits.py`, `model_loader.py`, `prediction.py` (Fase 8), `readiness.py` (Fase 9) |
| Acceso a recursos externos | `app/repositories/` | Consultas a la base, con SQL explícito y parametrizado | `database_health.py` (Fase 9). Los repositorios clínicos llegan en la Fase 10 |

Las piezas transversales están en `app/core/`; el pool de conexiones y el
runner de migraciones, en `app/db/` (Sección 2.4), y los modelos Pydantic de
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
   las rutas;
4. lee la serie de migraciones del repositorio (las versiones que el código
   espera encontrar aplicadas) y crea el pool de conexiones **cerrado**, junto
   con el `ReadinessService`.

El pool se abre en el ciclo de vida de la aplicación (`lifespan`), sin esperar
a la base, y se cierra de forma ordenada al apagar. Crear o importar la
aplicación nunca conecta: una base caída no impide arrancar.

Si la configuración, el contrato del modelo o la serie de migraciones no se
verifican, el proceso termina con código 1 y un mensaje que nombra la
variable, la parte del contrato o la migración que falla, sin traza
(`docs/DEPLOYMENT.md`, Secciones 5.3 y 5.4).

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

### 2.4 Capa de datos (Fase 9)

PostgreSQL gestionado por Supabase (región South America, São Paulo). El
esquema se describe en `docs/ERD.md`; las credenciales y RLS, en
`docs/SECURITY.md`.

| Pieza | Archivo | Qué hace |
| --- | --- | --- |
| Migraciones | `migrations/NNNN_nombre.up.sql` y `.down.sql` | SQL plano, numerado sin huecos, cada una con su reversión. Única vía para cambiar el esquema |
| Runner | `app/db/migrate.py` (`python -m app.db.migrate up\|down\|status`) | Toma un bloqueo consultivo antes de tocar nada, aplica cada migración en una transacción con `lock_timeout` junto con su registro, guarda su SHA-256 y aborta si una ya aplicada cambió. Rechaza `CONCURRENTLY` y el control de transacción dentro de un archivo. `status` solo lee. Usa `GYNFEM_MIGRATIONS_DATABASE_URL` (pooler en modo **Session**; rechaza el puerto 6543 del modo Transaction) |
| Pool | `app/db/pool.py` | `psycopg_pool.ConnectionPool` sobre `GYNFEM_DATABASE_URL` (pooler en modo **Transaction**): sin sentencias preparadas, con tiempos de conexión, de pool y por sentencia, keepalives TCP y `tcp_user_timeout`, y comprobación de cada conexión antes de entregarla |
| Repositorio | `app/repositories/database_health.py` | Qué migraciones tiene aplicadas la base |
| Servicio | `app/services/readiness.py` | «Lista» = la base responde **y** tiene exactamente las migraciones que el código espera |

**Por qué SQL directo y no un ORM.** Cinco tablas; el esquema ya vive en SQL
en las migraciones, y un ORM duplicaría esa definición en Python. Las consultas
de la Fase 10 y los reportes de la Fase 16 se escriben y se leen tal como las
ejecuta PostgreSQL. `psycopg` 3 síncrono, igual que las rutas actuales, que
FastAPI ejecuta en su *threadpool*.

**Por qué un runner propio.** La CLI de Supabase no tiene migraciones de
reversión; Alembic envuelve el SQL en Python y trae SQLAlchemy solo para
migrar; yoyo-migrations crea sus tablas de control en `public`, que la Data API
expone. El runner son unas 350 líneas, docstrings incluidas, cubiertas por
`tests/database/`.

```text
GET /api/v1/health/ready
  └─ ReadinessService.check()                         (app/services/readiness.py)
      └─ database_transaction(pool)                    espera ≤ GYNFEM_DB_POOL_TIMEOUT_S
          ├─ set_config('statement_timeout', …, true)  solo en esta transacción
          └─ applied_migration_versions()              (app/repositories/database_health.py)
  200 {"status": "ready", "checks": {…}}  ·  503 database_unavailable | schema_outdated
```

## 3. Lo previsto

Una o dos frases por componente. El detalle se documentará al implementarse.

- **Persistencia clínica — PENDIENTE (Fase 10).** Repositorios y endpoints
  que escriben pacientes, mediciones y predicciones con su trazabilidad sobre
  el esquema de la Fase 9 (`docs/ERD.md`).
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
`FastAPI /api/v1 (7)`, `validación + conversión + predicción (8)` y el
esquema de Supabase con su conexión (9) (Secciones 2.2 a 2.4); la escritura de
pacientes y evaluaciones es de la Fase 10. El resto es PENDIENTE y no tiene
código en este repositorio.

## 5. Estructura real de carpetas

Solo archivos versionados (`git ls-files`); se omiten las figuras una a una.

```text
gynfem-backend/
├── .env.example              variables de entorno de la API, con valores locales de ejemplo
├── CLAUDE.md                 reglas permanentes del repositorio
├── README.md                 solo el título
├── requirements.txt          dependencias fijadas con ==; lo único que instala el despliegue
├── requirements-dev.txt      requirements.txt + pgserver (PostgreSQL embebido), solo para los tests
├── app/                      backend FastAPI (Sección 2.2)
│   ├── __init__.py           __version__, única fuente de la versión de la aplicación
│   ├── main.py               objeto `app` que arranca uvicorn
│   ├── factory.py            create_app(): configuración, middleware, errores y rutas
│   ├── core/                 config, logging, middleware, errors
│   ├── db/                   pool de conexiones y runner de migraciones (Sección 2.4)
│   ├── api/                  router.py (prefijo /api/v1), v1/health.py y v1/prediction.py
│   ├── schemas/              modelos Pydantic (health, error, prediction)
│   ├── services/             conversión de unidades, límites fisiológicos, carga del modelo, predicción y readiness
│   └── repositories/         consultas a la base (database_health.py; las clínicas, Fase 10)
├── data/
│   ├── raw/                  RAW inmutable + README con su SHA-256
│   ├── interim/              vacía (.gitkeep); ningún script la usa hoy
│   └── processed/            las dos variantes generadas
├── docs/                     especificaciones (ML_SPEC.md es la del modelo)
├── migrations/               migraciones SQL versionadas, cada una con su .down.sql (docs/ERD.md)
├── models/                   modelo serializado, metadata y rangos
├── reports/ml/               reportes generados, métricas JSON y figuras
├── scripts/                  profile_dataset, prepare_dataset, train_model, training_report
└── tests/                    conftest + tests de integridad, limpieza y entrenamiento
    ├── api/                  suite de la API, con su propio conftest (docs/TEST_STRATEGY.md)
    └── database/             suite de la base: migraciones, esquema, pool y /health/ready, sobre PostgreSQL embebido
```
