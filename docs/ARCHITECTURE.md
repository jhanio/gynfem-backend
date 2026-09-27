# ARCHITECTURE — Arquitectura

- **Alcance de este documento:** qué componentes existen hoy, cómo fluyen los
  datos entre ellos, la estructura real de carpetas y los componentes previstos
  con su fase. No describe el modelo por dentro (dueño: `docs/ML_SPEC.md`), las
  entidades de datos (`docs/ERD.md`), el contrato HTTP (`docs/API_SPEC.md`) ni
  cómo reproducir o desplegar (`docs/DEPLOYMENT.md`).
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  en la Fase 7 (esqueleto de la API), PR #6, en la Fase 8 (predicción sin
  persistencia), PR #7, en la Fase 9 (base de datos), PR #8, en la Fase 10
  (persistencia clínica), PR #9, en la Fase 11 (autenticación y
  autorización), PR #10, y en la Fase 12 (despliegue en Render), PR #11.
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
| Persistencia clínica: pacientes, mediciones con predicción persistida, correcciones, auditoría | **Construido** (PR #9) | `app/repositories/`, `app/services/patients.py`, `app/services/clinical_records.py`, `app/api/v1/patients.py`, `app/api/v1/measurements.py`, `migrations/0007_*` |
| Autenticación con Supabase Auth, RBAC en todas las rutas, gestión de usuarios y primer administrador | **Construido** (PR #10) | `app/auth/`, `app/api/access.py`, `app/api/v1/users.py`, `app/api/v1/me.py`, `migrations/0008_*`, `tests/api/test_auth_*.py` |
| Despliegue del backend en Render (Oregon, plan Free), configuración como código y verificación posterior | **Construido** (PR #11) | `render.yaml`, `ops/verificar_despliegue.py`, `tests/api/test_render_config.py`, `docs/DEPLOYMENT.md` Sección 7 |
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
| Lógica de negocio | `app/services/` | Reglas del dominio. No conoce HTTP. Abre **una** transacción por operación | `unit_conversion.py`, `clinical_limits.py`, `model_loader.py`, `prediction.py` (Fase 8), `readiness.py` (Fase 9), `patients.py`, `clinical_records.py`, `actor.py`, `errors.py` (Fase 10) |
| Acceso a recursos externos | `app/repositories/` | Consultas a la base, con SQL explícito y parametrizado. Reciben una conexión abierta: nunca abren ni confirman una transacción. No importan de `services`, `api` ni `schemas` (`test_los_repositorios_no_dependen_de_capas_superiores`) | `database_health.py` (Fase 9), `patients.py`, `measurements.py`, `predictions.py`, `audit.py` (Fase 10) |

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

### 2.5 Flujo de la persistencia clínica (Fase 10)

```text
POST /api/v1/patients/{id}/measurements   {8 variables en unidad clínica, measured_at?}
  │  requiere(Role.MEDICO) → Actor del token verificado (Sección 2.6)
  ├─ MeasurementCreate (hereda de PredictionRequest)                 nivel a
  │    falla ──► 422 uniforme; ni se predice ni se escribe
  ▼
ClinicalRecordService.evaluate (app/services/clinical_records.py)
  ├─ 1. PredictionService.predict (Fase 8, sin cambios)        en memoria, sin base
  │       falla el modelo ──► 500; no hay nada que deshacer
  └─ 2. database_transaction ─── UNA transacción ───────────────────────────────┐
         ├─ patients.get_active(FOR UPDATE)     no existe o dada de baja ─► 404 │
         ├─ measurements.insert_measurement     unidades clínicas               │
         ├─ audit.insert_audit(clinical_measurement.create)                     │
         ├─ predictions.insert_prediction       input_*, model_* en el orden    │
         │                                       del contrato, versiones, avisos │
         └─ audit.insert_audit(prediction.create)                               │
            cualquier fallo ──► ROLLBACK de todo; 500, o 503 si cae la base ─────┘
  ▼
201 {measurement, prediction}  + una línea gynfem.clinical (acción y latencia)
```

**Por qué la predicción va antes de la transacción:** así no hay ningún estado
en que la medición esté escrita y la predicción no. Si el modelo falla, no se
escribió nada; si falla una escritura, PostgreSQL deshace las anteriores
(`test_fallo_de_la_prediccion_no_deja_escrito_nada`,
`test_fallo_a_mitad_de_la_transaccion_revierte_todo`). Además, no se ocupa una
conexión del pool mientras corre el modelo.

La corrección (`POST /measurements/{id}/corrections`) sigue el mismo orden y,
dentro de la transacción, bloquea la medición original, la da de baja e inserta
la nueva con `replaces_measurement_id`. Pacientes: una transacción por
operación, con su auditoría (`app/services/patients.py`).

**Errores.** `app/services/errors.py` define los del dominio sin conocer HTTP;
`app/core/errors.py` los traduce a 404 o 409 con el formato uniforme, y una
caída de la base (`PoolTimeout`, `OperationalError`) a 503
`database_unavailable`, registrando solo el tipo.

**Actor.** Desde la Fase 11, `app/api/deps.py:get_actor` devuelve el usuario
autenticado que resolvió la decisión de acceso de la ruta (Sección 2.6); los
servicios escriben su `user_id` en `*_by` y en la auditoría, sin cambios.

**Lectura exacta de los `float8`.** `database_transaction` fija
`extra_float_digits = 3` en cada transacción: Supabase lo tiene en 0, y con él
un valor como 6.111111111111111 se leía como 6.11111111111111. Lo detectó la
verificación contra la base real de la Fase 10
(`test_la_trazabilidad_se_relee_exacta_con_extra_float_digits_de_supabase`).

### 2.6 Flujo de autenticación y autorización (Fase 11)

```text
Frontend (Fase 13) ── correo + contraseña ──► Supabase Auth ──► access token ES256 (1 h)
    │                                                         + refresh token (solo el frontend)
    ▼
GET/POST /api/v1/…   Authorization: Bearer <access token>
  │
  ├─ ruta con publica("motivo")  (/health)  ──────────────────────────────► endpoint
  │
  └─ ruta con requiere(roles)   (app/api/access.py, antes que el cuerpo y el recurso)
       ├─ 1. HTTPBearer: sin token o con otro esquema ─────────────────► 401 not_authenticated
       ├─ 2. TokenVerifier.verify (app/auth/tokens.py)
       │      JWKS de Supabase (caché 300 s) ─ no responde ────────────► 503 auth_unavailable
       │      firma ES256, iss, aud, exp, iat, sub ─ falla ─────────────► 401 invalid_token / token_expired
       ├─ 3. UserDirectory.status(sub) (app/auth/directory.py)
       │      SELECT role, is_active FROM gynfem.user_profiles   — en CADA petición, sin caché
       │      sin perfil o inactivo ───────────────────────────────────► 403 account_disabled
       ├─ 4. rol ∉ roles de la ruta ───────────────────────────────────► 403 forbidden
       └─ 5. request.state.actor = Actor(sub, rol) ─► get_actor ─► endpoint ─► servicio
  (cada paso deja una línea gynfem.auth con user_id y auth_outcome; nunca el token)
```

- **La identidad sale solo del token**; el rol, solo de la base. Nada del
  cuerpo, la URL o las cabeceras (salvo `Authorization`) interviene.
- **Gestión de usuarios (HU002).** `UserService` (`app/services/users.py`)
  crea la cuenta con la Admin API de Supabase (`app/auth/supabase_admin.py`,
  clave secreta solo en el backend) y después, en una transacción, el perfil y
  la auditoría; si la transacción falla, borra la cuenta (compensación).
- **Primer administrador.** `python -m app.auth.bootstrap` (`docs/DEPLOYMENT.md`,
  Sección 6.3): por línea de comandos, porque el registro público está cerrado.
- **Sustituibles en los tests.** `create_app()` acepta el verificador, el
  directorio de usuarios y el cliente de la Admin API: los tests firman sus
  propios tokens y nunca desactivan la autenticación.

### 2.7 Topología desplegada (Fase 12)

```text
                       Internet (HTTPS)
                              │
                              ▼
 ┌─ Render · Oregon (EE. UU. oeste) · plan Free ────────────────────────────┐
 │  proxy de Render: TLS, health check GET /api/v1/health                   │
 │        │ HTTP + X-Forwarded-*                                            │
 │        ▼                                                                 │
 │  gynfem-api: 1 proceso uvicorn (app.main:app), modelo en memoria         │
 │  (≈186 MB de 512 MB). Definido en render.yaml; despliega desde main.     │
 └────────┬───────────────────────────────────────────┬─────────────────────┘
          │ PostgreSQL + TLS (sslmode=require),       │ HTTPS: JWKS (verificar tokens)
          │ pooler Transaction :6543                  │ y Admin API (HU002)
          ▼                                           ▼
 ┌─ Supabase · São Paulo · plan Free ──────────────────────────────────────┐
 │  Postgres 17.6: esquema gynfem (RLS: denegación total a la Data API)    │
 │  Supabase Auth: emite los JWT ES256, publica el JWKS                    │
 └─────────────────────────────────────────────────────────────────────────┘

 Local (quien opera): migraciones (pooler Session :5432), primer administrador
 y ops/verificar_despliegue.py. Nunca desde el servicio.
```

- **Regiones.** Render no tiene región en Sudamérica; la API está en Oregon
  (decisión 1) y la base en São Paulo. Cada petición autenticada hace al menos
  una transacción contra la base (la lectura del perfil, Sección 2.6); su coste
  medido está en `docs/DEPLOYMENT.md`, Sección 7.8.
- **Arranque.** Al arrancar se validan la configuración y el contrato del
  modelo y se carga el modelo (Sección 2.2); el pool se abre sin esperar a la
  base. El plan Free suspende el servicio tras 15 minutos sin tráfico: la
  primera petición después paga el arranque (`docs/DEPLOYMENT.md`, Sección 7.10).
- **Qué no corre en el servicio.** Las migraciones, la creación del primer
  administrador y la verificación posterior se ejecutan desde la máquina de
  quien opera, con credenciales que nunca llegan a Render.

## 3. Lo previsto

Una o dos frases por componente. El detalle se documentará al implementarse.

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
 │  en Vercel (14)             │   en Render (12, construido)    predicción (8)    │
 │                             │                                                   │
 │                             ├──► Supabase Auth: JWT + RBAC (11, construido)     │
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
├── requirements-dev.txt      requirements.txt + pgserver (PostgreSQL embebido) y PyYAML, solo para los tests
├── render.yaml               el servicio de Render como código, sin secretos (Sección 2.7)
├── ops/                      verificar_despliegue.py: verificación repetible de la API desplegada
├── app/                      backend FastAPI (Sección 2.2)
│   ├── __init__.py           __version__, única fuente de la versión de la aplicación
│   ├── main.py               objeto `app` que arranca uvicorn
│   ├── factory.py            create_app(): configuración, middleware, errores y rutas
│   ├── core/                 config, logging, middleware, errors
│   ├── db/                   pool de conexiones y runner de migraciones (Sección 2.4)
│   ├── auth/                 Supabase Auth: tokens (JWT/JWKS), directory (rol y estado), supabase_admin, roles, errors, bootstrap (primer administrador)
│   ├── api/                  router.py, prefix.py (/api/v1), access.py (requiere/publica), deps.py (get_actor) y v1/: health, prediction, patients, measurements, me, users, comun
│   ├── schemas/              modelos Pydantic (health, error, prediction, patients, clinical, pagination, users)
│   ├── services/             conversión, límites, carga del modelo, predicción, readiness, pacientes, mediciones, usuarios, actor y errores
│   └── repositories/         consultas a la base: database_health, patients, measurements, predictions, audit, users
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
    └── database/             suite de la base: migraciones, esquema, pool, /health/ready, persistencia clínica, usuarios y RLS, sobre PostgreSQL embebido
```
