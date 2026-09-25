# DEPLOYMENT — Despliegue

- **Alcance de este documento:** cómo preparar el entorno, reproducir en local
  el pipeline de datos y ML, arrancar la API en local, y el estado del
  despliegue en la nube. La arquitectura está en `docs/ARCHITECTURE.md` y la estrategia de
  pruebas en `docs/TEST_STRATEGY.md`.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  en la Fase 7 (esqueleto de la API), PR #6, en la Fase 8 (predicción sin
  persistencia), PR #7, y en la Fase 9 (base de datos), PR #8.
- **Convención:** lo que aún no existe se marca
  **PENDIENTE (Fase N) — se documentará al implementarse**.

---

## 1. Estado

**No hay nada desplegado** salvo la base de datos: desde la Fase 9 existe el
proyecto de Supabase con su esquema (Sección 6). La API, los scripts y los
tests se ejecutan en local (Sección 5).

## 2. Entorno local verificado

| Elemento | Valor | Fuente |
| --- | --- | --- |
| Python | 3.12.10 | Cabeceras de los tres reportes de `reports/ml/`; `models/model_metadata.json` |
| Sistema donde se generaron los artefactos | Windows (rutas `.venv\Scripts\python.exe`) | Comandos de regeneración de los reportes |
| Dependencias de datos y ML | `pandas==3.0.6`, `numpy==2.5.3`, `matplotlib==3.11.2`, `pytest==9.1.1`, `scikit-learn==1.9.1`, `joblib==1.6.0` | `requirements.txt` |
| Dependencias de la API (Fase 7) | `fastapi==0.141.1`, `starlette==1.7.0`, `pydantic==2.13.5`, `pydantic-settings==2.15.0`, `uvicorn==0.53.0`, `python-dotenv==1.2.3` (lo usan `uvicorn --env-file` y el runner de migraciones), `httpx2==2.13.1` (cliente de `TestClient`; Starlette 1.7 marca `httpx` como obsoleto para ese uso) | `requirements.txt` |
| Dependencias de la base de datos (Fase 9) | `psycopg[binary]==3.3.6`, `psycopg-pool==3.3.3` | `requirements.txt` |
| Solo para los tests (Fase 9) | `pgserver==0.1.4`: PostgreSQL 16.2 embebido para `tests/database/`, sin red. **No se instala en el despliegue** | `requirements-dev.txt` |

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
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` incluye `requirements.txt` y añade lo que solo necesitan
los tests. El despliegue (Render, Fase 12) instala únicamente
`requirements.txt` (`test_pgserver_solo_en_las_dependencias_de_desarrollo`).

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
| Solo la suite de ML | `.venv\Scripts\python.exe -m pytest tests --ignore=tests\api --ignore=tests\database` |
| Solo la suite de base de datos (PostgreSQL embebido; la primera vez tarda unos 15 s en arrancarlo) | `.venv\Scripts\python.exe -m pytest tests\database` |
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
| `GYNFEM_MODEL_DIR` | No (por defecto `models/` del repositorio) | Directorio con el `.joblib`, `model_metadata.json` y `feature_ranges.json`. Una ruta relativa se resuelve desde la raíz del repositorio, no desde el directorio de trabajo. Solo debe apuntar a un directorio que controle el operador: el `.joblib` se des-serializa (`docs/SECURITY.md`, Sección 2) | `models` |
| `GYNFEM_DATABASE_URL` | Sí | URL `postgresql://` (o `postgres://`) con host y nombre de base. En Supabase, la del **pooler en modo Transaction** (puerto 6543), con la contraseña codificada para URL. En `production` se exige `sslmode=require`, `verify-ca` o `verify-full`. Es un secreto (`docs/SECURITY.md`, Sección 2.2) | `postgresql://gynfem:cambiar@localhost:5432/gynfem` |
| `GYNFEM_DB_POOL_MIN_SIZE` | No (por defecto 1) | Entero > 0 | `1` |
| `GYNFEM_DB_POOL_MAX_SIZE` | No (por defecto 5) | Entero ≥ `GYNFEM_DB_POOL_MIN_SIZE` | `5` |
| `GYNFEM_DB_CONNECT_TIMEOUT_S` | No (por defecto 5) | Entero ≥ 2 (libpq trata cualquier valor menor como 2) | `5` |
| `GYNFEM_DB_POOL_TIMEOUT_S` | No (por defecto 5) | Segundos > 0 de espera por una conexión libre | `5` |
| `GYNFEM_DB_STATEMENT_TIMEOUT_MS` | No (por defecto 5000) | Milisegundos > 0 por sentencia, aplicados dentro de cada transacción | `5000` |

Los valores por defecto del pool son decisiones de ingeniería, no datos:
conservadores para el plan Free de Supabase y ajustables sin tocar el código.

El runner de migraciones lee además **`GYNFEM_MIGRATIONS_DATABASE_URL`** (Sección 6.2),
que la aplicación no usa.

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
`{"status": "ok", "version": "…", "timestamp": "…"}`, y
`GET http://127.0.0.1:8000/api/v1/health/ready` devuelve
`{"status": "ready", "checks": {"database": "ok", "schema": "ok"}}` si la base
responde y tiene todas las migraciones aplicadas (`docs/API_SPEC.md`,
Sección 3.4). La documentación
interactiva está en `http://127.0.0.1:8000/api/v1/docs`, salvo en
`production`. Una predicción de prueba, en PowerShell:

```powershell
$cuerpo = '{"age_years": 28, "temperature_c": 36.8, "heart_rate_bpm": 80, "systolic_bp_mmhg": 118, "diastolic_bp_mmhg": 76, "bmi_kg_m2": 22.5, "hba1c_percent": 5.2, "fasting_glucose_mg_dl": 85}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/predict -ContentType application/json -Body $cuerpo
```

El modelo se carga una vez al arrancar (alrededor de un segundo), no en cada
petición.

### 5.3 Arranque fallido por configuración

Si falta una variable obligatoria o alguna es inválida, el proceso termina
**antes de aceptar peticiones**, con código 1 y sin traza. El mensaje nombra
la variable, nunca su valor. Ejemplo, sin `GYNFEM_CORS_ORIGINS`:

```text
Configuración inválida:
  - GYNFEM_CORS_ORIGINS: falta la variable obligatoria
```

### 5.4 Arranque fallido por el contrato del modelo

Al arrancar se valida el contrato del modelo (`docs/ML_SPEC.md`, Sección 9.9).
Si no coincide, el proceso termina **antes de aceptar peticiones**, con código
1, sin traza y con un mensaje que nombra la parte del contrato que falla.
Ejemplo real, con una copia de `models/` cuyo metadata intercambia las
posiciones de la sistólica y la diastólica, apuntada con `GYNFEM_MODEL_DIR`:

```text
Contrato del modelo inválido: el orden de features del metadata no coincide con el del modelo (feature_names_in_).
```

No se corrige editando `models/`: sus artefactos los genera
`scripts/train_model.py` (Sección 3).

### 5.5 Arranque con la base caída

La conexión con la base **no** se comprueba al arrancar: el pool se abre en
segundo plano. Si Supabase no responde (caída, red, o proyecto Free pausado
por inactividad), la API arranca igual, `/api/v1/health` responde 200 y
`/api/v1/health/ready` responde 503 con `database_unavailable`. Si responde
pero le faltan migraciones, 503 con `schema_outdated`: se aplican con la
Sección 6.2.

## 6. Despliegue en la nube

| Destino | Fase | Estado |
| --- | --- | --- |
| Supabase (proyecto y base de datos) | **Fase 9** | Proyecto `gynfem`, región South America (São Paulo), plan Free, PostgreSQL 17.6. Esquema aplicado con las migraciones de `migrations/` (Sección 6.2) |
| Render (backend) | PENDIENTE (Fase 12) | Se documentará al implementarse |
| Vercel (frontend) | PENDIENTE (Fase 14) | Se documentará al implementarse |

Las variables de la aplicación son las de la Sección 5.1. Los comandos de
build y la configuración de Render y Vercel —incluido el valor de
`GYNFEM_CORS_ORIGINS` en producción y el uso de `/api/v1/health` como health
check de Render— se documentarán en su fase. `/api/v1/health/ready` **no** es
el health check de Render: reiniciar la instancia no arregla una base caída.

### 6.1 Conexiones a Supabase

| Uso | Cadena del panel (*Connect*) | Puerto | Variable | Por qué |
| --- | --- | --- | --- | --- |
| La API | Pooler en modo **Transaction** | 6543 | `GYNFEM_DATABASE_URL` | Conexiones cortas y compartidas. No admite sentencias preparadas: el pool las desactiva (`app/db/pool.py`) |
| Las migraciones | Pooler en modo **Session** | 5432 | `GYNFEM_MIGRATIONS_DATABASE_URL` | Una sesión estable, necesaria para el bloqueo consultivo del runner. La conexión directa del plan Free es solo IPv6; el pooler admite IPv4 |

Ambas con `?sslmode=require` al final y la contraseña codificada para URL (los
caracteres `@ : / ? # %` de la contraseña rompen la URL si no se codifican).

### 6.2 Procedimiento de migración

**El esquema solo cambia con una migración.** Nunca se modifica a mano desde el
panel de Supabase (Table Editor o SQL Editor). Si ocurre, se corrige creando
una migración nueva que lleve el esquema al estado correcto, nunca editando una
ya aplicada: el runner la rechazaría por su checksum.

```powershell
# Estado: cuántas hay aplicadas y cuáles faltan
.venv\Scripts\python.exe -m app.db.migrate --env-file .env status
# Aplicar todas las pendientes, en orden
.venv\Scripts\python.exe -m app.db.migrate --env-file .env up
# Revertir la última (o las N últimas con --steps N)
.venv\Scripts\python.exe -m app.db.migrate --env-file .env down
```

`--env-file` lee solo `GYNFEM_MIGRATIONS_DATABASE_URL` de ese archivo; sin él,
se lee del entorno. El runner nunca imprime la URL, y de un error de conexión
solo informa el tipo.

**Crear una migración.** Dos archivos con el número siguiente, sin huecos:
`migrations/NNNN_nombre.up.sql` y `NNNN_nombre.down.sql`. La reversión deja el
catálogo exactamente como estaba (`test_cada_migracion_revierte_y_reaplica`
lo comprueba para cada una). Toda tabla nueva se crea con
`ENABLE ROW LEVEL SECURITY` y el `REVOKE` para `anon` y `authenticated` en la
misma migración (`test_rls_habilitado_en_todas_las_tablas` recorre todas).

**Si una migración falla a medias.** Cada migración corre en una sola
transacción: PostgreSQL deshace todo lo de esa migración, que queda sin
registrar. Las anteriores siguen aplicadas. El runner sale con código 1 y el
mensaje del servidor (por ejemplo, un error de sintaxis). Se corrige el
archivo, que aún no está aplicado, y se vuelve a ejecutar `up`. Si la conexión
se corta justo durante el `COMMIT`, `status` dice si quedó aplicada. Las
sentencias que no admiten transacción (`CONCURRENTLY`) se rechazan antes de
ejecutar nada.

**En el despliegue (Fase 12).** Las migraciones se aplican antes de la
versión del código que las necesita. Si Render no ofrece un comando previo al
despliegue en el plan elegido, se aplican desde local con el comando de
arriba. Un código desplegado antes que su migración responde
`schema_outdated` en `/health/ready`.
