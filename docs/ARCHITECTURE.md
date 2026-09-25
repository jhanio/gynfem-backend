# ARCHITECTURE — Arquitectura

- **Alcance de este documento:** qué componentes existen hoy, cómo fluyen los
  datos entre ellos, la estructura real de carpetas y los componentes previstos
  con su fase. No describe el modelo por dentro (dueño: `docs/ML_SPEC.md`), las
  entidades de datos (`docs/ERD.md`), el contrato HTTP (`docs/API_SPEC.md`) ni
  cómo reproducir o desplegar (`docs/DEPLOYMENT.md`).
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  en la Fase 7 (esqueleto de la API), PR #6.
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
| Servicio de predicción | PENDIENTE (Fase 8) | — |
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

### 2.2 Esqueleto del backend (Fase 7)

Aplicación FastAPI en `app/`, servida por uvicorn. Todavía no carga el modelo
ni tiene endpoints de negocio: solo `GET /api/v1/health` (`docs/API_SPEC.md`,
Sección 3).

**Capas.** Tres capas, con dependencias en un solo sentido
(`api → services → repositories`, nunca al revés):

| Capa | Carpeta | Responsabilidad | Estado |
| --- | --- | --- | --- |
| Entrada HTTP | `app/api/` | Rutas, validación de la petición, forma de la respuesta. No accede a recursos externos: llama a un servicio | `v1/health.py` |
| Lógica de negocio | `app/services/` | Reglas del dominio. No conoce HTTP | Vacía; la llena la Fase 8 (predicción) |
| Acceso a recursos externos | `app/repositories/` | Base de datos y otros servicios externos | Vacía; la llenan las Fases 9 y 10 (Supabase) |

Las piezas transversales están en `app/core/`, y los modelos Pydantic de
respuesta en `app/schemas/`.

**Recorrido de una petición.** Cada capa envuelve a la siguiente:

```text
ServerErrorMiddleware (Starlette)
  └─ CORSMiddleware                orígenes de GYNFEM_CORS_ORIGINS
      └─ RequestContextMiddleware  X-Request-ID, log de acceso, 500 uniforme
          └─ ExceptionMiddleware   404 / 405 / 422 → formato uniforme
              └─ router /api/v1 → endpoint
```

`RequestContextMiddleware` va **dentro** de CORS a fin de que el 500 que
genera conserve las cabeceras CORS.

**Arranque.** `app/main.py` llama a `create_app()` (`app/factory.py`) al ser
importado por uvicorn. `create_app()` valida la configuración
(`app/core/config.py`) antes de construir nada. Si falta una variable o es
inválida, el proceso termina con código 1 y un mensaje que nombra la variable
(`docs/DEPLOYMENT.md`, Sección 5).

## 3. Lo previsto

Una o dos frases por componente. El detalle se documentará al implementarse.

- **Predicción — PENDIENTE (Fase 8).** Validación, conversión de unidades y
  llamada al modelo, sin persistencia (`ML_SPEC.md`, Secciones 4 y 5).
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
(`docs/TEST_STRATEGY.md`, Sección 3). De lo que está debajo solo existe el
esqueleto de `FastAPI /api/v1 (7)`, sin endpoints de negocio (Sección 2.2). El
resto es PENDIENTE y no tiene código en este repositorio.

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
│   ├── api/                  router.py (prefijo /api/v1) y v1/health.py
│   ├── schemas/              modelos Pydantic de respuesta (health, error)
│   ├── services/             vacía: lógica de negocio (Fase 8)
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
