# DEPLOYMENT — Despliegue

- **Alcance de este documento:** cómo preparar el entorno y reproducir en local
  el pipeline de datos y ML que existe hoy, y el estado del despliegue en la
  nube. La arquitectura está en `docs/ARCHITECTURE.md` y la estrategia de
  pruebas en `docs/TEST_STRATEGY.md`.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5.
- **Convención:** lo que aún no existe se marca
  **PENDIENTE (Fase N) — se documentará al implementarse**.

---

## 1. Estado

**No hay nada desplegado.** El único entorno que existe es el local, donde se
ejecutan los scripts y los tests.

## 2. Entorno local verificado

| Elemento | Valor | Fuente |
| --- | --- | --- |
| Python | 3.12.10 | Cabeceras de los tres reportes de `reports/ml/`; `models/model_metadata.json` |
| Sistema donde se generaron los artefactos | Windows (rutas `.venv\Scripts\python.exe`) | Comandos de regeneración de los reportes |
| Dependencias | `pandas==3.0.6`, `numpy==2.5.3`, `matplotlib==3.11.2`, `pytest==9.1.1`, `scikit-learn==1.9.1`, `joblib==1.6.0` | `requirements.txt` |

La versión de Python **no está fijada** en ningún archivo del repositorio (no
hay `.python-version` ni `pyproject.toml`). Un test compara la versión del
intérprete con la que registra `model_metadata.json` y falla si difieren
(`test_la_version_de_python_del_metadata_coincide_con_la_del_interprete`), así
que la suite exige 3.12.10.

`scikit-learn` y `joblib` se fijan con `==` porque cargar el `.joblib` con otra
versión puede cambiar el comportamiento en silencio (`ML_SPEC.md`,
Sección 9.4, Decisión F).

### 2.1 Preparar el entorno

El repositorio no documenta un comando propio que cree el entorno. El
procedimiento estándar de Python, en Windows:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 3. Reproducir el pipeline

Los comandos exactos son los que declaran los propios reportes. Cada paso
verifica la integridad de su entrada (`docs/ARCHITECTURE.md`, Sección 2).

| Paso | Comando | Escribe | Fuente |
| --- | --- | --- | --- |
| 1. Perfilado del RAW | `.venv\Scripts\python.exe scripts\profile_dataset.py` | `reports/ml/dataset_profile.md` y figuras | `dataset_profile.md`, cabecera |
| 2. Limpieza | `.venv\Scripts\python.exe scripts\prepare_dataset.py` | `data/processed/*.csv` | `data_cleaning_report.md`, cabecera |
| 3. Entrenamiento | `.venv\Scripts\python.exe scripts\train_model.py` | `models/*`, `reports/ml/training_*` | `training_report.md`, cabecera |

**El paso 3 tarda 13993 s (≈3 h 53 min)** con la rejilla completa
(`training_report.md`). No hace falta ejecutarlo al verificar el modelo: la
suite lo reajusta con los hiperparámetros ganadores y exige que las métricas se
reproduzcan exactamente (`training_report.md`, Sección 14.3).

Los pasos 2 y 3 son deterministas: regenerar produce archivos byte-idénticos,
salvo tres valores de reloj en el paso 3 (`ML_SPEC.md`, Sección 9.7). Si tras
regenerar `git status` muestra cambios en `data/processed/`, `models/` o
`reports/ml/` distintos de esos tres valores, algo cambió en el código o en el
entorno.

## 4. Verificar

| Verificación | Comando |
| --- | --- |
| Suite completa | `.venv\Scripts\python.exe -m pytest` |
| Además, el test lento de determinismo (sintaxis POSIX, tal como la cita `training_report.md`) | `GYNFEM_SLOW_TESTS=1 pytest tests/ -k todas_las_comprobaciones` |

El resto de comandos de verificación selectiva están en
`training_report.md`, Sección 14.3. Si la suite falla con `BrokenProcessPool` o
`WinError 6`, ver `docs/KNOWN_ISSUES.md`.

## 5. Despliegue en la nube

| Destino | Fase | Estado |
| --- | --- | --- |
| Supabase (proyecto y base de datos) | PENDIENTE (Fase 9) | Se documentará al implementarse |
| Render (backend) | PENDIENTE (Fase 12) | Se documentará al implementarse |
| Vercel (frontend) | PENDIENTE (Fase 14) | Se documentará al implementarse |

No hay variables de entorno de despliegue, comandos de build ni configuración de ninguno de
los tres servicios. Se documentarán en su fase.
