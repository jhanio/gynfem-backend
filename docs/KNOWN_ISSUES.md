# Problemas conocidos

## `BrokenProcessPool` / `WinError 6` en joblib-loky bajo CPU saturada (Windows)

**Resumen:** en Windows, con la CPU saturada al 100 %, los workers de
joblib/loky pueden fallar con `OSError: [WinError 6] Controlador no válido`
en `call_queue.get()` → `self._sem.release()`. El proceso padre lo reporta,
de forma engañosa, como
`BrokenProcessPool: A task has failed to un-serialize`.

**Dónde se ve:** en cualquier `GridSearchCV(n_jobs=-1)` de
`scripts/train_model.py`, y por tanto en los tests que llaman a
`train_model.main()`.

**Referencias upstream:** mismo síntoma que
[joblib#901](https://github.com/joblib/joblib/issues/901). Es de la misma
familia que [loky#175](https://github.com/joblib/loky/issues/175), abierto
desde 2018.

**Evidencia (2026-09-24, joblib 1.6.0 / loky 3.6.0, Python 3.12.10, 12 núcleos):**

- Se reproduce con un script mínimo sin ningún código de este proyecto: un
  `GridSearchCV(n_jobs=-1)` sobre datos sintéticos, con 12 procesos
  saturando la CPU.
- Sin carga: 0 fallos en 19 corridas completas de la suite, 0 en 11 corridas
  del ejercicio de mutación y 0 en 300 búsquedas del script mínimo.
- Con carga: falló en 3 de 3 corridas de la suite.
- Instrumentando los workers se vio que el handle del semáforo llega válido
  al worker y se cierra durante la ejecución de su primera tarea. Se
  descartaron los cierres desde código Python y los cierres desde otros
  procesos; no se identificó el cierre a nivel nativo.

**Conclusión:** no se reproduce en uso normal y no es código de este
proyecto. No requiere acción. Si una corrida falla con este error, repetirla
con la máquina sin carga.

## Fase 16: limitaciones conocidas de las historias de administración

Ninguna impide el uso. Se registran para que no se redescubran.

### El bloqueo de `PATCH /settings` no tiene test de concurrencia

**Resumen:** `SystemSettingsService.update` toma un bloqueo consultivo de
transacción (`pg_advisory_xact_lock`, `app/repositories/system_settings.py`)
antes de comparar con el valor vigente, para que dos peticiones simultáneas con
el mismo valor no inserten dos filas. Ningún test lanza dos peticiones a la vez:
la suite comprueba la comparación con el valor vigente y la atomicidad, no la
exclusión mutua.

**Consecuencia si el bloqueo fallara:** una fila y un registro de auditoría de
más, con el mismo valor. No se pierde ni se altera ningún dato.

**Acción:** ninguna por ahora. Un test con dos conexiones y una barrera sería
el modo de cubrirlo.

### El logger «escritura clínica» se reutiliza para acciones no clínicas

**Resumen:** el cambio de un parámetro (`system_setting.update`) y la generación
de un reporte (`prediction.report`) se registran con `registrar()`
(`app/api/v1/comun.py`), que escribe en el logger `gynfem.clinical` con el
mensaje «escritura clínica». La gestión de usuarios ya lo hacía desde la
Fase 11. El contenido es correcto —solo `action` y `duration_ms`—, pero el
nombre es impreciso: un cambio de configuración no es una escritura clínica, y
el reporte es una lectura auditada.

**Consecuencia:** quien filtre los logs por `gynfem.clinical` verá también esas
acciones. Se distinguen por el campo `action`.

**Acción:** ninguna en la Fase 16, para no tocar código de fases anteriores.

### La respuesta de `/model/metrics` se construye al arrancar

**Resumen:** `ModelMetricsService` lee `model_metadata.json`,
`feature_ranges.json` y `training_metrics.json` una sola vez, al construir la
aplicación. Si un artefacto cambia con el servicio en marcha, la respuesta no
cambia hasta reiniciar.

**Consecuencia:** ninguna en el despliegue actual: los artefactos están
versionados y cada commit en `main` redespliega y reinicia. Solo afecta a quien
edite un artefacto en un servidor ya arrancado, igual que ocurre con el modelo.

**Acción:** ninguna. Es deliberado: los artefactos no cambian mientras la
aplicación corre.

### Las verificaciones dejan un residuo permanente en la base

**Resumen:** la base no admite borrados físicos. `ops/verificar_despliegue.py`
con `--flujo-clinico` deja, **dadas de baja**, una paciente ficticia
(`PASAPORTE FICTICIOF16`), tres mediciones y tres predicciones, con sus
registros de auditoría; con `--cambio-de-parametro` deja 2 filas en
`gynfem.system_settings` y 2 en `gynfem.audit_log`. Cada corrida con esos
indicadores añade las suyas.

**Consecuencia:** filas que ninguna consulta de la API devuelve (las clínicas) y
ruido en el historial de `institution_name` y en la consulta de auditoría. El
valor vigente del parámetro queda como estaba, pero `updated_at` y `updated_by`
dejan de ser nulos: ya no se distingue de un valor por defecto nunca tocado.

**Acción:** ejecutar el guion con indicadores **una vez** tras el despliegue de
la fase; las verificaciones rutinarias van sin indicadores y no escriben
(`docs/DEPLOYMENT.md`, Sección 7.11).

## Gestión de usuarios: una operación sin cambio real se escribe y se audita

**Resumen:** `POST /users/{id}/deactivate` sobre un usuario ya inactivo responde
200 y escribe otra vez el perfil y un registro `user.deactivate` en
`gynfem.audit_log`, aunque nada haya cambiado. Lo mismo ocurre con
`POST /users/{id}/activate` sobre un usuario ya activo (`user.activate`) y con
`PATCH /users/{id}` con los mismos valores que ya tiene (`user.update`, con esos
campos en `changed_fields`).

**Dónde:** observado en el código, no en un test. Las tres rutas pasan por
`UserService._cambiar` (`app/services/users.py`), que ejecuta
`users_repo.update_profile` y después `audit_repo.insert_audit` sin comparar con
el valor vigente. `update_profile` (`app/repositories/users.py`) hace un
`UPDATE` sin condición sobre los valores y fija `updated_by` al actor.
**Ningún test fija este comportamiento**, ni en un sentido ni en el otro.

**Contraste:** `PATCH /settings` con un valor igual al vigente no escribe nada,
ni fila ni auditoría (`SystemSettingsService.update`,
`app/services/system_settings.py`).

**Consecuencia:** registros de auditoría sin cambio real, y `updated_by` deja
de indicar quién hizo el último cambio efectivo. Se vio en la verificación de
la Fase 15: un botón que no se deshabilitaba durante la escritura dejó 9
`user.deactivate` y 1 `user.activate` en 23 s (hallazgo H1 del PR #6 de
`gynfem-frontend`, corregido en el frontend).

**Acción:** ninguna por ahora; se documenta como comportamiento conocido y no
se corrige en este PR.

## Fase 17: límites conocidos del camino frontend → intermediario → API

Ninguno expone datos ni impide el uso. Se registran para que no se
redescubran. Evidencia y detalle: `docs/validation/FASE17.md`, Secciones 5 y 6.

### Cloudflare bloquea cargas con forma de inyección SQL con un 403 en HTML

**Resumen:** en producción, dos cargas con forma de inyección SQL
(`GET /api/v1/patients/1%20OR%201%3D1` y un `PATCH /api/v1/patients/{id}` con
`given_names` = `Robert'); DROP TABLE gynfem.patients;--`) recibieron un **403
en HTML** con `server: cloudflare` (`cf-ray` `a46611387ccd484e-LIM` y
`a46614b3f8e112b3-LIM`), sin formato de error uniforme ni `request_id`. Se
repitió en dos ejecuciones (2026-10-06, 13:24 y 16:32 UTC). La respuesta no la
emitió la aplicación. En local, la aplicación rechaza esas mismas cargas con
422 `validation_error`.

**Hipótesis no confirmada:** que lo emitiera el filtro de seguridad del proxy de
Render (Cloudflare) y que la petición no llegara a la aplicación. No se
confirmó con los logs de Render ni se identificó la regla, que no gestiona este
proyecto.

**Consecuencia:** en ese camino se pierde el contrato de errores uniformes
(`docs/API_SPEC.md` §2.5). **No es un defecto de la API.** La validación propia
de la API para esas cargas solo tiene evidencia local.

**Acción:** ninguna por ahora. Lo confirmarían los logs de Render de esas dos
ventanas.

### El BFF convierte esa respuesta en un 502, con dos efectos

**Resumen:** el BFF de `gynfem-frontend` no reenvía ningún cuerpo que no sea
JSON (`relay()` en `lib/server/proxy.ts`): un 403 en HTML de un intermediario
llega al navegador como **502** `upstream_unreachable`, uniforme y sin nada del
HTML. La interfaz muestra un mensaje genérico. Lo fija
`tests/server/proxy-intermediary-html.test.ts` (`gynfem-frontend` #8).

**Efectos del 502** (comportamiento actual, no corregido):

- **Lecturas:** el 502 es transitorio (`isTransient`), así que `retryRead`
  repite la petición dos veces (a 1 s y a 3 s) antes de mostrar el error. Ante
  un bloqueo determinista son tres peticiones bloqueadas y unos 4 s de espera.
- **Escrituras:** el 502 cuenta como resultado desconocido
  (`isOutcomeUnknown`). Los formularios de paciente, de evaluación y de
  configuración muestran «No sabemos si la operación se guardó. Compruébalo
  antes de repetirla.», y el botón de reporte, «No sabemos si el reporte llegó
  a generarse…», aunque el intermediario la rechazó y nada se guardó.

**Alcance:** un id que no es UUID no sale del BFF (404 por su lista de rutas),
así que el primer caso no se da desde el navegador. El segundo sí: el
formulario de pacientes no valida en el cliente el formato del nombre.

**Acción:** ninguna por ahora; corregirlo exige distinguir en el BFF un 4xx de
un intermediario de un fallo de conexión, con su decisión y su PR.
