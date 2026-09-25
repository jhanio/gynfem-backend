"""Renderiza `reports/ml/training_report.md` desde `training_metrics.json`.

Este modulo no calcula nada ni lee disco: recibe el diccionario de metricas que
emite `train_model.main()` y devuelve el texto del reporte. Esa separacion
impide editar a mano el `.md`: el test
`test_el_reporte_commiteado_se_regenera_identico_desde_el_json` vuelve a
renderizar el documento desde el JSON y lo compara byte a byte con el archivo
commiteado. No protege de un literal escrito en esta plantilla; por eso las
unicas cifras literales de este modulo son las constantes citadas de abajo, y
toda conclusion que depende de un dato se escribe condicionada a ese dato.

Los comentarios y docstrings van sin tildes, como el resto de `scripts/`; el
texto **del reporte** si las lleva, como los demas documentos de `reports/ml/`.

Nota de estilo: el texto evita tres palabras espaniolas corrientes que tambien
son valores de la columna `Name` del RAW (documentado en
`data_cleaning_report.md`, seccion "Politica sobre Name"). El barrido de tokens
de la suite es insensible a mayusculas, y esas tres darian falsos positivos.
"""

from __future__ import annotations

#: Un `---` pegado al parrafo anterior lo convertiria en encabezado setext.
SEPARATOR = "\n\n---\n\n"

#: Nombre de variante -> como se llama en el texto.
VARIANT_LABELS = {"clean": "PRINCIPAL (`clean`)", "paper": "COMPARACIÓN (`paper`)"}

#: Cifra del paper de origen, citada solo como referencia externa.
PAPER_ACCURACY = 0.9934
PAPER_CITATION = "Hossain et al., *BMC Medical Informatics and Decision Making*, 2026, 26:79"

#: Umbrales clinicos citados (OMS), usados solo en las limitaciones.
OBESITY_BMI_KG_M2 = 30
DIABETES_HBA1C_MMOL_MOL = 48


def _f4(valor: float) -> str:
    return f"{valor:.4f}"


def _f6(valor: float) -> str:
    return f"{valor:.6f}"


def _pct(valor: float) -> str:
    return f"{valor * 100:.2f}%"


def _grid_values(valores: list) -> str:
    return ", ".join(f"`{v}`" for v in valores)


def _params_inline(params: dict) -> str:
    return ", ".join(f"`{k}={v}`" for k, v in sorted(params.items()))


def _header(metricas: dict) -> str:
    entorno = metricas["environment"]
    return "\n".join(
        [
            "# Reporte de entrenamiento — Random Forest (PR #4)",
            "",
            f"- **Fecha de generación:** {metricas['generated_at']}",
            "- **Script:** `scripts/train_model.py`",
            "- **Renderizado por:** `scripts/training_report.py` desde "
            "`reports/ml/training_metrics.json`",
            f"- **Python:** {entorno['python']} — **scikit-learn:** {entorno['scikit_learn']} — "
            f"**joblib:** {entorno['joblib']} — **numpy:** {entorno['numpy']} — "
            f"**pandas:** {entorno['pandas']}",
            "- **Comando:** `.venv\\Scripts\\python.exe scripts\\train_model.py`",
            f"- **Semilla:** `{metricas['seed']}`, fijada antes de la primera ejecución y no "
            "modificada después",
            f"- **Tiempo de ejecución:** {metricas['elapsed_seconds']:.1f} s",
            f"- **Comprobaciones completas:** {'sí' if metricas['full_checks'] else 'no'}",
            "",
            "> **Ninguna cifra de este documento se escribe a mano.** El script emite",
            "> `reports/ml/training_metrics.json` y este documento se renderiza de ahí. La",
            "> Sección 13 detalla la procedencia de cada grupo de cifras. Editar un número",
            "> aquí hace fallar la suite.",
            "",
            "> **Alcance clínico:** el modelo es apoyo a la decisión, no un diagnóstico. Su",
            "> salida acompaña al juicio profesional del personal médico de GynFem; no lo",
            "> sustituye.",
        ]
    )


def _seccion_datos(metricas: dict) -> str:
    lineas = [
        "## 1. Datos de entrada",
        "",
        "El SHA-256 de cada variante se verifica **antes de leer una sola fila**, contra lo",
        "publicado en `reports/ml/data_cleaning_report.md` (Sección 3). Si no coincide, el",
        "script aborta con `DatasetIntegrityError` sin escribir nada.",
        "",
        "| Variante | Archivo | Filas | SHA-256 verificado |",
        "| --- | --- | --- | --- |",
    ]
    for nombre, datos in metricas["variants"].items():
        ds = datos["dataset"]
        lineas.append(
            f"| {VARIANT_LABELS[nombre]} | `{ds['path']}` | {ds['rows']} | `{ds['sha256']}` |"
        )

    clases = sorted(next(iter(metricas["variants"].values()))["dataset"]["class_distribution"])
    lineas += [
        "",
        "**Distribución de clases:**",
        "",
        "| Variante | " + " | ".join(f"`{c}`" for c in clases) + " |",
        "| --- | " + " | ".join(["---"] * len(clases)) + " |",
    ]
    for nombre, datos in metricas["variants"].items():
        dist = datos["dataset"]["class_distribution"]
        total = sum(dist.values())
        celdas = [f"{dist[c]} ({_pct(dist[c] / total)})" for c in clases]
        lineas.append(f"| {VARIANT_LABELS[nombre]} | " + " | ".join(celdas) + " |")

    lineas += [
        "",
        "Ambas variantes se entrenan bajo el **mismo protocolo** (ML_SPEC, Decisión D):",
        "mismo split, misma semilla, misma rejilla, mismas métricas. Las dos tablas de",
        "resultados se publican, se elija la que se elija.",
    ]
    return "\n".join(lineas)


def _seccion_split(metricas: dict) -> str:
    entrenamiento = int((1 - metricas["test_size"]) * 100)
    prueba = int(metricas["test_size"] * 100)
    lineas = [
        "## 2. Split",
        "",
        f"Split **{entrenamiento}/{prueba} estratificado** por `risk_level`, semilla",
        f"`{metricas['seed']}`. El conjunto de prueba se aparta al inicio y solo se toca en",
        "`evaluate()`, **una vez por variante**. No interviene en el escalado, ni en la",
        "búsqueda de hiperparámetros, ni en la elección de variante.",
        "",
        "| Variante | Entrenamiento | Prueba | Solapamiento exacto train/test |",
        "| --- | --- | --- | --- |",
    ]
    for nombre, datos in metricas["variants"].items():
        s = datos["split"]
        lineas.append(
            f"| {VARIANT_LABELS[nombre]} | {s['train_rows']} | {s['test_rows']} | "
            f"{s['overlap_exact_rows']} |"
        )

    solapamiento = metricas["variants"]["clean"]["split"]["overlap_exact_rows"]
    if solapamiento == 0:
        conclusion = (
            "En la variante principal el conteo es 0: ninguna fila repetida cruza el split."
        )
    else:
        conclusion = (
            f"**La variante principal tiene {solapamiento} filas de prueba repetidas en "
            "entrenamiento pese a estar deduplicada: hay que revisar la deduplicación.**"
        )
    lineas += [
        "",
        "El **solapamiento exacto** cuenta cuántas filas del conjunto de prueba tienen un",
        "vector de 8 variables que también aparece en entrenamiento. Dos filas distintas",
        "con las 8 variables idénticas serían una fuga aunque sus índices no se solapen.",
        "La variante principal está deduplicada (PR #2); la de comparación conserva a",
        "propósito los duplicados que conserva el paper, y su conteo dice si alguno quedó",
        "repartido entre los dos lados.",
        conclusion,
    ]
    return "\n".join(lineas)


def _seccion_busqueda(metricas: dict) -> str:
    plural = "configuración" if metricas["n_candidates"] == 1 else "configuraciones"
    lineas = [
        "## 3. Búsqueda de hiperparámetros",
        "",
        f"`GridSearchCV` con validación cruzada estratificada de **{metricas['cv_folds']}",
        f"folds sobre el entrenamiento**, métrica `{metricas['selection_metric']}`. La",
        f"rejilla tiene **{metricas['n_candidates']} {plural}**.",
        "",
        "| Hiperparámetro | Valores explorados |",
        "| --- | --- |",
    ]
    for parametro, valores in metricas["param_grid"].items():
        lineas.append(f"| `{parametro}` | {_grid_values(valores)} |")

    lineas += [
        "",
        "**Fijos, no buscados:** " + _params_inline(metricas["fixed_params"]) + ".",
        "",
        "`criterion` queda fijo en `gini` porque duplicaría la rejilla y su efecto dentro",
        "de un bosque es marginal. `max_features` explora `sqrt` y `None`: con solo 8",
        "variables, quedarse con 2 por división puede ser demasiado agresivo. `log2` se",
        "omite por redundante, ya que log2(8)=3 casi coincide con sqrt(8)≈2.8.",
        "",
        "**Regla de desempate** (`_refit_with_tie_break()`): entre las configuraciones que",
        "caen a menos de 1 desviación del mejor puntaje, gana la que menos errores",
        "`high risk` → `low risk` comete; si el empate persiste, la más simple (menos",
        "árboles, menos profundidad, hojas más grandes); y en último término, la primera.",
        "",
        "| Variante | Ganadora | Configuraciones a <1σ | Desempate aplicado | "
        "Tasa `high`→`low` en CV |",
        "| --- | --- | --- | --- | --- |",
    ]
    for nombre, datos in metricas["variants"].items():
        s = datos["search"]
        lineas.append(
            f"| {VARIANT_LABELS[nombre]} | {_params_inline(s['best_params'])} | "
            f"{s['n_within_one_std']} | {'sí' if s['tie_break_applied'] else 'no'} | "
            f"{_f4(s['mean_high_to_low_rate'])} |"
        )
    return "\n".join(lineas)


def _seccion_estimaciones(metricas: dict) -> str:
    lineas = [
        "## 4. Las tres estimaciones, y cuál es cuál",
        "",
        "Esta sección existe por la Decisión E. Usar la misma validación cruzada con el fin",
        "de elegir hiperparámetros y después reportar su puntaje como rendimiento produce",
        "una cifra optimista por selección. El script produce **tres números distintos** y",
        "este documento los mantiene separados.",
        "",
        "| Cifra | Cómo se obtiene | Qué es | Qué **no** es |",
        "| --- | --- | --- | --- |",
        f"| **Puntaje de selección** | Media de la CV de {metricas['cv_folds']} folds "
        "sobre entrenamiento de la configuración que elige la regla de desempate "
        "(con `refit` invocable, `GridSearchCV` no define `best_score_`) | El puntaje "
        "con el que se "
        "eligieron los hiperparámetros | **No es una estimación de rendimiento**: está "
        "sesgado al alza por haber elegido el máximo de la rejilla |",
        f"| **CV anidada** | Externa {metricas['cv_folds']} × interna "
        f"{metricas['nested_inner_folds']}, sobre entrenamiento | Estimación insesgada del "
        "**procedimiento** completo (buscar + ajustar) | No es el rendimiento del modelo "
        "final concreto |",
        f"| **Test apartado** | El {int(metricas['test_size'] * 100)}% separado al inicio, "
        "evaluado una sola vez | "
        "**La estimación de rendimiento del modelo que se entrega** | — |",
        "",
        "| Variante | Puntaje de selección | CV anidada | Test apartado |",
        "| --- | --- | --- | --- |",
    ]
    for nombre, datos in metricas["variants"].items():
        seleccion = datos["search"]["hyperparameter_selection_score"]
        anidada = datos["nested_cv"]
        lineas.append(
            f"| {VARIANT_LABELS[nombre]} | {_f4(seleccion['mean'])} ± {_f4(seleccion['std'])} | "
            f"{_f4(anidada['mean'])} ± {_f4(anidada['std'])} | "
            f"{_f4(datos['held_out_test']['f1_macro'])} |"
        )

    lineas += [
        "",
        f"Todas las cifras de la tabla son `{metricas['selection_metric']}`.",
        "**La cifra titular de este trabajo es la del test apartado**, no la de selección.",
    ]
    return "\n".join(lineas)


def _tabla_por_clase(held_out: dict) -> list[str]:
    lineas = [
        "| Clase | Precisión | Recall | F1 | Soporte |",
        "| --- | --- | --- | --- | --- |",
    ]
    for etiqueta in held_out["labels"]:
        m = held_out["per_class"][etiqueta]
        lineas.append(
            f"| `{etiqueta}` | {_f4(m['precision'])} | {_f4(m['recall'])} | "
            f"{_f4(m['f1'])} | {m['support']} |"
        )
    lineas.append(
        f"| **macro** | {_f4(held_out['precision_macro'])} | "
        f"{_f4(held_out['recall_macro'])} | {_f4(held_out['f1_macro'])} | "
        f"{sum(m['support'] for m in held_out['per_class'].values())} |"
    )
    return lineas


def _tabla_confusion(held_out: dict) -> list[str]:
    etiquetas = held_out["labels"]
    lineas = [
        "| Real \\ Predicho | " + " | ".join(f"`{e}`" for e in etiquetas) + " |",
        "| --- | " + " | ".join(["---"] * len(etiquetas)) + " |",
    ]
    for i, etiqueta in enumerate(etiquetas):
        fila = " | ".join(str(v) for v in held_out["confusion_matrix"][i])
        lineas.append(f"| `{etiqueta}` | {fila} |")
    return lineas


def _seccion_metricas(metricas: dict) -> str:
    lineas = [
        "## 5. Métricas sobre el conjunto de prueba apartado",
        "",
        "| Variante | Accuracy | Precisión macro | Recall macro | F1 macro | `high`→`low` |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for nombre, datos in metricas["variants"].items():
        h = datos["held_out_test"]
        lineas.append(
            f"| {VARIANT_LABELS[nombre]} | {_f4(h['accuracy'])} | "
            f"{_f4(h['precision_macro'])} | {_f4(h['recall_macro'])} | "
            f"{_f4(h['f1_macro'])} | {h['high_to_low']} |"
        )

    lineas += [
        "",
        "La última columna es el número de gestantes de **alto riesgo clasificadas como",
        "bajo riesgo**. Es el error clínicamente grave, y ninguna métrica agregada lo",
        "distingue del error inverso: por eso se publica aparte (Decisión B).",
    ]

    for indice, (nombre, datos) in enumerate(metricas["variants"].items(), start=1):
        h = datos["held_out_test"]
        lineas += [
            "",
            f"### 5.{indice} {VARIANT_LABELS[nombre]}",
            "",
            "**Por clase:**",
            "",
            *_tabla_por_clase(h),
            "",
            "**Matriz de confusión:**",
            "",
            *_tabla_confusion(h),
            "",
            f"Accuracy de entrenamiento: {_f4(datos['train_accuracy'])}. En un bosque con",
            "`max_depth=None` este número roza 1.0 por diseño (cada árbol crece hasta hojas",
            "puras) y **no** es por sí mismo evidencia de sobreajuste; lo informativo son",
            "las comprobaciones de la Sección 7.",
            "",
            f"Figura: `reports/ml/figures/training_confusion_matrix_{nombre}.png`",
        ]
    return "\n".join(lineas)


def _seccion_referencia(metricas: dict) -> str:
    lineas = [
        "## 6. Modelos de referencia",
        "",
        "Un 98% de accuracy no significa nada sin saber qué consigue el modelo que ignora",
        "las variables y el que usa un solo árbol. Ambos se ajustan sobre el mismo",
        "entrenamiento y se evalúan sobre el mismo conjunto de prueba.",
        "",
        "| Variante | Modelo | Accuracy | F1 macro | `high`→`low` |",
        "| --- | --- | --- | --- | --- |",
    ]
    nombres = {
        "dummy": "`DummyClassifier(most_frequent)`",
        "decision_tree": "`DecisionTreeClassifier`",
        "random_forest": "**Random Forest**",
    }
    for nombre, datos in metricas["variants"].items():
        modelos = dict(datos["reference_models"])
        modelos["random_forest"] = datos["held_out_test"]
        for clave in ("dummy", "decision_tree", "random_forest"):
            m = modelos[clave]
            lineas.append(
                f"| {VARIANT_LABELS[nombre]} | {nombres[clave]} | {_f4(m['accuracy'])} | "
                f"{_f4(m['f1_macro'])} | {m['high_to_low']} |"
            )

    lineas += [
        "",
        "El clasificador trivial fija el suelo: su accuracy es exactamente la proporción de",
        "la clase mayoritaria en el conjunto de prueba. El árbol simple mide cuánto aporta",
        "el promediado del bosque frente a una sola partición del espacio.",
    ]
    return "\n".join(lineas)


def _seccion_sobreajuste(metricas: dict) -> str:
    lineas = [
        "## 7. Comprobaciones de sobreajuste (Decisión C)",
        "",
        "Una accuracy muy alta obliga a demostrar que es señal y no memorización. Estas",
        "comprobaciones existen con ese fin.",
    ]

    primera = next(iter(metricas["variants"].values()))
    if "permutation" in primera["checks"]:
        lineas += [
            "",
            "### 7.1 Etiquetas permutadas (C1)",
            "",
            "Se baraja `risk_level` y se reentrena. Si el modelo siguiera acertando, habría",
            "fuga en el split o en el pipeline y la accuracy real no significaría nada.",
            "",
            "| Variante | Puntaje real | Con etiquetas barajadas | Máximo barajado | Azar | p |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for nombre, datos in metricas["variants"].items():
            p = datos["checks"]["permutation"]
            lineas.append(
                f"| {VARIANT_LABELS[nombre]} | {_f4(p['true_score'])} | "
                f"{_f4(p['permuted_mean'])} ± {_f4(p['permuted_std'])} | "
                f"{_f4(p['permuted_max'])} | {_f4(p['chance_level'])} | "
                f"{_f4(p['p_value'])} |"
            )
        n_perm = primera["checks"]["permutation"]["n_permutations"]
        p_minimo = 1 / (n_perm + 1)
        todas_al_minimo = all(
            abs(d["checks"]["permutation"]["p_value"] - p_minimo) < 1e-12
            for d in metricas["variants"].values()
        )
        if todas_al_minimo:
            conclusion = [
                "En todas las variantes el p es ese mínimo: ninguna permutación igualó el",
                "puntaje real, que es lo que se espera de un procedimiento sin fuga.",
            ]
        else:
            conclusion = [
                "**En alguna variante el p supera ese mínimo: al menos una permutación",
                "igualó o superó el puntaje real, y eso exige revisar el procedimiento.**",
            ]
        lineas += [
            "",
            f"Con {n_perm} permutaciones, el p mínimo alcanzable es 1/(n+1) =",
            f"{_f4(p_minimo)}. Compárese la media barajada con la columna de azar.",
            *conclusion,
        ]

    sigmas = primera["checks"]["consistency_band"]["sigmas"]
    lineas += [
        "",
        "### 7.2 Coherencia entre el test apartado y la CV anidada (C4)",
        "",
        f"Banda de **dos lados**: `|test − CV anidada| ≤ {sigmas}σ`. Una sola cota detectaría solo",
        "una de las dos anomalías posibles.",
        "",
        "- **Por debajo de la banda:** el conjunto de prueba salió desfavorable, o el split",
        "  es degenerado.",
        "- **Por encima de la banda:** partición afortunada, o una fuga que la CV anidada no",
        "  alcanza a ver.",
        "",
        f"| Variante | Test | CV anidada | Diferencia | Límite {sigmas}σ | Lado | Dentro |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for nombre, datos in metricas["variants"].items():
        b = datos["checks"]["consistency_band"]
        lado = "por encima" if b["side"] == "above" else "por debajo"
        lineas.append(
            f"| {VARIANT_LABELS[nombre]} | {_f4(datos['held_out_test']['f1_macro'])} | "
            f"{_f4(datos['nested_cv']['mean'])} | {_f6(b['delta'])} | {_f6(b['limit'])} | "
            f"{lado} | {'sí' if b['within'] else '**NO**'} |"
        )

    if "partition_variance" in primera["checks"]:
        lineas += [
            "",
            "### 7.3 Varianza de partición (C5)",
            "",
            "`RepeatedStratifiedKFold` **solo sobre el entrenamiento**. Volver a partir el",
            "conjunto de prueba con otras semillas lo expondría, y el contrato dice que se",
            "toca una sola vez; repetir la partición del entrenamiento responde la misma",
            "pregunta sin gastarlo.",
            "",
            "| Variante | Repeticiones | Media | Desviación | Mínimo | Máximo |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for nombre, datos in metricas["variants"].items():
            v = datos["checks"]["partition_variance"]
            lineas.append(
                f"| {VARIANT_LABELS[nombre]} | {v['n_splits']}×{v['n_repeats']} | "
                f"{_f4(v['mean'])} | {_f4(v['std'])} | {_f4(v['min'])} | {_f4(v['max'])} |"
            )

    curva = metricas.get("learning_curve")
    if curva:
        lineas += [
            "",
            "### 7.4 Curva de aprendizaje (C2)",
            "",
            f"Variante `{curva['variant']}`, métrica `{curva['metric']}`.",
            "",
            "| Filas de entrenamiento | Entrenamiento | Validación (CV) |",
            "| --- | --- | --- |",
        ]
        for tamano, entrena, valida in zip(
            curva["train_sizes"], curva["train_scores_mean"], curva["test_scores_mean"]
        ):
            lineas.append(f"| {tamano} | {_f4(entrena)} | {_f4(valida)} |")
        lineas += [
            "",
            f"Brecha final entrenamiento − validación: {_f4(curva['final_gap'])}. Lo",
            "informativo no es que la curva de entrenamiento roce 1.0 —eso lo impone",
            "`max_depth=None`— sino si la de validación converge hacia ella al crecer la",
            "muestra. Figura: `reports/ml/figures/training_learning_curve.png`",
        ]

    ablacion = metricas["variants"]["clean"]["checks"].get("hypothermia_ablation")
    if ablacion:
        lineas += [
            "",
            "### 7.5 Ablación de las filas de hipotermia (C6)",
            "",
            "ML_SPEC Sección 7.1 documenta que las filas del dataset con temperatura de",
            f"{ablacion['band_f'][0]}–{ablacion['band_f'][1]} °F son todas `high risk`, muy",
            "por encima de la tasa base de la clase (las cifras exactas están en ese",
            "documento y en el reporte de limpieza de PR #2; no las regenera este script).",
            "",
            f"La ablación opera **sobre el split de entrenamiento**, donde cayeron",
            f"{ablacion['rows_removed']} de esas filas; las restantes están en el conjunto de",
            "prueba y no intervienen aquí.",
            "",
            "**Qué mide y qué no.** Las filas se retiran del entrenamiento y, por tanto,",
            "también de la validación de la CV anidada. La ablación mide si el **rendimiento",
            "agregado** depende de ellas. **No** mide si el modelo aprendió la regla",
            f"«{ablacion['band_f'][0]}–{ablacion['band_f'][1]} °F ⇒ alto riesgo»: la CV ablada",
            "nunca evalúa filas de esa banda. Contrastar esa hipótesis exigiría predecir",
            "sobre la banda con un modelo entrenado sin ella, y eso no se hizo en PR #4.",
            "",
            "| Medida | Valor |",
            "| --- | --- |",
            f"| Filas retiradas del entrenamiento | {ablacion['rows_removed']} |",
            f"| Filas de entrenamiento restantes | {ablacion['training_rows_after']} |",
            f"| CV anidada sin esas filas | {_f4(ablacion['nested_cv_mean'])} ± "
            f"{_f4(ablacion['nested_cv_std'])} |",
            f"| CV anidada con todas las filas | "
            f"{_f4(metricas['variants']['clean']['nested_cv']['mean'])} |",
            f"| Diferencia (con todas − sin esas filas) | {_f6(ablacion['delta_vs_full'])} |",
        ]
    return "\n".join(lineas)


def _seccion_importancia(metricas: dict) -> str:
    lineas = [
        "## 8. Importancia de variables",
        "",
        "Reducción media de impureza. Es una medida **descriptiva del modelo ajustado**, no",
        "una afirmación causal: variables correlacionadas se reparten la importancia y el",
        "criterio favorece a las de mayor cardinalidad.",
        "",
        "| Variable | " + " | ".join(VARIANT_LABELS[n] for n in metricas["variants"]) + " |",
        "| --- | " + " | ".join(["---"] * len(metricas["variants"])) + " |",
    ]
    produccion = metricas["production"]["variant"]
    orden = sorted(
        next(iter(metricas["variants"].values()))["feature_importance"],
        key=lambda v: -metricas["variants"][produccion]["feature_importance"][v],
    )
    for variable in orden:
        celdas = [
            _f4(metricas["variants"][n]["feature_importance"][variable])
            for n in metricas["variants"]
        ]
        lineas.append(f"| `{variable}` | " + " | ".join(celdas) + " |")

    lineas += [
        "",
        "Figuras: `reports/ml/figures/training_feature_importance_{clean,paper}.png` y",
        "`reports/ml/figures/training_cv_scores_{clean,paper}.png`.",
    ]
    return "\n".join(lineas)


def _seccion_decision_d(metricas: dict) -> str:
    p = metricas["production"]
    ablacion = metricas["variants"]["clean"]["checks"].get("hypothermia_ablation")
    retiradas = ablacion["rows_removed"] if ablacion else "las"

    # Con `D1` o `D4` no hay ventaja que explicar y el script publica `None`.
    if p["ablation_explains"] is None:
        explica = "no aplica (el caso activado no depende de la ablación)"
    else:
        explica = "sí" if p["ablation_explains"] else "no"

    delta_test = (
        metricas["variants"]["clean"]["held_out_test"]["f1_macro"]
        - metricas["variants"]["paper"]["held_out_test"]["f1_macro"]
    )
    # Que caso habria activado la misma regla con el `delta` medido sobre el test.
    ganadora_test = "clean" if delta_test >= 0 else "paper"
    umbral_test = metricas["variants"][ganadora_test]["nested_cv"]["std"]
    if abs(delta_test) <= umbral_test:
        caso_test = "`D1` (variante `clean`)"
    elif delta_test < 0:
        caso_test = "`D4` (variante `paper`)"
    else:
        caso_test = "`D2` o `D3`, según la ablación"
    # Ninguna caracterizacion de magnitud se escribe a mano: el cociente y el
    # numero equivalente de aciertos salen de las cifras medidas.
    delta_nested = abs(p["delta_f1_macro"])
    razon_veces = round(abs(delta_test) / delta_nested) if delta_nested else "—"
    filas_clean = metricas["variants"]["clean"]["dataset"]["rows"]
    filas_paper = metricas["variants"]["paper"]["dataset"]["rows"]
    test_rows = metricas["variants"][p["variant"]]["split"]["test_rows"]
    aciertos_equivalentes = round(abs(delta_test) * test_rows)

    return "\n".join(
        [
            "## 9. Decisión D — variante de producción",
            "",
            "La regla está codificada en `choose_production_variant()`, con sus cuatro",
            "casos. El `delta` se calcula sobre la **CV anidada** (solo entrenamiento), no",
            "sobre el conjunto de prueba: así la elección de variante no consulta el test",
            "de ninguna de las dos.",
            "",
            "**Sobre cuándo se fijó la base del `delta`, sin adornos.** El repositorio no",
            "permite demostrar que la regla se fijara antes de la primera medición: antes de",
            "PR #4, ML_SPEC solo recogía la regla cualitativa, y el umbral y la base",
            "entraron en el mismo PR que los resultados. La primera redacción del plan de",
            "PR #4, que no está versionada, definía el `delta` sobre el conjunto de prueba.",
            f"Con esa base el `delta` sería {delta_test:+.6f}, con un umbral de",
            f"{_f6(umbral_test)}, y el caso activado habría sido {caso_test}. La base",
            "actual es preferible porque no consulta el test (Sección 9.1), pero es un",
            "cambio respecto de esa primera redacción y se declara como tal.",
            "",
            "| Caso | Condición | Variante |",
            "| --- | --- | --- |",
            "| `D1` | `\\|delta\\| ≤ umbral` | `clean` |",
            "| `D2` | `delta > umbral` y la ablación explica la ventaja | `paper` |",
            "| `D3` | `delta > umbral` sin que la ablación la explique | `clean` |",
            "| `D4` | `delta < −umbral` | `paper` |",
            "",
            f"«La ablación explica la ventaja» significa que al retirar del entrenamiento",
            f"las {retiradas} filas de hipotermia se pierde al menos el "
            f"{p['ablation_explains_fraction'] * 100:.0f}% del `delta`.",
            "",
            "| Magnitud | Valor |",
            "| --- | --- |",
            f"| `delta` (CV anidada, `clean` − `paper`) | {_f6(p['delta_f1_macro'])} |",
            f"| Umbral (1σ de la CV anidada de la ganadora) | {_f6(p['threshold'])} |",
            f"| La ablación explica la ventaja | {explica} |",
            f"| **Caso activado** | **`{p['rule_branch']}`** |",
            f"| **Variante de producción** | **`{p['variant']}`** |",
            "",
            p["reason"],
            "",
            "### 9.1 El test y la CV anidada no dicen lo mismo, y eso se explica",
            "",
            f"Sobre el conjunto de prueba la diferencia entre variantes es {_f6(delta_test)}",
            f"`f1_macro`, {razon_veces} veces mayor que el `delta` de",
            f"{_f6(p['delta_f1_macro'])} con el que se decide. Conviene decir por qué no es",
            "una contradicción:",
            "",
            "- **No son conjuntos comparables.** Cada variante tiene su propio conjunto de",
            "  prueba, de extensión y composición distintas, porque parten de datasets con",
            f"  distinto número de filas ({filas_clean} y {filas_paper}). No es una",
            "  comparación pareada: comparar esas dos cifras entre sí mide, en buena parte,",
            "  qué conjunto de prueba salió más fácil.",
            f"- **La magnitud cabe en el ruido.** {_f6(abs(delta_test))} es del mismo orden",
            f"  que la desviación de la CV anidada ({_f6(p['threshold'])}). Con {test_rows}",
            f"  filas de prueba, un solo acierto mueve la métrica {_f6(1 / test_rows)}, así",
            f"  que esa diferencia equivale al orden de {aciertos_equivalentes} aciertos.",
            f"- **La CV anidada promedia {metricas['cv_folds']} particiones; el test es una "
            "sola.** Por eso es la",
            "  base de la decisión: elegir por el test sería elegir por una partición.",
            "",
            "El modelo serializado corresponde **solo** a la variante de producción. La otra",
            "se entrena y se mide bajo el mismo protocolo, y sus métricas se publican en",
            "este documento, pero no se empaqueta: dos `.joblib` con el mismo contrato de",
            "metadatos serían una ambigüedad que el backend podría resolver mal.",
        ]
    )


def _seccion_decision_a(metricas: dict) -> str:
    lineas = [
        "## 10. Decisión A — escalado de variables",
        "",
        "**No se escala.** Un árbol parte por umbrales `x ≤ t`; una transformación afín por",
        "columna preserva el orden de los valores de esa columna, luego el conjunto de",
        "particiones alcanzables es idéntico. Lo mismo vale al árbol simple, y el",
        "clasificador trivial ignora las variables por completo. Ninguno de los tres",
        "modelos del alcance puede beneficiarse.",
        "",
        "El `Pipeline` se conserva de todos modos: garantiza que cualquier preprocesamiento",
        "futuro se ajuste dentro de cada fold, y el backend carga un solo objeto.",
    ]

    if "scaler_ablation" in next(iter(metricas["variants"].values()))["checks"]:
        lineas += [
            "",
            "La afirmación se mide, no se asume. Validación cruzada sobre el entrenamiento",
            "(el conjunto de prueba no se gasta en diagnósticos):",
            "",
            "| Variante | Sin escalador | Con `StandardScaler` | Diferencia |",
            "| --- | --- | --- | --- |",
        ]
        for nombre, datos in metricas["variants"].items():
            a = datos["checks"]["scaler_ablation"]
            lineas.append(
                f"| {VARIANT_LABELS[nombre]} | {_f4(a['without_scaler'])} | "
                f"{_f4(a['with_scaler'])} | {_f6(a['delta'])} |"
            )
        no_nulas = [
            VARIANT_LABELS[n]
            for n, d in metricas["variants"].items()
            if d["checks"]["scaler_ablation"]["delta"] != 0
        ]
        if not no_nulas:
            cierre = ["La diferencia es exactamente 0 en todas las variantes."]
        else:
            cierre = [
                f"La diferencia no es 0 en {', '.join(no_nulas)}. El argumento de arriba",
                "predice que solo puede venir de cómo se sitúan los umbrales de corte entre",
                "valores (el punto medio cambia de escala con la transformación), no de un",
                "cambio en las particiones alcanzables; esa atribución es teórica y no está",
                "medida aquí.",
            ]
        lineas += ["", *cierre]
    return "\n".join(lineas)


def _seccion_limitaciones(metricas: dict) -> str:
    rangos = metricas["feature_ranges"]
    lineas = [
        "## 11. Limitaciones",
        "",
        "### 11.1 El rango de entrenamiento es estrecho",
        "",
        "Estos son los valores que el modelo vio de verdad. Fuera de ellos, cualquier",
        "predicción es extrapolación.",
        "",
        f"Origen: {rangos['source']}.",
        "",
        "| Variable | Mínimo | Máximo | Unidad |",
        "| --- | --- | --- | --- |",
    ]
    for variable, rango in rangos["features"].items():
        lineas.append(f"| `{variable}` | {rango['min']} | {rango['max']} | {rango['unit']} |")

    imc = rangos["features"]["bmi_kg_m2"]
    hba1c = rangos["features"]["hba1c_mmol_mol"]
    edad = rangos["features"]["age_years"]
    if imc["max"] < OBESITY_BMI_KG_M2:
        consecuencia_imc = [
            f"- **IMC máximo {imc['max']} kg/m².** El umbral de obesidad es",
            f"  {OBESITY_BMI_KG_M2}. El modelo **nunca ha visto una gestante con obesidad**,",
            "  que es precisamente un grupo de riesgo elevado. Una paciente con obesidad",
            "  recibiría una predicción extrapolada, fuera de todo respaldo empírico.",
        ]
    else:
        consecuencia_imc = [
            f"- **IMC máximo {imc['max']} kg/m².** El entrenamiento alcanza el umbral de",
            f"  obesidad ({OBESITY_BMI_KG_M2}); por encima de {imc['max']} la predicción",
            "  es extrapolada.",
        ]
    if hba1c["max"] < DIABETES_HBA1C_MMOL_MOL:
        cierre_hba1c = "así que el rango diabético no está representado."
    else:
        cierre_hba1c = f"y el entrenamiento solo llega a {hba1c['max']}, apenas por encima."
    lineas += [
        "",
        "Tres consecuencias concretas, y ninguna es menor:",
        "",
        *consecuencia_imc,
        f"- **HbA1c hasta {hba1c['max']} mmol/mol** "
        f"(≈{(hba1c['max'] / 10.929) + 2.152:.1f}%). El umbral diagnóstico de diabetes es",
        f"  {DIABETES_HBA1C_MMOL_MOL} mmol/mol, {cierre_hba1c}",
        f"- **Edad entre {edad['min']} y {edad['max']} años.** Las gestantes fuera de ese",
        "  intervalo quedan sin respaldo.",
        "",
        "`models/feature_ranges.json` se genera de estos mismos datos, nunca se escribe a",
        "mano, y el backend debe usarlo emitiendo una **advertencia de extrapolación**, no",
        "un bloqueo (ML_SPEC, Sección 5).",
        "",
        "### 11.2 Otras limitaciones",
        "",
        "- **El dataset no es de GynFem.** Procede de la publicación de origen; su",
        "  población, su instrumentación y sus criterios de etiquetado no son los del",
        "  contexto peruano donde se desplegará.",
        "- **Las etiquetas son la variable objetivo del dataset original**, no un",
        "  diagnóstico verificado de forma independiente. El modelo reproduce ese criterio,",
        "  con sus sesgos.",
        "- **La elección de variante es una selección entre dos opciones.** Aunque el",
        "  `delta` se mide sobre la CV anidada y no sobre el test, elegir el mejor de dos",
        "  introduce una dosis pequeña de sesgo de selección. Es mucho menor que elegir",
        "  entre las configuraciones de la rejilla, pero no es cero, y conviene decirlo.",
        "- **La importancia por impureza es descriptiva**, no causal.",
        "- **No hay validación externa**: ningún conjunto de otra institución o periodo.",
    ]
    return "\n".join(lineas)


def _nota_coincidencia(metricas: dict) -> list[str]:
    """Avisa si alguna variante coincide con la cifra publicada al redondear.

    Una coincidencia asi se leeria como replica si nadie la seniala, y no lo es:
    aqui sale del cociente de aciertos sobre el tamanio del conjunto de prueba.
    """
    coincidentes = [
        (nombre, datos)
        for nombre, datos in metricas["variants"].items()
        if f"{datos['held_out_test']['accuracy'] * 100:.2f}" == f"{PAPER_ACCURACY * 100:.2f}"
    ]
    if not coincidentes:
        return []

    nombre, datos = coincidentes[0]
    matriz = datos["held_out_test"]["confusion_matrix"]
    aciertos = sum(matriz[i][i] for i in range(len(matriz)))
    total = datos["split"]["test_rows"]
    return [
        f"> **Coincidencia, no réplica.** La variante `{nombre}` obtiene exactamente",
        f"> {_pct(datos['held_out_test']['accuracy'])} sobre su conjunto de prueba, la misma",
        "> cifra que publica el paper al redondear a dos decimales. Es una casualidad",
        f"> aritmética: sale de {aciertos} aciertos sobre {total} filas. Un acierto más o",
        "> menos la habría movido, y nada de este trabajo se orientó a reproducirla. No",
        "> debe leerse como una replicación del resultado publicado.",
        "",
    ]


def _seccion_paper(metricas: dict) -> str:
    produccion = metricas["variants"][metricas["production"]["variant"]]
    nuestra = produccion["held_out_test"]["accuracy"]
    diferencia = nuestra - PAPER_ACCURACY
    return "\n".join(
        [
            "## 12. Comparación con el paper de origen",
            "",
            f"{PAPER_CITATION} reporta **{_pct(PAPER_ACCURACY)}** de accuracy con Random",
            "Forest. Esa cifra se cita **solo como referencia externa**. No es una meta de",
            "este proyecto, no se ha verificado de forma independiente en este repositorio,",
            "y el paper no publica su protocolo con el detalle necesario a fin de",
            "replicarlo.",
            "",
            "| Origen | Accuracy | Procedencia |",
            "| --- | --- | --- |",
            f"| Paper de origen | {_pct(PAPER_ACCURACY)} | Citada, no verificada |",
            f"| Este trabajo (`{metricas['production']['variant']}`, test apartado) | "
            f"{_pct(nuestra)} | Medida por `scripts/train_model.py` |",
            f"| Diferencia | {diferencia * 100:+.2f} pp | — |",
            "",
            *_nota_coincidencia(metricas),
            "**Por qué no son directamente comparables**, aunque las cifras se parezcan:",
            "",
            "- El paper no declara semilla ni proporción de split, así que su cifra podría",
            "  proceder de una partición distinta.",
            "- No queda claro si su accuracy sale de un conjunto apartado o de validación",
            "  cruzada; si fuera el puntaje con el que eligió hiperparámetros, estaría",
            "  sesgado al alza igual que nuestro puntaje de selección (Sección 4).",
            "- Nuestra variante `clean` conserva las filas de hipotermia que el paper",
            "  elimina, y deduplica lo que el paper conserva (PR #2).",
            "",
            "Nuestra cifra es la que es. No se ajustó nada con el objeto de acercarla a la",
            "publicada, y si difiere, la explicación está arriba y no en el modelo.",
        ]
    )


def _seccion_procedencia(metricas: dict) -> str:
    return "\n".join(
        [
            "## 13. Procedencia de las cifras",
            "",
            "| Origen | Cifras |",
            "| --- | --- |",
            "| **Emitidas por `scripts/train_model.py`** en cada ejecución, vía "
            "`reports/ml/training_metrics.json` | Todas las cifras de resultados: SHA-256, "
            "filas, distribuciones, split, rejilla y ganadora, las tres estimaciones, "
            "métricas por clase y macro, matrices de confusión, modelos de referencia, "
            "comprobaciones de sobreajuste, importancias, rangos de variables y el caso "
            "activado de la Decisión D. También los parámetros del protocolo (semilla, "
            "proporción, folds, bandas, umbrales de la regla), que el JSON copia de las "
            "constantes del script |",
            "| **Recalculadas por la suite por defecto** (fallan si dejan de cuadrar) | El "
            "reporte completo, byte a byte desde el JSON; el test apartado, las importancias "
            "y los modelos de referencia de ambas variantes, reentrenando; los folds de la "
            "CV de selección de ambas variantes; los rangos, desde el split; el solapamiento "
            "train/test; el bloque completo de la Decisión D, reaplicando la regla; las "
            "cuatro ramas de la regla y el desempate, con datos sintéticos; las versiones "
            "de Python y scikit-learn |",
            "| **Emitidas por el script pero no recalculadas por la suite por defecto** | La "
            "CV anidada, las etiquetas permutadas, la varianza de partición, la curva de "
            "aprendizaje y las dos ablaciones. La suite comprueba su coherencia interna y "
            "sus umbrales, no su valor; el test lento (Sección 14.3) ejercita ese código, "
            "pero compara dos ejecuciones entre sí, no con este JSON |",
            "| **Citadas de una fuente externa** | La accuracy del paper de origen "
            f"(Sección 12), los umbrales clínicos de las limitaciones (obesidad IMC "
            f"{OBESITY_BMI_KG_M2}, diabetes {DIABETES_HBA1C_MMOL_MOL} mmol/mol) y la "
            "conversión de HbA1c de mmol/mol a % |",
            "| **Citadas de otros documentos del repositorio**, sin cifra | La composición "
            "de la banda de hipotermia y la política de deduplicación (ML_SPEC Sección 7.1 "
            "y reporte de limpieza de PR #2) |",
            "",
            "La tercera fila es la deuda de verificación de este PR: esas cifras las",
            "produce el código, pero ninguna prueba de la suite por defecto las recalcula.",
        ]
    )


def _seccion_reproducibilidad(metricas: dict) -> str:
    return "\n".join(
        [
            "## 14. Reproducibilidad y su verificación",
            "",
            "### 14.1 De dónde sale el determinismo",
            "",
            f"Semilla `{metricas['seed']}` fija en el `random_state` del bosque, en el split",
            "estratificado, en cada `StratifiedKFold`, en la prueba de etiquetas permutadas,",
            "en la curva de aprendizaje y en la varianza de partición. `n_jobs` reparte el",
            "trabajo entre núcleos pero no altera el resultado: el estado aleatorio de cada",
            "árbol queda fijado por la semilla, no por el orden en que se ajustan.",
            "",
            "Las figuras también son byte-idénticas entre ejecuciones: `savefig` recibe",
            "`metadata={\"Software\": None}` porque matplotlib escribiría su propia versión en",
            "el PNG y los bytes cambiarían con cada actualización de la librería.",
            "",
            "Entre dos ejecuciones solo cambian tres valores, todos de reloj:",
            "`generated_at`, `created_at` y `elapsed_seconds`.",
            "",
            "### 14.2 Cómo se verificó, y una desviación declarada",
            "",
            "**La desviación:** la rejilla completa de",
            f"{metricas['n_candidates']} configuraciones se ejecutó **una sola vez**",
            f"({metricas['elapsed_seconds']:.0f} s). El determinismo de todos los caminos lo",
            "comprueba un test que compara **dos ejecuciones independientes de rejilla",
            "reducida pero con todas las comprobaciones activadas**, en lugar de repetir dos",
            "veces la rejilla completa.",
            "",
            "**Por qué esta evidencia es al menos tan fuerte.** El número de configuraciones",
            "cambia *cuántas veces* se llama a `fit`, no *qué código se ejecuta*. Repetir la",
            "rejilla completa una segunda vez recorrería el mismo camino otra vez, y a un",
            "coste de horas. La verificación elegida recorre en cambio **todas las ramas**",
            "donde podría esconderse una fuente de aleatoriedad, que es donde está el riesgo",
            "real:",
            "",
            "| Camino de código | ¿Lo cubre la verificación? |",
            "| --- | --- |",
            f"| Split estratificado y búsqueda con CV de {metricas['cv_folds']} folds | sí |",
            f"| CV anidada (externa {metricas['cv_folds']} × interna "
            f"{metricas['nested_inner_folds']}) | sí |",
            "| Prueba de etiquetas permutadas | sí |",
            "| Curva de aprendizaje | sí |",
            "| Varianza de partición (`RepeatedStratifiedKFold`) | sí |",
            "| Ablación del escalador | sí |",
            "| Ablación de las filas de hipotermia | sí |",
            "| Evaluación, modelos de referencia y escritura de artefactos | sí |",
            "",
            "Ese test no corre en la suite por defecto y el script no emite su resultado, así",
            "que este reporte no lo publica: se repite con el comando de la Sección 14.3.",
            "",
            "**Qué no cubre, dicho sin adornos.** La rejilla reducida (`REDUCED_PARAM_GRID`",
            "en `tests/conftest.py`) no explora todos los valores de la rejilla completa. Si",
            "existiera una no-determinación que solo apareciese con alguno de los valores",
            "que omite, esta verificación no la vería.",
            "",
            "Ese hueco lo cierran otros tests, y estos sí corren en la suite por defecto:",
            "`test_las_metricas_publicadas_se_reproducen_al_reentrenar` y",
            "`test_los_folds_de_la_cv_de_seleccion_se_reproducen` reajustan el modelo con",
            "**los hiperparámetros ganadores concretos** que publica este reporte y exigen",
            "que el test apartado y los folds de la CV se reproduzcan exactamente. Es decir:",
            "la configuración que de verdad se entrega está fijada por tests que corren",
            "siempre.",
            "",
            "### 14.3 Cómo repetir cada verificación",
            "",
            "| Verificación | Comando | En la suite por defecto |",
            "| --- | --- | --- |",
            "| Métricas publicadas reproducibles al reentrenar | `pytest tests/ -k "
            "metricas_publicadas` | sí |",
            "| Dos ejecuciones idénticas (camino rápido) | `pytest tests/ -k "
            "dos_ejecuciones_con_la_misma` | sí |",
            "| Dos ejecuciones idénticas (**todos** los caminos) | `GYNFEM_SLOW_TESTS=1 "
            "pytest tests/ -k todas_las_comprobaciones` | no, es lento |",
            "| Reporte regenerado byte a byte desde el JSON | `pytest tests/ -k "
            "regenera_identico` | sí |",
            "| Regenerar todo desde cero | `.venv\\Scripts\\python.exe scripts\\"
            f"train_model.py` | no, {metricas['elapsed_seconds']:.0f} s |",
        ]
    )


def _seccion_contrato(metricas: dict) -> str:
    return "\n".join(
        [
            "## 15. Contrato del artefacto",
            "",
            f"- **Modelo:** `models/{metricas['model_file']}`",
            f"- **Versión:** `{metricas['model_version']}`",
            "- **Metadatos:** `models/model_metadata.json`",
            "- **Rangos de variables:** `models/feature_ranges.json`",
            "",
            "El modelo entregado se ajusta **solo con el 80% de entrenamiento**, no se",
            "reajusta sobre el dataset completo. Reajustar daría un modelo marginalmente",
            "mejor, pero la métrica publicada dejaría de ser la de este artefacto: lo medido",
            "y lo entregado son el mismo objeto.",
            "",
            "`model_metadata.json` registra el orden exacto de las 8 variables con su",
            "unidad, el orden de las clases tal como lo expone el modelo serializado, los",
            "hiperparámetros finales, la semilla, las versiones de Python y scikit-learn, el",
            "SHA-256 del dataset de entrenamiento y el resumen de métricas. Cargar el modelo",
            "con una versión de scikit-learn distinta de la registrada puede cambiar su",
            "comportamiento en silencio; un test compara ambas y falla si difieren.",
        ]
    )


def render(metricas: dict) -> str:
    """Devuelve el texto completo del reporte. Funcion pura: no toca disco."""
    secciones = [
        _header(metricas),
        _seccion_datos(metricas),
        _seccion_split(metricas),
        _seccion_busqueda(metricas),
        _seccion_estimaciones(metricas),
        _seccion_metricas(metricas),
        _seccion_referencia(metricas),
        _seccion_sobreajuste(metricas),
        _seccion_importancia(metricas),
        _seccion_decision_d(metricas),
        _seccion_decision_a(metricas),
        _seccion_limitaciones(metricas),
        _seccion_paper(metricas),
        _seccion_procedencia(metricas),
        _seccion_reproducibilidad(metricas),
        _seccion_contrato(metricas),
    ]
    return SEPARATOR.join(secciones) + "\n"
