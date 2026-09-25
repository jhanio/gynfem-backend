# SECURITY — Seguridad

- **Alcance de este documento:** los controles de seguridad y privacidad que ya
  rigen en el repositorio, los previstos con su fase, y las advertencias
  clínicas obligatorias sobre el uso del modelo. Las cifras del modelo
  pertenecen a `docs/ML_SPEC.md` y a `reports/ml/training_report.md`; aquí se
  citan. El contrato de la API está en `docs/API_SPEC.md`.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5. Actualizado
  en la Fase 7 (esqueleto de la API), PR #6, y en la Fase 8 (predicción sin
  persistencia), PR #7.
- **Convención:** lo que aún no existe se marca
  **PENDIENTE (Fase N) — se documentará al implementarse**. Donde la fase no
  está asignada todavía se indica **fase por confirmar**.

---

## 1. Superficie actual

El repositorio contiene scripts de datos, un modelo serializado, reportes,
tests y la API (`app/`). Desde la Fase 8 la API **recibe datos clínicos**
(`POST /api/v1/predict`) y carga el modelo al arrancar. No los guarda: la
respuesta se devuelve y se descarta. **No hay base de datos, autenticación ni
datos de usuarios**, así que `/predict` es hoy accesible sin credenciales
(la autenticación llega en la Fase 11). Los controles de la Sección 2 son los
únicos que aplican hoy.

## 2. Controles que ya rigen (verificables)

| Control | Cómo se verifica |
| --- | --- |
| **Ningún dato real de pacientes de GynFem.** El único dataset es la publicación de Hossain et al. (2026) en Mendeley Data, licencia CC BY 4.0. El repositorio es público | `data/raw/README.md`; visibilidad pública en GitHub (`jhanio/gynfem-backend`) |
| **Material de referencia local fuera de Git.** `workspace-reference/`, `*.docx` y `*.pdf` están ignorados | `.gitignore` |
| **Secretos fuera de Git.** `.env` y `.env.*` están ignorados, salvo `.env.example`. Este declara exactamente las variables de la aplicación, con valores locales de ejemplo. Hoy el código no usa ningún secreto | `.gitignore`; `test_env_example_declara_exactamente_las_variables_de_settings`; `test_env_example_es_una_configuracion_valida_y_solo_local` |
| **Configuración validada al arrancar.** Si falta una variable obligatoria o es inválida, la API no arranca. El mensaje nombra la variable, nunca su valor | `tests/api/test_api_config.py` (`test_arranque_real_falla_sin_variable_obligatoria`, `test_mensaje_de_configuracion_no_repite_el_valor`) |
| **CORS restringido.** Solo los orígenes de `GYNFEM_CORS_ORIGINS`, nunca `*` (tampoco dentro del host, como `https://*.vercel.app`). Cada origen es esquema, host en minúsculas y puerto válido, sin credenciales ni ruta. En `development` y `test`, solo localhost. En `production`, solo `https` y nunca localhost. Sin credenciales CORS | `tests/api/test_api_cors.py`; `test_comodin_se_rechaza`; `test_comodin_en_el_host_se_rechaza_en_produccion`; `test_origen_malformado_se_rechaza`; `test_en_produccion_se_exige_https_y_no_localhost` |
| **Logs sin datos clínicos ni identificadores.** Una línea JSON por evento, con `request_id`. Solo claves de una lista cerrada. Una predicción añade una línea `gynfem.prediction` con solo `risk_level`, `warning_count` y `duration_ms`: nunca un valor clínico ni el vector enviado al modelo, tampoco en un 422. Se registra la plantilla de la ruta, nunca el path real, la query string, las cabeceras ni el cuerpo. Si la plantilla no se puede reconstruir sin arriesgar un valor real (por ejemplo, un parámetro en el prefijo de un router padre), se registra `<sin coincidencia>`. De una excepción se registra el tipo y la pila, nunca su mensaje. Desde el código, sin depender del comando de arranque: `uvicorn.access` queda desactivado y `uvicorn.error` registra de una excepción solo su tipo | `tests/api/test_api_logging.py` (`test_logs_no_contienen_valores_clinicos`, con un valor centinela en path, query, cabecera, cuerpo y mensaje de excepción; `test_parametro_en_el_prefijo_de_un_router_padre_no_se_registra`; `test_el_log_de_acceso_de_uvicorn_queda_desactivado_sin_depender_del_flag`; `test_uvicorn_error_no_registra_el_mensaje_de_la_excepcion`); `test_los_logs_de_prediccion_no_contienen_valores_clinicos`; `test_el_log_de_prediccion_solo_lleva_el_resultado_agregado` |
| **Errores sin detalles internos.** Formato uniforme (`docs/API_SPEC.md`, Sección 2.5). El 500 no lleva traza, rutas del sistema ni el mensaje de la excepción. El 422 no repite el valor recibido | `test_excepcion_no_controlada_no_filtra_traza`; `test_error_de_validacion_no_refleja_el_valor` |
| **`/health` sin información interna.** Solo estado, versión de la aplicación y hora | `test_health_no_expone_informacion_interna` |
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

## 3. Controles previstos

| Control | Fase | Alcance previsto |
| --- | --- | --- |
| Autenticación con JWT | PENDIENTE (Fase 11) | Supabase Auth emite el token y FastAPI lo valida (HU001) |
| RBAC | PENDIENTE (Fase 11) | Permisos diferenciados entre Médico y Administrador (`docs/PRD.md`, Sección 3) |
| Límites fisiológicos validados por el equipo médico | PENDIENTE (validación clínica con GynFem) | Sustituir los provisionales de `app/services/clinical_limits.py` (`ML_SPEC.md`, Sección 5.1) |
| Origen de producción en CORS | PENDIENTE (Fase 12) | El control ya existe (Sección 2); falta fijar en Render el origen del frontend desplegado |
| Auditoría | PENDIENTE (fase por confirmar; transversal) | Registro de quién hizo qué y cuándo (`docs/ERD.md`, Sección 2) |
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
