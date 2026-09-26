# SECURITY — Seguridad

- **Alcance de este documento:** los controles de seguridad y privacidad que ya
  rigen en el repositorio, los previstos con su fase, y las advertencias
  clínicas obligatorias sobre el uso del modelo. Las cifras del modelo
  pertenecen a `docs/ML_SPEC.md` y a `reports/ml/training_report.md`; aquí se
  citan. El contrato de la API está en `docs/API_SPEC.md`.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  en la Fase 7 (esqueleto de la API), PR #6, en la Fase 8 (predicción sin
  persistencia), PR #7, en la Fase 9 (base de datos), PR #8, y en la Fase 10
  (persistencia clínica), PR #9.
- **Convención:** lo que aún no existe se marca
  **PENDIENTE (Fase N) — se documentará al implementarse**. Donde la fase no
  está asignada todavía se indica **fase por confirmar**.

---

## 1. Superficie actual

El repositorio contiene scripts de datos, un modelo serializado, reportes,
tests y la API (`app/`). Desde la Fase 8 la API **recibe datos clínicos**
(`POST /api/v1/predict`) y carga el modelo al arrancar. Desde la Fase 9 existe
la base de datos en Supabase. **Desde la Fase 10 la API guarda datos
personales y clínicos**: identidad de la paciente (documento, nombres y
apellidos), sus mediciones y sus predicciones (`docs/API_SPEC.md` §3.5).
**No hay autenticación ni datos de usuarios**: los endpoints clínicos son
accesibles sin credenciales **por diseño y de forma temporal** (Sección 3.1).
Los controles de la Sección 2 son los únicos que aplican hoy.

## 2. Controles que ya rigen (verificables)

| Control | Cómo se verifica |
| --- | --- |
| **Ningún dato real de pacientes de GynFem.** El único dataset es la publicación de Hossain et al. (2026) en Mendeley Data, licencia CC BY 4.0. El repositorio es público | `data/raw/README.md`; visibilidad pública en GitHub (`jhanio/gynfem-backend`) |
| **Material de referencia local fuera de Git.** `workspace-reference/`, `*.docx` y `*.pdf` están ignorados | `.gitignore` |
| **Secretos fuera de Git.** `.env` y `.env.*` están ignorados, salvo `.env.example`. Este declara exactamente las variables de la aplicación y la del runner de migraciones, con valores locales de ejemplo y nunca reales. Desde la Fase 9 el código usa un secreto: las URL de la base, que llevan la contraseña (Sección 2.2) | `.gitignore`; `test_env_example_declara_exactamente_las_variables_de_settings`; `test_env_example_es_una_configuracion_valida_y_solo_local` |
| **Configuración validada al arrancar.** Si falta una variable obligatoria o es inválida, la API no arranca. El mensaje nombra la variable, nunca su valor | `tests/api/test_api_config.py` (`test_arranque_real_falla_sin_variable_obligatoria`, `test_mensaje_de_configuracion_no_repite_el_valor`); `test_mensaje_no_repite_la_database_url` |
| **CORS restringido.** Solo los orígenes de `GYNFEM_CORS_ORIGINS`, nunca `*` (tampoco dentro del host, como `https://*.vercel.app`). Cada origen es esquema, host en minúsculas y puerto válido, sin credenciales ni ruta. En `development` y `test`, solo localhost. En `production`, solo `https` y nunca localhost. Sin credenciales CORS | `tests/api/test_api_cors.py`; `test_comodin_se_rechaza`; `test_comodin_en_el_host_se_rechaza_en_produccion`; `test_origen_malformado_se_rechaza`; `test_en_produccion_se_exige_https_y_no_localhost` |
| **Logs sin datos clínicos ni identificadores.** Una línea JSON por evento, con `request_id`. Solo claves de una lista cerrada. Una predicción añade una línea `gynfem.prediction` con solo `risk_level`, `warning_count` y `duration_ms`: nunca un valor clínico ni el vector enviado al modelo, tampoco en un 422. Se registra la plantilla de la ruta, nunca el path real, la query string, las cabeceras ni el cuerpo. Si la plantilla no se puede reconstruir sin arriesgar un valor real (por ejemplo, un parámetro en el prefijo de un router padre), se registra `<sin coincidencia>`. De una excepción se registra el tipo y la pila, nunca su mensaje. Desde el código, sin depender del comando de arranque: `uvicorn.access` queda desactivado y `uvicorn.error` registra de una excepción solo su tipo | `tests/api/test_api_logging.py` (`test_logs_no_contienen_valores_clinicos`, con un valor centinela en path, query, cabecera, cuerpo y mensaje de excepción; `test_parametro_en_el_prefijo_de_un_router_padre_no_se_registra`; `test_el_log_de_acceso_de_uvicorn_queda_desactivado_sin_depender_del_flag`; `test_uvicorn_error_no_registra_el_mensaje_de_la_excepcion`); `test_los_logs_de_prediccion_no_contienen_valores_clinicos`; `test_el_log_de_prediccion_solo_lleva_el_resultado_agregado` |
| **Errores sin detalles internos.** Formato uniforme (`docs/API_SPEC.md`, Sección 2.5). El 500 no lleva traza, rutas del sistema ni el mensaje de la excepción. El 422 no repite el valor recibido | `test_excepcion_no_controlada_no_filtra_traza`; `test_error_de_validacion_no_refleja_el_valor` |
| **`/health` sin información interna.** Solo estado, versión de la aplicación y hora | `test_health_no_expone_informacion_interna` |
| **`/health/ready` sin detalles de la conexión.** Solo `ok` por comprobación, o un 503 con `database_unavailable` o `schema_outdated`. Nunca host, puerto, usuario, base, tipo ni mensaje de la excepción | `test_ready_no_expone_detalles_de_conexion` (con un servidor alcanzable cuyo error de libpq nombra host, puerto y usuario); `test_ready_200_no_expone_la_base` |
| **Logs sin datos personales ni clínicos de la persistencia (Fase 10).** Una escritura clínica añade una línea `gynfem.clinical` con solo `action` y `duration_ms`. El log de acceso registra la plantilla de la ruta (`/patients/{patient_id}`), nunca el id. Ningún nombre, documento, id ni valor clínico | `test_logs_sin_valores_clinicos_nombres_ni_documentos` (centinelas en nombres, documento y las 8 variables, recorriendo todos los endpoints) |
| **Minimización en las respuestas y en la búsqueda (Fase 10).** Ninguna respuesta expone `deleted_at`, `*_by`, `search_key` ni `replaces_measurement_id`. La búsqueda exige un criterio (documento exacto o nombre de al menos 3 caracteres), enmascara el documento, limita a 50 por página y no da el total | `test_respuestas_de_pacientes_sin_campos_internos`, `test_respuestas_de_mediciones_sin_campos_internos`, `test_busqueda_invalida_422`, `test_busqueda_enmascara_el_documento`, `test_listado_paginado_respeta_el_limite` |
| **Auditoría de toda escritura (Fase 10).** En la misma transacción que la escritura; sin valores: acción, entidad, id, actor, `request_id` y, en una actualización, solo los nombres de los campos | `test_crear_paciente_audita_patient_create`, `test_actualizar_audita_solo_nombres_de_campos`, `test_desactivar_audita_patient_deactivate`, `test_registrar_medicion_audita_medicion_y_prediccion`, `test_corregir_audita_correccion_y_prediccion` |
| **Logs sin datos de conexión.** De un fallo de la base se registra el tipo de la excepción. Los registros de psycopg y de su pool, que copian el mensaje de libpq, pierden el mensaje y no se propagan a otros handlers | `test_logs_sin_cadena_de_conexion`; `test_runner_no_imprime_la_cadena_de_conexion_al_fallar` y `…_al_funcionar` |
| **Validación de entrada en tres niveles** (`docs/API_SPEC.md`, Sección 2.3). Nivel a: un valor fuera de los límites fisiológicos (provisionales, `ML_SPEC.md`, Sección 5.1), o una diastólica no menor que la sistólica, se rechaza con 422 y **no llega al modelo**. Esquema estricto: solo números finitos, sin texto, booleanos, nulos, `NaN`, infinito ni campos extra. El 422 dice qué campo falla y por qué regla, nunca el valor. Nivel b: fuera del rango de entrenamiento se predice con aviso | `test_valor_imposible_422_sin_predecir` (16 casos, con un espía que confirma que el modelo no se llamó); `test_diastolica_no_menor_que_sistolica_422`; `test_entrada_malformada_422`; `test_nan_e_infinito_422`; `test_el_422_no_repite_el_valor`; `test_fuera_del_rango_200_con_aviso` |
| **Contrato del modelo verificado al arrancar.** Si el orden de features, el de clases, la versión de scikit-learn o los rangos no coinciden, la API no arranca (`ML_SPEC.md`, Sección 9.9) | `tests/api/test_model_contract.py` (`test_metadata_alterado_impide_cargar`, `test_arranque_real_falla_con_contrato_invalido`) |
| **El modelo solo se des-serializa desde el directorio del operador.** `joblib.load` ejecuta un pickle; solo lee `GYNFEM_MODEL_DIR`, fijado por quien despliega, nunca algo que envíe un cliente | Código (`app/services/model_loader.py`); no verificado por test |
| **Advertencia clínica en toda predicción** (Sección 4, advertencia 1) | `test_siempre_incluye_la_advertencia_clinica` |
| **`X-Request-ID` saneado.** Uno entrante se respeta solo si tiene de 1 a 64 caracteres `[A-Za-z0-9-]`; si no, se genera otro, para que no se puedan inyectar líneas en los logs. Riesgo residual: lo elige el cliente, así que el frontend debe enviar un UUID aleatorio y nunca un dato del paciente (`docs/API_SPEC.md`, Sección 2.6) | `test_request_id_malicioso_se_reemplaza` |
| **Documentación interactiva deshabilitada en producción** | `test_docs_deshabilitadas_en_produccion` |
| **Integridad del RAW por SHA-256.** El hash registrado en `data/raw/README.md` se comprueba con un test, y la limpieza aborta antes de leer o escribir si no coincide | `tests/test_raw_integrity.py`; `test_el_pipeline_aborta_si_el_raw_no_coincide_con_el_readme` |
| **Integridad del dataset procesado por SHA-256.** El entrenamiento aborta si el CSV no coincide con el hash de `data_cleaning_report.md`, y el metadata del modelo registra ese hash | `test_el_entrenamiento_aborta_si_el_dataset_no_coincide_con_su_sha`; `test_el_sha_del_dataset_en_el_metadata_es_el_del_csv_commiteado` |
| **Git no altera los bytes de los CSV.** Se marcan como `binary` a fin de que `core.autocrlf` no cambie su SHA-256 | `.gitattributes`; `test_gitattributes_protege_los_csv_generados_de_la_conversion_de_eol` |

### 2.1 La columna `Name`

`Name` existe en el RAW y **se versiona sin alterar**, solo a fin de conservar el
SHA-256 frente a la fuente original. Sus valores provienen de la publicación
original y no pertenecen a pacientes de GynFem (`data/raw/README.md`).

Qué se garantiza y cómo, sin exagerar el alcance de los tests:

| Garantía | Respaldo |
| --- | --- |
| `prepare_dataset.py` descarta `Name` antes de cualquier otra transformación | Código; `ML_SPEC.md`, Sección 3 |
| Ningún valor de `Name` aparece en las dos variantes de `data/processed/`, ni en la cabecera ni en el cuerpo | `test_salida_no_contiene_name_ni_patient_id`; `test_ningun_valor_de_name_aparece_en_el_cuerpo_de_la_salida` |
| Ningún valor de `Name` aparece en `model_metadata.json`, `feature_ranges.json`, `training_metrics.json`, `training_report.md` ni en el `.joblib` (en el `.joblib`, solo tokens de ≥3 caracteres: 1 de los 5794 valores distintos queda fuera, según el docstring del test) | `test_ningun_artefacto_generado_contiene_valores_de_name`; `test_el_modelo_serializado_no_contiene_valores_de_name` |
| Aclaración: `ML_SPEC.md`, Sección 3, deja los reportes fuera del alcance de los tests de `test_prepare_dataset.py`; el barrido de `training_report.md` lo hace `test_train_model.py` (fila anterior) | — |
| Los tests que leen `Name` informan **cuántas** coincidencias hubo, nunca cuáles | `data_cleaning_report.md`, «Política sobre `Name`» |
| `Name` no se imprime en logs ni salida de consola | **Propiedad del código, no verificada por test** (`ML_SPEC.md`, Sección 3) |

### 2.2 Base de datos (Fase 9)

**Barreras de acceso.** El backend es el único que accede a la base. Tres
barreras independientes impiden que la Data API de Supabase (PostgREST, con la
*anon key*, que es pública porque va en el frontend) llegue a las tablas:

| Barrera | Cómo | Test |
| --- | --- | --- |
| Esquema no expuesto | Las tablas viven en `gynfem`, no en `public`. En el panel, *Settings → API → Data API → Exposed schemas* lista solo `public` y `graphql_public` (comprobado al configurar el proyecto) | — (configuración del panel) |
| Sin privilegios | Cada migración revoca todo a `PUBLIC`, `anon` y `authenticated` sobre el esquema, sus tablas y sus funciones. Sin `USAGE` sobre el esquema, ni siquiera un `GRANT` por error en una tabla futura da acceso | `test_roles_de_la_data_api_sin_privilegios`; `test_roles_de_la_data_api_no_leen_nada`; `test_el_esquema_cierra_el_paso_aunque_una_tabla_se_conceda` |
| **Row Level Security** | Habilitado en **todas** las tablas, en la misma migración que las crea, incluida la de control del runner. **Sin políticas:** las políticas concretas son **PENDIENTE (Fase 11)**, junto con la autenticación. Sin políticas, RLS niega toda fila a cualquier rol que no la omita | `test_rls_habilitado_en_todas_las_tablas` (recorre todas las tablas de los dos esquemas, también las futuras) |

**Límite declarado: RLS no restringe al backend.** La API se conecta con el
usuario `postgres` del pooler, que es el dueño de las tablas, y el dueño omite
RLS mientras no se use `FORCE ROW LEVEL SECURITY`. RLS protege el camino de la
Data API, no el del backend. Un rol de mínimo privilegio para la aplicación es
**PENDIENTE (Fase 11 o 12)**.

**Integridad impuesta por la base** (detalle en `docs/ERD.md`, Sección 4.3):
nada se borra físicamente; una predicción es inmutable; la auditoría es de solo
inserción y no tiene columnas donde quepa un valor clínico; ninguna tabla tiene
campos de contraseña ni de hash (`test_ninguna_tabla_tiene_campos_de_contrasena`):
la autenticación de la Fase 11 la hace Supabase Auth.

**Gestión de credenciales.**

| Credencial | Dónde vive | Quién la usa |
| --- | --- | --- |
| `GYNFEM_DATABASE_URL` (pooler Transaction) | Solo en `.env` en local y en las variables de entorno de Render (Fase 12) | La API |
| `GYNFEM_MIGRATIONS_DATABASE_URL` (pooler Session) | Solo en `.env` de quien migra | `python -m app.db.migrate` |
| *anon key*, URL del proyecto | `.env` | Nadie en la Fase 9; Supabase Auth en la Fase 11 |
| *service_role key* | `.env` | **Nadie.** La Fase 9 no la carga. Si la Fase 11 la necesita (por ejemplo, para crear usuarios en HU002), se decidirá allí |

- La URL de la base es `SecretStr`: su `repr`, `str` y volcado JSON la ocultan
  (`test_settings_no_expone_la_url`). Se lee en claro solo al crear el pool.
- En `production` se exige `sslmode=require`, `verify-ca` o `verify-full`
  (`test_en_produccion_se_exige_ssl`). `require` cifra pero no verifica el
  certificado: `verify-full` con el certificado raíz de Supabase queda como
  recomendación para la Fase 12 (`docs/DEPLOYMENT.md`, Sección 6.2).
- Ningún archivo versionado contiene un valor real: `.env.example` solo lleva
  URLs de `localhost` (`test_env_example_es_una_configuracion_valida_y_solo_local`).
- Los tests nunca usan la Supabase real: la fixture `entorno_limpio` borra
  toda variable `GYNFEM_*` heredada, y la suite de base de datos usa un
  PostgreSQL embebido en `127.0.0.1` (`test_la_suite_solo_usa_loopback`).

**Rotación.** La *service_role key* omite toda la seguridad de la base,
incluido RLS. Si aparece en un commit, un log, un chat o una captura, se rota
de inmediato, según el sistema de claves del proyecto: con las claves
heredadas (JWT), rotar el *JWT secret* en el panel, lo que regenera a la vez
la *anon key* y la *service_role key*; con las nuevas *API keys*, revocar la
clave secreta y crear otra. Después, actualizar `.env` y, desde la Fase 12,
las variables de Render, y revisar los *logs* de Supabase en busca de
accesos. Lo mismo con la contraseña de la base:
*Settings → Database → Reset database password*, y actualizar las dos URL.
Rotar invalida la credencial anterior en el acto. Borrar el commit no basta,
porque el repositorio es público.

## 3. Controles previstos

### 3.1 Deuda conocida: endpoints clínicos sin autenticación

**Estado:** los endpoints de `/api/v1/patients`, `/api/v1/measurements` y
`/api/v1/predictions` (Fase 10, PR #9) **no exigen credenciales**. Es una
decisión deliberada y temporal del plan, no un descuido: la autenticación y el
RBAC (HU001, HU002) son la Fase 11.

| | |
| --- | --- |
| **Cierre** | **PR #10 (Fase 11)**: Supabase Auth emite el JWT, FastAPI lo valida en `get_actor` y aplica RBAC |
| **Punto de enganche** | `app/api/deps.py:get_actor`. Todas las rutas clínicas dependen de él (`test_toda_ruta_clinica_depende_de_get_actor`); los servicios ya escriben el `user_id` del actor en `*_by` y en `audit_log.actor_user_id`, hoy `NULL` |
| **Condición bloqueante** | **La API no se despliega en un entorno accesible (Render, Fase 12) hasta cerrar esta deuda.** Hasta entonces solo corre en local |
| **Mitigaciones mientras tanto** | Sin listado abierto de pacientes, búsqueda con criterio mínimo y documento enmascarado, paginación con límite, respuestas mínimas, logs sin datos, auditoría de toda escritura. Los datos de prueba son sintéticos; la verificación contra la Supabase real se hizo con datos sintéticos, que después se eliminaron (`down --steps 7` y `up`) |

| Control | Fase | Alcance previsto |
| --- | --- | --- |
| Autenticación con JWT | PENDIENTE (Fase 11) | Supabase Auth emite el token y FastAPI lo valida (HU001) |
| RBAC | PENDIENTE (Fase 11) | Permisos diferenciados entre Médico y Administrador (`docs/PRD.md`, Sección 3) |
| Límites fisiológicos validados por el equipo médico | PENDIENTE (validación clínica con GynFem) | Sustituir los provisionales de `app/services/clinical_limits.py` (`ML_SPEC.md`, Sección 5.1) |
| Origen de producción en CORS | PENDIENTE (Fase 12) | El control ya existe (Sección 2); falta fijar en Render el origen del frontend desplegado |
| Auditoría del actor | Las escrituras se auditan desde la Fase 10, con `actor_user_id` en `NULL`; el actor real llega con la Fase 11. Auditar lecturas y fallos (`denied`, `error`): por decidir en la Fase 11 | `docs/ERD.md`, Sección 4.2 |
| Políticas RLS | PENDIENTE (Fase 11) | RLS ya está habilitado en todas las tablas (Sección 2.2); faltan las políticas por rol |
| Rol de mínimo privilegio para la API | PENDIENTE (Fase 11 o 12) | Que el backend no se conecte como dueño de las tablas (Sección 2.2) |
| Limitación de tasa | PENDIENTE (fase por confirmar) | Por definir |
| Pruebas de seguridad | PENDIENTE (Fase 17) | Parte de la validación integral (`docs/TEST_STRATEGY.md`, Sección 5) |

## 4. Advertencias clínicas obligatorias

Toda interfaz que muestre una predicción debe hacer visibles estas
advertencias. `ML_SPEC.md`, Sección 5, exige la de extrapolación y HU007 exige
una advertencia clínica; el carácter obligatorio del resto lo fija este
baseline a partir de las limitaciones documentadas.

**Qué entrega la API desde la Fase 8:** la advertencia 1 en
`clinical_disclaimer`, presente en toda predicción, y la 2 como
`extrapolation_warnings`, una por variable fuera del rango
(`docs/API_SPEC.md`, Sección 3.2). Las advertencias 3 a 5 no viajan en la
respuesta. Cómo se muestran todas es PENDIENTE (Fase 13).

1. **Apoyo, no diagnóstico.** La salida es una señal de apoyo que el personal
   clínico interpreta con su juicio profesional; no reemplaza la evaluación
   médica (`ML_SPEC.md`, Sección 1).
2. **Extrapolación fuera del rango de entrenamiento.** Fuera de los rangos de
   `models/feature_ranges.json`, la predicción no tiene respaldo empírico
   (`training_report.md`, Sección 11.1). Tres casos concretos:
   - **IMC máximo 27.9 kg/m².** El modelo nunca vio una gestante con obesidad
     (IMC ≥ 30), que es un grupo de riesgo elevado.
   - **HbA1c máxima 50.0 mmol/mol** (≈6.7 %), apenas por encima del umbral
     diagnóstico de diabetes (48 mmol/mol).
   - **Edad entre 15.0 y 47.0 años.**
3. **El dataset no es de GynFem.** Su población, instrumentación y criterio de
   etiquetado no son los del contexto peruano, y no hay validación externa
   (`training_report.md`, Sección 11.2).
4. **Las etiquetas son las del dataset original**, no un diagnóstico verificado
   de forma independiente (`training_report.md`, Sección 11.2).
5. **Banda de 93.0–94.9 °F.** No se ha verificado que el modelo no haya
   aprendido la regla «93–95 °F ⇒ alto riesgo» a partir de 42 filas con
   concordancia atípica (`ML_SPEC.md`, Sección 7.2). Esa banda (≈33.9–34.9 °C)
   está **dentro** del rango de entrenamiento, así que la API no emite aviso
   de extrapolación para ella.

A quien implemente la presentación: el orden de las probabilidades que
devuelve el modelo no es el de severidad (`ML_SPEC.md`, Sección 9.6).
