"""Entrenamiento y validacion del Random Forest de riesgo gestacional (PR #4).

Lee las dos variantes de `data/processed/` y escribe **solo** en `models/` y
`reports/ml/`. `data/` es de solo lectura para este script.

Antes de leer nada, verifica que cada CSV procesado coincide con el SHA-256
publicado en `reports/ml/data_cleaning_report.md` (Seccion 3) y aborta con
`DatasetIntegrityError` si no.

Protocolo, identico para ambas variantes (ML_SPEC.md, Decision D):

1. Split 80/20 estratificado con semilla fija. El 20% se aparta al inicio y
   solo se toca en `evaluate()`, una vez por variante.
2. Busqueda de hiperparametros con `GridSearchCV` y CV estratificada de 10
   folds **sobre el entrenamiento**. Su puntaje es de SELECCION, no de
   rendimiento (Decision E).
3. CV anidada (externa 10 x interna 5) sobre el entrenamiento: estimacion
   insesgada del procedimiento. Es la cifra con la que se eligen variante y
   umbral, para que la eleccion no consulte el conjunto de prueba.
4. Evaluacion final sobre el 20% apartado: la estimacion de rendimiento del
   modelo que se entrega.
5. Modelos de referencia (Dummy y arbol simple) bajo el mismo protocolo.
6. Comprobaciones de sobreajuste (Decision C).

Determinista: misma semilla -> mismas metricas. `n_jobs` no altera el
resultado, solo el reparto de trabajo.

El modelo serializado se ajusta **solo con el 80% de entrenamiento**: lo medido
y lo entregado son el mismo objeto.

Regenerar:  .venv\\Scripts\\python.exe scripts\\train_model.py
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import sklearn  # noqa: E402
from sklearn.dummy import DummyClassifier  # noqa: E402
from sklearn.ensemble import RandomForestClassifier  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    accuracy_score,
    confusion_matrix,
    make_scorer,
    precision_recall_fscore_support,
)
from sklearn.model_selection import (  # noqa: E402
    GridSearchCV,
    RepeatedStratifiedKFold,
    StratifiedKFold,
    cross_val_score,
    learning_curve,
    permutation_test_score,
    train_test_split,
)
from sklearn.pipeline import Pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402
from sklearn.tree import DecisionTreeClassifier  # noqa: E402

import training_report  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
CLEANING_REPORT = REPO_ROOT / "reports" / "ml" / "data_cleaning_report.md"

#: Nombre de variante -> CSV de entrada. Ambas se entrenan (ML_SPEC, Decision D).
VARIANTS = {
    "clean": PROCESSED_DIR / "maternal_risk_clean.csv",
    "paper": PROCESSED_DIR / "maternal_risk_paper.csv",
}

#: Las 8 variables clinicas, en el orden que fija ML_SPEC.md (Seccion 3).
#: Este orden es contrato: el backend debe enviar el vector asi.
FEATURE_COLUMNS = (
    "age_years",
    "temperature_f",
    "heart_rate_bpm",
    "systolic_bp_mmhg",
    "diastolic_bp_mmhg",
    "bmi_kg_m2",
    "hba1c_mmol_mol",
    "fasting_glucose_mmol_l",
)

#: Unidad real de cada feature. El dataset conserva las del paper (F, mmol/mol,
#: mmol/L); la conversion desde unidades clinicas peruanas vive en el backend.
FEATURE_UNITS = {
    "age_years": "años",
    "temperature_f": "°F",
    "heart_rate_bpm": "lpm",
    "systolic_bp_mmhg": "mmHg",
    "diastolic_bp_mmhg": "mmHg",
    "bmi_kg_m2": "kg/m²",
    "hba1c_mmol_mol": "mmol/mol",
    "fasting_glucose_mmol_l": "mmol/L",
}

TARGET_COLUMN = "risk_level"
HIGH_RISK = "high risk"
LOW_RISK = "low risk"

#: Fijados antes de la primera ejecucion y nunca modificados despues.
RANDOM_SEED = 42
TEST_SIZE = 0.20
CV_FOLDS = 10
NESTED_INNER_FOLDS = 5
N_PERMUTATIONS = 100
PARTITION_VARIANCE_SPLITS = 5
PARTITION_VARIANCE_REPEATS = 5
LEARNING_CURVE_FRACTIONS = (0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0)

MODEL_VERSION = "1.0.0"
MODEL_FILENAME = f"maternal_risk_rf_v{MODEL_VERSION}.joblib"

#: Metrica principal de decision (ML_SPEC, Decision B). Multiclase y con las
#: clases casi balanceadas, penaliza precision y recall a la vez.
SELECTION_METRIC = "f1_macro"

#: Rejilla de busqueda. Se publica en el reporte leyendola de aqui, no
#: transcrita. `criterion` queda fijo en "gini": duplicaria la rejilla y su
#: efecto en un bosque es marginal.
PARAM_GRID = {
    "n_estimators": [200, 500],
    "max_depth": [None, 10, 20],
    "min_samples_leaf": [1, 2, 5],
    "max_features": ["sqrt", None],
    "class_weight": [None, "balanced"],
}
FIXED_PARAMS = {"criterion": "gini", "random_state": RANDOM_SEED, "n_jobs": 1}

#: Banda de coherencia entre el test apartado y la CV anidada (Decision C4).
CONSISTENCY_BAND_SIGMAS = 3

#: Fraccion de la ventaja que la ablacion debe explicar para atribuirla a las
#: 42 filas de hipotermia (Decision D, rama D2).
ABLATION_EXPLAINS_FRACTION = 0.5

#: Banda de temperatura sospechosa (ML_SPEC, Seccion 7.1).
HYPOTHERMIA_BAND_F = (93.0, 94.9)

FIGURE_DPI = 100
#: matplotlib escribe su version en el PNG; sin esto los bytes cambiarian con
#: cada actualizacion de la libreria aunque la figura fuera identica.
FIGURE_METADATA = {"Software": None}


class DatasetIntegrityError(RuntimeError):
    """Un CSV procesado no coincide con su SHA-256 publicado."""


# --- Integridad de entrada -------------------------------------------------


def sha256_of_file(path: Path) -> str:
    """Devuelve el SHA-256 hexadecimal del archivo."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    """Ruta relativa al repo cuando aplica; absoluta si esta fuera de el."""
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def recorded_dataset_sha256(csv_name: str) -> str:
    """SHA-256 de una variante tal como lo publica la Seccion 3 del reporte de limpieza."""
    texto = CLEANING_REPORT.read_text(encoding="utf-8")
    patron = rf"`data/processed/{re.escape(csv_name)}`\s*\|\s*\d+\s*\|\s*`([0-9a-f]{{64}})`"
    match = re.search(patron, texto)
    if match is None:
        raise DatasetIntegrityError(
            f"No se encontro el SHA-256 de {csv_name} en {_display_path(CLEANING_REPORT)}. "
            "No se entrena sobre un dataset sin referencia de integridad."
        )
    return match.group(1)


def verify_dataset_integrity(path: Path) -> str:
    """Aborta si el dataset cambio. Devuelve el SHA-256 verificado.

    Entrenar sobre un dataset alterado produciria metricas que nadie podria
    reproducir, con un `model_metadata.json` que apuntaria a otro archivo.
    """
    actual = sha256_of_file(path)
    registrado = recorded_dataset_sha256(path.name)
    if actual != registrado:
        raise DatasetIntegrityError(
            f"El dataset procesado no coincide con el SHA-256 registrado.\n"
            f"  archivo:    {_display_path(path)}\n"
            f"  registrado: {registrado}  ({_display_path(CLEANING_REPORT)})\n"
            f"  calculado:  {actual}\n"
            "Regenera data/processed/ con scripts/prepare_dataset.py en vez de "
            "actualizar el reporte."
        )
    return actual


# --- Datos y split ---------------------------------------------------------


def load_variant(path: Path) -> tuple[pd.DataFrame, pd.Series]:
    """Lee una variante y devuelve `(X, y)` con las 8 features en orden fijo."""
    df = pd.read_csv(path)
    return df[list(FEATURE_COLUMNS)], df[TARGET_COLUMN]


def make_split(X: pd.DataFrame, y: pd.Series):
    """Split 80/20 estratificado con la semilla fija. Conserva los indices."""
    return train_test_split(
        X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_SEED, shuffle=True
    )


def _exact_overlap(X_train: pd.DataFrame, X_test: pd.DataFrame) -> int:
    """Filas del test cuyo vector de 8 features tambien esta en entrenamiento.

    Dos filas distintas con las 8 variables identicas serian una fuga aunque
    sus indices no se solapen. La variante principal esta deduplicada, asi que
    deberia dar 0; la de comparacion conserva 1 grupo duplicado a proposito.
    """
    en_entrenamiento = set(map(tuple, X_train.to_numpy().tolist()))
    return sum(1 for fila in X_test.to_numpy().tolist() if tuple(fila) in en_entrenamiento)


def feature_ranges(X_train: pd.DataFrame) -> dict:
    """Minimo y maximo por feature, generados del split de entrenamiento.

    Es el rango que el modelo vio de verdad. El backend lo usa para advertir de
    extrapolacion, no para bloquear (ML_SPEC, Seccion 5).
    """
    return {
        "source": (
            f"split de entrenamiento ({int((1 - TEST_SIZE) * 100)}%), semilla {RANDOM_SEED}"
        ),
        "seed": RANDOM_SEED,
        "features": {
            columna: {
                "min": float(X_train[columna].min()),
                "max": float(X_train[columna].max()),
                "unit": FEATURE_UNITS[columna],
            }
            for columna in FEATURE_COLUMNS
        },
    }


# --- Modelo y busqueda -----------------------------------------------------


def build_pipeline(**params) -> Pipeline:
    """Pipeline de un solo paso: el bosque.

    Sin escalador (ML_SPEC, Decision A): un arbol parte por umbrales, y una
    transformacion afin por columna preserva el orden de los valores, luego no
    puede cambiar ninguna particion alcanzable. El Pipeline se conserva porque
    garantiza que cualquier preprocesamiento futuro se ajuste dentro del fold.
    """
    return Pipeline([("model", RandomForestClassifier(**{**FIXED_PARAMS, **params}))])


def _high_to_low_rate(y_true, y_pred) -> float:
    """Proporcion de casos `high risk` clasificados como `low risk`.

    Es el error clinicamente grave: subestimar a una gestante de alto riesgo.
    Ninguna metrica agregada lo distingue del error inverso.
    """
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    return float(np.mean((y_true == HIGH_RISK) & (y_pred == LOW_RISK)))


SCORING = {
    "f1_macro": "f1_macro",
    "neg_high_to_low": make_scorer(_high_to_low_rate, greater_is_better=False),
}


def _complexity_key(params: dict) -> tuple:
    """Orden de simplicidad: menos arboles, menos profundidad, hojas mas grandes."""
    profundidad = params.get("model__max_depth")
    return (
        params.get("model__n_estimators", 0),
        float("inf") if profundidad is None else profundidad,
        -params.get("model__min_samples_leaf", 0),
    )


def _refit_with_tie_break(cv_results) -> int:
    """Elige la configuracion ganadora con la regla declarada antes de medir.

    1. Mejor `f1_macro` medio.
    2. Entre las que caen a menos de 1 desviacion del mejor, la que menos
       errores `high -> low` comete.
    3. Si persiste el empate, la mas simple; y en ultimo termino, la primera.
    """
    f1 = np.asarray(cv_results["mean_test_f1_macro"])
    mejor = int(np.argmax(f1))
    limite = f1[mejor] - cv_results["std_test_f1_macro"][mejor]
    dentro = np.flatnonzero(f1 >= limite)

    h2l = np.asarray(cv_results["mean_test_neg_high_to_low"])[dentro]
    candidatas = dentro[h2l == h2l.max()]

    return int(min(candidatas, key=lambda i: (_complexity_key(cv_results["params"][i]), i)))


def _prefixed(grid: dict) -> dict:
    """Traduce la rejilla al espacio de nombres del Pipeline."""
    return {f"model__{clave}": valores for clave, valores in grid.items()}


def _strip_prefix(params: dict) -> dict:
    return {clave.removeprefix("model__"): valor for clave, valor in params.items()}


def _make_search(grid: dict, folds: int, n_jobs: int) -> GridSearchCV:
    return GridSearchCV(
        build_pipeline(),
        _prefixed(grid),
        scoring=SCORING,
        refit=_refit_with_tie_break,
        cv=StratifiedKFold(n_splits=folds, shuffle=True, random_state=RANDOM_SEED),
        n_jobs=n_jobs,
    )


def search_hyperparameters(X_train, y_train, grid: dict) -> tuple[GridSearchCV, dict]:
    """CV estratificada de 10 folds sobre el entrenamiento. Devuelve la busqueda y su resumen.

    El puntaje que sale de aqui es de **seleccion**: esta sesgado al alza por
    haber elegido el maximo de la rejilla. No es una estimacion de rendimiento.
    """
    busqueda = _make_search(grid, CV_FOLDS, n_jobs=-1)
    busqueda.fit(X_train, y_train)

    resultados = busqueda.cv_results_
    indice = busqueda.best_index_
    argmax_f1 = int(np.argmax(resultados["mean_test_f1_macro"]))
    limite = resultados["mean_test_f1_macro"][argmax_f1] - resultados["std_test_f1_macro"][argmax_f1]

    resumen = {
        "n_candidates": len(resultados["params"]),
        "best_params": _strip_prefix(busqueda.best_params_),
        "hyperparameter_selection_score": {
            "metric": SELECTION_METRIC,
            "mean": float(resultados["mean_test_f1_macro"][indice]),
            "std": float(resultados["std_test_f1_macro"][indice]),
        },
        "n_within_one_std": int(np.sum(resultados["mean_test_f1_macro"] >= limite)),
        "tie_break_applied": indice != argmax_f1,
        "mean_high_to_low_rate": float(-resultados["mean_test_neg_high_to_low"][indice]),
    }
    folds = [float(resultados[f"split{i}_test_f1_macro"][indice]) for i in range(CV_FOLDS)]
    cv_scores = {
        "metric": SELECTION_METRIC,
        "scores": folds,
        "mean": float(np.mean(folds)),
        "std": float(np.std(folds)),
    }
    return busqueda, {"search": resumen, "cv_scores": cv_scores}


def nested_cv_estimate(X_train, y_train, grid: dict) -> dict:
    """CV anidada: externa 10 x interna 5, solo sobre el entrenamiento.

    Estima el rendimiento del **procedimiento completo** (buscar + ajustar) sin
    el sesgo de seleccion del punto anterior, y sin tocar el conjunto de prueba.
    La interna usa 5 folds en vez de 10 por coste: son 10 x N x 5 ajustes.
    """
    externa = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_SEED)
    scores = cross_val_score(
        _make_search(grid, NESTED_INNER_FOLDS, n_jobs=-1),
        X_train,
        y_train,
        cv=externa,
        scoring=SELECTION_METRIC,
        n_jobs=1,
    )
    return {
        "metric": SELECTION_METRIC,
        "outer_folds": CV_FOLDS,
        "inner_folds": NESTED_INNER_FOLDS,
        "scores": [float(s) for s in scores],
        "mean": float(np.mean(scores)),
        "std": float(np.std(scores)),
    }


# --- Evaluacion ------------------------------------------------------------


def evaluate(model, X, y) -> dict:
    """Metricas completas de un modelo ya ajustado sobre un conjunto.

    Unico punto del script que toca el conjunto de prueba, y solo una vez por
    variante.
    """
    etiquetas = list(model.classes_)
    y_pred = model.predict(X)

    precision, recall, f1, soporte = precision_recall_fscore_support(
        y, y_pred, labels=etiquetas, zero_division=0
    )
    macro = precision_recall_fscore_support(
        y, y_pred, labels=etiquetas, average="macro", zero_division=0
    )
    matriz = confusion_matrix(y, y_pred, labels=etiquetas)

    return {
        "accuracy": float(accuracy_score(y, y_pred)),
        "precision_macro": float(macro[0]),
        "recall_macro": float(macro[1]),
        "f1_macro": float(macro[2]),
        "labels": etiquetas,
        "per_class": {
            etiqueta: {
                "precision": float(precision[i]),
                "recall": float(recall[i]),
                "f1": float(f1[i]),
                "support": int(soporte[i]),
            }
            for i, etiqueta in enumerate(etiquetas)
        },
        "confusion_matrix": [[int(v) for v in fila] for fila in matriz],
        "high_to_low": int(matriz[etiquetas.index(HIGH_RISK)][etiquetas.index(LOW_RISK)]),
    }


def reference_models(X_train, y_train, X_test, y_test) -> dict:
    """Dummy (clase mas frecuente) y arbol simple, bajo el mismo protocolo.

    Sin ellos, un 98% de accuracy no dice nada: hay que saber que da el modelo
    que no mira las features y el que mira solo un arbol.
    """
    candidatos = {
        "dummy": DummyClassifier(strategy="most_frequent"),
        "decision_tree": DecisionTreeClassifier(random_state=RANDOM_SEED),
    }
    salida = {}
    for nombre, estimador in candidatos.items():
        estimador.fit(X_train, y_train)
        salida[nombre] = evaluate(estimador, X_test, y_test)
    return salida


# --- Comprobaciones de sobreajuste (Decision C) ----------------------------


def permutation_check(X_train, y_train, best_params: dict) -> dict:
    """C1: con `risk_level` barajado, el modelo no debe aprender nada.

    Si el puntaje con etiquetas permutadas se mantuviera alto, habria fuga en
    el split o en el pipeline y la accuracy real no significaria nada.
    """
    verdadero, permutados, p_valor = permutation_test_score(
        build_pipeline(**best_params),
        X_train,
        y_train,
        cv=StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_SEED),
        n_permutations=N_PERMUTATIONS,
        scoring="accuracy",
        random_state=RANDOM_SEED,
        n_jobs=-1,
    )
    return {
        "metric": "accuracy",
        "true_score": float(verdadero),
        "permuted_mean": float(np.mean(permutados)),
        "permuted_std": float(np.std(permutados)),
        "permuted_max": float(np.max(permutados)),
        "p_value": float(p_valor),
        "n_permutations": N_PERMUTATIONS,
        "chance_level": float(y_train.value_counts(normalize=True).max()),
    }


def partition_variance(X_train, y_train, best_params: dict) -> dict:
    """C5: cuanto depende el resultado de como caiga la particion.

    Se mide con `RepeatedStratifiedKFold` **solo sobre el entrenamiento**:
    volver a partir el conjunto de prueba con otras semillas lo expondria, y
    el contrato dice que se toca una sola vez.
    """
    scores = cross_val_score(
        build_pipeline(**best_params),
        X_train,
        y_train,
        cv=RepeatedStratifiedKFold(
            n_splits=PARTITION_VARIANCE_SPLITS,
            n_repeats=PARTITION_VARIANCE_REPEATS,
            random_state=RANDOM_SEED,
        ),
        scoring=SELECTION_METRIC,
        n_jobs=-1,
    )
    return {
        "metric": SELECTION_METRIC,
        "n_splits": PARTITION_VARIANCE_SPLITS,
        "n_repeats": PARTITION_VARIANCE_REPEATS,
        "mean": float(np.mean(scores)),
        "std": float(np.std(scores)),
        "min": float(np.min(scores)),
        "max": float(np.max(scores)),
    }


def scaler_ablation(X_train, y_train, best_params: dict) -> dict:
    """Evidencia de la Decision A: el escalado no aporta nada a un bosque.

    Se mide con CV sobre el entrenamiento, no sobre el test apartado: es un
    diagnostico, y el test no se gasta en diagnosticos.
    """
    particion = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_SEED)
    variantes = {
        "without_scaler": build_pipeline(**best_params),
        "with_scaler": Pipeline(
            [
                ("scaler", StandardScaler()),
                ("model", RandomForestClassifier(**{**FIXED_PARAMS, **best_params})),
            ]
        ),
    }
    medidas = {
        nombre: cross_val_score(
            pipeline, X_train, y_train, cv=particion, scoring=SELECTION_METRIC, n_jobs=-1
        )
        for nombre, pipeline in variantes.items()
    }
    return {
        "metric": SELECTION_METRIC,
        **{nombre: float(np.mean(scores)) for nombre, scores in medidas.items()},
        "delta": float(np.mean(medidas["with_scaler"]) - np.mean(medidas["without_scaler"])),
    }


def hypothermia_ablation(X_train, y_train, grid: dict, referencia: dict) -> dict:
    """C6: cuanto del rendimiento cargan las 42 filas de 93.0-94.9 F.

    ML_SPEC Seccion 7.1 documenta que las 42 son `high risk` al 100% frente a
    una tasa base del 33.28%. Si al quitarlas el rendimiento se desploma, el
    modelo aprendio «93-95 F => high risk», que es un artefacto de sensor y no
    se sostendria en produccion.

    Se compara en la escala de la CV anidada, la misma con la que la Decision D
    elige variante, para que ambos numeros sean comparables.
    """
    minimo, maximo = HYPOTHERMIA_BAND_F
    fuera_de_banda = ~X_train["temperature_f"].between(minimo, maximo)
    X_ablado = X_train.loc[fuera_de_banda]
    y_ablado = y_train.loc[fuera_de_banda]

    anidada = nested_cv_estimate(X_ablado, y_ablado, grid)
    return {
        "band_f": list(HYPOTHERMIA_BAND_F),
        "rows_removed": int((~fuera_de_banda).sum()),
        "training_rows_after": int(len(X_ablado)),
        "nested_cv_mean": anidada["mean"],
        "nested_cv_std": anidada["std"],
        "delta_vs_full": float(referencia["mean"] - anidada["mean"]),
    }


def learning_curve_data(X_train, y_train, best_params: dict) -> dict:
    """C2: train vs CV segun el tamano del entrenamiento.

    Una brecha grande y persistente indicaria memorizacion. En un bosque con
    `max_depth=None` la curva de entrenamiento roza 1.0 por diseno, asi que lo
    informativo es si la de validacion converge hacia ella.
    """
    tamanos, train_scores, cv_scores = learning_curve(
        build_pipeline(**best_params),
        X_train,
        y_train,
        train_sizes=np.array(LEARNING_CURVE_FRACTIONS),
        cv=StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_SEED),
        scoring=SELECTION_METRIC,
        shuffle=True,
        random_state=RANDOM_SEED,
        n_jobs=-1,
    )
    return {
        "metric": SELECTION_METRIC,
        "train_sizes": [int(t) for t in tamanos],
        "train_scores_mean": [float(v) for v in train_scores.mean(axis=1)],
        "test_scores_mean": [float(v) for v in cv_scores.mean(axis=1)],
        "final_gap": float(train_scores.mean(axis=1)[-1] - cv_scores.mean(axis=1)[-1]),
    }


def consistency_band(held_out_f1: float, anidada: dict) -> dict:
    """C4: banda de DOS lados entre el test apartado y la CV anidada.

    Por debajo indicaria un test desfavorable o un split degenerado; por encima,
    una particion afortunada o una fuga que la CV anidada no ve. Una sola cota
    solo detectaria una de las dos.
    """
    delta = abs(held_out_f1 - anidada["mean"])
    limite = CONSISTENCY_BAND_SIGMAS * anidada["std"]
    return {
        "sigmas": CONSISTENCY_BAND_SIGMAS,
        "delta": float(delta),
        "limit": float(limite),
        "within": bool(delta <= limite),
        "side": "above" if held_out_f1 > anidada["mean"] else "below",
    }


# --- Orquestacion por variante ---------------------------------------------


def train_variant(nombre: str, path: Path, sha256: str, grid: dict, full_checks: bool):
    """Aplica el protocolo completo a una variante.

    Devuelve `(datos, modelo, split)`. `datos` es serializable a JSON; el modelo
    y el split se usan despues para los artefactos y las figuras.
    """
    X, y = load_variant(path)
    X_train, X_test, y_train, y_test = make_split(X, y)

    busqueda, resumen = search_hyperparameters(X_train, y_train, grid)
    best_params = resumen["search"]["best_params"]

    modelo = build_pipeline(**best_params)
    modelo.fit(X_train, y_train)

    anidada = (
        nested_cv_estimate(X_train, y_train, grid)
        if full_checks
        else {**resumen["cv_scores"], "outer_folds": CV_FOLDS, "inner_folds": NESTED_INNER_FOLDS}
    )
    held_out = evaluate(modelo, X_test, y_test)

    checks = {"consistency_band": consistency_band(held_out["f1_macro"], anidada)}
    if full_checks:
        checks["permutation"] = permutation_check(X_train, y_train, best_params)
        checks["partition_variance"] = partition_variance(X_train, y_train, best_params)
        checks["scaler_ablation"] = scaler_ablation(X_train, y_train, best_params)
        if nombre == "clean":
            checks["hypothermia_ablation"] = hypothermia_ablation(
                X_train, y_train, grid, anidada
            )

    datos = {
        "dataset": {
            "path": _display_path(path),
            "sha256": sha256,
            "rows": int(len(X)),
            "class_distribution": {k: int(v) for k, v in sorted(y.value_counts().items())},
        },
        "split": {
            "seed": RANDOM_SEED,
            "test_size": TEST_SIZE,
            "train_rows": int(len(X_train)),
            "test_rows": int(len(X_test)),
            "train_distribution": {k: int(v) for k, v in sorted(y_train.value_counts().items())},
            "test_distribution": {k: int(v) for k, v in sorted(y_test.value_counts().items())},
            "overlap_exact_rows": _exact_overlap(X_train, X_test),
        },
        **resumen,
        "nested_cv": anidada,
        "held_out_test": held_out,
        "train_accuracy": float(modelo.score(X_train, y_train)),
        "reference_models": reference_models(X_train, y_train, X_test, y_test),
        "feature_importance": {
            columna: float(peso)
            for columna, peso in zip(
                FEATURE_COLUMNS, modelo.named_steps["model"].feature_importances_
            )
        },
        "checks": checks,
    }
    del busqueda  # ya extraido todo lo que se publica; no se serializa
    return datos, modelo, (X_train, X_test, y_train, y_test)


def choose_production_variant(variantes: dict) -> dict:
    """Aplica la regla de la Decision D, declarada antes de la primera medicion.

    El `delta` se calcula sobre la **CV anidada** (solo entrenamiento), no sobre
    el test apartado: asi la eleccion de variante no consulta el conjunto de
    prueba de ninguna de las dos.

    - D1  |delta| <= umbral                        -> `clean`
    - D2  delta > umbral y la ablacion lo explica  -> `paper` (artefacto)
    - D3  delta > umbral sin explicacion            -> `clean`
    - D4  delta < -umbral                           -> `paper`
    """
    delta = variantes["clean"]["nested_cv"]["mean"] - variantes["paper"]["nested_cv"]["mean"]
    ganadora = "clean" if delta >= 0 else "paper"
    umbral = variantes[ganadora]["nested_cv"]["std"]

    ablacion = variantes["clean"]["checks"].get("hypothermia_ablation")
    explicada = (
        ablacion is not None
        and delta > 0
        and ablacion["delta_vs_full"] >= ABLATION_EXPLAINS_FRACTION * delta
    )

    if abs(delta) <= umbral:
        rama, variante = "D1", "clean"
        razon = (
            "Las dos variantes rinden igual dentro del ruido del procedimiento: la "
            "sospecha de artefacto sobre las 42 filas de hipotermia no se sostiene, "
            "y conservarlas preserva casos `high risk` reales."
        )
    elif delta > umbral and explicada:
        rama, variante = "D2", "paper"
        razon = (
            "La ventaja de la variante principal desaparece al quitar las 42 filas de "
            "93.0-94.9 F: la cargaban ellas. Se trata como artefacto de captura y se "
            "adopta la variante que las excluye."
        )
    elif delta > umbral:
        rama, variante = "D3", "clean"
        razon = (
            "La ventaja de la variante principal sobrevive a quitar las 42 filas de "
            "hipotermia, luego no procede de esa banda sino del resto de filas "
            "conservadas y de la deduplicacion."
        )
    else:
        rama, variante = "D4", "paper"
        razon = (
            "La variante de comparacion rinde mejor por encima del umbral: las reglas "
            "de outliers del paper resultan preferibles sobre estos datos."
        )

    return {
        "variant": variante,
        "rule_branch": rama,
        "metric": SELECTION_METRIC,
        "basis": "nested_cv",
        "delta_f1_macro": float(delta),
        "threshold": float(umbral),
        "ablation_explains": bool(explicada),
        "reason": razon,
    }


# --- Artefactos ------------------------------------------------------------


def build_metadata(nombre: str, datos: dict, modelo, sha256: str) -> dict:
    """Contrato del artefacto: todo lo que el backend necesita para cargarlo sin ambiguedad."""
    held_out = datos["held_out_test"]
    return {
        "model_version": MODEL_VERSION,
        "model_file": MODEL_FILENAME,
        "algorithm": "RandomForestClassifier",
        "created_at": datos["created_at"],
        "variant": nombre,
        "dataset": {
            "path": datos["dataset"]["path"],
            "sha256": sha256,
            "rows": datos["dataset"]["rows"],
        },
        "training_rows": datos["split"]["train_rows"],
        "features": [
            {"name": columna, "unit": FEATURE_UNITS[columna], "position": i}
            for i, columna in enumerate(FEATURE_COLUMNS)
        ],
        "classes": list(modelo.classes_),
        "hyperparameters": datos["search"]["best_params"],
        "fixed_params": {k: v for k, v in FIXED_PARAMS.items() if k != "n_jobs"},
        "seed": RANDOM_SEED,
        "split": {"test_size": TEST_SIZE, "stratified": True, "seed": RANDOM_SEED},
        "environment": _environment(),
        "metrics_summary": {
            "source": "held_out_test",
            "accuracy": held_out["accuracy"],
            "f1_macro": held_out["f1_macro"],
            "precision_macro": held_out["precision_macro"],
            "recall_macro": held_out["recall_macro"],
            "high_to_low_errors": held_out["high_to_low"],
        },
        # Texto destinado a personas, no a codigo: va acentuado, como las
        # unidades de `features` y como los documentos de reports/ml/.
        "disclaimer": (
            "Apoyo a la decisión clínica. No es un diagnóstico y no reemplaza la "
            "evaluación del personal médico."
        ),
    }


def _environment() -> dict:
    return {
        "python": platform.python_version(),
        "scikit_learn": sklearn.__version__,
        "joblib": joblib.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
    }


def _save_figure(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=FIGURE_DPI, metadata=FIGURE_METADATA, bbox_inches="tight")
    plt.close(fig)


def _plot_confusion_matrix(datos: dict, nombre: str, path: Path) -> None:
    matriz = np.array(datos["held_out_test"]["confusion_matrix"])
    etiquetas = datos["held_out_test"]["labels"]

    fig, ax = plt.subplots(figsize=(5.5, 4.8))
    ax.imshow(matriz, cmap="Blues")
    ax.set_xticks(range(len(etiquetas)), etiquetas, rotation=20, ha="right")
    ax.set_yticks(range(len(etiquetas)), etiquetas)
    ax.set_xlabel("Predicho")
    ax.set_ylabel("Real")
    ax.set_title(f"Matriz de confusion — {nombre} (test apartado)")
    umbral = matriz.max() / 2
    for i in range(matriz.shape[0]):
        for j in range(matriz.shape[1]):
            ax.text(
                j,
                i,
                str(matriz[i, j]),
                ha="center",
                va="center",
                color="white" if matriz[i, j] > umbral else "black",
            )
    _save_figure(fig, path)


def _plot_feature_importance(datos: dict, nombre: str, path: Path) -> None:
    pares = sorted(datos["feature_importance"].items(), key=lambda kv: kv[1])
    nombres = [p[0] for p in pares]
    pesos = [p[1] for p in pares]

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.barh(nombres, pesos, color="#3b6ea5")
    ax.set_xlabel("Importancia (reduccion media de impureza)")
    ax.set_title(f"Importancia de variables — {nombre}")
    _save_figure(fig, path)


def _plot_cv_scores(datos: dict, nombre: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    series = [datos["cv_scores"]["scores"], datos["nested_cv"]["scores"]]
    ax.boxplot(series, tick_labels=["Seleccion (10 folds)", "CV anidada (10x5)"])
    for i, valores in enumerate(series, start=1):
        ax.scatter([i] * len(valores), valores, alpha=0.6, color="#3b6ea5", zorder=3)
    ax.set_ylabel(SELECTION_METRIC)
    ax.set_title(f"Distribucion de puntajes de validacion cruzada — {nombre}")
    _save_figure(fig, path)


def _plot_learning_curve(curva: dict, nombre: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    ax.plot(curva["train_sizes"], curva["train_scores_mean"], marker="o", label="Entrenamiento")
    ax.plot(curva["train_sizes"], curva["test_scores_mean"], marker="s", label="Validacion (CV)")
    ax.set_xlabel("Filas de entrenamiento")
    ax.set_ylabel(SELECTION_METRIC)
    ax.set_title(f"Curva de aprendizaje — {nombre}")
    ax.legend()
    ax.grid(alpha=0.3)
    _save_figure(fig, path)


def write_figures(resultados: dict, curva: dict, variante_produccion: str, figures_dir: Path):
    """Genera las figuras y devuelve sus rutas relativas al repo."""
    generadas = []
    for nombre, datos in resultados.items():
        for sufijo, dibujar in (
            ("confusion_matrix", _plot_confusion_matrix),
            ("feature_importance", _plot_feature_importance),
            ("cv_scores", _plot_cv_scores),
        ):
            path = figures_dir / f"training_{sufijo}_{nombre}.png"
            dibujar(datos, nombre, path)
            generadas.append(path.name)

    if curva is not None:
        path = figures_dir / "training_learning_curve.png"
        _plot_learning_curve(curva, variante_produccion, path)
        generadas.append(path.name)

    return sorted(generadas)


def _write_json(path: Path, datos: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(datos, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


# --- Punto de entrada ------------------------------------------------------


def main(out_dir: Path | None = None, param_grid: dict | None = None, full_checks: bool = True):
    """Entrena, valida y escribe todos los artefactos.

    `out_dir` es la raiz bajo la que se crean `models/` y `reports/ml/`. Los
    tests la apuntan a un `tmp_path` para no reescribir nunca lo commiteado.
    `param_grid` y `full_checks` existen para que la suite no pague los miles
    de ajustes de la CV anidada: lo que esos tests comprueban es el
    determinismo del procedimiento, no el tamano de la busqueda.
    """
    inicio = time.perf_counter()
    rejilla = PARAM_GRID if param_grid is None else param_grid

    # La integridad se verifica ANTES de crear nada: si un dataset no coincide,
    # no debe quedar ni un directorio a medias.
    shas = {nombre: verify_dataset_integrity(path) for nombre, path in VARIANTS.items()}

    raiz = REPO_ROOT if out_dir is None else Path(out_dir)
    models_dir = raiz / "models"
    reports_dir = raiz / "reports" / "ml"
    creado = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    resultados, modelos, splits = {}, {}, {}
    for nombre, path in VARIANTS.items():
        datos, modelo, split = train_variant(nombre, path, shas[nombre], rejilla, full_checks)
        datos["created_at"] = creado
        resultados[nombre], modelos[nombre], splits[nombre] = datos, modelo, split

    produccion = choose_production_variant(resultados)
    elegida = produccion["variant"]
    X_train, _, y_train, _ = splits[elegida]

    curva = (
        learning_curve_data(X_train, y_train, resultados[elegida]["search"]["best_params"])
        if full_checks
        else None
    )
    if curva is not None:
        curva["variant"] = elegida

    rangos = feature_ranges(X_train)
    metadata = build_metadata(elegida, resultados[elegida], modelos[elegida], shas[elegida])

    models_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(modelos[elegida], models_dir / MODEL_FILENAME)
    _write_json(models_dir / "model_metadata.json", metadata)
    _write_json(models_dir / "feature_ranges.json", rangos)

    figuras = write_figures(resultados, curva, elegida, reports_dir / "figures")

    for datos in resultados.values():
        datos.pop("created_at")

    metricas = {
        "generated_at": creado,
        "seed": RANDOM_SEED,
        "test_size": TEST_SIZE,
        "cv_folds": CV_FOLDS,
        "nested_inner_folds": NESTED_INNER_FOLDS,
        "selection_metric": SELECTION_METRIC,
        "n_candidates": resultados[elegida]["search"]["n_candidates"],
        "param_grid": rejilla,
        "fixed_params": {k: v for k, v in FIXED_PARAMS.items() if k != "n_jobs"},
        "environment": _environment(),
        "model_version": MODEL_VERSION,
        "model_file": MODEL_FILENAME,
        "full_checks": full_checks,
        "production": produccion,
        "variants": resultados,
        "learning_curve": curva,
        "feature_ranges": rangos,
        "figures": figuras,
        "elapsed_seconds": round(time.perf_counter() - inicio, 3),
    }
    _write_json(reports_dir / "training_metrics.json", metricas)

    reporte = reports_dir / "training_report.md"
    reporte.parent.mkdir(parents=True, exist_ok=True)
    reporte.write_text(training_report.render(metricas), encoding="utf-8", newline="\n")

    _print_summary(metricas)
    return metricas


def _print_summary(metricas: dict) -> None:
    print(f"Semilla: {metricas['seed']}  |  test: {metricas['test_size']:.0%}")
    print(f"Candidatos en la rejilla: {metricas['n_candidates']}")
    for nombre, datos in metricas["variants"].items():
        held = datos["held_out_test"]
        print(f"\n{nombre}: {datos['dataset']['path']}")
        print(f"  SHA-256 verificado: {datos['dataset']['sha256']}")
        print(f"  train/test: {datos['split']['train_rows']}/{datos['split']['test_rows']}")
        print(f"  solapamiento exacto train/test: {datos['split']['overlap_exact_rows']}")
        print(f"  hiperparametros: {datos['search']['best_params']}")
        print(
            f"  puntaje de SELECCION (no es rendimiento): "
            f"{datos['search']['hyperparameter_selection_score']['mean']:.4f}"
        )
        print(f"  CV anidada: {datos['nested_cv']['mean']:.4f} ± {datos['nested_cv']['std']:.4f}")
        print(
            f"  TEST apartado: accuracy {held['accuracy']:.4f}  "
            f"f1_macro {held['f1_macro']:.4f}  high->low {held['high_to_low']}"
        )
    produccion = metricas["production"]
    print(
        f"\nProduccion: {produccion['variant']} (rama {produccion['rule_branch']}, "
        f"delta {produccion['delta_f1_macro']:+.6f}, umbral {produccion['threshold']:.6f})"
    )
    print(f"Tiempo total: {metricas['elapsed_seconds']:.1f} s")


if __name__ == "__main__":
    main()
