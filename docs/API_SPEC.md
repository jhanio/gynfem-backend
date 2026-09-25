# API_SPEC — Contrato de la API

- **Alcance de este documento:** los principios aprobados del contrato HTTP y
  qué fase aporta cada grupo de endpoints. Los nombres, unidades, conversiones
  y rangos de las variables pertenecen a `docs/ML_SPEC.md` (Secciones 4, 5 y
  9.6); este documento los referencia y no los copia. Los controles de acceso
  están en `docs/SECURITY.md`.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  en la Fase 7 (esqueleto de la API), PR #6.
- **Convención:** lo que aún no existe se marca
  **PENDIENTE (Fase N) — se documentará al implementarse**.

---

## 1. Estado

Existe el esqueleto de la API (Fase 7, PR #6), con código en `app/`:

- el prefijo `/api/v1` (Sección 2.1);
- el formato de error uniforme (Sección 2.5);
- CORS, correlación por petición y documentación interactiva (Sección 2.6);
- un único endpoint, `GET /api/v1/health` (Sección 3).

Todavía no hay endpoints de negocio: la predicción llega en la Fase 8. Lo que
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
| **Rechazo** | Valor fisiológicamente imposible | La solicitud se rechaza y no se predice | **PENDIENTE de validación clínica con GynFem.** No se fijan números sin fuente clínica aprobada (`ML_SPEC.md`, Sección 5) |
| **Aviso** | Valor posible, pero fuera del rango de entrenamiento | Se predice, con una **advertencia de extrapolación** visible | `models/feature_ranges.json`, generado, nunca escrito a mano (`ML_SPEC.md`, Sección 5) |
| **Normal** | Dentro del rango de entrenamiento | Se predice sin advertencia de extrapolación | — |

`feature_ranges.json` está en unidades del dataset (°F, mmol/mol, mmol/L),
mientras que la entrada llega en unidades clínicas. Si la comparación se hace
tras convertir la entrada o convirtiendo los rangos es **PENDIENTE (Fase 8)**.

### 2.4 El esquema de campos y rangos se publica

Un endpoint publica los campos de entrada, su unidad y sus rangos, de modo que el
frontend **no codifique ningún número**. La fuente de esos rangos es la misma
que usa la validación del backend, de modo que no puede haber dos versiones.

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
| `details` | Solo en el 422: lista de `{"loc": [...], "type": "..."}`. Indica qué campo falló y por qué tipo de regla, **nunca el valor recibido** |

| Estado | `code` | Origen |
| --- | --- | --- |
| 404 | `not_found` | Ruta inexistente |
| 405 | `method_not_allowed` | Método no admitido por la ruta |
| 422 | `validation_error` | La petición no cumple su esquema Pydantic |
| 500 | `internal_error` | Excepción no controlada. La traza se registra en el log del servidor sin el mensaje de la excepción; al cliente solo le llega este cuerpo |
| Otros 4xx | `http_error` | Cualquier otro `HTTPException` |

Las respuestas correctas **no** se envuelven: esta sección solo fija la forma
de los errores.

Una excepción: el rechazo de un preflight CORS desde un origen no permitido
lo emite `CORSMiddleware` como texto plano con estado 400, antes de llegar a la
aplicación. El navegador no expone ese cuerpo al código del frontend.

### 2.6 CORS, correlación y documentación interactiva

- **CORS.** Solo los orígenes de `GYNFEM_CORS_ORIGINS`, devueltos uno a uno,
  nunca `*` (`docs/SECURITY.md`, Sección 2). Métodos `GET` y `POST`; cabeceras
  `Authorization`, `Content-Type` y `X-Request-ID`; sin credenciales, porque
  el JWT de la Fase 11 viaja en `Authorization` y no en cookies.
- **`X-Request-ID`.** Toda respuesta lo lleva y el frontend puede leerlo
  (`Access-Control-Expose-Headers`). Si la petición trae uno de 1 a 64
  caracteres `[A-Za-z0-9-]`, se respeta. Si no, se genera un UUID4.
- **Documentación interactiva.** `/api/v1/docs` y `/api/v1/openapi.json` en
  `development` y `test`. En `production` no existen (404).

## 3. Endpoints implementados

### `GET /api/v1/health`

Comprueba que la propia aplicación responde (liveness). **No consulta
dependencias externas**: Render lo usará (Fase 12) para decidir si reinicia la
instancia, y reiniciar no arregla la caída de un servicio externo. En la
Fase 8 el modelo se cargará al arrancar, así que «responde» implicará «el
modelo está cargado». La comprobación de la base de datos irá en un endpoint
aparte, `/api/v1/health/ready`, previsto para la Fase 9 y fuera del health
check de Render.

Respuesta `200`:

```json
{"status": "ok", "version": "0.1.0", "timestamp": "2026-09-24T12:00:00.000000Z"}
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

## 4. Grupos de endpoints por fase

La definición endpoint por endpoint —ruta, método, cuerpo, respuesta y
errores— se documentará en cada fase.

| Grupo | Fase | HU |
| --- | --- | --- |
| Esqueleto: prefijo `/api/v1`, formato de error y `/health` | **Construido** (Fase 7, PR #6) | — |
| Predicción sin persistencia y esquema de campos y rangos | PENDIENTE (Fase 8) | HU006, HU007 |
| Pacientes, variables clínicas y evaluaciones persistidas | PENDIENTE (Fase 10) | HU003, HU004, HU005 |
| Autenticación y gestión de usuarios y roles | PENDIENTE (Fase 11) | HU001, HU002 |
| Historial, reportes, métricas ML y configuración | PENDIENTE (Fase 16) | HU008, HU009, HU010, HU011 |

## 5. Obligaciones que ya fija ML_SPEC sobre la respuesta de predicción

No son decisiones de este documento. Se listan a fin de que quien implemente la
Fase 8 no las pase por alto:

- El orden de las probabilidades del modelo es `["high risk", "low risk",
  "mid risk"]`, **no** el de severidad; el backend no debe asumir que lo es
  (`ML_SPEC.md`, Sección 9.6).
- Cada predicción queda asociada a la versión del modelo y del esquema de
  conversión que la produjeron (`ML_SPEC.md`, Sección 6). Si esas versiones
  también viajan en la respuesta es PENDIENTE (Fase 8).
- El ajuste del umbral de decisión sobre `predict_proba` ante la asimetría de
  coste clínico está abierto (`ML_SPEC.md`, Sección 9.4, Decisión B).
