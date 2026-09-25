# TASK_BREAKDOWN — Desglose y trazabilidad

- **Alcance de este documento:** la tabla maestra de fases del proyecto con su
  estado real, y la trazabilidad de cada historia de usuario hasta su PR, sus
  tests y su evidencia. Las HU se definen en `docs/PRD.md`; aquí solo se
  ubican.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  al cierre de la Fase 7 (esqueleto de la API), PR #6.
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
| 8 | Predicción sin persistencia | Validación, conversión de unidades y predicción | HU006, HU007 | | Pendiente |
| 9 | Base de datos | Supabase: proyecto, esquema y migraciones | | | Pendiente |
| 10 | Persistencia clínica | Pacientes, variables clínicas y evaluaciones con trazabilidad | HU003, HU004, HU005 | | Pendiente |
| 11 | Autenticación y autorización | Supabase Auth, JWT y RBAC | HU001, HU002 | | Pendiente |
| 12 | Despliegue backend | Render | | | Pendiente |
| 13 | Frontend | Interfaz en `gynfem-frontend` | HU007 (vista) | | Pendiente |
| 14 | Despliegue frontend | Vercel | | | Pendiente |
| 15 | Integración E2E | Vercel ↔ Render ↔ Supabase | | | Pendiente |
| 16 | HU de administración | Historial, reportes, métricas y configuración | HU008, HU009, HU010, HU011 | | Pendiente |
| 17 | Validación integral | Unitarias, integración, RBAC, seguridad, E2E y regresión | | | Pendiente |
| 18 | Consolidación de evidencia | Commits, PRs, reportes, tests, resultados del modelo y despliegue | | | Pendiente |
| 19 | Actualización de tesis | Actualización final de la tesis | | | Pendiente |

**Notas:**

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
- La auditoría es transversal y no tiene fase propia.

## 2. Trazabilidad HU → fase → PR → tests → evidencia

Ninguna HU está implementada (`docs/PRD.md`, Sección 4). Las columnas PR,
Tests y Evidencia se llenan al cerrar la fase que implementa cada HU.

| HU | Fase | PR | Tests | Evidencia | Base técnica ya existente (no implementa la HU) |
| --- | --- | --- | --- | --- | --- |
| HU001 | 11 | | | | |
| HU002 | 11 | | | | |
| HU003 | 10 | | | | |
| HU004 | 10 | | | | |
| HU005 | 10 | | | | |
| HU006 | 8 | | | | Modelo `models/maternal_risk_rf_v1.0.0.joblib` y su contrato (PR #4; `ML_SPEC.md`, Sección 9.6) |
| HU007 | 8, 13 | | | | |
| HU008 | 16 | | | | |
| HU009 | 16 | | | | |
| HU010 | 16 | | | | `reports/ml/training_metrics.json` y `training_report.md` (PR #4) |
| HU011 | 16 | | | | |
