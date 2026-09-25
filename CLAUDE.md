# CLAUDE.md — Reglas permanentes de gynfem-backend

- **Alcance de este documento:** reglas de trabajo que aplican a cualquier
  cambio en este repositorio. No describe el producto ni el modelo: remite a
  los documentos dueños de cada tema (Sección 6).

## 1. Propósito

Backend de un sistema de apoyo a la decisión clínica que clasifica el riesgo
gestacional (bajo, medio, alto) dirigido al personal clínico de GynFem. Hoy contiene
el pipeline reproducible de datos y el modelo Random Forest entrenado; la API,
la base de datos y la autenticación aún no existen.

## 2. Stack

| | Tecnología |
| --- | --- |
| **Real** | Python 3.12.10, pandas, numpy, scikit-learn, joblib, matplotlib, pytest — versiones fijadas en `requirements.txt` |
| **Previsto** | FastAPI (Fase 7), Supabase (Fases 9–11), Render (Fase 12), frontend en Vercel (Fases 13–14) |

## 3. Reglas no negociables

1. **`data/raw/` es inmutable.** Nunca se edita, limpia ni sobrescribe. Todo
   procesamiento lee de ahí y escribe en `data/interim/` o `data/processed/`.
2. **La columna `Name` nunca se expone.** Está en el RAW solo a fin de conservar su
   SHA-256. Nunca aparece en salidas derivadas, reportes, logs, salida de
   consola ni mensajes de error. Un test que la lea informa cuántas
   coincidencias hubo, nunca cuáles.
3. **Ningún dato real de pacientes de GynFem** entra en el repositorio, que es
   público.
4. **Nada se inventa.** Unidades, rangos, métricas e hiperparámetros salen del
   dato o de una fuente citada. Todo número de un documento cita el archivo
   que lo produce.
5. **Las cifras del paper son comparación, nunca meta.**
6. **Los umbrales y rangos se generan, no se escriben a mano.**
7. **Tests antes del código**, y cada test debe fallar cuando el código se
   altera a propósito (`docs/TEST_STRATEGY.md`).
8. **Los tests no reescriben artefactos versionados**: escriben en `tmp_path`.
   Toda llamada a `train_model.main()` en un test pasa
   `param_grid=TINY_PARAM_GRID`.
9. **`docs/ML_SPEC.md` no se modifica sin aprobación explícita.** Los demás
   documentos lo referencian, nunca lo duplican ni lo contradicen.
10. **Nunca commit sin mostrar antes el diff.**
11. **Nunca push a `main`.**
12. **Nunca crear un PR sin que se pida.**
13. **Nunca reentrenar con la rejilla completa sin que se pida** (tarda
    ≈3 h 53 min).

## 4. Convenciones de Git (tal como se han usado)

- **Ramas:** `feat/…`, `fix/…`, `docs/…` desde `main` actualizado
  (`feat/dataset-cleaning`, `fix/dataset-cleaning-review`,
  `feat/random-forest-training`, `docs/technical-baseline-v2`).
- **Commits:** `tipo(ámbito): descripción`, con el ámbito opcional.
  - Tipos usados: `feat`, `fix`, `docs`, `test`, `chore`.
  - Ámbitos usados: `ml`, `data`, `test`, `deps`.
  - Idioma: mayoritariamente español; los commits de PR #1 y uno de PR #2
    están en inglés.
- **Títulos de PR:** `PR #N — descripción`.

## 5. Comandos frecuentes

```powershell
# Suite completa
.venv\Scripts\python.exe -m pytest

# Regenerar el dataset procesado (determinista)
.venv\Scripts\python.exe scripts\prepare_dataset.py

# Regenerar el perfilado del RAW
.venv\Scripts\python.exe scripts\profile_dataset.py

# Contar los tests
.venv\Scripts\python.exe -m pytest --collect-only -q
```

El entrenamiento completo y el test lento están en `docs/DEPLOYMENT.md`. Si
la suite falla con `BrokenProcessPool` o `WinError 6`, ver
`docs/KNOWN_ISSUES.md`.

## 6. Dónde vive cada tema

| Tema | Documento dueño |
| --- | --- |
| Dataset, unidades, conversión, rangos, métricas, contrato del artefacto, trazabilidad | `docs/ML_SPEC.md` |
| Evidencia numérica | `reports/ml/` |
| Producto, roles e historias de usuario | `docs/PRD.md` |
| Componentes, flujo y carpetas | `docs/ARCHITECTURE.md` |
| Entidades de datos | `docs/ERD.md` |
| Contrato de la API | `docs/API_SPEC.md` |
| Seguridad, privacidad y advertencias clínicas | `docs/SECURITY.md` |
| Estrategia de pruebas | `docs/TEST_STRATEGY.md` |
| Entorno, reproducción y despliegue | `docs/DEPLOYMENT.md` |
| Fases, estado y trazabilidad HU → PR | `docs/TASK_BREAKDOWN.md` |
| Fallos conocidos del entorno | `docs/KNOWN_ISSUES.md` |
