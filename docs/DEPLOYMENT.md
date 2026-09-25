# DEPLOYMENT — Despliegue

- **Alcance de este documento:** cómo preparar el entorno, reproducir en local
  el pipeline de datos y ML, arrancar la API en local, y el estado del
  despliegue en la nube. La arquitectura está en `docs/ARCHITECTURE.md` y la estrategia de
  pruebas en `docs/TEST_STRATEGY.md`.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  en la Fase 7 (esqueleto de la API), PR #6.
- **Convención:** lo que aún no existe se marca
  **PENDIENTE (Fase N) — se documentará al implementarse**.

---

## 1. Estado

**No hay nada desplegado.** El único entorno que existe es el local, donde se
ejecutan los scripts, los tests y la API (Sección 5).

## 2. Entorno local verificado

| Elemento | Valor | Fuente |
| --- | --- | --- |
| Python | 3.12.10 | Cabeceras de los tres reportes de `reports/ml/`; `models/model_metadata.json` |
| Sistema donde se generaron los artefactos | Windows (rutas `.venv\Scripts\python.exe`) | Comandos de regeneración de los reportes |
| Dependencias de datos y ML | `pandas==3.0.6`, `numpy==2.5.3`, `matplotlib==3.11.2`, `pytest==9.1.1`, `scikit-learn==1.9.1`, `joblib==1.6.0` | `requirements.txt` |
| Dependencias de la API (Fase 7) | `fastapi==0.141.1`, `starlette==1.7.0`, `pydantic==2.13.5`, `pydantic-settings==2.15.0`, `uvicorn==0.53.0`, `python-dotenv==1.2.3` (lo usa `uvicorn --env-file`), `httpx2==2.13.1` (cliente de `TestClient`; Starlette 1.7 marca `httpx` como obsoleto para ese uso) | `requirements.txt` |

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

El paso 1 escribe la fecha del día en `dataset_profile.md`, así que regenerarlo
siempre cambia ese archivo. Los pasos 2 y 3 son deterministas: regenerar produce archivos byte-idénticos,
salvo tres valores de reloj en el paso 3 (`ML_SPEC.md`, Sección 9.7). Si tras
regenerar los pasos 2 y 3 `git status` muestra cambios en `data/processed/`,
`models/` o `reports/ml/` distintos de esos tres valores, algo cambió en el código o en el
entorno.

## 4. Verificar

| Verificación | Comando |
| --- | --- |
| Suite completa (ML y API) | `.venv\Scripts\python.exe -m pytest` |
| Solo la suite de la API | `.venv\Scripts\python.exe -m pytest tests\api` |
| Solo la suite de ML | `.venv\Scripts\python.exe -m pytest tests --ignore=tests\api` |
| Además, el test lento de determinismo (sintaxis POSIX, tal como la cita `training_report.md`) | `GYNFEM_SLOW_TESTS=1 pytest tests/ -k todas_las_comprobaciones` |

El resto de comandos de verificación selectiva están en
`training_report.md`, Sección 14.3. Si la suite falla con `BrokenProcessPool` o
`WinError 6`, ver `docs/KNOWN_ISSUES.md`.

## 5. Arrancar la API en local

### 5.1 Variables de entorno

La aplicación solo lee variables de entorno y las valida al arrancar
(`app/core/config.py`). `.env.example` es la plantilla versionada, con un
comentario por variable. El `.env` real **nunca se versiona** (`.gitignore`).

| Variable | Obligatoria | Valores admitidos | Ejemplo local |
| --- | --- | --- | --- |
| `GYNFEM_ENVIRONMENT` | Sí | `development`, `test`, `production` | `development` |
| `GYNFEM_CORS_ORIGINS` | Sí | Orígenes separados por comas: esquema, host en minúsculas y puerto opcional válido, sin credenciales, ruta ni barra final. Prohibidos `*` (también dentro del host) y `null`. No se admiten hosts IPv6. En `development` y `test`, solo `localhost` o `127.0.0.1`. En `production`, solo `https` y nunca localhost | `http://localhost:5173` |
| `GYNFEM_LOG_LEVEL` | No (por defecto `INFO`) | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |

El host y el puerto no son configuración de la aplicación: son argumentos de
uvicorn.

### 5.2 Comando de arranque

```powershell
Copy-Item .env.example .env
.venv\Scripts\python.exe -m uvicorn app.main:app --env-file .env --no-access-log --no-server-header
```

- `--env-file .env`: uvicorn carga `.env` antes de importar la aplicación. La
  aplicación no lee `.env` por su cuenta.
- `--no-access-log`: el log de acceso de uvicorn registra el path y la query
  string, que pueden llevar datos clínicos. Lo reemplaza el log de acceso
  propio, que registra la plantilla de la ruta (`docs/SECURITY.md`, Sección 2).
  La aplicación ya desactiva ese logger al arrancar, así que el flag es una
  segunda barrera y no la única.
- `--no-server-header`: no anuncia el servidor en la cabecera `server`.

Comprobación: `GET http://127.0.0.1:8000/api/v1/health` devuelve
`{"status": "ok", "version": "…", "timestamp": "…"}`. La documentación
interactiva está en `http://127.0.0.1:8000/api/v1/docs`, salvo en
`production`.

### 5.3 Arranque fallido por configuración

Si falta una variable obligatoria o alguna es inválida, el proceso termina
**antes de aceptar peticiones**, con código 1 y sin traza. El mensaje nombra
la variable, nunca su valor. Ejemplo, sin `GYNFEM_CORS_ORIGINS`:

```text
Configuración inválida:
  - GYNFEM_CORS_ORIGINS: falta la variable obligatoria
```

## 6. Despliegue en la nube

| Destino | Fase | Estado |
| --- | --- | --- |
| Supabase (proyecto y base de datos) | PENDIENTE (Fase 9) | Se documentará al implementarse |
| Render (backend) | PENDIENTE (Fase 12) | Se documentará al implementarse |
| Vercel (frontend) | PENDIENTE (Fase 14) | Se documentará al implementarse |

Las variables de la aplicación son las de la Sección 5.1. Los comandos de
build y la configuración de los tres servicios —incluido el valor de
`GYNFEM_CORS_ORIGINS` en producción y el uso de `/api/v1/health` como health
check de Render— se documentarán en su fase.
