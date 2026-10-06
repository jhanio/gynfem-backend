# FASE 17 — Informe de validación integral

- **Alcance de este documento:** los resultados de la Fase 17 acotada: la matriz
  RBAC y las sondas de seguridad contra producción, sus hallazgos y lo que queda
  pendiente. El guion de regresión manual está en
  [`E2E_GUION.md`](E2E_GUION.md). El contrato de la API es `docs/API_SPEC.md`; los
  controles de seguridad, `docs/SECURITY.md`.
- **Fecha:** 2026-10-06. Rama `test/fase17-validacion`.
- **Estado de la fase: Completada (acotada).** Se ejecutaron la matriz RBAC y
  las sondas de seguridad contra producción. **No se ejecutó** (PENDIENTE): la
  regresión E2E manual (guion redactado en [`E2E_GUION.md`](E2E_GUION.md)), S4,
  S6 con un recurso real, S7, S10, S13, S14 y `npm run verify:deployment`
  contra producción (Sección 7).
- **Convención:** cada afirmación cita su evidencia (salida de un comando, una
  evidencia JSONL o una prueba). Lo que no se comprobó se marca **PENDIENTE**.
  Lo que se infiere sin comprobarse se marca **hipótesis**.
- **Evidencias en bruto:** JSONL en `reports/fase17/`, ignorada por git
  (`.gitignore`). Solo llevan método, ruta, identidad, estado, `code` y
  `request_id`, y en respuestas que no son JSON, cabeceras de diagnóstico y 80
  caracteres del cuerpo con correos y JWT tachados. Se comprobó en cada una que
  no contienen tokens, correos, claves ni documentos.

---

## 1. Estado de partida

| Qué | Evidencia |
| --- | --- |
| Backend | `main` = `97b88cf`, `__version__ = "0.6.0"` (`app/__init__.py`) |
| Frontend | `main` = `1a1c9a5` (PR #7 fusionado) |
| API en Render | `GET /api/v1/health` → 200, `{"status":"ok","version":"0.6.0"}` (2026-10-05 23:36 UTC) |
| Frontend en Vercel | `GET /` → 200 (2026-10-05) |

Ningún dato real de pacientes ha entrado en el sistema (`docs/SECURITY.md`,
Sección 2.2): la producción solo contiene datos sintéticos.

## 2. Herramientas

| Herramienta | Qué hace | Por qué no escribe | Pruebas |
| --- | --- | --- | --- |
| `ops/matriz_rbac.py` | Cada ruta de la matriz de `API_SPEC.md` §3.6 (28) × sin sesión, médica y administradora: 84 celdas | Una celda permitida se demuestra con un 200 de lectura, un 404 sobre un UUID aleatorio o un 422 de un cuerpo inválido | `tests/api/test_matriz_rbac.py` (25); `tests/database/test_matriz_rbac.py` (86): pasa contra la aplicación real, el recuento de filas de **todas** las tablas no cambia, y cada una de las 84 celdas falla si la API respondiera otra cosa |
| `ops/sondas_seguridad.py` | 34 sondas de los casos S1, S2, S3, S5, S6, S8, S9, S11 y S12 | UUID aleatorios, cuerpos que el esquema rechaza y búsquedas, que no se auditan | `tests/api/test_sondas_seguridad.py` (32); `tests/database/test_sondas_seguridad.py` (72): pasan contra la aplicación real sin escribir, cada sonda rechaza un 500 y el defecto propio de su caso, y las de comodines fallan si se quita el escape de `LIKE` de la aplicación |

Las dos se detienen sin probar nada si la versión desplegada no es la local, si
falla un inicio de sesión o si una cuenta no tiene el rol que dice (`GET /me`).

## 3. Matriz RBAC contra producción

**Resultado: 84 de 84 celdas coinciden con `API_SPEC.md` §3.6.** Una ejecución,
2026-10-06 01:02 UTC. Evidencia: `reports/fase17/matriz_rbac_20261006T010208Z.jsonl`.

| Identidad | Resultado |
| --- | --- |
| Sin sesión | 401 `not_authenticated` en las 25 rutas protegidas; 200 en `/health`; 404 `not_found` en `/openapi.json` y `/docs`, que no existen en production |
| Médica | 403 `forbidden` en `/health/ready`, las 6 rutas de usuarios, `/settings` (2) y `/audit-log`; autorizada en las rutas clínicas, `/predict`, `/prediction/schema`, `/model/metrics` y `/me` |
| Administradora | 403 `forbidden` en las 11 rutas clínicas; autorizada en `/health/ready`, usuarios, `/settings`, `/audit-log`, `/predict`, `/prediction/schema`, `/model/metrics` y `/me` |

El servicio estaba suspendido: la primera respuesta tardó 62.5 s (dentro de los
120 s del guion, sin cambiar ningún tiempo de espera).

## 4. Sondas de seguridad contra producción

**Resultado: 32 de 34 sondas pasan.** Una ejecución completa, 2026-10-06 13:24
UTC. Evidencia: `reports/fase17/sondas_seguridad_20261006T132454Z.jsonl`.

| Caso | Sondas | Resultado |
| --- | --- | --- |
| S1 sin `Authorization` u otro esquema | 5 | 5 OK: 401 `not_authenticated` con `WWW-Authenticate: Bearer` |
| S2 token con carga alterada o firma truncada | 2 | 2 OK: 401 `invalid_token` |
| S3 token HS256 con clave inventada o `alg: none` | 2 | 2 OK: 401 `invalid_token` |
| S5 rol declarado en cabeceras, consulta o cuerpo | 4 | 4 OK: 403 `forbidden` |
| S6 administradora en recursos clínicos | 5 | 5 OK: 403 sin repetir el id; la médica, 404 en el mismo UUID |
| S8 id que no es UUID | 4 | **3 OK, 1 falla** (Sección 5) |
| S9 inyección en texto | 5 | **4 OK, 1 falla** (Sección 5) |
| S11 errores uniformes | 5 | 5 OK: 404, 405 y tres 422, sin trazas y con el mismo `request_id` en cuerpo y cabecera |
| S12 CORS desde un origen ajeno | 2 | 2 OK: sin `Access-Control-Allow-Origin` |

**Límites de estas sondas:**

- **S6** usa UUID aleatorios: muestra que la administradora recibe 403 sin que
  el error repita el id, pero no que el 403 sea igual cuando el recurso existe.
  Eso se comprueba con la paciente sintética del guion E2E (paso 11).
  **PENDIENTE.**
- **S9** (búsqueda literal) da evidencia completa en producción solo porque no
  hay pacientes activas cuyo nombre case con los comodines. Con una que sí casa,
  el escape se comprueba en local
  (`test_con_una_paciente_que_casaria_los_comodines_siguen_sin_resultados`).

## 5. Hallazgo S8/S9: un intermediario responde 403 en HTML

### 5.1 Evidencia

- Dos cargas con forma de inyección SQL recibieron en producción un **403 en
  HTML**, sin formato de error uniforme ni `request_id`:
  - S8: `GET /api/v1/patients/1%20OR%201%3D1`, como médica.
  - S9: `PATCH /api/v1/patients/{UUID aleatorio}` con
    `given_names = "Robert'); DROP TABLE gynfem.patients;--"`, como médica.
- Cabeceras de la respuesta (ejecución del 2026-10-06 16:32 UTC, solo esas dos
  sondas; evidencia `reports/fase17/sondas_seguridad_20261006T163213Z.jsonl`):

  | Sonda | `server` | `cf-ray` | `content-type` | Comienzo del cuerpo |
  | --- | --- | --- | --- | --- |
  | S8 | `cloudflare` | `a46611387ccd484e-LIM` | `text/html; charset=UTF-8` | `<!DOCTYPE html> <html lang="en"> <head> <meta charset="utf-8" /> …` |
  | S9 | `cloudflare` | `a46614b3f8e112b3-LIM` | `text/html; charset=UTF-8` | igual |

- **La respuesta no la emitió la aplicación.** La API responde todos sus
  errores en JSON con `request_id` (`API_SPEC.md` §2.5), también sus 403: los
  de S5, S6 y la matriz lo llevan.
- **Se repitió en dos ejecuciones** (13:24 y 16:32 UTC), solo en esas dos
  sondas. Con la misma cuenta y las mismas rutas, las cargas sin forma de SQL
  recibieron el 422 de la API (`abcdef`, `';--`, 200 caracteres, un nombre con
  HTML).
- **En pruebas locales la aplicación rechaza esas mismas cargas con 422**
  `validation_error`, sin repetir el valor
  (`tests/database/test_sondas_seguridad.py`).

### 5.2 Hipótesis (no confirmadas)

- Que el 403 lo emitiera el **filtro de seguridad del proxy de Render
  (Cloudflare)** y que la petición **no llegara a la aplicación**.
- **No se confirmó** con los logs de Render ni se identificó la regla. Que haya
  `server: cloudflare` y `cf-ray` muestra que la respuesta atravesó Cloudflare,
  pero no basta para saber quién la generó: esas cabeceras aparecen en
  cualquier respuesta que pase por Cloudflare, y los 80 caracteres guardados no
  llegan al `<title>` de la página.

### 5.3 Consecuencia

- En ese camino **se pierde el contrato de errores uniformes** (`API_SPEC.md`
  §2.5): quien llama recibe un 403 sin `code` ni `request_id`.
- **No es un defecto de la API**: la API no llegó a responder, o su respuesta
  no es la que llegó. La validación propia de la API para esas cargas tiene
  evidencia local (422), no de producción.
- Lo que ve la interfaz, en la Sección 6.

## 6. El BFF ante un 403 en HTML de un intermediario

Comprobado **en local** en `gynfem-frontend`, con una prueba nueva de
caracterización que no toca código de aplicación:
`tests/server/proxy-intermediary-html.test.ts` (4 pruebas, todas en verde; la
suite del frontend, 37 archivos y 699 pruebas, en verde; lint y typecheck
limpios). La prueba entró en **`gynfem-frontend` #8**, fusionado el 2026-10-06
(`a0930c1`). Como no se tocó código de aplicación, no se hizo la mutación de
`relay()`: la prueba fija el comportamiento actual.

| Comprobación | Resultado |
| --- | --- |
| Qué devuelve el BFF | `relay()` (`lib/server/proxy.ts`) no reenvía ningún cuerpo que no sea `application/json`: responde **502** `upstream_unreachable`, «No se pudo conectar con el servidor.», con el `request_id` del propio BFF en el cuerpo y en `X-Request-ID` |
| ¿Llega algo del HTML al navegador? | **No**: ni `<`, ni `DOCTYPE`, ni «Cloudflare», ni el Ray ID, ni rutas del servidor; tampoco las cabeceras `server` ni `cf-ray` |
| Qué mensaje ve la persona | Genérico: «No se pudo completar la operación. Inténtalo de nuevo.» (`UNKNOWN_ERROR_MESSAGE`), con la referencia del BFF |
| Si el HTML llegara al cliente sin pasar por el BFF | `parseErrorResponse` lo convierte en `http_error` y la interfaz muestra «No tienes permiso para esta operación.»: tampoco se muestra el HTML |

**Efectos secundarios de que llegue como 502** (comportamiento actual,
observado; registrado como límite conocido en `docs/KNOWN_ISSUES.md` y no
corregido):

- **Lecturas:** el 502 es transitorio (`isTransient`), así que `retryRead` repite
  la petición dos veces más (a 1 s y a 3 s) antes de mostrar el error. Con un
  bloqueo determinista del intermediario, son tres peticiones bloqueadas.
- **Escrituras:** el 502 cuenta como resultado desconocido (`isOutcomeUnknown`).
  `PatientForm`, `PatientFile`, `AssessmentForm` (en una evaluación con
  paciente) y `SystemConfiguration` muestran «No sabemos si la operación se
  guardó. Compruébalo antes de repetirla.», y `GenerateReportButton`, «No
  sabemos si el reporte llegó a generarse…», aunque el intermediario la
  rechazó.
- **Alcance real:** una ruta con un id que no es UUID nunca sale del BFF (404
  por su lista de rutas: `tests/server/proxy.test.ts`), así que S8 no se da desde
  el navegador. S9 sí: el formulario de pacientes no valida en el cliente el
  formato del nombre, así que un nombre con forma de SQL viajaría hasta el
  intermediario.

## 7. Lo no ejecutado y los pendientes

La fase se cierra **acotada**: lo marcado PENDIENTE no se ejecutó y no cuenta
como hecho.

| Qué | Estado |
| --- | --- |
| S4 token caducado en producción | **PENDIENTE** (evidencia local: `test_token_caducado_401_token_expired`) |
| S6 con un recurso que existe | **PENDIENTE**: paso 11 del guion E2E |
| S7 recursos dados de baja | **PENDIENTE**: paso 13 del guion E2E |
| S10 `institution_name` con HTML | **PENDIENTE**, opcional: solo con orden expresa, porque escribe en `settings` de producción |
| S13 logs sin datos clínicos | **PENDIENTE** hasta recibir los logs de Render y Vercel de la ventana del E2E |
| S14 cookies `__Host-` en Vercel | **PENDIENTE**: paso 1 del guion E2E |
| Regresión E2E manual | **PENDIENTE**: [`E2E_GUION.md`](E2E_GUION.md), redactado y **no ejecutado** |
| Suite E2E automatizada (Playwright) | **Fuera de alcance** de la Fase 17 |
| `npm run verify:deployment` contra producción | **PENDIENTE** |
| Hallazgo S8/S9: confirmar quién emite el 403 | **PENDIENTE**: logs de Render de 13:24 y 16:32 UTC del 2026-10-06 |
| Arranque intermitente en Render | **PENDIENTE**, opcional: solo si se reciben los *Events* y logs |
| `FORCE ROW LEVEL SECURITY` | **Fuera de alcance**: trabajo futuro (`docs/SECURITY.md`, Sección 2.3). Sigue vigente la condición: ningún dato real de pacientes hasta que esté implementado |
| Aislamiento de pacientes entre médicas | **No es un requisito**: decisión de diseño, consultorio único (`docs/SECURITY.md`, Sección 2.3) |
