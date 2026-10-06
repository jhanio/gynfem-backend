# E2E_GUION — Regresión manual contra producción

- **Alcance de este documento:** el guion manual y repetible de la regresión
  extremo a extremo de la Fase 17, de Vercel a Render y Supabase, y la evidencia
  que se guarda en cada paso. Los resultados de cada ejecución van al informe,
  [`FASE17.md`](FASE17.md). **Sin automatizar:** la suite Playwright quedó fuera
  de la Fase 17.
- **Fecha:** 2026-10-06 — redactado, **sin ejecutar**.
- **Quién lo ejecuta:** la persona responsable, con las dos cuentas de
  verificación (médica y administradora). Nunca con datos reales ni con cuentas
  personales.

---

## 1. Reglas

1. **Datos inequívocamente ficticios** (`CLAUDE.md`, regla 3):

   | Dato | Valor |
   | --- | --- |
   | Documento | `PASAPORTE` · `FICTICIOF17A` |
   | Nombres · apellidos | `Paciente Ficticia` · `Sintetica Fdiecisiete` |
   | Evaluación 1 (en rango) | `ENTRADA_NORMAL` de `ops/verificar_despliegue.py`: 28 años, 36.8 °C, 80 lpm, 118/76 mmHg, IMC 22.5, HbA1c 5.2 %, glucosa 85 mg/dL |
   | Evaluación 2 (con aviso de extrapolación) | `ENTRADA_EXTRAPOLADA` de `ops/verificar_despliegue.py`: 34 años, 37.0 °C, 88 lpm, 132/86 mmHg, IMC 32.0, HbA1c 7.2 %, glucosa 110 mg/dL |
   | Corrección de la evaluación 2 | La misma entrada con frecuencia cardíaca 90 lpm |

2. **Limpieza por baja lógica, nunca borrado físico.** La paciente se da de baja
   desde la interfaz (paso 12). Los triggers `*_forbid_delete` no se tocan.
3. **Nada secreto en la evidencia.** En las capturas no aparece ningún correo,
   contraseña, token ni el valor de una cookie: se recorta o se tapa antes de
   guardarlas. En la pestaña *Network* solo se copian el método, la ruta, el
   estado y `X-Request-ID`.
4. **Dónde se guarda:** `reports/fase17/e2e/<AAAA-MM-DD>/`, ignorada por git.
   Nombre de cada captura: `paso-NN-<qué>.png`. Al informe solo pasan estados,
   `request_id`, ids opacos y la conclusión de cada paso.
5. **Sin escribir en `settings`.** El caso S10 (`institution_name` con HTML) no
   forma parte de este guion: solo se ejecuta con una orden expresa aparte, con
   el frontend en local apuntando a producción, y restaurando el valor.
6. **Si un paso falla:** se anota con su evidencia y se sigue solo si los pasos
   siguientes no dependen de él. No se corrige nada durante la ejecución. La
   paciente sintética se da de baja siempre (paso 12), aunque haya fallos.

## 2. Pasos

Cada paso anota la **hora UTC**. Para el «estado y `X-Request-ID`», se usa la
petición `/api/v1/…` correspondiente en *Herramientas del navegador → Network*.

| Paso | Quién | Acción | Resultado esperado | Evidencia que se guarda |
| --- | --- | --- | --- | --- |
| 0 | — | Abrir `https://gynfem-api.onrender.com/api/v1/health` y esperar la respuesta (hasta unos 2 minutos si el servicio estaba suspendido). Anotar el **inicio de la ventana** | 200, `"version": "0.6.0"` | Hora de inicio; segundos hasta el 200 (arranque en frío); versión |
| 1 | Médica | Iniciar sesión en `https://gynfem-frontend.vercel.app`. **S14:** *Application → Cookies*; en la consola, `document.cookie`, `localStorage.length` y `sessionStorage.length`; recargar la página | Panel de la médica. Existen `__Host-gf_at` y `__Host-gf_rt`, ambas `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`, sin `Domain`; ninguna `gf_at`/`gf_rt` sin prefijo. `document.cookie` no las muestra; los dos almacenamientos, vacíos. La sesión se conserva al recargar | `paso-01-cookies.png` (nombres y atributos, **con la columna del valor tapada**); estado y `X-Request-ID` de `GET /api/v1/me` |
| 2 | Médica | Buscar por documento `PASAPORTE` · `FICTICIOF17A` | Sin resultados. Si aparece una de una ejecución interrumpida, **darla de baja primero** (como en el paso 12) y anotarlo | `paso-02-busqueda.png`; estado de `POST /api/v1/patients/search` |
| 3 | Médica | Registrar la paciente sintética | Ficha creada | Estado 201 y `X-Request-ID` de `POST /api/v1/patients`; **id de la paciente** (solo el campo `id` de esa respuesta en *Network*: la interfaz es una sola página y la ficha no tiene URL propia) |
| 4 | Médica | Registrar la evaluación 1 y después la evaluación 2 | Evaluación 1: nivel de riesgo, sin aviso de extrapolación. Evaluación 2: aviso de extrapolación visible en IMC y HbA1c. En las dos, la advertencia clínica | `paso-04-evaluacion-1.png`, `paso-04-evaluacion-2.png`; estado 201 y `X-Request-ID` de cada `POST …/measurements` |
| 5 | Médica | En el historial, «Corregir» la evaluación 2 con la corrección de la Sección 1 y «Guardar corrección y recalcular» | «Corrección registrada. La evaluación original deja de estar vigente.» | `paso-05-correccion.png`; estado 201 y `X-Request-ID` de `POST /api/v1/measurements/{id}/corrections`; id de la medición corregida |
| 6 | Médica | Abrir el historial de la paciente | Tres evaluaciones: la original marcada como corregida, sin botón «Corregir», y la advertencia clínica una sola vez | `paso-06-historial.png`; estado de `GET …/evaluations` |
| 7 | Médica | «Generar reporte» de la evaluación vigente; después «Imprimir o guardar como PDF» y cancelar el diálogo | Reporte con la advertencia clínica; vista de impresión sin la navegación de la aplicación | `paso-07-reporte.png`, `paso-07-impresion.png`; estado 200, `X-Request-ID` y `Cache-Control: no-store` de `POST /api/v1/predictions/{id}/report`; **id de la predicción** |
| 8 | Médica | Abrir las métricas del modelo | Las métricas y sus nueve limitaciones | `paso-08-metricas.png`; estado de `GET /api/v1/model/metrics` |
| 9 | Administradora | Cerrar la sesión de la médica (las dos cookies desaparecen). Iniciar sesión como administradora y abrir la configuración, **sin cambiar nada** | Parámetros visibles; ningún dato clínico en el menú | `paso-09-configuracion.png`; estado de `GET /api/v1/settings` |
| 10 | Administradora | Abrir la auditoría y filtrar por la ventana del paso 0 en adelante | Las acciones de los pasos 3 a 7 (`patient.create`, las mediciones, la corrección y `prediction.report`), con ids opacos, sin nombres, documentos ni valores clínicos | `paso-10-auditoria.png`; número de filas por acción |
| 11 | Administradora | **S6 con un recurso que existe.** La interfaz no ofrece las vistas clínicas a este rol, así que se piden directamente al BFF (lecturas: el navegador envía las cookies y el BFF no exige la cabecera CSRF en un GET). En una pestaña nueva, abrir `https://gynfem-frontend.vercel.app/api/v1/patients/<id del paso 3>` y `…/api/v1/patients/<id del paso 3>/evaluations`; después, las mismas con un UUID inventado | Las cuatro: 403 con `{"error": {"code": "forbidden", …}}`. **El cuerpo es igual en la paciente real y en la inventada, salvo el `request_id`**: la administradora no puede saber si la paciente existe | `paso-11-s6.png`; de cada petición, estado, `code`, `message` y `X-Request-ID` |
| 12 | Médica | Cerrar la sesión de la administradora; entrar como médica; en la ficha, «Dar de baja» y confirmar | Baja confirmada; la paciente ya no aparece al buscarla | `paso-12-baja.png`; estado 204 y `X-Request-ID` de `DELETE /api/v1/patients/{id}`; hora de la baja |
| 13 | Médica | **S7**, igual que el paso 11 (GET directas al BFF en una pestaña nueva): `…/api/v1/patients/<id del paso 3>`, `…/api/v1/patients/<id del paso 3>/evaluations` y `…/api/v1/predictions/<id del paso 7>` | Las tres: 404 sin ningún dato de la paciente (`patient_not_found`, `patient_not_found` y `prediction_not_found`) | `paso-13-s7.png`; estado, `code` y `X-Request-ID` de cada petición |
| 14 | — | Cerrar sesión. Añadir una fila al registro de datos sintéticos de `gynfem-frontend/docs/DEPLOYMENT.md` §12.3 | — | Fecha, ventana, actor (ids de las dos cuentas), id de la paciente, id de la medición corregida, estado «baja lógica» y hora |
| 15 | — | Exportar los logs de Render y de Vercel de la ventana (pasos 0 a 14) y entregarlos para el caso S13 | — | En los logs **no** aparecen `FICTICIOF17A`, `Fdiecisiete`, los valores clínicos de la Sección 1 como conjunto, `eyJ` ni ningún correo. Se anota el número de coincidencias de cada búsqueda, nunca las líneas |

## 3. Qué queda en la base

La base no admite borrados físicos. Después de una ejecución completa quedan,
**dados de baja**: la paciente, sus tres mediciones y sus tres predicciones, y
las filas de auditoría de los pasos 3 a 12. Ninguna consulta de la API las
devuelve (paso 13). El registro del paso 14 las identifica.

## 4. Cierre en el informe

Por cada paso: hora, resultado (**OK**, **FALLA** o **PENDIENTE**), estado HTTP,
`request_id` y la captura correspondiente. Lo que no se pudo comprobar se marca
PENDIENTE, nunca OK. Los casos S6 (paso 11), S7 (paso 13), S13 (paso 15) y S14
(paso 1) cierran sus filas de `FASE17.md` §7.
