# SECURITY — Seguridad

- **Alcance de este documento:** los controles de seguridad y privacidad que ya
  rigen en el repositorio, los previstos con su fase, y las advertencias
  clínicas obligatorias sobre el uso del modelo. Las cifras del modelo
  pertenecen a `docs/ML_SPEC.md` y a `reports/ml/training_report.md`; aquí se
  citan. El contrato de la API está en `docs/API_SPEC.md`.
- **Fecha:** 2026-09-24 — Fase 3 (baseline documental), PR #5.
- **Convención:** lo que aún no existe se marca
  **PENDIENTE (Fase N) — se documentará al implementarse**. Donde la fase no
  está asignada todavía se indica **fase por confirmar**.

---

## 1. Superficie actual

El repositorio contiene scripts de datos, un modelo serializado, reportes y
tests. **No hay servidor, base de datos, autenticación ni datos de usuarios.**
Los controles de la Sección 2 son los únicos que aplican hoy.

## 2. Controles que ya rigen (verificables)

| Control | Cómo se verifica |
| --- | --- |
| **Ningún dato real de pacientes de GynFem.** El único dataset es la publicación de Hossain et al. (2026) en Mendeley Data, licencia CC BY 4.0. El repositorio es público | `data/raw/README.md`; visibilidad pública en GitHub (`jhanio/gynfem-backend`) |
| **Material de referencia local fuera de Git.** `workspace-reference/`, `*.docx` y `*.pdf` están ignorados | `.gitignore` |
| **Secretos fuera de Git.** `.env` y `.env.*` están ignorados (salvo `.env.example`, que hoy no existe). Hoy el código no usa ningún secreto | `.gitignore` |
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
| Validación de entrada con Pydantic (tecnología prevista en el plan del proyecto, no versionado) | PENDIENTE (Fase 8) | Los tres niveles de `docs/API_SPEC.md`, Sección 2.3 |
| CORS restringido | PENDIENTE (fase por confirmar) | Solo el origen del frontend desplegado |
| Logs sin datos clínicos | PENDIENTE (fase por confirmar) | Ningún valor clínico ni identificador de paciente en logs ni en mensajes de error |
| Auditoría | PENDIENTE (fase por confirmar; transversal) | Registro de quién hizo qué y cuándo (`docs/ERD.md`, Sección 2) |
| Limitación de tasa | PENDIENTE (fase por confirmar) | Por definir |
| Pruebas de seguridad | PENDIENTE (Fase 17) | Parte de la validación integral (`docs/TEST_STRATEGY.md`, Sección 5) |

## 4. Advertencias clínicas obligatorias

Toda interfaz que muestre una predicción debe hacer visibles estas
advertencias. `ML_SPEC.md`, Sección 5, exige la de extrapolación y HU007 exige
una advertencia clínica; el carácter obligatorio del resto lo fija este
baseline a partir de las limitaciones documentadas. Cómo se muestran es PENDIENTE (Fases 8 y 13).

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
   concordancia atípica (`ML_SPEC.md`, Sección 7.2).

A quien implemente la presentación: el orden de las probabilidades que
devuelve el modelo no es el de severidad (`ML_SPEC.md`, Sección 9.6).
