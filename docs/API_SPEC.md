# API_SPEC — Contrato de la API

- **Alcance de este documento:** los principios aprobados del contrato HTTP y
  qué fase aporta cada grupo de endpoints. Los nombres, unidades, conversiones
  y rangos de las variables pertenecen a `docs/ML_SPEC.md` (Secciones 4, 5 y
  9.6); este documento los referencia y no los copia. Los controles de acceso
  están en `docs/SECURITY.md`.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  en la Fase 7 (esqueleto de la API), PR #6, en la Fase 8 (predicción sin
  persistencia), PR #7, y en la Fase 9 (base de datos), PR #8.
- **Convención:** lo que aún no existe se marca
  **PENDIENTE (Fase N) — se documentará al implementarse**.

---

## 1. Estado

Código en `app/`:

- el prefijo `/api/v1` (Sección 2.1), el formato de error uniforme
  (Sección 2.5) y CORS, correlación y documentación interactiva (Sección 2.6),
  desde la Fase 7 (PR #6);
- `GET /api/v1/health` (Sección 3.1), desde la Fase 7;
- la predicción sin persistencia, desde la Fase 8 (PR #7):
  `POST /api/v1/predict` (Sección 3.2) y `GET /api/v1/prediction/schema`
  (Sección 3.3);
- `GET /api/v1/health/ready` (Sección 3.4), desde la Fase 9 (PR #8).

Desde la Fase 9 la API se conecta a la base de datos, pero ningún endpoint
guarda todavía nada (Fase 10), y ninguno exige credenciales (Fase 11). Lo que
aún no tiene código se sigue marcando como PENDIENTE.

## 2. Principios aprobados

Los aprobó el equipo del proyecto en la planificación, que no está versionada
en el repositorio. Donde un principio sale de `ML_SPEC.md`, se cita.

### 2.1 Versionado

Todas las rutas cuelgan del prefijo **`/api/v1`** (`API_V1_PREFIX` en
`app/api/router.py`). Fuera del prefijo no hay ninguna ruta: `/health` devuelve
404.

### 2.2 Entradas en unidades clínicas, con la unidad en el nombre del campo

El cliente envía las 8 variables en **unidades clínicas peruanas** (°C, %,
mg/dl…). Cada campo declara su unidad en el nombre, de modo que un valor nunca
llega sin unidad explícita. Los nombres de campo aprobados son los de la
columna «Campo de entrada (backend)» de `ML_SPEC.md`, Sección 4.

La conversión a las unidades del dataset ocurre **solo en el backend**, antes de
invocar el modelo (`ML_SPEC.md`, Sección 4). El cliente nunca envía el vector
del modelo.

### 2.3 Validación en tres niveles

| Nivel | Condición | Efecto | Fuente de los límites |
| --- | --- | --- | --- |
| **Rechazo** | Valor fisiológicamente imposible | 422 (Sección 2.5); no se predice | **Provisionales, pendientes de validación clínica con GynFem** (`ML_SPEC.md`, Sección 5.1). Única fuente: `app/services/clinical_limits.py` |
| **Aviso** | Valor posible, pero fuera del rango de entrenamiento | Se predice, con una **advertencia de extrapolación** visible | `models/feature_ranges.json`, generado, nunca escrito a mano (`ML_SPEC.md`, Sección 5) |
| **Normal** | Dentro del rango de entrenamiento | Se predice sin advertencia de extrapolación | — |

`feature_ranges.json` está en unidades del dataset (°F, mmol/mol, mmol/L),
mientras que la entrada llega en unidades clínicas. **Se convierten los
rangos**, no la entrada: la entrada clínica se compara con los extremos ya
convertidos, que son los mismos números que publica
`/api/v1/prediction/schema` (Sección 3.3). Así el frontend y el backend nunca
discrepan en un extremo por el redondeo de la conversión (`ML_SPEC.md`,
Sección 5.2).

### 2.4 El esquema de campos y rangos se publica

Un endpoint publica los campos de entrada, su unidad y sus rangos, de modo que el
frontend **no codifique ningún número**. La fuente de esos rangos es la misma
que usa la validación del backend, de modo que no puede haber dos versiones.
**Construido en la Fase 8:** `GET /api/v1/prediction/schema` (Sección 3.3).

### 2.5 Formato de error uniforme

Todos los errores comparten una misma estructura, sea cual sea el endpoint o el
nivel que los origina (`app/core/errors.py`, `app/schemas/error.py`):

```json
{"error": {"code": "not_found", "message": "Recurso no encontrado.", "request_id": "3f0c…"}}
```

| Campo | Contenido |
| --- | --- |
| `code` | Identificador estable en `snake_case`. El cliente decide con él, no con `message` |
| `message` | Texto en español para mostrar. Nunca contiene datos clínicos, trazas, rutas del sistema ni el mensaje de una excepción |
| `request_id` | El mismo valor que la cabecera `X-Request-ID` de la respuesta y que el `request_id` de los logs (Sección 2.6) |
| `details` | Solo en el 422: lista de `{"loc": [...], "type": "..."}`. Indica qué campo falló y por qué tipo de regla, **nunca el valor recibido**. Limitación: si el cliente envía una clave que no existe en el esquema (un campo extra, o la clave de un diccionario), `loc` repite ese **nombre de clave** tal como lo envió. Solo vuelve al propio cliente y no se registra en los logs |

| Estado | `code` | Origen |
| --- | --- | --- |
| 404 | `not_found` | Ruta inexistente |
| 405 | `method_not_allowed` | Método no admitido por la ruta |
| 422 | `validation_error` | La petición no cumple su esquema Pydantic. En `/predict`, también un valor fisiológicamente imposible (Sección 3.2) |
| 503 | `database_unavailable` | `/health/ready`: la base no responde dentro de los tiempos configurados (Sección 3.4) |
| 503 | `schema_outdated` | `/health/ready`: la base responde, pero sus migraciones no son las que espera el código, de menos o de más (Sección 3.4) |
| 500 | `internal_error` | Excepción no controlada. La traza se registra en el log del servidor sin el mensaje de la excepción; al cliente solo le llega este cuerpo |
| Otros 4xx | `http_error` | Cualquier otro `HTTPException` |

Las respuestas correctas **no** se envuelven: esta sección solo fija la forma
de los errores. Los errores tampoco llevan versiones del modelo ni del esquema
de conversión: un rechazo no ha convertido ni predicho nada, y ambas versiones
se consultan en `/api/v1/prediction/schema`.

Una excepción: el rechazo de un preflight CORS desde un origen no permitido
lo emite `CORSMiddleware` como texto plano con estado 400, antes de llegar a la
aplicación. El navegador no expone ese cuerpo al código del frontend.

### 2.6 CORS, correlación y documentación interactiva

- **CORS.** Solo los orígenes de `GYNFEM_CORS_ORIGINS`, devueltos uno a uno,
  nunca `*` (`docs/SECURITY.md`, Sección 2). Métodos `GET` y `POST`; cabeceras
  `Authorization`, `Content-Type` y `X-Request-ID`; sin credenciales, porque
  el JWT de la Fase 11 viaja en `Authorization` y no en cookies.
- **`X-Request-ID`.** Toda respuesta de la aplicación lo lleva y el frontend
  puede leerlo (`Access-Control-Expose-Headers`). Las respuestas a un
  preflight CORS no lo llevan: las emite `CORSMiddleware` antes de llegar a la
  aplicación. Si la petición trae uno de 1 a 64 caracteres `[A-Za-z0-9-]`, se
  respeta. Si no, se genera un UUID4. Como lo elige el cliente y acaba en los
  logs, el frontend debe enviar un identificador aleatorio (UUID), nunca uno
  derivado de datos del paciente.
- **Documentación interactiva.** `/api/v1/docs` y `/api/v1/openapi.json` en
  `development` y `test`. En `production` no existen (404).

## 3. Endpoints implementados

### 3.1 `GET /api/v1/health`

Comprueba que la propia aplicación responde (liveness). **No consulta
dependencias externas**: Render lo usará (Fase 12) para decidir si reinicia la
instancia, y reiniciar no arregla la caída de un servicio externo. Desde la
Fase 8 el modelo se carga y se valida al arrancar, y si su contrato no se
verifica la aplicación no arranca: «responde» implica «el modelo está
cargado». La comprobación de la base de datos está en un endpoint aparte,
`/api/v1/health/ready` (Sección 3.4), fuera del health check de Render.

Respuesta `200`:

```json
{"status": "ok", "version": "0.3.0", "timestamp": "2026-09-25T12:00:00.000000Z"}
```

| Campo | Contenido |
| --- | --- |
| `status` | Siempre `"ok"`: si la aplicación no está sana, no responde |
| `version` | Versión de la aplicación, de `app/__init__.py` (`__version__`), única fuente. Se sube en cada PR que cambie la API. No es la versión del modelo |
| `timestamp` | Hora del servidor en UTC, ISO 8601 |

No expone versiones de Python ni de dependencias, rutas del sistema, el
entorno ni la configuración (`test_health_no_expone_informacion_interna`). Un
test comprueba que la versión del ejemplo de arriba es la de `__version__`
(`test_version_del_ejemplo_de_api_spec_coincide`).

### 3.2 `POST /api/v1/predict` (HU006, HU007)

Clasifica el riesgo gestacional a partir de las 8 variables en unidad clínica.
**Sin persistencia**: la respuesta se devuelve y se descarta (Fase 10). Sin
autenticación todavía (Fase 11).

**Petición.** Un objeto JSON con exactamente estos 8 campos numéricos, los de
`ML_SPEC.md`, Sección 4: `age_years`, `temperature_c`, `heart_rate_bpm`,
`systolic_bp_mmhg`, `diastolic_bp_mmhg`, `bmi_kg_m2`, `hba1c_percent`,
`fasting_glucose_mg_dl`. Se admiten enteros y decimales.

**Validación (nivel a, 422 sin predecir).** Esquema estricto
(`app/schemas/prediction.py`):

| Regla | `type` en `details` |
| --- | --- |
| Valor por debajo de su límite fisiológico | `greater_than_equal` |
| Valor por encima de su límite fisiológico | `less_than_equal` |
| Diastólica mayor o igual que la sistólica (`loc` es `["body"]`) | `diastolic_not_below_systolic` |
| Falta un campo | `missing` |
| Campo que no es una de las 8 variables | `extra_forbidden` |
| Texto, booleano o nulo en lugar de un número | `float_type` |
| `NaN` o infinito | `finite_number` |

Los límites son los de `ML_SPEC.md`, Sección 5.1, y se publican en la
Sección 3.3. El 422 dice qué campo falla y por qué regla, nunca el valor.

**Respuesta `200`.**

| Campo | Contenido |
| --- | --- |
| `risk_level` | `high`, `mid` o `low`: la clase con mayor probabilidad (`ML_SPEC.md`, Sección 5.3) |
| `probabilities` | Objeto `{high, mid, low}` con la probabilidad de cada clase. Suma 1. Asignadas **por nombre** de clase, nunca por posición. Sin redondear |
| `extrapolation_warnings` | Un aviso por variable fuera del rango de entrenamiento (nivel b), en el orden del contrato del modelo; lista vacía si no hay ninguna. Cada aviso: `field`, `direction` (`below`/`above`), `unit`, `training_min` y `training_max` en unidad clínica, y `message` |
| `clinical_disclaimer` | Advertencia clínica obligatoria (HU007). Siempre presente. Texto único en `CLINICAL_DISCLAIMER` (`app/services/prediction.py`) |
| `input` | Las 8 variables recibidas, en unidad clínica |
| `model_input` | El vector que entró al modelo, en unidades del dataset y en el orden del contrato (`ML_SPEC.md`, Sección 9.6) |
| `model_version` | `model_metadata.json → model_version` |
| `conversion_schema_version` | `CONVERSION_SCHEMA_VERSION` (`ML_SPEC.md`, Sección 4) |
| `predicted_at` | Hora de la predicción, UTC, ISO 8601 |

`input`, `model_input`, `model_version` y `conversion_schema_version` son los
cuatro elementos de trazabilidad de `ML_SPEC.md`, Sección 6: la Fase 10 los
guardará tal cual, sin cambiar esta respuesta. La misma entrada produce
siempre la misma respuesta, salvo `predicted_at`.

El aviso no gradúa el alejamiento: para el modelo, cualquier valor más allá de
un extremo equivale al extremo (`ML_SPEC.md`, Sección 5.3, decisión C). No hay
umbral de «resultado no concluyente» (decisión D).

**Ejemplos reales** (servidor local, modelo `1.0.0`, 2026-09-25).

*Dentro del rango: 200 sin avisos.*

```json
{"age_years": 28, "temperature_c": 36.8, "heart_rate_bpm": 80, "systolic_bp_mmhg": 118,
 "diastolic_bp_mmhg": 76, "bmi_kg_m2": 22.5, "hba1c_percent": 5.2, "fasting_glucose_mg_dl": 85}
```

```json
{
  "risk_level": "mid",
  "probabilities": {"high": 0.255, "mid": 0.695, "low": 0.05},
  "extrapolation_warnings": [],
  "clinical_disclaimer": "Herramienta de apoyo a la decisión clínica. No es un diagnóstico y no sustituye el criterio del profesional de salud.",
  "input": {"age_years": 28.0, "temperature_c": 36.8, "heart_rate_bpm": 80.0, "systolic_bp_mmhg": 118.0,
            "diastolic_bp_mmhg": 76.0, "bmi_kg_m2": 22.5, "hba1c_percent": 5.2, "fasting_glucose_mg_dl": 85.0},
  "model_input": {"age_years": 28.0, "temperature_f": 98.24, "heart_rate_bpm": 80.0, "systolic_bp_mmhg": 118.0,
                  "diastolic_bp_mmhg": 76.0, "bmi_kg_m2": 22.5, "hba1c_mmol_mol": 33.311592000000005,
                  "fasting_glucose_mmol_l": 4.722222222222222},
  "model_version": "1.0.0",
  "conversion_schema_version": "1.0.0",
  "predicted_at": "2026-09-25T06:56:46.545140Z"
}
```

*IMC 32 y HbA1c 7.2 %: 200 con dos avisos.*

```json
{"age_years": 34, "temperature_c": 37.0, "heart_rate_bpm": 88, "systolic_bp_mmhg": 132,
 "diastolic_bp_mmhg": 86, "bmi_kg_m2": 32.0, "hba1c_percent": 7.2, "fasting_glucose_mg_dl": 110}
```

```json
{
  "risk_level": "high",
  "probabilities": {"high": 0.715, "mid": 0.28, "low": 0.005},
  "extrapolation_warnings": [
    {"field": "bmi_kg_m2", "direction": "above", "unit": "kg/m²", "training_min": 14.9, "training_max": 27.9,
     "message": "Valor por encima del rango de entrenamiento. Para el modelo, cualquier valor por encima del máximo equivale al máximo: la predicción no refleja cuánto se aleja."},
    {"field": "hba1c_percent", "direction": "above", "unit": "%", "training_min": 4.896990392533626, "training_max": 6.726983987556044,
     "message": "Valor por encima del rango de entrenamiento. Para el modelo, cualquier valor por encima del máximo equivale al máximo: la predicción no refleja cuánto se aleja."}
  ],
  "clinical_disclaimer": "Herramienta de apoyo a la decisión clínica. No es un diagnóstico y no sustituye el criterio del profesional de salud.",
  "input": {"age_years": 34.0, "temperature_c": 37.0, "heart_rate_bpm": 88.0, "systolic_bp_mmhg": 132.0,
            "diastolic_bp_mmhg": 86.0, "bmi_kg_m2": 32.0, "hba1c_percent": 7.2, "fasting_glucose_mg_dl": 110.0},
  "model_input": {"age_years": 34.0, "temperature_f": 98.6, "heart_rate_bpm": 88.0, "systolic_bp_mmhg": 132.0,
                  "diastolic_bp_mmhg": 86.0, "bmi_kg_m2": 32.0, "hba1c_mmol_mol": 55.169592,
                  "fasting_glucose_mmol_l": 6.111111111111111},
  "model_version": "1.0.0",
  "conversion_schema_version": "1.0.0",
  "predicted_at": "2026-09-25T06:56:46.833588Z"
}
```

*Temperatura escrita en °F dentro del campo en °C: 422, sin predecir.*

```json
{"age_years": 30, "temperature_c": 98.6, "heart_rate_bpm": 80, "systolic_bp_mmhg": 120,
 "diastolic_bp_mmhg": 80, "bmi_kg_m2": 23.0, "hba1c_percent": 5.4, "fasting_glucose_mg_dl": 90}
```

```json
{"error": {"code": "validation_error", "message": "La solicitud no es válida.",
           "request_id": "cf61a9b4-eb3b-4aa5-97dd-0582f8ea892c",
           "details": [{"loc": ["body", "temperature_c"], "type": "less_than_equal"}]}}
```

**Log.** Una línea `gynfem.prediction` por predicción, con `request_id`,
`duration_ms`, `risk_level` y `warning_count`. Nunca un valor clínico ni el
vector (`docs/SECURITY.md`, Sección 2).

Tests: `tests/api/test_api_prediction.py`, `tests/api/test_prediction_service.py`.

### 3.3 `GET /api/v1/prediction/schema`

Publica, por variable y en el orden del contrato, todo lo que el frontend
necesita para construir sus notas y validaciones sin codificar ningún número
(Sección 2.4). Sale de las mismas fuentes que usa la validación.

```json
{
  "model_version": "1.0.0",
  "conversion_schema_version": "1.0.0",
  "fields": [
    {
      "name": "temperature_c",
      "unit": "°C",
      "model_feature": "temperature_f",
      "model_unit": "°F",
      "physiological_limits": {"min": 30.0, "max": 43.0, "status": "provisional",
                               "rationale": "Provisional, pendiente de validación clínica con GynFem. Contiene el rango de entrenamiento; rechaza una temperatura escrita en °F."},
      "training_range": {"min": 33.888888888888886, "max": 40.0},
      "training_range_model_units": {"min": 93.0, "max": 104.0}
    }
  ]
}
```

(Se muestra una de las 8 entradas de `fields`.)

| Campo de cada entrada | Contenido |
| --- | --- |
| `name`, `unit` | Campo de entrada y su unidad clínica |
| `model_feature`, `model_unit` | Feature del dataset a la que se convierte, y su unidad |
| `physiological_limits` | Nivel a: `min`, `max` (inclusivos), `status` (`provisional` o `validated`) y `rationale`. Fuente: `app/services/clinical_limits.py` |
| `training_range` | Nivel b en **unidad clínica**: los extremos de `feature_ranges.json` convertidos, sin redondear. Son exactamente los que aplica `/predict` |
| `training_range_model_units` | Los mismos extremos tal como están en `feature_ranges.json` |

Los números sin redondear (por ejemplo, 33.888888888888886 °C) son deliberados:
cómo mostrarlos es decisión del frontend, pero debe comparar contra estos
valores exactos.

### 3.4 `GET /api/v1/health/ready`

Comprueba que la aplicación puede usar la base de datos (readiness). Sirve para
diagnóstico y monitorización, **no** para que Render decida si reinicia la
instancia (Sección 3.1). Está lista si se cumplen las dos condiciones:

1. la base responde dentro de `GYNFEM_DB_POOL_TIMEOUT_S` y de
   `GYNFEM_DB_STATEMENT_TIMEOUT_MS` (`docs/DEPLOYMENT.md`, Sección 5.1);
2. tiene aplicadas **exactamente** las migraciones de `migrations/` que conoce
   el código, ni una menos ni una más. Durante un despliegue que migra antes
   de cambiar el código, la versión anterior responde `schema_outdated` hasta
   que la sustituye la nueva: es esperable, y por eso el mensaje dice «no
   coincide» y no «está atrasada».

Los tiempos acotan cada fase de la comprobación: `GYNFEM_DB_CONNECT_TIMEOUT_S`
al conectar, `GYNFEM_DB_POOL_TIMEOUT_S` al esperar una conexión libre y
`GYNFEM_DB_STATEMENT_TIMEOUT_MS` en el servidor. Si la conexión ya abierta
pierde a su peer, la cortan los keepalives TCP y `tcp_user_timeout`, y el pool
comprueba cada conexión antes de entregarla (`app/db/pool.py`). Cada llamada
usa una conexión del pool: el endpoint no está autenticado ni limitado, y la
limitación de tasa es PENDIENTE (`docs/SECURITY.md`, Sección 3).

Respuesta `200`:

```json
{"status": "ready", "checks": {"database": "ok", "schema": "ok"}}
```

Respuesta `503`, con el formato de error uniforme (Sección 2.5):

```json
{"error": {"code": "database_unavailable", "message": "La base de datos no está disponible.", "request_id": "…"}}
```

```json
{"error": {"code": "schema_outdated", "message": "El esquema de la base de datos no coincide con el que espera la aplicación.", "request_id": "…"}}
```

No expone el host, el puerto, el usuario, el nombre de la base, el número de
migraciones, ni el tipo o el mensaje de la excepción
(`test_ready_no_expone_detalles_de_conexion`, `test_ready_200_no_expone_la_base`).
Un fallo se registra en el log con su tipo, nunca con su mensaje
(`docs/SECURITY.md`, Sección 2).

Tests: `tests/database/test_api_health_ready.py`.

## 4. Grupos de endpoints por fase

La definición endpoint por endpoint —ruta, método, cuerpo, respuesta y
errores— se documentará en cada fase.

| Grupo | Fase | HU |
| --- | --- | --- |
| Esqueleto: prefijo `/api/v1`, formato de error y `/health` | **Construido** (Fase 7, PR #6) | — |
| Predicción sin persistencia y esquema de campos y rangos | **Construido** (Fase 8, PR #7) | HU006, HU007 |
| Readiness de la base de datos (`/health/ready`) | **Construido** (Fase 9, PR #8) | — |
| Pacientes, variables clínicas y evaluaciones persistidas | PENDIENTE (Fase 10) | HU003, HU004, HU005 |
| Autenticación y gestión de usuarios y roles | PENDIENTE (Fase 11) | HU001, HU002 |
| Historial, reportes, métricas ML y configuración | PENDIENTE (Fase 16) | HU008, HU009, HU010, HU011 |

## 5. Obligaciones que fija ML_SPEC sobre la respuesta de predicción

No son decisiones de este documento. Cómo las cumple la Fase 8:

- El orden de las probabilidades del modelo es `["high risk", "low risk",
  "mid risk"]`, **no** el de severidad (`ML_SPEC.md`, Sección 9.6).
  **Cumplida:** `probabilities` es un objeto con claves, asignado por nombre de
  clase (Sección 3.2).
- Cada predicción queda asociada a la versión del modelo y del esquema de
  conversión que la produjeron (`ML_SPEC.md`, Sección 6). **Cumplida:** ambas
  viajan en cada respuesta correcta, junto con `input` y `model_input`.
- El ajuste del umbral de decisión sobre `predict_proba` ante la asimetría de
  coste clínico sigue **PENDIENTE (fase por confirmar)** (`ML_SPEC.md`,
  Sección 5.3, decisión D).
