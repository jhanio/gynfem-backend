# PRD — Producto y alcance

- **Alcance de este documento:** qué problema resuelve el sistema, qué es y qué
  no es, quién lo usa, las historias de usuario HU001–HU011 y lo que queda
  explícitamente fuera. No describe el modelo (dueño: `docs/ML_SPEC.md`), la
  arquitectura (`docs/ARCHITECTURE.md`) ni el plan por fases
  (`docs/TASK_BREAKDOWN.md`).
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  el estado de HU006 y HU007 en la Fase 8, PR #7, y el de HU003, HU004 y HU005
  en la Fase 10, PR #9, el de HU001 y HU002, con los roles, en la Fase 11,
  PR #10, y el de HU008 a HU011 en la Fase 16, PR #16. El 2026-10-05, la
  interfaz de las once HU (`gynfem-frontend` #6 y #7).
- **Convención:** lo que aún no existe se marca
  **PENDIENTE (Fase N) — se documentará al implementarse**. Las HU y los roles
  provienen del documento inicial del proyecto, que no está versionado en este
  repositorio; se transcriben tal como se definieron.

---

## 1. Problema

El personal clínico de GynFem necesita estimar el **riesgo gestacional**
(`low risk`, `mid risk`, `high risk`) de una gestante a partir de ocho variables
clínicas, ingresadas en unidades clínicas peruanas
(`docs/ML_SPEC.md`, Secciones 1 y 4).

El sistema previsto aporta esa estimación como señal adicional al juicio
profesional y registrará cada evaluación de forma trazable
(`docs/ML_SPEC.md`, Sección 6).

Descripción ampliada del problema de negocio (volumen de consultas, proceso
actual, indicadores de éxito): **PENDIENTE, a definir por el producto** — no
consta en el repositorio.

## 2. Qué es y qué no es

Esta tabla describe el producto previsto. Lo que está construido hoy se detalla
en `docs/ARCHITECTURE.md`, Sección 1.

| Es | No es |
| --- | --- |
| Una herramienta de **apoyo a la decisión clínica** (`ML_SPEC.md`, Sección 1) | Un diagnóstico autónomo; su salida no reemplaza la evaluación médica |
| Un clasificador entrenado con un dataset público (Hossain et al., 2026, CC BY 4.0; `data/raw/README.md`) | Un modelo entrenado con datos de pacientes de GynFem |
| Un sistema que advertirá cuando la entrada salga del rango que el modelo vio (`ML_SPEC.md`, Sección 5). Construido en la Fase 8: `POST /api/v1/predict` emite un aviso por variable fuera del rango de `models/feature_ranges.json` | Un sistema validado en toda la población gestante: el entrenamiento no incluye, por ejemplo, IMC ≥ 30 (ver `docs/SECURITY.md`, Sección 4) |

## 3. Roles

- **Médico** — HU003–HU007: pacientes, variables clínicas y predicción; HU008
  y HU009: historial y reporte de sus pacientes; HU010: métricas del modelo.
- **Administrador** — HU002: gestión de usuarios y roles; HU010: métricas del
  modelo; HU011: configuración de parámetros; y la consulta de la auditoría.
  **No accede a datos clínicos** (mínimo privilegio; decisión aprobada en la
  Fase 11): recibe 403 en el historial y en el reporte, y la auditoría no
  muestra datos clínicos. Puede usar `/predict`, que no toca pacientes.

Un usuario tiene un solo rol: quien sea médico y administrador a la vez usa
dos cuentas. La matriz rol × endpoint completa está en `docs/API_SPEC.md`,
Sección 3.6.

## 4. Historias de usuario

**Estado de implementación:** HU006 está implementada en el backend desde la
Fase 8, y HU007 en su parte de datos: la respuesta de la API lleva lo que la
vista debe mostrar (`docs/API_SPEC.md`, Sección 3.2); la vista se hizo en la
Fase 13 y se conectó a la API en la Fase 15 (`gynfem-frontend` #6). HU003, HU004 y HU005 están implementadas en el backend desde la
Fase 10 (`docs/API_SPEC.md`, Sección 3.5). HU001 y HU002 lo están desde la
Fase 11 (Sección 3.6), y desde entonces todas las HU exigen autenticación.
HU008, HU009, HU010 y HU011 están implementadas en el backend desde la Fase 16
(`docs/API_SPEC.md`, Sección 3.7), y su interfaz, desde el PR #7 de
`gynfem-frontend`. La interfaz de HU001 a HU007 usa la API real desde la
Fase 15 (`gynfem-frontend` #6). Con ellas, las once HU tienen backend e
interfaz; sus criterios de aceptación siguen pendientes de validar por el
producto.

El documento inicial no define un criterio de aceptación formal por HU. Donde
falta, se indica en lugar de inventarlo.

| HU | Sprint | Historia | Descripción (documento inicial) | Criterio de aceptación | Estado |
| --- | --- | --- | --- | --- | --- |
| HU003 | 1 — Base clínica | Registrar paciente gestante | Crear paciente y almacenar información. | Propuesto en la Fase 10, pendiente de validar por el producto: se registra con tipo y número de documento, nombres y apellidos válidos; un documento no se repite entre pacientes activas; la creación queda auditada | Implementada en el backend (Fase 10, PR #9): `POST /api/v1/patients` |
| HU004 | 1 — Base clínica | Consultar y actualizar paciente | Buscar y actualizar datos. | Propuesto en la Fase 10, pendiente de validar: se consulta por id; se busca por documento exacto o por nombre (al menos 3 caracteres), paginado y con el documento enmascarado; se actualiza parcialmente con auditoría de los campos cambiados; se da de baja sin perder el historial | Implementada en el backend (Fase 10, PR #9): `GET`/`PATCH`/`DELETE /api/v1/patients…` |
| HU005 | 1 — Base clínica | Registrar y actualizar variables clínicas | Capturar las 8 variables. | Propuesto en la Fase 10, pendiente de validar: se registran las 8 variables en unidades clínicas con las mismas reglas que `/predict` y se obtiene su predicción, todo en una operación; se consultan paginadas; una corrección crea una medición nueva y conserva la evaluación original | Implementada en el backend (Fase 10, PR #9): `POST`/`GET …/measurements`, `POST /measurements/{id}/corrections` |
| HU006 | 2 — ML | Ejecutar clasificación predictiva | 8 variables → FastAPI → validation → preprocessing → Random Forest → prediction | PENDIENTE, a definir por el producto | Implementada en el backend (Fase 8, PR #7): `POST /api/v1/predict` |
| HU007 | 2 — ML | Visualizar resultado | Mostrar: riesgo bajo; medio; alto; probabilidades cuando corresponda; fecha; advertencia clínica. | PENDIENTE, a definir por el producto | Datos en la respuesta de la API (Fase 8, PR #7); vista en `gynfem-frontend` (Fase 13, #2), conectada a la API en la Fase 15 (#6) |
| HU001 | 3 — Seguridad | Autenticarse | Supabase Auth → JWT → FastAPI → RBAC | Propuesto en la Fase 11, pendiente de validar por el producto: solo un token de Supabase Auth válido (firma, emisor, audiencia y vigencia) da acceso; el rol se decide en la base en cada petición; sin token, 401; con un rol insuficiente, 403; un usuario desactivado no opera aunque conserve el token | Implementada en el backend (Fase 11, PR #10): verificación del JWT, RBAC en todas las rutas, `GET /api/v1/me`. El inicio de sesión lo hace el BFF del frontend contra Supabase Auth (Fase 15, `gynfem-frontend` #6) |
| HU002 | 3 — Seguridad | Gestionar usuarios y roles | Administrador: crear usuario; consultar; modificar; asignar rol; activar; desactivar. | Propuesto en la Fase 11, pendiente de validar: solo el administrador; crea la cuenta con una contraseña temporal y un rol; consulta paginado; modifica el nombre y asigna el rol; activa y desactiva con efecto inmediato; nunca deja el sistema sin un administrador activo; todo queda auditado | Implementada en el backend (Fase 11, PR #10): `/api/v1/users…`; primer administrador por línea de comandos |
| HU008 | 4 — Administración | Consultar historial | El documento inicial no la describe. Propuesto en la Fase 16, pendiente de validar por el producto: consultar las evaluaciones previas de una paciente, ordenadas en el tiempo, con su riesgo | Propuesto en la Fase 16, pendiente de validar por el producto: solo el médico; las evaluaciones salen de la medición más reciente a la más antigua, paginadas y sin total; cada una lleva sus 8 variables, su riesgo, sus probabilidades, sus avisos y sus versiones; las corregidas aparecen marcadas como tales; no aparece ninguna evaluación de otra paciente; una paciente dada de baja responde 404; la respuesta lleva la advertencia clínica | Implementada en el backend (Fase 16, PR #16): `GET /api/v1/patients/{id}/evaluations`; interfaz en `gynfem-frontend` #7 |
| HU009 | 4 — Administración | Generar reporte | El documento inicial no la describe. Propuesto en la Fase 16, pendiente de validar por el producto: un documento con los datos de la paciente, sus mediciones, el resultado y la advertencia clínica | Propuesto en la Fase 16, pendiente de validar por el producto: solo el médico; el reporte de una evaluación contiene solo lo ya almacenado (paciente, medición, resultado) más el nombre de la institución y la advertencia clínica obligatoria, sin recalcular nada; son datos estructurados que el frontend compone e imprime; cada generación queda auditada; una paciente dada de baja responde 404 | Implementada en el backend (Fase 16, PR #16): `POST /api/v1/predictions/{id}/report`; interfaz en `gynfem-frontend` #7 |
| HU010 | 4 — Administración | Visualizar métricas ML | El documento inicial no la describe. Propuesto en la Fase 16, pendiente de validar por el producto: ver las métricas reales obtenidas al entrenar el modelo (Fase 6), no calculadas de nuevo | Propuesto en la Fase 16, pendiente de validar por el producto: médico y administrador; cada cifra publicada es exactamente la del artefacto del modelo; nada se reentrena ni se recalcula; una cifra que no está en los artefactos se omite; las limitaciones documentadas —en particular, el rango estrecho de entrenamiento— van siempre en la misma respuesta, en lenguaje para un médico | Implementada en el backend (Fase 16, PR #16): `GET /api/v1/model/metrics`. Contrato en `docs/ML_SPEC.md`, Sección 9.10; interfaz en `gynfem-frontend` #7 |
| HU011 | 4 — Administración | Configurar parámetros básicos | El documento inicial no la describe ni exige ningún parámetro. Propuesto en la Fase 16, pendiente de validar por el producto: parámetros ajustables por el administrador sin tocar código | Propuesto en la Fase 16, pendiente de validar por el producto: solo el administrador; catálogo cerrado de dos parámetros **no clínicos** (nombre de la institución en el reporte y tamaño de página por defecto del historial); un cambio rige sin desplegar ni reiniciar; cada cambio queda auditado y conserva el valor anterior; ningún parámetro altera el comportamiento clínico | Implementada en el backend (Fase 16, PR #16): `GET` y `PATCH /api/v1/settings`; interfaz en `gynfem-frontend` #7 |

**Transversal:** auditoría. Alcance en `docs/SECURITY.md`, Sección 3. Desde la
Fase 16 el administrador puede consultarla, sin datos clínicos
(`GET /api/v1/audit-log`; `docs/API_SPEC.md`, Sección 3.7.5).

Notas que las HU heredan de `docs/ML_SPEC.md`, sin redefinirlas aquí:

- **HU006** — «preprocessing» es la conversión desde unidades clínicas peruanas
  a las unidades del dataset (`ML_SPEC.md`, Sección 4) y el vector debe seguir
  el orden de variables del contrato del artefacto (Sección 9.6).
- **HU007** — el orden de las probabilidades que devuelve el modelo **no** es el
  de severidad (`ML_SPEC.md`, Sección 9.6). La advertencia clínica incluye la
  de extrapolación (Sección 5).

La fase en que se implementa cada HU está en `docs/TASK_BREAKDOWN.md`.

## 5. Fuera de alcance

- **Diagnóstico autónomo** o cualquier decisión clínica sin intervención médica.
- **Uso de datos reales de pacientes de GynFem** en el repositorio o en el
  entrenamiento (`docs/SECURITY.md`, Sección 2).
- **Validación externa** con datos de otra institución o periodo: no
  planificada (`ML_SPEC.md`, Sección 9.8).
- **Límites fisiológicos duros de validación de entrada** fijados sin fuente
  clínica: quedan pendientes de validación clínica con GynFem
  (`ML_SPEC.md`, Sección 5).
- **Parámetros clínicos configurables** (umbrales de riesgo, rangos de
  validación, texto de la advertencia clínica): cambiarían el comportamiento
  del sistema sin la trazabilidad de un cambio de código. HU011 no los incluye
  (decisión de la Fase 16).
- **Generación de PDF en el backend**: el reporte de HU009 son datos
  estructurados que el frontend compone e imprime (decisión de la Fase 16).
