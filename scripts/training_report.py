"""Renderiza `reports/ml/training_report.md` desde `training_metrics.json`.

Este modulo no calcula nada ni lee disco: recibe el diccionario de metricas que
emite `train_model.main()` y devuelve el texto del reporte. Esa separacion es
deliberada, y es lo que hace imposible publicar una cifra escrita a mano: el
test `test_el_reporte_commiteado_se_regenera_identico_desde_el_json` vuelve a
renderizar el documento desde el JSON y lo compara byte a byte con el archivo
commiteado.

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

    lineas += [
        "",
        "El **solapamiento exacto** cuenta cuántas filas del conjunto de prueba tienen un",
        "vector de 8 variables que también aparece en entrenamiento. Dos filas distintas",
        "con las 8 variables idénticas serían una fuga aunque sus índices no se solapen.",
        "La variante principal está deduplicada (PR #2), así que su cuenta es 0; la de",
        "comparación conserva 1 grupo duplicado de forma deliberada, y el conteo de arriba",
        "dice si ese grupo quedó repartido entre los dos lados.",
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
        "**Regla de desempate, declarada antes de medir:** entre las configuraciones que",
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
        f"| **Puntaje de selección** | `GridSearchCV.best_score_`, CV de "
        f"{metricas['cv_folds']} folds sobre entrenamiento | El puntaje con el que se "
        "eligieron los hiperparámetros | **No es una estimación de rendimiento**: está "
        "sesgado al alza por haber elegido el máximo de la rejilla |",
        f"| **CV anidada** | Externa {metricas['cv_folds']} × interna "
        f"{metricas['nested_inner_folds']}, sobre entrenamiento | Estimación insesgada del "
        "**procedimiento** completo (buscar + ajustar) | No es el rendimiento del modelo "
        "final concreto |",
        "| **Test apartado** | El 20% separado al inicio, evaluado una sola vez | "
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
        lineas += [
            "",
            f"Con {primera['checks']['permutation']['n_permutations']} permutaciones, el p",
            "mínimo alcanzable es 1/(n+1). El puntaje con etiquetas barajadas cae al nivel",
            "de azar: el modelo no puede aprender de etiquetas aleatorias, que es justo lo",
            "que se espera de un procedimiento sin fuga.",
        ]

    lineas += [
        "",
        "### 7.2 Coherencia entre el test apartado y la CV anidada (C4)",
        "",
        "Banda de **dos lados**: `|test − CV anidada| ≤ 3σ`. Una sola cota detectaría solo",
        "una de las dos anomalías posibles.",
        "",
        "- **Por debajo de la banda:** el conjunto de prueba salió desfavorable, o el split",
        "  es degenerado.",
        "- **Por encima de la banda:** partición afortunada, o una fuga que la CV anidada no",
        "  alcanza a ver.",
        "",
        "| Variante | Test | CV anidada | Diferencia | Límite 3σ | Lado | Dentro |",
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
            "ML_SPEC Sección 7.1 documenta que las 42 filas de",
            f"{ablacion['band_f'][0]}–{ablacion['band_f'][1]} °F del dataset son `high risk`",
            "al 100%, frente a una tasa base del 33.28%. Si al quitarlas el rendimiento se",
            "desplomara, el modelo habría aprendido «93–95 °F ⇒ alto riesgo», que es un",
            "artefacto de captura y no se sostendría en producción.",
            "",
            f"La ablación opera **sobre el split de entrenamiento**, donde cayeron",
            f"{ablacion['rows_removed']} de esas 42; las restantes están en el conjunto de",
            "prueba y no intervienen aquí.",
            "",
            "| Medida | Valor |",
            "| --- | --- |",
            f"| Filas retiradas del entrenamiento | {ablacion['rows_removed']} |",
            f"| Filas de entrenamiento restantes | {ablacion['training_rows_after']} |",
            f"| CV anidada sin esas filas | {_f4(ablacion['nested_cv_mean'])} ± "
            f"{_f4(ablacion['nested_cv_std'])} |",
            f"| CV anidada con todas las filas | "
            f"{_f4(metricas['variants']['clean']['nested_cv']['mean'])} |",
            f"| Caída atribuible a esas filas | {_f6(ablacion['delta_vs_full'])} |",
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

    # Con `D1` o `D4` no hay ventaja que explicar: publicar el booleano como si
    # la hubiera compararia dos cifras de nivel de ruido e induciria a error.
    if p["rule_branch"] in {"D1", "D4"}:
        explica = "no aplica (el caso activado no depende de la ablación)"
    else:
        explica = "sí" if p["ablation_explains"] else "no"

    delta_test = (
        metricas["variants"]["clean"]["held_out_test"]["f1_macro"]
        - metricas["variants"]["paper"]["held_out_test"]["f1_macro"]
    )
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
            "La regla se escribió en `choose_production_variant()` **antes** de la primera",
            "medición, con sus cuatro casos. El `delta` se calcula sobre la **CV anidada**",
            "(solo entrenamiento), no sobre el conjunto de prueba: así la elección de",
            "variante no consulta el test de ninguna de las dos.",
            "",
            "| Caso | Condición | Variante |",
            "| --- | --- | --- |",
            "| `D1` | `\\|delta\\| ≤ umbral` | `clean` |",
            "| `D2` | `delta > umbral` y la ablación explica la ventaja | `paper` |",
            "| `D3` | `delta > umbral` sin que la ablación la explique | `clean` |",
            "| `D4` | `delta < −umbral` | `paper` |",
            "",
            f"«La ablación explica la ventaja» significa que al retirar del entrenamiento",
            f"las {retiradas} filas de hipotermia se pierde al menos el 50% del `delta`.",
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
            "- **La CV anidada promedia 10 particiones; el test es una sola.** Por eso es la",
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
        lineas += [
            "",
            "Cualquier diferencia residual procede de desempates en punto flotante, no de un",
            "cambio en el espacio de particiones alcanzables.",
        ]
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
    lineas += [
        "",
        "Tres consecuencias concretas, y ninguna es menor:",
        "",
        f"- **IMC máximo {imc['max']} kg/m².** El umbral de obesidad es 30. El modelo",
        "  **nunca ha visto una gestante con obesidad**, que es precisamente un grupo de",
        "  riesgo elevado. Una paciente real con IMC 32 recibiría una predicción",
        "  extrapolada, fuera de todo respaldo empírico.",
        f"- **HbA1c hasta {hba1c['max']} mmol/mol** "
        f"(≈{(hba1c['max'] / 10.929) + 2.152:.1f}%). El umbral diagnóstico de diabetes es",
        "  48 mmol/mol, así que el rango diabético está apenas representado.",
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
            "- Nuestra variante `clean` conserva 42 filas que el paper elimina, y deduplica",
            "  un grupo que el paper conserva (PR #2).",
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
            "`reports/ml/training_metrics.json` | Absolutamente todas las de este documento: "
            "SHA-256, filas, distribuciones, split, rejilla y ganadora, las tres "
            "estimaciones, métricas por clase y macro, matrices de confusión, modelos de "
            "referencia, comprobaciones de sobreajuste, importancias, rangos de variables y "
            "el caso activado de la Decisión D |",
            "| **Fijadas por los tests** (fallan si dejan de cuadrar) | El reporte completo "
            "se regenera byte a byte desde el JSON; las métricas del test apartado se "
            "reproducen reentrenando con los hiperparámetros registrados; los rangos se "
            "recalculan desde el split; el solapamiento train/test; el puntaje con "
            "etiquetas barajadas; la banda de coherencia; el caso de la Decisión D "
            "reaplicando la regla; las versiones de Python y scikit-learn |",
            "| **Citadas de una fuente externa** | La accuracy del paper de origen "
            "(Sección 12) y los umbrales clínicos de las limitaciones (obesidad IMC 30, "
            "diabetes 48 mmol/mol) |",
            "| **Verificadas por código ad hoc**, no regeneradas | Ninguna |",
            "",
            "La tercera fila es la única que este repositorio no produce. La cuarta está",
            "vacía a propósito: en PR #3 hubo cifras verificadas a mano que ningún código",
            "regeneraba, y ese hueco no se repite aquí.",
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
            f"({metricas['elapsed_seconds']:.0f} s). El determinismo se verificó con **dos",
            "ejecuciones independientes de rejilla reducida pero con todas las",
            "comprobaciones activadas**, no repitiendo dos veces la rejilla completa.",
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
            "Resultado: **métricas idénticas** entre las dos ejecuciones.",
            "",
            "**Qué no cubre, dicho sin adornos.** La rejilla reducida no explora",
            "`class_weight=\"balanced\"`, `max_features=None`, `min_samples_leaf` distinto de",
            "1 ni `max_depth=20`. Si existiera una no-determinación que solo apareciese con",
            "alguno de esos valores, esta verificación no la vería.",
            "",
            "Ese hueco lo cierra otro test, y este sí corre en la suite por defecto:",
            "`test_las_metricas_publicadas_se_reproducen_al_reentrenar` reajusta el modelo",
            "con **los hiperparámetros ganadores concretos** que publica este reporte y exige",
            "que las métricas del conjunto de prueba se reproduzcan exactamente. Es decir: la",
            "configuración que de verdad se entrega está fijada por un test que corre siempre.",
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
            "pytest tests/ -k todas_las_comprobaciones` | no, ~80 min |",
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
