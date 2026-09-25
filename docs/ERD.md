# ERD — Modelo de datos

- **Alcance de este documento:** las entidades que el negocio necesita y qué
  información conceptual guarda cada una. **No** define tablas, columnas,
  tipos, claves ni relaciones físicas. La regla de trazabilidad de las
  predicciones pertenece a `docs/ML_SPEC.md`, Sección 6; aquí solo se
  referencia. Las reglas de protección de estos datos están en
  `docs/SECURITY.md`.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5.
- **Convención:** lo que aún no existe se marca
  **PENDIENTE (Fase N) — se documentará al implementarse**.

---

## 1. Estado

No existe base de datos. El único dato versionado hoy es el dataset público de
entrenamiento (`data/`), que **no** es parte de este modelo de datos: no
contiene pacientes de GynFem (`data/raw/README.md`).

- **Esquema concreto** (tablas, columnas, tipos, claves, migraciones):
  **PENDIENTE (Fase 9) — se documentará al implementarse.**
- **Persistencia de datos clínicos:** **PENDIENTE (Fase 10).**

## 2. Entidades previstas

Derivadas de las historias de usuario (`docs/PRD.md`, Sección 4). Nivel
conceptual.

| Entidad | Qué necesita guardar el negocio | HU que la originan |
| --- | --- | --- |
| **Usuario** | Identidad de quien usa el sistema, su rol (Médico o Administrador) y si está activo o desactivado | HU001, HU002 |
| **Paciente gestante** | Los datos de la paciente que el producto defina, consultables y actualizables | HU003, HU004 |
| **Registro de variables clínicas** | Las 8 variables clínicas de una paciente en un momento dado, en unidades clínicas peruanas | HU005 |
| **Evaluación (predicción)** | El resultado de clasificar un registro de variables, con los elementos de trazabilidad de la Sección 3 | HU006, HU007, HU008 |
| **Registro de auditoría** | Quién hizo qué acción y cuándo | Auditoría transversal |
| **Parámetros del sistema** | La configuración básica que el Administrador pueda ajustar | HU011 |

Qué datos concretos de la paciente se guardan (HU003) es **PENDIENTE, a definir
por el producto**. HU009 (reportes) y HU010 (métricas ML) leen de estas
entidades y de `reports/ml/training_metrics.json`; que necesiten una entidad
propia es **PENDIENTE (Fase 16)**.

## 3. Regla fija de trazabilidad (aprobada)

Cada evaluación guarda los **cuatro** elementos que fija `docs/ML_SPEC.md`,
Sección 6:

1. Las 8 variables clínicas ingresadas, en unidades clínicas peruanas.
2. El vector convertido que efectivamente entró al modelo, en unidades del
   dataset y en el orden del contrato del artefacto (`ML_SPEC.md`, Sección 9.6).
3. La versión del modelo utilizada — hoy `1.0.0`, de
   `models/model_metadata.json → model_version`.
4. La versión del esquema de unidades y conversión (`ML_SPEC.md`, Sección 4).

Guardar a la vez el valor clínico y el vector enviado permite reconstruir
cualquier predicción aunque cambien la conversión o el modelo.

## 4. Lo que este documento no decide

- Si el Registro de variables y la Evaluación son una o dos entidades físicas.
- Cómo se versiona el esquema de conversión (punto 4 de la Sección 3).
- Qué parte de la auditoría vive en la base de datos y cuál en los logs.

Los dos primeros quedan **PENDIENTES (Fase 9)**. El tercero es **PENDIENTE
(fase por confirmar)**, igual que la auditoría en `docs/SECURITY.md`,
Sección 3.
