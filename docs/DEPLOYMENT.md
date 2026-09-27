# DEPLOYMENT — Despliegue

- **Alcance de este documento:** cómo preparar el entorno, reproducir en local
  el pipeline de datos y ML, arrancar la API en local, y el estado del
  despliegue en la nube. La arquitectura está en `docs/ARCHITECTURE.md` y la estrategia de
  pruebas en `docs/TEST_STRATEGY.md`.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  en la Fase 7 (esqueleto de la API), PR #6, en la Fase 8 (predicción sin
  persistencia), PR #7, en la Fase 9 (base de datos), PR #8, en la Fase 11
  (autenticación y autorización), PR #10, y en la Fase 12 (despliegue del
  backend en Render), PR #11.
- **Convención:** lo que aún no existe se marca
  **PENDIENTE (Fase N) — se documentará al implementarse**.

---

## 1. Estado

**La API está desplegada en Render desde la Fase 12** (Sección 7), contra el
proyecto de Supabase de la Fase 9 (Sección 6). El frontend es PENDIENTE
(Fases 13 y 14). El pipeline de datos, el entrenamiento y los tests se ejecutan
en local (Secciones 2 a 5).

**Un solo proyecto de Supabase, que es producción.** Desde la Fase 12 no se
escriben datos sintéticos en él salvo en una verificación puntual con limpieza
posterior (Sección 7.7). Un proyecto de desarrollo aparte (el plan Free admite
dos) es una mejora futura, no una necesidad de esta fase.

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
| `GYNFEM_SUPABASE_URL` | Sí (Fase 11) | `https://<project-ref>.supabase.co`, sin ruta, query ni credenciales. `http` solo hacia localhost y nunca en `production`. De ella salen el emisor esperado del JWT (`{url}/auth/v1`) y el JWKS | `http://localhost:54321` |
| `GYNFEM_SUPABASE_SECRET_KEY` | Sí (Fase 11) | Clave secreta del proyecto (`sb_secret_…`, en *Project Settings → API Keys*) o la `service_role` heredada. Solo para la Admin API de Auth. Es un secreto (`docs/SECURITY.md`, Sección 2.2) | `cambiar` |
| `GYNFEM_AUTH_HTTP_TIMEOUT_S` | No (por defecto 5) | Segundos > 0 de cada llamada a Supabase Auth (JWKS y Admin API) | `5` |

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
| Render (backend) | **Fase 12** | Servicio `gynfem-api`, plan Free, región Oregon, definido como código en `render.yaml` (Sección 7) |
| Vercel (frontend) | PENDIENTE (Fase 14) | Se documentará al implementarse |

Las variables de la aplicación son las de la Sección 5.1; las de Render, las
de la Sección 7.3. `/api/v1/health/ready` **no** es el health check de Render:
exige administrador (un health check sin token recibiría 401 y Render
reiniciaría en bucle) y consulta la base (una caída momentánea de Supabase
provocaría reinicios en cadena, y reiniciar no la arregla).

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
solo informa el tipo. Rechaza una URL al puerto 6543 (pooler en modo
Transaction), donde el bloqueo consultivo no serializaría nada. `status` solo
lee: no crea nada en una base nueva.

**Reglas de un archivo de migración.** Sin `BEGIN`, `COMMIT`, `ROLLBACK`,
`END`, `ABORT` ni `START TRANSACTION` fuera de los cuerpos `$$` de las
funciones (un `COMMIT` intermedio confirmaría media migración sin registrarla),
y sin `CONCURRENTLY`: el runner los rechaza. Cada migración corre con
`lock_timeout` de 5 s: si una tabla está bloqueada por la aplicación, falla en
vez de dejar en cola todas las consultas siguientes, y se reintenta. El
checksum cubre el `.up.sql`: un `.down.sql` sí puede corregirse después de
aplicado, porque no cambia lo que hay en la base.

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

**Cifrado.** `sslmode=require` cifra la conexión pero no verifica el
certificado del servidor. Decidido en la Fase 12: **`require` en producción por
ahora**; `sslmode=verify-full` con el certificado raíz de Supabase
(`sslrootcert`, público y versionable) queda **PENDIENTE (fase por
confirmar)**, para no mezclar dos cambios nuevos en el primer despliegue.

**En el despliegue (Fase 12).** Las migraciones **nunca** se ejecutan al
arrancar ni en el build (`test_el_arranque_no_migra`). Se aplican a mano, desde
la máquina de quien migra y **antes** de fusionar en `main` el código que las
necesita (Sección 7.5). Un código desplegado antes que su migración responde
`schema_outdated` en `/health/ready` y en toda ruta protegida si falta la tabla
de perfiles.

### 6.3 Supabase Auth y el primer administrador (Fase 11)

**Configuración del proyecto** (panel de Supabase, hecha en la Fase 11):

| Dónde | Valor |
| --- | --- |
| *Authentication → Providers* | Solo **Email** habilitado. *Confirm email* desactivado hasta el despliegue real (Fase 12) |
| *Authentication → Sign In / Providers* | *Allow new users to sign up*: **OFF**. Los usuarios los crea el administrador (HU002) |
| *Project Settings → JWT Keys* | Clave de firma **ECC (P-256), ES256**. *Access token expiry*: **3600 s** |

**Primer administrador.** Con el registro público cerrado, una base limpia (en
local o en Render) no tiene a nadie que pueda crear usuarios. Tras aplicar las
migraciones, **en una terminal propia** (la contraseña se pide sin eco y nunca
es un argumento):

```powershell
.venv\Scripts\python.exe -m app.db.migrate --env-file .env up
.venv\Scripts\python.exe -m app.auth.bootstrap --env-file .env --email <correo> --full-name "<Nombre Apellido>"
```

| Situación | Resultado |
| --- | --- |
| No hay ningún administrador activo | Pide la contraseña dos veces (12–72 bytes), crea la cuenta en Supabase Auth ya confirmada, y el perfil. Imprime `Administrador creado: <uuid>` |
| El correo ya existe en Supabase Auth (base limpiada, fallo a medias) | No pide contraseña: reutiliza la cuenta y la deja como administrador activo. `Administrador restablecido con la cuenta existente: <uuid>` |
| Ya hay un administrador activo | Sale con código 1: `ya existe un administrador activo; gestione los usuarios con la API` |
| Faltan las migraciones | Sale con código 1 y lo dice |

Nunca imprime el correo ni la contraseña. Para automatizar, `--password-stdin`
lee la contraseña de la entrada estándar. Si se pierden todos los
administradores activos, el mismo comando vuelve a funcionar (procedimiento de
emergencia). Queda auditado como `user.bootstrap_admin`.

Los demás usuarios los crea el administrador con `POST /api/v1/users`
(`docs/API_SPEC.md`, Sección 3.6).

## 7. Backend en Render (Fase 12)

El servicio está definido como código en **`render.yaml`** (raíz del
repositorio). Es público: ninguna variable secreta o que identifique el
proyecto lleva valor ahí, solo su nombre con `sync: false`, y Render la pide al
crear el Blueprint. `tests/api/test_render_config.py` fija lo que no puede
cambiar sin una decisión.

| | Valor | Motivo |
| --- | --- | --- |
| Servicio | `gynfem-api`, tipo `web`, runtime `python` | — |
| Plan y región | **Free**, **Oregon** | Decisión 1. Supabase sigue en São Paulo (latencia: Sección 7.8) |
| Rama | **`main`**, `autoDeployTrigger: commit` | Decisión 3: cada commit en `main` despliega; ninguna otra rama |
| Python | `PYTHON_VERSION=3.12.10` | La versión exacta que entrenó y validó el modelo. Render exige la versión completa en esta variable |
| Build | `pip install -r requirements.txt` | Solo las dependencias de producción; `pgserver` y `PyYAML` están en `requirements-dev.txt` |
| Arranque | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --no-access-log --no-server-header --proxy-headers --forwarded-allow-ips "*"` | Ver abajo |
| Health check | **`/api/v1/health`** | Público y sin base (Sección 6). Nunca `/api/v1/health/ready` |

**Por qué ese arranque (decisión A).**

- **Un solo proceso de uvicorn, sin gunicorn.** Medido en local, un proceso
  con el modelo cargado ocupa **≈186 MB** de memoria residente (Python 17 MB,
  importaciones 150 MB, modelo +27 MB, aplicación +7 MB) de los 512 MB del plan
  Free. Dos procesos rondarían 370 MB más los picos, y la CPU del plan no
  ganaría nada. Gunicorn añadiría un proceso maestro sin beneficio con un solo
  trabajador; si el proceso muere, Render lo reinicia.
- El modelo (200 árboles, 92 638 nodos, `n_jobs=1`) no lanza un hilo por
  núcleo; `predict_proba` tarda ≈10 ms en local.
- `--no-access-log` y `--no-server-header`: la misma política de la Fase 7
  (Sección 5.2).
- `--proxy-headers --forwarded-allow-ips "*"`: Render termina TLS en su proxy;
  sin ellas, una redirección (una barra final) apuntaría a `http://`. Confiar
  en cualquier IP es aceptable **solo** porque el servicio es inalcanzable
  salvo a través de ese proxy.
- Tiempos de espera: los de uvicorn. Los de la base ya los fija la aplicación
  (Sección 5.1).
- La validación de la Fase 7 se mantiene: si falta una variable obligatoria o
  el contrato del modelo no se verifica, el proceso termina **al arrancar** con
  el mensaje en los logs de Render (Secciones 5.3 y 5.4), y el despliegue
  queda como fallido sin sustituir al anterior.

### 7.1 Requisitos previos

- Acceso de administración al repositorio de GitHub y una cuenta de Render
  vinculada a GitHub con acceso a ese repositorio.
- El proyecto de Supabase con todas las migraciones aplicadas (Sección 6.2) y
  Supabase Auth configurado (Sección 6.3).
- Un `.env` local con las variables de la Sección 5.1, la de migraciones y las
  del guion de verificación (Sección 7.7).

### 7.2 Crear el servicio (una vez)

1. En Render, *New → Blueprint*. Elegir el repositorio y la rama que contiene
   `render.yaml` (`main` una vez fusionado el PR #11).
2. Render lee `render.yaml` y muestra el servicio `gynfem-api` (Web Service,
   Free, Oregon) y un formulario con las cuatro variables `sync: false`.
3. Pegar sus valores (Sección 7.3) directamente en el formulario y pulsar
   *Apply*. Nunca se escriben en el repositorio.
4. *Logs*: el build instala `requirements.txt` y termina con *Build
   successful*; el arranque no muestra `Configuración inválida` ni `Contrato
   del modelo inválido`, y el despliegue termina con *Your service is live*.
5. *Events*: el despliegue figura como *Deploy live*, y
   `https://<servicio>.onrender.com/api/v1/health` responde
   `{"status": "ok", "version": "…", "timestamp": "…"}`.
6. *Metrics*: la memoria debe rondar los 190–250 MB.

Render solo pide las variables `sync: false` al **crear** el Blueprint: para
cambiarlas después se usa *Environment* en el servicio, que redespliega.

### 7.3 Variables de entorno en Render

| Variable | Dónde | Secreta | Valor o formato |
| --- | --- | --- | --- |
| `PYTHON_VERSION` | `render.yaml` | No | `3.12.10` |
| `GYNFEM_ENVIRONMENT` | `render.yaml` | No | `production` |
| `GYNFEM_LOG_LEVEL` | `render.yaml` | No | `INFO` |
| `GYNFEM_CORS_ORIGINS` | Consola | No | **`https://gynfem-frontend.invalid` hasta la Fase 14**: `.invalid` es un dominio reservado (RFC 2606) que nunca resuelve, así que ningún navegador coincide y CORS queda cerrado sin comodín; pasa la validación de production (https, no localhost). **En la Fase 14 se sustituye** por el origen real de Vercel |
| `GYNFEM_DATABASE_URL` | Consola | **Sí** | Pooler de Supabase en modo **Transaction** (puerto 6543), `postgresql://…?sslmode=require`, contraseña codificada para URL |
| `GYNFEM_SUPABASE_URL` | Consola | No, pero identifica el proyecto | `https://<project-ref>.supabase.co` |
| `GYNFEM_SUPABASE_SECRET_KEY` | Consola | **Sí** | Clave secreta `sb_secret_…` (*Project Settings → API Keys*) |

Las opcionales del pool y de Auth (Sección 5.1) no se declaran: rigen sus
valores por defecto. `GYNFEM_MIGRATIONS_DATABASE_URL` **nunca** va a Render: las
migraciones se aplican desde local (`test_la_url_de_migraciones_no_llega_a_render`).

### 7.4 Despliegues

Cada commit en `main` despliega solo. Un despliegue cuyo arranque falla (una
variable, el contrato del modelo) no sustituye al anterior: Render mantiene la
versión que estaba viva y marca el despliegue como fallido en *Events*.

### 7.5 Orden cuando hay migraciones

1. Antes de fusionar: `status` contra producción (Sección 6.2) muestra la
   migración nueva como pendiente.
2. Aplicarla: `.venv\Scripts\python.exe -m app.db.migrate --env-file .env up`.
   Debe ser **compatible con el código que sigue desplegado** (añadir, no
   renombrar ni borrar), porque durante unos minutos convive con él.
3. Fusionar en `main`: Render despliega el código que la usa.
4. `/api/v1/health/ready` (con token de administrador) responde `ready`.

### 7.6 Primer administrador en producción

El procedimiento de la Sección 6.3 (`python -m app.auth.bootstrap`), desde
local contra la misma base. Producción usa el proyecto de Supabase de las
Fases 9 a 11, así que la cuenta de administrador ya existe en Supabase Auth: el
comando la reutiliza sin pedir contraseña.

### 7.7 Verificación posterior al despliegue

Repetible, tras cada despliegue, **sin crear datos clínicos**:

```powershell
.venv\Scripts\python.exe -m ops.verificar_despliegue --url https://<servicio>.onrender.com --env-file .env
```

Lee de `.env` por nombre `GYNFEM_SUPABASE_URL`,
`GYNFEM_SUPABASE_PUBLISHABLE_KEY`, `GYNFEM_SMOKE_ADMIN_EMAIL` y
`GYNFEM_SMOKE_ADMIN_PASSWORD` (el administrador). Comprueba salud y versión,
documentación cerrada (404), 401 sin token y con token alterado, inicio de
sesión en Supabase, rol de la base, readiness, rol insuficiente (403 en
pacientes) y correcto (200 en usuarios), predicción normal, con aviso de
extrapolación y rechazada (422), errores 404 y 405 uniformes y sin detalles
internos, y la latencia de `/health`, `/health/ready` y `/me`. Imprime solo
estados y códigos, nunca un token, un correo ni una clave, y sale con código 1
si algo falla. Si el servicio dormía, la primera línea mide el despertar.

La verificación **del flujo clínico** (crear, buscar, medir, corregir y dar de
baja, como médico) escribe datos que la base nunca borra físicamente. Se hizo
**una sola vez**, en la Fase 12, antes de que hubiera datos reales, y se limpió
con `down --steps 8` + `up` y el primer administrador de nuevo (Sección 6.3).
Con datos reales, **nunca** se repite esa limpieza.

### 7.8 Qué revisar en los logs

En *Logs* de Render, una línea JSON por evento (`docs/SECURITY.md`, Sección 2):

- `gynfem.access`: método, **plantilla** de la ruta, estado y `duration_ms`.
  Las peticiones del health check de Render aparecen como `/api/v1/health`.
- `gynfem.auth`: `user_id` (UUID opaco) y `auth_outcome`. Un pico de
  `invalid_token` o `not_authenticated` es tráfico sin credenciales; de
  `account_disabled`, un usuario desactivado que sigue intentándolo.
- `gynfem.errors`: el tipo de la excepción y la pila, nunca su mensaje.
  `database_unavailable` repetido: revisar el estado del proyecto de Supabase
  (el plan Free lo pausa tras días de inactividad).
- Nunca debe aparecer un valor clínico, un nombre, un documento, un token, un
  correo ni una cadena de conexión. Si aparece, es un fallo de seguridad
  (`docs/SECURITY.md`, rotación).

**Latencia hacia Supabase (decisión E).** El `duration_ms` de
`/api/v1/health/ready` es solo trabajo contra la base, y el de `/api/v1/me`,
exactamente una transacción (la lectura del perfil): su mediana, restada la de
`/api/v1/health`, es el coste de la base medido desde Render.

### 7.9 Revertir un despliegue

1. **Código**: en Render, *Events* → el último despliegue correcto →
   *Rollback*. Redespliega ese build sin tocar la base, en segundos. Después,
   revertir el commit en `main` (`git revert`), o el siguiente despliegue
   automático volvería a publicar el código defectuoso.
2. **Migración**: solo si la causa es la migración y su reversión es segura con
   los datos que ya hay. `down` (Sección 6.2) **antes** de hacer el *Rollback*
   del código, porque el código anterior espera el esquema anterior.
3. Verificar con `ops.verificar_despliegue` (Sección 7.7).

### 7.10 Plan Free: suspensión e impacto en la sustentación (decisión B)

Render **suspende un servicio Free tras 15 minutos sin tráfico**, y despertarlo
«tarda alrededor de un minuto» (documentación de Render, *Deploy for Free*),
con la carga del modelo encima. Además, el plan Free da 750 horas de instancia
al mes por espacio de trabajo, suficientes para un servicio.

Para una demostración en vivo:

1. **Cinco minutos antes**, abrir `https://<servicio>.onrender.com/api/v1/health`
   y esperar el 200; después, una predicción, para que la primera petición real
   no pague ningún arranque.
2. No dejar más de 15 minutos sin peticiones durante la demostración.
3. **Recomendado para la semana de la sustentación: el plan de pago Starter**
   (7 USD/mes según la página de precios de Render; confirmarlo al contratar,
   se factura prorrateado). No se suspende, y su CPU hace el arranque tras un
   despliegue más corto. Se cambia en *Settings → Instance type* y se vuelve a
   Free después, sin tocar `render.yaml`.

**No** se usan servicios externos que hagan ping periódico para mantenerlo
despierto: el plan Free existe para que los servicios inactivos duerman.
