# API_SPEC — Contrato de la API

- **Alcance de este documento:** los principios aprobados del contrato HTTP y
  qué fase aporta cada grupo de endpoints. Los nombres, unidades, conversiones
  y rangos de las variables pertenecen a `docs/ML_SPEC.md` (Secciones 4, 5 y
  9.6); este documento los referencia y no los copia. Los controles de acceso
  están en `docs/SECURITY.md`.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  en la Fase 7 (esqueleto de la API), PR #6, en la Fase 8 (predicción sin
  persistencia), PR #7, en la Fase 9 (base de datos), PR #8, en la Fase 10
  (persistencia clínica), PR #9, en la Fase 11 (autenticación y
  autorización), PR #10, y en la Fase 16 (administración: historial, reportes,
  métricas del modelo, configuración y auditoría), PR #16.
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
- `GET /api/v1/health/ready` (Sección 3.4), desde la Fase 9 (PR #8);
- la persistencia clínica, desde la Fase 10 (PR #9): pacientes, mediciones con
  predicción persistida, correcciones y consulta de predicciones (Sección 3.5);
- la autenticación con Supabase Auth, el RBAC sobre todas las rutas, `GET /me`
  y la gestión de usuarios y roles, desde la Fase 11 (PR #10) (Sección 3.6);
- la administración, desde la Fase 16 (PR #16): historial de evaluaciones,
  reporte, métricas del modelo, configuración de parámetros y consulta de la
  auditoría (Sección 3.7).

**Este documento es el contrato con el frontend.** No existe un documento de
contrato aparte: lo que `gynfem-frontend` necesita de cada endpoint —roles,
parámetros, respuesta y errores— está aquí, y los avisos específicos para el
frontend de la Fase 16, en la Sección 3.7.6.

**Toda ruta exige un JWT de Supabase Auth y un rol**, salvo `/health` y la
documentación interactiva de desarrollo. La matriz rol × endpoint completa está
en la Sección 3.6. Lo que aún no tiene código se sigue marcando como PENDIENTE.

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
| 503 | `database_unavailable` | `/health/ready`: la base no responde dentro de los tiempos configurados (Sección 3.4). Desde la Fase 10, también una operación clínica que no puede conectar con la base |
| 401 | `not_authenticated` | Sin `Authorization: Bearer …` o con otro esquema. Con `WWW-Authenticate: Bearer` (Sección 3.6) |
| 401 | `invalid_token` | Token mal firmado, de otro emisor o audiencia, sin un claim obligatorio, o con `alg` distinto de ES256 |
| 401 | `token_expired` | Token caducado: el frontend refresca la sesión y reintenta |
| 403 | `forbidden` | Usuario autenticado sin el rol que exige la ruta. No dice si el recurso existe |
| 403 | `account_disabled` | Usuario desactivado o sin perfil, aunque su token sea válido |
| 503 | `auth_unavailable` | Supabase Auth (JWKS o Admin API) no responde |
| 404 | `patient_not_found`, `measurement_not_found`, `prediction_not_found` | El recurso no existe **o está dado de baja** (Sección 3.5) |
| 404 | `user_not_found` | El usuario no tiene perfil (Sección 3.6) |
| 409 | `patient_already_exists` | Ya hay una paciente **activa** con ese documento |
| 409 | `user_already_exists` | Ya existe una cuenta de Supabase Auth con ese correo |
| 409 | `last_active_admin` | La operación dejaría el sistema sin un administrador activo |
| 422 | `weak_password` | Supabase Auth rechaza la contraseña temporal por su política |
| 422 | `user_rejected` | Supabase Auth rechaza otros datos del usuario (por ejemplo, un correo que la API admite y Supabase no) |
| 409 | `measurement_already_corrected` | La medición ya fue corregida (por una corrección anterior o simultánea): se corrige la nueva |
| 503 | `schema_outdated` | `/health/ready`: la base responde, pero sus migraciones no son las que espera el código, de menos o de más (Sección 3.4). Desde la Fase 11, también cualquier ruta protegida si falta la tabla de perfiles |
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
  nunca `*` (`docs/SECURITY.md`, Sección 2). Métodos `GET`, `POST`, `PATCH` y
  `DELETE` (los dos últimos desde la Fase 11: los usan `/patients/{id}` y
  `/users/{id}`; desde la Fase 16, también `PATCH /settings`); cabeceras `Authorization`, `Content-Type` y `X-Request-ID`;
  sin credenciales CORS, porque el JWT viaja en `Authorization` y no en cookies.
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
{"status": "ok", "version": "0.6.0", "timestamp": "2026-09-25T12:00:00.000000Z"}
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
**Sin persistencia**: la respuesta se devuelve y se descarta. Desde la Fase 11
exige un token de médico o administrador (Sección 3.6); solo lee el perfil del
usuario, sin escribir nada.

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

### 3.5 Persistencia clínica (Fase 10: HU003, HU004, HU005)

**Solo el médico** (Sección 3.6). El actor de cada escritura es el usuario del
token verificado (`get_actor`, `app/api/deps.py`), nunca un dato del cuerpo.

| Método | Ruta | HU | Recibe | Devuelve | Errores |
| --- | --- | --- | --- | --- | --- |
| POST | `/patients` | HU003 | `document_type` (`DNI`, `CE`, `PASAPORTE`), `document_number`, `given_names`, `family_names` | 201 paciente | 409 `patient_already_exists`; 422 |
| GET | `/patients/{patient_id}` | HU004 | — | 200 paciente | 404 `patient_not_found` (también si está dada de baja); 422 |
| POST | `/patients/search` | HU004 | **En el cuerpo**, nunca en la URL: `{document_type, document_number}` o `{name}`, y `limit` (1–50, por defecto 20) y `offset` | 200 página de resúmenes con el documento **enmascarado** | 422 sin criterio, con dos criterios, con nombre de menos de 3 letras o dígitos, documento con formato inválido, campo extra o paginación inválida |
| PATCH | `/patients/{patient_id}` | HU004 | Al menos un campo; tipo y número de documento juntos | 200 paciente | 404; 409; 422 |
| DELETE | `/patients/{patient_id}` | Baja lógica | — | 204 sin cuerpo | 404 (inexistente o ya dada de baja) |
| POST | `/patients/{patient_id}/measurements` | HU005 | Las 8 variables de `/predict` y `measured_at` opcional (con zona horaria, no futura) | 201 `{measurement, prediction}` | 404; 422 (sin escribir ni predecir); 503 |
| GET | `/patients/{patient_id}/measurements` | HU005 | `limit`, `offset` | 200 página de mediciones vigentes, la más reciente primero, con su `prediction_id` | 404; 422 |
| POST | `/measurements/{measurement_id}/corrections` | HU005 (actualizar) | Las 8 variables y `measured_at` opcional (por defecto, la de la original) | 201 `{measurement, prediction}` | 404; 409; 422; 503 |
| GET | `/predictions/{prediction_id}` | Predicción persistida | — | 200 con la trazabilidad completa | 404 `prediction_not_found` |

**Paciente.** Identidad mínima (`docs/ERD.md`, Sección 6): DNI de 8 dígitos
(RENIEC); CE y pasaporte de 4 a 20 caracteres alfanuméricos, **regla
provisional** pendiente de confirmar con GynFem. Nombres y apellidos: letras,
espacios, guion y apóstrofo, de 1 a 100 caracteres; se recortan los espacios y
el documento se pasa a mayúsculas. La respuesta: `id`, los cuatro campos,
`created_at` y `updated_at`. Nunca `deleted_at`, `*_by` ni `search_key`.

**Búsqueda.** `POST /patients/search`, de solo lectura: se usa `POST` para que
el criterio viaje **en el cuerpo y nunca en la URL**, donde el documento o el
nombre quedarían en proxies, CDN o el historial del navegador (hallazgo 5 de la
autorrevisión de PR #9). La ruta no declara ningún parámetro de URL, y
`GET /patients?…` no existe (405). Siempre con un criterio: no hay listado
abierto de pacientes.

```json
{"name": "perez", "limit": 20, "offset": 0}
{"document_type": "DNI", "document_number": "00000001"}
```

Por documento, coincidencia **exacta**, con el mismo formato por tipo que el
alta (un DNI de 7 dígitos da 422). Por nombre, al menos **3 letras o dígitos
contados después de normalizar** (tildes sueltas y signos no cuentan: tres
tildes combinantes quedarían en «» y coincidirían con todas), y coincidencia
por **prefijo de cualquier palabra** de nombres o apellidos, sin distinguir
mayúsculas ni tildes («perez» encuentra «Pérez»; «rez», no). `%` y `_` se
buscan literalmente. Cada
resultado lleva `document_number_masked` (`*****001`), no el documento. La
página lleva `items`, `limit`, `offset` y `has_more`, **sin el total**, que
revelaría cuántas pacientes hay. Las dadas de baja no aparecen.

**Medición y predicción en una operación (decisión B).** El nivel a de la
validación es el mismo de `/predict` (`MeasurementCreate` hereda de
`PredictionRequest`): un valor imposible da 422 sin escribir ni predecir. La
predicción se calcula **antes** de abrir la transacción, y la medición, la
predicción y la auditoría se escriben en **una** transacción: si algo falla,
no queda nada escrito. La respuesta:

```json
{"measurement": {"id": "…", "patient_id": "…", "measured_at": "2026-09-26T01:21:37.192880Z",
                 "age_years": 34.0, "temperature_c": 37.0, "heart_rate_bpm": 88.0, "systolic_bp_mmhg": 132.0,
                 "diastolic_bp_mmhg": 86.0, "bmi_kg_m2": 32.0, "hba1c_percent": 7.2, "fasting_glucose_mg_dl": 110.0},
 "prediction": {"id": "…", "risk_level": "high", "probabilities": {"high": 0.715, "mid": 0.28, "low": 0.005},
                "extrapolation_warnings": [{"field": "bmi_kg_m2", "direction": "above", "…": "…"},
                                           {"field": "hba1c_percent", "direction": "above", "…": "…"}],
                "clinical_disclaimer": "Herramienta de apoyo a la decisión clínica. …",
                "model_version": "1.0.0", "conversion_schema_version": "1.0.0",
                "predicted_at": "2026-09-26T01:21:37.045038Z"}}
```

(Respuesta real contra la Supabase real, con datos sintéticos; se abrevian los
avisos, que son los mismos de la Sección 3.2.) Misma entrada, misma predicción
que `/predict`. La respuesta no lleva `input` ni `model_input`: los da
`GET /predictions/{id}`, que añade `measurement_id`, `input` (unidad clínica) y
`model_input` (el vector que entró al modelo, en el orden de su contrato):

```json
"model_input": {"age_years": 34.0, "temperature_f": 98.6, "heart_rate_bpm": 88.0, "systolic_bp_mmhg": 132.0,
                "diastolic_bp_mmhg": 86.0, "bmi_kg_m2": 32.0, "hba1c_mmol_mol": 55.169592,
                "fasting_glucose_mmol_l": 6.111111111111111}
```

Es idéntico, bit a bit, al que devuelve `/predict` para la misma entrada.

**Corrección (decisión C).** Los valores de una medición no se editan. Una
corrección crea una medición nueva con su predicción nueva y da de baja la
original, en la misma transacción. La predicción original se conserva intacta
y sigue consultable. Una medición se corrige una sola vez: corregirla otra vez
da 409 `measurement_already_corrected`, y para volver a corregir se corrige la
nueva.

**Baja lógica.** `DELETE /patients/{id}` no borra nada: la paciente deja de
aparecer en búsquedas y consultas —también `GET /predictions/{id}` de sus
predicciones da 404—, y sus mediciones y predicciones se conservan. La baja no se deshace (`docs/ERD.md`, Sección 6). Su documento se
puede volver a registrar.

**Auditoría.** Cada escritura añade su registro en la misma transacción:
`patient.create`, `patient.update` (con `changed_fields`, solo nombres),
`patient.deactivate`, `clinical_measurement.create`,
`clinical_measurement.correct`, `clinical_measurement.deactivate` (la baja de
la original al corregirla) y `prediction.create`. Las lecturas no se auditan
en esta fase.

**Nombres en Unicode.** Nombres y apellidos se normalizan a NFC: «José» escrito
con una tilde combinante se guarda igual que «José».

**Logs.** Una línea `gynfem.clinical` por escritura, con solo `action` y
`duration_ms`; el log de acceso registra la plantilla de la ruta. Nunca un id,
nombre, documento ni valor clínico.

**`/predict` no cambia**: sin paciente, sin estado y sin escribir en la base
(`test_predict_sin_paciente_sigue_igual_y_no_escribe`). Desde la Fase 11 solo lee
el perfil del usuario para autorizar (decisión 8;
`test_predict_solo_lee_el_perfil_del_usuario`).

Tests: `tests/database/test_api_patients.py`, `test_api_measurements.py` y
`test_api_clinical_transversal.py`.

### 3.6 Autenticación y autorización (Fase 11: HU001, HU002)

Supabase Auth autentica y emite el JWT; la API **solo lo verifica** y resuelve
el rol y el estado del usuario en la base en **cada** petición
(`docs/SECURITY.md`, Sección 3.1). Toda ruta protegida exige
`Authorization: Bearer <access token de Supabase>`.

**Matriz rol × endpoint.** Es la fuente de verdad del acceso:
`tests/api/test_auth_rbac.py` la lee de este documento y la compara con la
lista real de rutas de la aplicación; una ruta sin decisión, o distinta de esta
tabla, hace fallar la suite. ✔ = permitido; 401 = sin token o token inválido;
403 = rol insuficiente. Un usuario desactivado o sin perfil recibe 403
`account_disabled` en toda ruta protegida.

<!-- matriz-rbac:inicio -->
| Método | Ruta | Anónimo | Médico | Administrador | Decisión |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/v1/health` | ✔ | ✔ | ✔ | **Pública** (excepción aprobada): liveness de Render; solo estado, versión y hora |
| `GET` | `/api/v1/health/ready` | 401 | 403 | ✔ | Diagnóstico de operación: consume una conexión del pool y revela el estado del esquema |
| `POST` | `/api/v1/predict` | 401 | ✔ | ✔ | Recibe datos clínicos y no hay limitación de tasa. Sin paciente ni escritura. En la sustentación se demuestra con una cuenta de médico |
| `GET` | `/api/v1/prediction/schema` | 401 | ✔ | ✔ | Sin secretos, pero su único consumidor es el formulario autenticado: cerrado por defecto |
| `GET` | `/api/v1/model/metrics` | 401 | ✔ | ✔ | HU010: métricas del modelo con sus limitaciones. Sin datos de pacientes; el médico necesita saber cuánto falla el modelo |
| `POST` | `/api/v1/patients` | 401 | ✔ | 403 | HU003. El administrador no ve datos clínicos |
| `POST` | `/api/v1/patients/search` | 401 | ✔ | 403 | HU004 |
| `GET` | `/api/v1/patients/{patient_id}` | 401 | ✔ | 403 | HU004 |
| `PATCH` | `/api/v1/patients/{patient_id}` | 401 | ✔ | 403 | HU004 |
| `DELETE` | `/api/v1/patients/{patient_id}` | 401 | ✔ | 403 | Baja lógica |
| `POST` | `/api/v1/patients/{patient_id}/measurements` | 401 | ✔ | 403 | HU005 |
| `GET` | `/api/v1/patients/{patient_id}/measurements` | 401 | ✔ | 403 | HU005 |
| `GET` | `/api/v1/patients/{patient_id}/evaluations` | 401 | ✔ | 403 | HU008: historial de evaluaciones. Clínico: el administrador no lo ve |
| `POST` | `/api/v1/measurements/{measurement_id}/corrections` | 401 | ✔ | 403 | HU005 |
| `GET` | `/api/v1/predictions/{prediction_id}` | 401 | ✔ | 403 | Predicción persistida |
| `POST` | `/api/v1/predictions/{prediction_id}/report` | 401 | ✔ | 403 | HU009: reporte de una evaluación. `POST` porque cada generación se audita (`prediction.report`): salen datos personales |
| `GET` | `/api/v1/me` | 401 | ✔ | ✔ | HU001: id y rol del usuario del token |
| `POST` | `/api/v1/users` | 401 | 403 | ✔ | HU002: crear |
| `GET` | `/api/v1/users` | 401 | 403 | ✔ | HU002: consultar |
| `GET` | `/api/v1/users/{user_id}` | 401 | 403 | ✔ | HU002: consultar |
| `PATCH` | `/api/v1/users/{user_id}` | 401 | 403 | ✔ | HU002: modificar el nombre y asignar el rol |
| `POST` | `/api/v1/users/{user_id}/deactivate` | 401 | 403 | ✔ | HU002: desactivar |
| `POST` | `/api/v1/users/{user_id}/activate` | 401 | 403 | ✔ | HU002: activar |
| `GET` | `/api/v1/settings` | 401 | 403 | ✔ | HU011: consultar los parámetros. Ninguno es clínico |
| `PATCH` | `/api/v1/settings` | 401 | 403 | ✔ | HU011: cambiar parámetros; cada cambio queda auditado |
| `GET` | `/api/v1/audit-log` | 401 | 403 | ✔ | Consulta de la auditoría, solo lectura. Sin datos clínicos: acciones e ids opacos que el administrador no puede resolver |
| `GET` | `/api/v1/openapi.json` | ✔ | ✔ | ✔ | **Pública solo en development y test**: el contrato, sin datos. No existe en production |
| `GET` | `/api/v1/docs` | ✔ | ✔ | ✔ | Igual que la anterior |
<!-- matriz-rbac:fin -->

**Verificación del token** (`app/auth/tokens.py`; `docs/SECURITY.md` §2.3):
firma ES256 contra el JWKS de `GYNFEM_SUPABASE_URL`; `exp`, `iat`, `sub`,
`iss` y `aud` obligatorios; `iss` = `{URL}/auth/v1`; `aud` = `authenticated`;
30 s de tolerancia de reloj. El rol **nunca** sale del token.

**Orden.** Se autoriza antes de validar el cuerpo contra su esquema y de
consultar el recurso: sin token, un JSON válido con campos incorrectos da 401 y
no 422, y un 401 o 403 es idéntico exista o no el recurso. **Límite:** FastAPI
parsea el JSON antes de resolver las dependencias, así que un cuerpo que no es
JSON válido da 422 `json_invalid` también sin token; no revela el esquema ni si
el recurso existe (`test_json_malformado_sin_token_da_422_sin_revelar_nada`).

**`GET /api/v1/me`** (HU001). `{"id": "…", "role": "medico"}`: el usuario del
token y su rol de la base. Si responde, el usuario está activo.

**Gestión de usuarios (HU002), solo el administrador.**

| Método | Ruta | Recibe | Devuelve | Errores |
| --- | --- | --- | --- | --- |
| POST | `/users` | `email`, `password` (temporal, 12–72 bytes), `full_name`, `role` (`medico` o `administrador`) | 201 usuario | 409 `user_already_exists`; 422 (también `weak_password` y `user_rejected`); 503 `auth_unavailable` |
| GET | `/users` | `limit` (1–50, por defecto 20), `offset` | 200 página, sin total | 422 |
| GET | `/users/{user_id}` | — | 200 usuario | 404 `user_not_found` |
| PATCH | `/users/{user_id}` | `full_name` y/o `role`; nada más | 200 usuario | 404; 409 `last_active_admin`; 422 |
| POST | `/users/{user_id}/deactivate` | — | 200 usuario | 404; 409 `last_active_admin` |
| POST | `/users/{user_id}/activate` | — | 200 usuario | 404 |

Un usuario: `id`, `email`, `full_name`, `role`, `is_active`, `created_at`,
`updated_at`. Nunca la contraseña. El correo se lee de `auth.users` (su única
fuente) y el backend lo guarda en minúsculas.

- **Crear.** La cuenta la crea la Admin API de Supabase Auth, ya confirmada
  (el registro público está cerrado). Después, en una transacción, el perfil y
  la auditoría `user.create`. Si esa transacción falla, se borra la cuenta en
  Supabase y se responde 503.
- **Activar y desactivar** rigen desde la petición siguiente del usuario
  afectado, aunque conserve un token válido. Nada se borra.
- **Último administrador.** Desactivar o degradar al único administrador activo
  da 409 `last_active_admin`.
- **Auditoría.** `user.create`, `user.update` (con `changed_fields`, solo
  nombres), `user.activate`, `user.deactivate` y `user.bootstrap_admin` (el
  primer administrador, creado por línea de comandos: `docs/DEPLOYMENT.md`).

Tests: `tests/api/test_auth_tokens.py`, `test_auth_rbac.py`,
`test_auth_logging.py`, `test_supabase_admin.py`;
`tests/database/test_api_users.py`, `test_auth_flujo.py`, `test_auth_schema.py`
y `test_bootstrap_admin.py`.

### 3.7 Administración (Fase 16: HU008, HU009, HU010, HU011 y consulta de auditoría)

Seis rutas. Todas exigen token; sin él, 401 `not_authenticated`, y con un rol
que no es el de la ruta, 403 `forbidden`, en ambos casos **exista o no el
recurso** (Sección 3.6). Los ejemplos son respuestas reales de la aplicación
contra una base de pruebas con datos sintéticos (2026-10-01); los cuerpos de
error llevan siempre el formato de la Sección 2.5.

| Método | Ruta | HU | Roles | Recibe | Devuelve | Errores propios |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/patients/{patient_id}/evaluations` | HU008 | médico | `limit` (1–50; si se omite, el parámetro `history_default_page_size`), `offset` | 200 página de evaluaciones con `clinical_disclaimer`, sin total | 404 `patient_not_found`; 422 |
| POST | `/predictions/{prediction_id}/report` | HU009 | médico | Sin cuerpo | 200 reporte, con `Cache-Control: no-store` | 404 `prediction_not_found`; 422 |
| GET | `/model/metrics` | HU010 | médico y administrador | Nada: no admite parámetros | 200 métricas, rangos, detalle y limitaciones | — |
| GET | `/settings` | HU011 | administrador | — | 200 los parámetros | — |
| PATCH | `/settings` | HU011 | administrador | Uno o más parámetros | 200 los parámetros | 422 |
| GET | `/audit-log` | Auditoría | administrador | `limit` (1–50, por defecto 20), `offset` y filtros | 200 página, con `Cache-Control: no-store`, sin total | 422; 405 en `POST`, `PUT`, `PATCH` y `DELETE` |

Además, cualquiera puede responder 503 `database_unavailable`, salvo
`/model/metrics`, que no consulta más base que la del perfil del usuario.

#### 3.7.1 `GET /patients/{patient_id}/evaluations` (HU008)

Las evaluaciones de una paciente —cada una, una medición con su predicción—, de
la medición **más reciente a la más antigua**. Orden estable: `measured_at`
descendente, después la registrada más tarde y, a igualdad, el id, de modo que
la paginación no repite ni pierde filas aunque las horas coincidan.

- **Incluye las evaluaciones corregidas**, con `status: "corrected"`: el médico
  pudo decidir con ellas y su predicción se conserva intacta (Sección 3.5). Las
  vigentes llevan `status: "current"`.
- `limit`: si el cliente lo omite, rige el parámetro `history_default_page_size`
  (Sección 3.7.4); la respuesta devuelve en `limit` el que se aplicó.
- Una paciente inexistente y una dada de baja responden **el mismo 404**.
- Solo lectura: no escribe nada ni se audita.

```json
{
  "items": [
    {
      "measurement": {"id": "43a5695c-1b6d-43b7-a311-0b750b7d5540", "patient_id": "384386f6-196b-4a73-ac96-79eecf62268e",
                      "measured_at": "2026-10-01T15:00:00Z", "age_years": 34.0, "temperature_c": 37.0,
                      "heart_rate_bpm": 88.0, "systolic_bp_mmhg": 132.0, "diastolic_bp_mmhg": 86.0,
                      "bmi_kg_m2": 32.0, "hba1c_percent": 7.2, "fasting_glucose_mg_dl": 110.0},
      "prediction": {"id": "594baa6c-8aa8-468f-b805-dce0a3be0f5e", "risk_level": "high",
                     "probabilities": {"high": 0.715, "mid": 0.28, "low": 0.005},
                     "extrapolation_warnings": [{"field": "bmi_kg_m2", "direction": "above", "…": "…"},
                                                {"field": "hba1c_percent", "direction": "above", "…": "…"}],
                     "model_version": "1.0.0", "conversion_schema_version": "1.0.0",
                     "predicted_at": "2026-10-02T00:10:47.056192Z"},
      "status": "current"
    },
    {
      "measurement": {"id": "b880b321-2fef-4e35-a597-d31e4592ec7b", "patient_id": "384386f6-196b-4a73-ac96-79eecf62268e",
                      "measured_at": "2026-09-30T15:00:00Z", "age_years": 28.0, "temperature_c": 36.8,
                      "heart_rate_bpm": 82.0, "systolic_bp_mmhg": 118.0, "diastolic_bp_mmhg": 76.0,
                      "bmi_kg_m2": 22.5, "hba1c_percent": 5.2, "fasting_glucose_mg_dl": 85.0},
      "prediction": {"id": "734e5d55-6bb4-40f0-a491-7414a05ac81b", "risk_level": "mid",
                     "probabilities": {"high": 0.245, "mid": 0.705, "low": 0.05}, "extrapolation_warnings": [],
                     "model_version": "1.0.0", "conversion_schema_version": "1.0.0",
                     "predicted_at": "2026-10-02T00:10:47.069468Z"},
      "status": "current"
    }
  ],
  "limit": 2,
  "offset": 0,
  "has_more": true,
  "clinical_disclaimer": "Herramienta de apoyo a la decisión clínica. No es un diagnóstico y no sustituye el criterio del profesional de salud."
}
```

(Petición con `limit=2` sobre una paciente con tres evaluaciones; se abrevian los
avisos, que son los de la Sección 3.2.)

| Campo | Contenido |
| --- | --- |
| `items[].measurement` | `id`, `patient_id`, `measured_at` y las 8 variables en unidad clínica, tal como se registraron |
| `items[].prediction` | `id`, `risk_level`, `probabilities`, `extrapolation_warnings`, `model_version`, `conversion_schema_version` y `predicted_at`, tal como se guardaron. Sin `input` ni `model_input`: los da `GET /predictions/{id}` |
| `items[].status` | `current` o `corrected` |
| `limit`, `offset`, `has_more` | Paginación, **sin el total** |
| `clinical_disclaimer` | La advertencia clínica obligatoria, **una vez** en la página, no en cada ítem |

Errores:

```json
{"error": {"code": "patient_not_found", "message": "Paciente no encontrada.", "request_id": "167adcab-…"}}
{"error": {"code": "forbidden", "message": "No tiene permiso para esta operación.", "request_id": "b371f64a-…"}}
{"error": {"code": "validation_error", "message": "La solicitud no es válida.", "request_id": "0e27a6b0-…",
           "details": [{"loc": ["query", "limit"], "type": "less_than_equal"}]}}
```

Tests: `tests/database/test_api_history.py`.

#### 3.7.2 `POST /predictions/{prediction_id}/report` (HU009)

El reporte de **una evaluación**: los datos de la paciente, la medición, el
resultado y la advertencia clínica. **Datos estructurados**: el frontend compone
la vista de impresión y el médico la archiva o entrega con «Imprimir → Guardar
como PDF» (decisión A de la Fase 16; el backend no genera PDF).

- **No inventa ni recalcula nada**: todo sale de lo ya almacenado. El modelo no
  se invoca.
- **Por qué es `POST` aunque no cree nada clínico.** Cada generación escribe un
  registro de auditoría (`prediction.report`), en la misma transacción que la
  lectura: es el punto en que datos personales salen del sistema. Un `GET` debe
  ser seguro —sin efectos— y un navegador o un proxy puede repetirlo,
  precargarlo o guardarlo en caché. Si la auditoría falla, no hay reporte (500).
  `GET` sobre esta ruta da 405.
- Sin cuerpo. La respuesta 200 lleva **`Cache-Control: no-store`**.
- Una predicción inexistente y la de una paciente dada de baja responden **el
  mismo 404** y no se auditan.
- El reporte de una evaluación corregida se puede generar y lleva
  `status: "corrected"`.

```json
{
  "institution_name": "GynFem",
  "generated_at": "2026-10-02T00:10:47.131416Z",
  "patient": {"id": "384386f6-196b-4a73-ac96-79eecf62268e", "document_type": "PASAPORTE",
              "document_number": "FICTICIOF16", "given_names": "Paciente Ficticia",
              "family_names": "Sintetica Fdieciseis"},
  "measurement": {"id": "b880b321-2fef-4e35-a597-d31e4592ec7b", "measured_at": "2026-09-30T15:00:00Z",
                  "age_years": 28.0, "temperature_c": 36.8, "heart_rate_bpm": 82.0, "systolic_bp_mmhg": 118.0,
                  "diastolic_bp_mmhg": 76.0, "bmi_kg_m2": 22.5, "hba1c_percent": 5.2, "fasting_glucose_mg_dl": 85.0},
  "prediction": {"id": "734e5d55-6bb4-40f0-a491-7414a05ac81b", "risk_level": "mid",
                 "probabilities": {"high": 0.245, "mid": 0.705, "low": 0.05}, "extrapolation_warnings": [],
                 "model_version": "1.0.0", "conversion_schema_version": "1.0.0",
                 "predicted_at": "2026-10-02T00:10:47.069468Z", "status": "current"},
  "clinical_disclaimer": "Herramienta de apoyo a la decisión clínica. No es un diagnóstico y no sustituye el criterio del profesional de salud."
}
```

| Campo | Contenido |
| --- | --- |
| `institution_name` | El parámetro del sistema vigente (Sección 3.7.4), leído en la misma transacción |
| `generated_at` | Hora UTC del **servidor de aplicación**, tomada tras confirmar la transacción. Puede diferir en milisegundos del `created_at` del registro de auditoría |
| `patient` | `id`, `document_type`, `document_number` **completo, sin enmascarar**, `given_names`, `family_names` |
| `measurement` | `id`, `measured_at` y las 8 variables en unidad clínica (la unidad va en el nombre del campo). Sin `patient_id` |
| `prediction` | Lo mismo que en el historial, más `status` |
| `clinical_disclaimer` | La advertencia clínica obligatoria. Siempre presente |

Error (el mismo cuerpo para la inexistente y para la de una paciente dada de baja):

```json
{"error": {"code": "prediction_not_found", "message": "Predicción no encontrada.", "request_id": "e6e93df4-…"}}
```

Log: una línea `gynfem.clinical` con `action: "prediction.report"` y la
latencia; nunca un nombre, un documento, un id ni un valor clínico.

Tests: `tests/database/test_api_reports.py`.

#### 3.7.3 `GET /model/metrics` (HU010)

Las métricas **reales** del modelo, las obtenidas en la Fase 6. Nada se
entrena, se recalcula ni se predice: la respuesta se lee de los artefactos
versionados. El contrato (qué cifra sale de qué artefacto) es de
`docs/ML_SPEC.md`, Sección 9.10; aquí, su forma.

- **Las limitaciones van siempre en la misma respuesta.** La ruta no admite
  ningún parámetro: no existe un modo de pedir solo las cifras. Una exactitud
  sin su contexto es engañosa para un usuario clínico.
- **Roles:** el médico, porque quien usa la predicción necesita saber cuánto
  falla y dónde no tiene respaldo; el administrador, porque no hay datos de
  pacientes.
- Una cifra que no exista en los artefactos **no aparece** en la respuesta (ni
  `null` ni cero).
- `detail` va `null`, con su motivo en `detail_unavailable_reason`, si el
  archivo del detalle falta (`training_metrics_missing`), no se puede leer
  (`training_metrics_invalid`) o no coincide con el metadata del modelo
  (`training_metrics_mismatch`). El resumen y las limitaciones siguen saliendo.
- La respuesta se construye **una vez, al arrancar**: cambiar un artefacto exige
  reiniciar, igual que cambiar el modelo.

```json
{
  "model": {"model_version": "1.0.0", "algorithm": "RandomForestClassifier",
            "trained_at": "2026-09-23T12:43:32Z", "variant": "clean"},
  "evaluation": {"source": "held_out_test", "dataset_rows": 6099, "training_rows": 4879,
                 "test_size": 0.2, "stratified": true},
  "metrics": {"accuracy": 0.9877049180327869, "f1_macro": 0.9877663501478118,
              "precision_macro": 0.9879121721238051, "recall_macro": 0.9877144723639596,
              "high_to_low_errors": 0},
  "training_ranges": [
    {"feature": "temperature_f", "unit": "°F", "min": 93.0, "max": 104.0,
     "clinical_field": "temperature_c", "clinical_unit": "°C",
     "clinical_min": 33.888888888888886, "clinical_max": 40.0}
  ],
  "detail": {
    "test_rows": 1220,
    "labels": ["high risk", "low risk", "mid risk"],
    "confusion_matrix": [[405, 0, 7], [1, 394, 4], [2, 1, 406]],
    "per_class": {"high risk": {"precision": 0.9926470588235294, "recall": 0.9830097087378641,
                                "f1": 0.9878048780487805, "support": 412}},
    "procedure_estimate": {
      "label": "Estimación del procedimiento (validación cruzada anidada)",
      "metric": "f1_macro", "mean": 0.9906143060396209, "std": 0.004388183845017006,
      "outer_folds": 10, "inner_folds": 5,
      "description": "Estimación del procedimiento (validación cruzada anidada): 0,991 ± 0,004 de F1 macro. Estima cómo rinde el método completo de entrenamiento al repetirlo sobre distintas particiones de los datos de entrenamiento. No es el rendimiento del modelo entregado ni el que cabe esperar con pacientes reales."
    }
  },
  "detail_unavailable_reason": null,
  "limitations": [
    {"code": "metrics_scope", "title": "Qué miden estas cifras",
     "message": "Estas métricas se calcularon una sola vez, sobre 1220 casos apartados del mismo conjunto de datos público con el que se entrenó el modelo. Indican qué tan bien reproduce el modelo las etiquetas de ese conjunto. No indican qué tan bien acierta con las pacientes de GynFem: eso no se ha medido.",
     "sources": ["models/model_metadata.json: metrics_summary.source, split.test_size",
                 "reports/ml/training_metrics.json: variants.<variante>.split.test_rows",
                 "reports/ml/training_report.md, Sección 4"]}
  ]
}
```

(Se muestra uno de los 8 rangos, una de las 3 clases de `per_class` y una de las
9 limitaciones.)

| Campo | Contenido |
| --- | --- |
| `model`, `evaluation`, `metrics` | El resumen, de `models/model_metadata.json`. `high_to_low_errors`: casos de riesgo alto clasificados como riesgo bajo, el error clínicamente grave. Sin redondear |
| `training_ranges` | Los 8 rangos de `models/feature_ranges.json`, en el orden del contrato: en unidad del dataset (`min`, `max`, `unit`) y en unidad clínica (`clinical_*`), con los mismos extremos de `/prediction/schema` |
| `detail.labels` | Orden de filas y columnas de `confusion_matrix`. **No es el de severidad**: se lee de aquí, nunca se supone |
| `detail.confusion_matrix` | Filas: clase real. Columnas: clase predicha |
| `detail.per_class` | Precisión, recall, F1 y soporte por clase |
| `detail.procedure_estimate` | La validación cruzada anidada, **rotulada como estimación del procedimiento**: no es el rendimiento del modelo. Por eso no está en `metrics` |
| `limitations` | Las 9, en este orden: `metrics_scope`, `accuracy_meaning`, `high_risk_errors`, `narrow_training_range`, `dataset_not_local`, `labels_not_verified`, `variant_selection`, `low_temperature_band`, `clinical_disclaimer`. Cada una: `code`, `title`, `message` (texto para el médico: qué significa y qué no) y `sources` (artefacto y sección de los que sale) |

En la prosa de `message` y de `description` las cifras van redondeadas y con
**coma decimal** (98,8 %); los valores exactos son los de los campos
estructurados.

Tests: `tests/api/test_api_model_metrics.py`.

#### 3.7.4 `GET /settings` y `PATCH /settings` (HU011)

Los parámetros que el administrador ajusta sin tocar código. **Ninguno es
clínico**: el catálogo es cerrado (`app/services/settings_catalog.py`) y no
incluye umbrales de riesgo, límites fisiológicos, rangos de entrenamiento ni el
texto de la advertencia clínica.

| Parámetro | Tipo y validación | Valor por defecto | Dónde se usa |
| --- | --- | --- | --- |
| `institution_name` | Texto de 1 a 100 caracteres tras normalizar a NFC y recortar espacios. Se rechazan los caracteres de control, los de formato (ancho cero, inversión de dirección) y los separadores de línea | `"GynFem"` | Encabezado del reporte (Sección 3.7.2) |
| `history_default_page_size` | Entero de 1 a 50, estricto (ni texto ni decimal ni booleano) | `20` | Tamaño de página del historial cuando el cliente omite `limit` (Sección 3.7.1) |

`GET /settings`, sin cambios guardados:

```json
{"institution_name": {"value": "GynFem", "default": "GynFem", "updated_at": null, "updated_by": null},
 "history_default_page_size": {"value": 20, "default": 20, "updated_at": null, "updated_by": null}}
```

`PATCH /settings` con `{"institution_name": "Centro de Prueba"}`:

```json
{"institution_name": {"value": "Centro de Prueba", "default": "GynFem",
                      "updated_at": "2026-10-02T00:10:47.169852Z",
                      "updated_by": "10000000-0000-4000-8000-000000000002"},
 "history_default_page_size": {"value": 20, "default": 20, "updated_at": null, "updated_by": null}}
```

- El cuerpo lleva una o las dos claves, y nada más. `updated_at` y `updated_by`
  son nulos mientras rige el valor por defecto.
- **Un cambio rige desde la petición siguiente**, en cualquier instancia y sin
  reiniciar: no hay caché.
- Cada cambio inserta una fila en `gynfem.system_settings` y un registro
  `system_setting.update` en la auditoría, **en una transacción**; en la
  auditoría va solo el nombre de la clave (`changed_fields`), nunca el valor.
- **Un valor igual al vigente no escribe nada** —ni fila ni auditoría— y
  responde **200 con el estado vigente**, el mismo cuerpo que un cambio: el
  `PATCH` es idempotente. «Vigente» incluye el valor por defecto, y la
  comparación se hace tras normalizar.

Errores, todos 422 `validation_error` **sin escribir nada**; `details` dice el
campo y el tipo de regla, nunca el valor:

| Caso | `loc` | `type` |
| --- | --- | --- |
| Cuerpo vacío | `["body"]` | `empty_update` |
| Un parámetro nulo | `["body"]` | `null_field` |
| Clave que no es del catálogo | `["body", "<clave>"]` | `extra_forbidden` |
| Página fuera de 1–50 | `["body", "history_default_page_size"]` | `greater_than_equal`, `less_than_equal` |
| Página que no es un entero | `["body", "history_default_page_size"]` | `int_type` |
| Nombre que no es texto | `["body", "institution_name"]` | `string_type` |
| Nombre vacío o de más de 100 caracteres | `["body", "institution_name"]` | `institution_name_length` |
| Nombre con un carácter de control | `["body", "institution_name"]` | `control_character` |

```json
{"error": {"code": "validation_error", "message": "La solicitud no es válida.", "request_id": "354860e4-…",
           "details": [{"loc": ["body", "institution_name"], "type": "control_character"}]}}
```

`POST`, `PUT` y `DELETE` sobre `/settings` dan 405.

Tests: `tests/database/test_api_settings.py`, `test_settings_schema.py`.

#### 3.7.5 `GET /audit-log` (consulta de auditoría)

Quién hizo qué acción, sobre qué entidad y cuándo. **Solo lectura**: la
auditoría no se crea, no se modifica y no se borra por la API (`POST`, `PUT`,
`PATCH` y `DELETE` dan 405); cada registro lo escribe la operación que audita.
Consultarla no se audita.

De lo más reciente a lo más antiguo (`created_at` descendente y, a igualdad —las
filas de una transacción comparten hora—, el orden de inserción descendente).
`limit` de 1 a 50, **20 por defecto, fijo**: no usa `history_default_page_size`.
Sin total. La respuesta 200 lleva `Cache-Control: no-store`.

| Filtro | Valor | Efecto |
| --- | --- | --- |
| `action` | `entidad.accion` (`^[a-z_]+\.[a-z_]+$`, hasta 100 caracteres) | Igualdad |
| `entity_type` | `patient`, `clinical_measurement`, `prediction`, `user` o `system_setting` | Igualdad |
| `entity_id` | UUID | Igualdad |
| `actor_user_id` | UUID | Igualdad |
| `from` | Fecha y hora **con zona horaria** | `created_at >= from` (inclusivo) |
| `to` | Fecha y hora **con zona horaria** | `created_at < to` (exclusivo) |

Los filtros se combinan (todos deben cumplirse). `from` igual a `to` es un
intervalo vacío (200 sin ítems). **`from` posterior a `to` da 422**
`date_range_inverted`: es un error de quien llama, y una página vacía lo
ocultaría. Un parámetro que no existe da 422, igual que un valor inválido.

```json
{
  "items": [
    {"created_at": "2026-10-02T00:10:47.169852Z", "actor_user_id": "10000000-0000-4000-8000-000000000002",
     "action": "system_setting.update", "entity_type": "system_setting", "entity_id": null,
     "request_id": "fbaec1f6-656f-4a3c-8d8a-dcab559dd0ae", "outcome": "success",
     "changed_fields": ["institution_name"]},
    {"created_at": "2026-10-02T00:10:47.120031Z", "actor_user_id": "10000000-0000-4000-8000-000000000001",
     "action": "prediction.report", "entity_type": "prediction",
     "entity_id": "734e5d55-6bb4-40f0-a491-7414a05ac81b",
     "request_id": "aa48e089-be02-428c-a49d-20bc781f26db", "outcome": "success", "changed_fields": null},
    {"created_at": "2026-10-02T00:10:47.070636Z", "actor_user_id": "10000000-0000-4000-8000-000000000001",
     "action": "prediction.create", "entity_type": "prediction",
     "entity_id": "734e5d55-6bb4-40f0-a491-7414a05ac81b",
     "request_id": "c83a651a-b722-48c2-b1b0-cad07e141da6", "outcome": "success", "changed_fields": null}
  ],
  "limit": 3,
  "offset": 0,
  "has_more": true
}
```

Cada ítem lleva **exactamente** esas ocho claves. Nunca el id numérico interno.

- **Sin datos clínicos en claro.** La tabla no tiene columnas donde quepan
  (`docs/SECURITY.md`): `changed_fields` son nombres de campo o de parámetro,
  nunca valores.
- **`entity_id` es opaco para el administrador**: ve el id, pero no puede
  resolverlo, porque recibe 403 en todo lo clínico (ficha, historial,
  predicción y reporte). Es nulo en el cambio de un parámetro.
- `actor_user_id` es nulo solo en la creación del primer administrador.

Acciones que existen hoy: `patient.create`, `patient.update`,
`patient.deactivate`, `clinical_measurement.create`,
`clinical_measurement.correct`, `clinical_measurement.deactivate`,
`prediction.create`, `prediction.report` (Fase 16), `user.create`,
`user.update`, `user.activate`, `user.deactivate`, `user.bootstrap_admin` y
`system_setting.update` (Fase 16).

Errores:

```json
{"error": {"code": "validation_error", "message": "La solicitud no es válida.", "request_id": "993b400d-…",
           "details": [{"loc": ["query"], "type": "date_range_inverted"}]}}
{"error": {"code": "validation_error", "message": "La solicitud no es válida.", "request_id": "d62d2cb0-…",
           "details": [{"loc": ["query", "entity_type"], "type": "literal_error"}]}}
{"error": {"code": "method_not_allowed", "message": "Método no permitido.", "request_id": "d9b2fd19-…"}}
```

Tests: `tests/database/test_api_audit_log.py`.

#### 3.7.6 Avisos para el frontend

1. **`%2B` en las zonas horarias.** En `from` y `to` de `/audit-log`, el signo
   `+` de un desplazamiento (`+00:00`) debe ir codificado como `%2B`: sin
   codificar llega como un espacio y la fecha da 422. `URLSearchParams` y
   `encodeURIComponent` lo codifican; una URL armada a mano, no. La forma `Z` y
   los desplazamientos negativos (`-05:00`) no lo necesitan.
2. **La advertencia clínica de `/model/metrics` es la limitación 9**
   (`code: "clinical_disclaimer"`), no un campo `clinical_disclaimer` en la raíz
   como en el historial y el reporte.
3. **`patient_id` va dentro de `measurement` en el historial** y es siempre el de
   la paciente consultada. En el reporte, `measurement` no lo lleva: la
   paciente está en `patient`.
4. **`generated_at` del reporte** es la hora del servidor tras confirmar la
   transacción; puede diferir en milisegundos del registro de auditoría. No es
   un identificador del reporte.
5. **`Cache-Control: no-store` solo va en el 200** del reporte y de la
   auditoría. Los errores (403, 404, 405, 422, 500) no la llevan: no contienen
   datos de pacientes ni filas. El 405 de `/audit-log` lleva `Allow: GET`.
6. **Dos limitaciones pueden faltar** si el metadata del modelo no trae la cifra
   que explican (`accuracy_meaning`, `high_risk_errors`): no se asuma que la
   lista tiene siempre nueve; con los artefactos versionados, las tiene.
7. **El reporte es `POST` sin cuerpo.** Cada llamada deja un registro de
   auditoría: no debe repetirse al recargar la vista ni precargarse.
8. **Las etiquetas de `detail.labels` son las del dataset** (`high risk`,
   `low risk`, `mid risk`), no los niveles `high`/`mid`/`low` del resto de la
   API, y su orden no es el de severidad.

## 4. Grupos de endpoints por fase

La definición endpoint por endpoint —ruta, método, cuerpo, respuesta y
errores— se documentará en cada fase.

| Grupo | Fase | HU |
| --- | --- | --- |
| Esqueleto: prefijo `/api/v1`, formato de error y `/health` | **Construido** (Fase 7, PR #6) | — |
| Predicción sin persistencia y esquema de campos y rangos | **Construido** (Fase 8, PR #7) | HU006, HU007 |
| Readiness de la base de datos (`/health/ready`) | **Construido** (Fase 9, PR #8) | — |
| Pacientes, variables clínicas y evaluaciones persistidas | **Construido** (Fase 10, PR #9) | HU003, HU004, HU005 |
| Autenticación, RBAC y gestión de usuarios y roles | **Construido** (Fase 11, PR #10) | HU001, HU002 |
| Historial, reportes, métricas ML, configuración y consulta de auditoría | **Construido** (Fase 16, PR #16) | HU008, HU009, HU010, HU011 |

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
