# API_SPEC — Contrato de la API

- **Alcance de este documento:** los principios aprobados del contrato HTTP y
  qué fase aporta cada grupo de endpoints. Los nombres, unidades, conversiones
  y rangos de las variables pertenecen a `docs/ML_SPEC.md` (Secciones 4, 5 y
  9.6); este documento los referencia y no los copia. Los controles de acceso
  están en `docs/SECURITY.md`.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5.
- **Convención:** lo que aún no existe se marca
  **PENDIENTE (Fase N) — se documentará al implementarse**.

---

## 1. Estado

**No existe ninguna API.** No hay código de servidor en este repositorio. Todo
lo que sigue son principios aprobados. Ninguna ruta, cuerpo de petición,
cuerpo de respuesta ni código de estado está definido todavía.

## 2. Principios aprobados

Los aprobó el equipo del proyecto en la planificación, que no está versionada
en el repositorio. Donde un principio sale de `ML_SPEC.md`, se cita.

### 2.1 Versionado

Todas las rutas cuelgan del prefijo **`/api/v1`**.

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
nivel que los origina. La forma concreta es **PENDIENTE (Fase 7)**. Los
mensajes de error no contienen datos clínicos (`docs/SECURITY.md`, Sección 3).

## 3. Grupos de endpoints por fase

La definición endpoint por endpoint —ruta, método, cuerpo, respuesta y
errores— se documentará en cada fase.

| Grupo | Fase | HU |
| --- | --- | --- |
| Esqueleto: prefijo `/api/v1` y formato de error | PENDIENTE (Fase 7) | — |
| Predicción sin persistencia y esquema de campos y rangos | PENDIENTE (Fase 8) | HU006, HU007 |
| Pacientes, variables clínicas y evaluaciones persistidas | PENDIENTE (Fase 10) | HU003, HU004, HU005 |
| Autenticación y gestión de usuarios y roles | PENDIENTE (Fase 11) | HU001, HU002 |
| Historial, reportes, métricas ML y configuración | PENDIENTE (Fase 16) | HU008, HU009, HU010, HU011 |

## 4. Obligaciones que ya fija ML_SPEC sobre la respuesta de predicción

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
