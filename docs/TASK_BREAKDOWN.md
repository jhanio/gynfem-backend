# TASK_BREAKDOWN — Desglose y trazabilidad

- **Alcance de este documento:** la tabla maestra de fases del proyecto con su
  estado real, y la trazabilidad de cada historia de usuario hasta su PR, sus
  tests y su evidencia. Las HU se definen en `docs/PRD.md`; aquí solo se
  ubican.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  al cierre de la Fase 7 (esqueleto de la API), PR #6, de la Fase 8
  (predicción sin persistencia), PR #7, de la Fase 9 (base de datos), PR #8,
  de la Fase 10 (persistencia clínica), PR #9, de la Fase 11 (autenticación y
  autorización), PR #10, de la Fase 12 (despliegue del backend), PR #11, de
  la Fase 13 (frontend), PR #2 y PR #3 de `gynfem-frontend`, de la Fase 14
  (despliegue del frontend), PR #4 y PR #5 de `gynfem-frontend`, de la
  Fase 16 (HU de administración, backend), PR #16, y de la Fase 15
  (integración, PR #6 de `gynfem-frontend`) y la interfaz de la Fase 16
  (PR #7 de `gynfem-frontend`), en un PR de documentación del 2026-10-05, y
  al cierre de la Fase 17 (acotada), el 2026-10-06, y al cierre de la Fase 18
  (consolidación de evidencia), el mismo día.
- **Mantenimiento:** este documento **se actualiza al cierre de cada fase**,
  en el mismo PR que la cierra.
- **Convención:** una celda vacía indica un dato que aún no existe.

---

## 1. Tabla maestra de fases

Numeración de 0 a 19 (veinte fases). Es una renumeración más granular que la
del documento inicial del proyecto, que tenía 17 fases (0–16): allí «Supabase»
ocupaba una sola fase y aquí se divide en base de datos (9) y persistencia clínica
(10), y la autenticación (11) pasa a ser una fase propia.

| Fase | Título | Objetivo | HU | PR | Estado |
| --- | --- | --- | --- | --- | --- |
| 0 | Preparación del entorno | Repositorio, `.gitignore` y `.gitattributes` que protegen el RAW (`e5b2bc7`) | — | #1 | Completada |
| 1 | Incorporación de fuentes | RAW inmutable con su fuente, licencia y SHA-256 (`313a9bc`) | — | #1 | Completada |
| 2 | Perfilado | Perfilado reproducible del RAW (`0af3f0f`, `cf4d0fc`) | Base de HU006 y HU010 | #1 | Completada |
| 3 | Baseline documental | Documentos técnicos de base: ocho en `docs/` y `CLAUDE.md` en PR #5; `ML_SPEC.md` existe desde PR #1 | — | #5 | Completada |
| 4 | Revisión y aprobación | Revisión de lo anterior. Sin PR propio: `ML_SPEC.md` v1 entró en PR #1 (`735cec7`) | — | #1 | Completada |
| 5 | Limpieza reproducible | Dos variantes del dataset, deterministas, con tests vinculantes | — | #2, #3 | Completada |
| 6 | Random Forest | Entrenamiento, validación y artefactos del modelo v1.0.0 | Base de HU006 y HU010 | #4 | Completada |
| 7 | Esqueleto backend | FastAPI bajo `/api/v1`: configuración validada al arrancar, `/health`, CORS, logs con correlación y errores uniformes | — | #6 | Completada |
| 8 | Predicción sin persistencia | Conversión de unidades, carga validada del modelo, validación en tres niveles, `POST /api/v1/predict` y `GET /api/v1/prediction/schema` | HU006, HU007 | #7 | Completada |
| 9 | Base de datos | Supabase (São Paulo, PostgreSQL 17.6): esquema `gynfem` con seis migraciones versionadas y reversibles, RLS en todas las tablas, pool de conexiones y `GET /api/v1/health/ready` | Prevé HU001–HU008 (sin implementarlas) | #8 | Completada |
| 10 | Persistencia clínica | Pacientes, mediciones con predicción persistida en una transacción, correcciones, auditoría de toda escritura y migración 0007. **Sin autenticación hasta la Fase 11** | HU003, HU004, HU005 | #9 | Completada |
| 11 | Autenticación y autorización | Supabase Auth (ES256/JWKS), verificación del JWT, RBAC en todas las rutas con matriz verificada contra las rutas reales, gestión de usuarios y roles, primer administrador por línea de comandos, migración 0008 con políticas RLS definitivas. Cierra la deuda de autenticación del PR #9 | HU001, HU002 | #10 | Completada |
| 12 | Despliegue backend | https://gynfem-api.onrender.com. Render (plan Free, Oregon) con el servicio como código (`render.yaml`), sin secretos versionados, health check sin base, sin migraciones automáticas; verificación repetible (`ops/verificar_despliegue.py`) y procedimiento reproducible (`docs/DEPLOYMENT.md`, Sección 7) | — | #11 | Completada |
| 13 | Frontend | Interfaz en `gynfem-frontend`: login, búsqueda y ficha de pacientes, evaluación clínica de 8 campos y administración de usuarios. Se entregó **en modo simulado, sin backend conectado**; la conexión llegó en la Fase 15 (`gynfem-frontend` #6). PR #2: revisión completa del código generado con v0 — 17 hallazgos aprobados más N1–N3 y R1–R5, 121 pruebas, 29/31 mutaciones letales (2 equivalentes documentadas) y CI obligatorio. PR #3: registro del workflow de CI en `main` | HU001–HU007 (interfaz) | `gynfem-frontend` #2, #3 | Completada |
| 14 | Despliegue frontend | https://gynfem-frontend.vercel.app. Vercel, con CSP completa, 7 cabeceras de seguridad, Standard Protection en las vistas previas y verificación automatizada (`npm run verify:deployment`). PR #4: configuración de Vercel, cabeceras de seguridad, CSP, guion de verificación, 194 pruebas y revisión con agente externo. PR #5: dos lecciones de verificación añadidas a `DEPLOYMENT.md` de `gynfem-frontend`, surgidas de un incidente real durante el cierre de la fase. CORS del backend (`GYNFEM_CORS_ORIGINS`) actualizado a https://gynfem-frontend.vercel.app y verificado con `curl` y con un navegador real | — | `gynfem-frontend` #4, #5 | Completada |
| 15 | Integración E2E | Vercel ↔ Render ↔ Supabase, con las pruebas E2E funcionales de cada flujo. PR #6 de `gynfem-frontend`: BFF con cookies httpOnly que reenvía a Supabase Auth y a la API, fin del modo simulado y pruebas con MSW (unitarias, BFF, flujos y contrato). **Salvedad:** la verificación extremo a extremo fue **manual**, con el frontend en local (`npm run start`, http) contra la API de producción, el 2026-10-01 (`DEPLOYMENT.md` de `gynfem-frontend`, Sección 12); no hay suite E2E automatizada, que pasa a la Fase 17. Quedan sin evidencia en el PR #6, y por tanto PENDIENTES, `npm run verify:deployment` contra producción y la comprobación de las cookies `__Host-` en Vercel (Sección 12.4 de ese documento) | HU001–HU007 (integración) | `gynfem-frontend` #6 | Completada |
| 16 | HU de administración | Backend de las últimas cuatro HU: historial de evaluaciones de una paciente (con las corregidas marcadas), reporte estructurado de una evaluación con auditoría de cada generación, métricas reales del modelo leídas de los artefactos con sus limitaciones siempre en la respuesta, configuración de dos parámetros no clínicos en una tabla de solo inserción (migración 0009) y consulta de solo lectura de la auditoría. Seis rutas nuevas en la matriz de roles; verificación de despliegue ampliada. Interfaz en el PR #7 de `gynfem-frontend`: historial, reporte con vista de impresión, métricas con sus limitaciones, configuración y consulta de auditoría. La revisión visual de la impresión del reporte en Chrome y Firefox o Edge queda PENDIENTE según ese PR | HU008, HU009, HU010, HU011 | #16; `gynfem-frontend` #7 | Completada |
| 17 | Validación integral (acotada) | **Alcance acordado el 2026-10-05:** matriz RBAC y sondas de seguridad contra producción, guion E2E manual, pendientes heredados. **Hecho:** matriz RBAC de las 28 rutas × 3 identidades, 84 de 84 celdas (`ops/matriz_rbac.py`); sondas de seguridad S1, S2, S3, S5, S6, S8, S9, S11 y S12, 32 de 34 (`ops/sondas_seguridad.py`; las 2 restantes las bloqueó un intermediario, `docs/KNOWN_ISSUES.md`); prueba del BFF ante un 403 en HTML (`gynfem-frontend` #8); guion E2E redactado (`docs/validation/E2E_GUION.md`). **No ejecutado (PENDIENTE):** la regresión E2E manual, S4, S6 con un recurso real, S7, S10, S13, S14 y `npm run verify:deployment` contra producción. **Fuera de alcance:** la suite E2E automatizada (Playwright) y el rol de mínimo privilegio con `FORCE ROW LEVEL SECURITY`, que pasa a trabajo futuro (`docs/SECURITY.md`, Sección 2.3). Informe: `docs/validation/FASE17.md` | | #18; `gynfem-frontend` #8 | Completada (acotada) |
| 18 | Consolidación de evidencia | Índice de la evidencia para la sustentación, `docs/EVIDENCIA.md`: cada afirmación enlaza el archivo, PR, commit o informe que la demuestra; las cifras del modelo, desde `reports/ml/` y `models/`; lo no comprobado, como PENDIENTE, y una sección de lo que el proyecto no afirma. Incluye una ejecución fechada de la suite completa (`docs/EVIDENCIA.md`, Sección 7.1). Solo documentación: no cambia código ni artefactos | | | Completada |
| 19 | Actualización de tesis | Actualización final de la tesis | | | Pendiente |

**Notas:**

- **Condición sobre los datos reales (decidida en la Fase 12).** Ningún dato real
  de pacientes entra al sistema hasta que se implemente el rol de
  mínimo privilegio con `FORCE ROW LEVEL SECURITY` (`docs/SECURITY.md`,
  Sección 2.3), que la Fase 17 acotada dejó como trabajo futuro. Hasta entonces, la base de producción no recibe datos de
  pacientes; los sintéticos, solo en una verificación puntual con limpieza
  posterior (`docs/DEPLOYMENT.md`, Sección 7.7).
- **Pruebas E2E y CSP (corregido el 2026-09-28).** Las pruebas E2E
  funcionales (frontend ↔ backend ↔ base de datos) pertenecen a la Fase 15; la
  Fase 17 las repite como regresión E2E, no las construye. **Corregido el
  2026-10-05:** la Fase 15 las hizo a mano (Fase 15 en la tabla), así que la
  Fase 17 construye la suite E2E automatizada. **Corregido el 2026-10-06:**
  la Fase 17 acotada no la construye; deja un guion manual
  (`docs/validation/E2E_GUION.md`), sin ejecutar. La CSP y las
  cabeceras de seguridad del frontend se configuran en la Fase 14 (despliegue
  en Vercel, vía `next.config`), no en la Fase 16, que es la de las HU de
  administración. La inconsistencia se detectó al revisar el PR #2 de
  `gynfem-frontend`.
- **Incidente de proceso en `gynfem-frontend` (Fase 13).** El PR #1 de
  `gynfem-frontend` se fusionó automáticamente porque el ruleset de la rama
  no tenía target configurado. Se corrigió configurando el target y exigiendo
  PR para fusionar en `main`; el código de ese PR se revisó completo en el
  PR #2.
- **Incidente de proceso en el CORS del backend (Fase 14).** La variable
  `GYNFEM_CORS_ORIGINS` no se había guardado correctamente en Render, así que
  el backend seguía sin aceptar el origen de Vercel. Se corrigió en la consola
  de Render y se documentó un control negativo en `DEPLOYMENT.md` de
  `gynfem-frontend` (PR #5): comprobar que el origen
  `https://gynfem-frontend.invalid` sigue rechazado, a fin de distinguir un
  cambio aplicado de uno que no llegó a guardarse.
- **Incidente de despliegue del backend (Fase 15).** El despliegue en Render
  del commit `fab898f` (fusión del PR #15, el 2026-10-01 a las 03:18 UTC, que
  es el 30-09 en hora de Perú) falló el 30 de septiembre: el arranque se
  colgó en la carga inicial. Se resolvió con un redespliegue manual del mismo
  commit. Fuente: la descripción del PR #6 de `gynfem-frontend`. La causa
  queda sin determinar: no se consultaron los logs de Render. Procedimiento
  en `docs/DEPLOYMENT.md`, Sección 7.9.
- La Fase 3 llega **después** del código (Fases 5 y 6): debió escribirse antes
  y se omitió. Por eso documenta evidencia ya existente.
- **Los diez documentos técnicos de la Fase 3.** El plan original habla de 10
  documentos técnicos: los 9 de `docs/` más `CLAUDE.md` (sin contar
  `docs/KNOWN_ISSUES.md`, que es un registro de fallos, no un documento de
  base). `ML_SPEC.md` ya existía
  desde PR #1; PR #5 entregó los 8 restantes de `docs/` más `CLAUDE.md`, y
  con ellos completó los 10.
- La columna HU de las fases 8, 10, 11, 13 y 16 se deriva del título de cada
  fase y de la agrupación por Sprint del documento inicial; no es una
  asignación explícita de ese documento.
- La auditoría es transversal y no tiene fase propia. Su tabla existe desde la
  Fase 9; la escriben la Fase 10 y siguientes.
- La Fase 9 no implementa ninguna HU: construye el esquema sobre el que las
  Fases 10, 11 y 16 las implementarán (`docs/ERD.md`, Sección 2).

## 2. Trazabilidad HU → fase → PR → tests → evidencia

HU006 y la parte de backend de HU007 están implementadas desde la Fase 8;
HU003–HU005, desde la Fase 10; HU001 y HU002, desde la Fase 11; HU008–HU011,
en su parte de backend, desde la Fase 16 (`docs/PRD.md`, Sección 4). La interfaz
de HU001–HU007 está conectada a la API desde la Fase 15 (`gynfem-frontend` #6),
y la de HU008–HU011 existe desde el PR #7 de `gynfem-frontend`. Las columnas PR, Tests y Evidencia se
llenan al cerrar la fase que implementa cada HU.

| HU | Fase | PR | Tests | Evidencia | Base técnica ya existente (no implementa la HU) |
| --- | --- | --- | --- | --- | --- |
| HU001 | 11 | #10; `gynfem-frontend` #2 (interfaz, modo simulado) y #6 (conectada a la API) | `tests/api/test_auth_tokens.py`, `test_auth_rbac.py`, `test_auth_logging.py`; `tests/database/test_auth_flujo.py` | Llamadas reales con tokens de Supabase: 401, 403, 200 y usuario desactivado (descripción de PR #10) | |
| HU002 | 11 | #10; `gynfem-frontend` #2 (interfaz, modo simulado) y #6 (conectada a la API) | `tests/database/test_api_users.py`, `test_bootstrap_admin.py`, `test_auth_schema.py`; `tests/api/test_supabase_admin.py` | Primer administrador y gestión de un médico contra la Supabase real (descripción de PR #10) | |
| HU003 | 10 | #9; `gynfem-frontend` #2 (interfaz, modo simulado) y #6 (conectada a la API) | `tests/database/test_api_patients.py` | Flujo real contra Supabase con datos sintéticos (descripción de PR #9) | Tabla `gynfem.patients` (PR #8) e identidad (0007) |
| HU004 | 10 | #9; `gynfem-frontend` #2 (interfaz, modo simulado) y #6 (conectada a la API) | `tests/database/test_api_patients.py` | Idem | Tabla `gynfem.patients` (PR #8) |
| HU005 | 10 | #9; `gynfem-frontend` #2 (interfaz, modo simulado) y #6 (conectada a la API) | `tests/database/test_api_measurements.py`, `test_api_clinical_transversal.py` | Idem, y el vector guardado comparado bit a bit con el enviado al modelo | Tablas `clinical_measurements` y `predictions` (PR #8) |
| HU006 | 8 | #7; `gynfem-frontend` #2 (interfaz, modo simulado) y #6 (conectada a la API) | `tests/api/test_api_prediction.py`, `test_prediction_service.py`, `test_unit_conversion.py`, `test_model_contract.py` | Respuestas reales de `/predict` y `/prediction/schema` en `docs/API_SPEC.md`, Secciones 3.2 y 3.3, y en la descripción de PR #7 | Modelo `models/maternal_risk_rf_v1.0.0.joblib` y su contrato (PR #4; `ML_SPEC.md`, Sección 9.6) |
| HU007 | 8 (datos), 13 (vista), 15 (conexión) | #7 (datos); `gynfem-frontend` #2 (vista, modo simulado) y #6 (conectada a la API) | `test_clase_y_probabilidades_validas`, `test_siempre_incluye_la_advertencia_clinica`, `test_predicted_at_es_utc_actual` | La respuesta de `/predict` lleva nivel de riesgo, probabilidades, fecha y advertencia clínica (`docs/API_SPEC.md`, Sección 3.2). La vista existe desde la Fase 13, en modo simulado; su conexión al backend es de la Fase 15 | |
| HU008 | 16 | #16 (backend); `gynfem-frontend` #7 (interfaz) | `tests/database/test_api_history.py` | Respuesta real del historial en `docs/API_SPEC.md`, Sección 3.7.1, y tabla de mutaciones en la descripción de PR #16 | Tabla `gynfem.predictions`, con trazabilidad completa e inmutable (PR #8) |
| HU009 | 16 | #16 (backend); `gynfem-frontend` #7 (interfaz) | `tests/database/test_api_reports.py` | Respuesta real del reporte en `docs/API_SPEC.md`, Sección 3.7.2; auditoría `prediction.report` | Tablas `patients`, `clinical_measurements` y `predictions` (PR #8, PR #9) |
| HU010 | 16 | #16 (backend); `gynfem-frontend` #7 (interfaz) | `tests/api/test_api_model_metrics.py` | Respuesta real en `docs/API_SPEC.md`, Sección 3.7.3; procedencia de cada cifra en `docs/ML_SPEC.md`, Sección 9.10 | `models/model_metadata.json`, `models/feature_ranges.json`, `reports/ml/training_metrics.json` y `training_report.md` (PR #4) |
| HU011 | 16 | #16 (backend); `gynfem-frontend` #7 (interfaz) | `tests/database/test_api_settings.py`, `test_settings_schema.py` | Respuestas reales en `docs/API_SPEC.md`, Sección 3.7.4; migración 0009 (`docs/ERD.md`, Sección 8) | |
