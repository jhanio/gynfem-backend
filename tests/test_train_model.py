"""Tests de scripts/train_model.py — entrenamiento del Random Forest (PR #4).

Estos tests se escribieron **antes** que el script. Verifican tres cosas
distintas, y conviene no confundirlas:

1. **El contrato del artefacto**: que `models/` describa sin ambigüedad el
   modelo que contiene (orden de features, unidades, orden de clases,
   hiperparámetros, versiones).
2. **La honestidad del protocolo**: que el conjunto de prueba no haya entrado
   en el entrenamiento, que el split sea el registrado y que las comprobaciones
   de sobreajuste realmente se hayan ejecutado y superado.
3. **Que ninguna cifra publicada esté escrita a mano**: el reporte se regenera
   byte a byte desde `training_metrics.json`, y las métricas de ese JSON se
   reproducen reentrenando.

`test_ningun_artefacto_generado_contiene_valores_de_name` lee la columna `Name`
del RAW para poder buscarla en los artefactos, igual que su equivalente de
PR #3. Ningún test de este archivo imprime un valor concreto de `Name`.
"""

import json
import os
import platform
import re
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
import sklearn
from sklearn.preprocessing import StandardScaler

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import train_model  # noqa: E402
import training_report  # noqa: E402

from conftest import (  # noqa: E402
    FEATURE_RANGES,
    ML_SPEC,
    MODEL_METADATA,
    MODELS_DIR,
    RAW_CSV,
    REDUCED_PARAM_GRID,
    REQUIREMENTS,
    TINY_PARAM_GRID,
    TRAINING_METRICS,
    TRAINING_REPORT,
)

#: Las 8 variables clínicas, en el orden que fija ML_SPEC.md (Sección 3).
#: Escritas aquí a propósito, independientes de la constante del script: si
#: alguien reordena `train_model.FEATURE_COLUMNS`, estos tests lo detectan.
EXPECTED_FEATURES = [
    "age_years",
    "temperature_f",
    "heart_rate_bpm",
    "systolic_bp_mmhg",
    "diastolic_bp_mmhg",
    "bmi_kg_m2",
    "hba1c_mmol_mol",
    "fasting_glucose_mmol_l",
]

#: Unidad real de cada feature (ML_SPEC.md, Sección 3). También literales:
#: el backend convierte a estas unidades antes de invocar el modelo, así que
#: un cambio silencioso aquí sería un error clínico, no cosmético.
EXPECTED_UNITS = {
    "age_years": "años",
    "temperature_f": "°F",
    "heart_rate_bpm": "lpm",
    "systolic_bp_mmhg": "mmHg",
    "diastolic_bp_mmhg": "mmHg",
    "bmi_kg_m2": "kg/m²",
    "hba1c_mmol_mol": "mmol/mol",
    "fasting_glucose_mmol_l": "mmol/L",
}

RISK_LABELS = {"low risk", "mid risk", "high risk"}

#: Semilla y proporción declaradas en el plan **antes** de la primera
#: ejecución. Fijarlas aquí impide elegirlas a posteriori.
EXPECTED_SEED = 42
EXPECTED_TEST_SIZE = 0.20
EXPECTED_CV_FOLDS = 10

#: Tolerancia de comparación de flotantes. Solo absorbe el formateo de JSON:
#: el cálculo es determinista, así que cualquier diferencia real es mucho mayor.
FLOAT_TOLERANCE = 1e-12

#: Nivel de azar en un problema de 3 clases casi balanceadas (≈33.4%). La
#: prueba de etiquetas permutadas debe caer aquí; el margen cubre la varianza
#: de las permutaciones sin dejar pasar una fuga.
PERMUTATION_MAX_SCORE = 0.40
PERMUTATION_MAX_P_VALUE = 0.01

#: Máxima desviación tolerada entre el split y la distribución global.
STRATIFICATION_TOLERANCE_PP = 0.5


# --- Utilidades ------------------------------------------------------------


def _tokens(texto: str) -> set[str]:
    """Tokens alfabéticos de un texto, normalizados a minúsculas."""
    return {t.lower() for t in re.findall(r"[A-Za-z']{2,}", texto)}


def _name_tokens() -> set[str]:
    """Valores distintos de `Name` en el RAW, en minúsculas. Nunca se imprimen."""
    nombres = pd.read_csv(RAW_CSV, usecols=["Name"])["Name"].astype(str).str.strip()
    return {n.lower() for n in nombres.unique() if len(n) >= 2}


def _assert_close(actual, esperado, ruta: str = "") -> None:
    """Compara estructuras anidadas de métricas con tolerancia de formato."""
    assert type(actual) is type(esperado) or isinstance(actual, (int, float)), (
        f"{ruta}: tipos distintos ({type(actual).__name__} vs {type(esperado).__name__})"
    )
    if isinstance(esperado, dict):
        assert set(actual) == set(esperado), f"{ruta}: claves distintas"
        for clave in esperado:
            _assert_close(actual[clave], esperado[clave], f"{ruta}.{clave}")
    elif isinstance(esperado, list):
        assert len(actual) == len(esperado), f"{ruta}: longitudes distintas"
        for i, (a, e) in enumerate(zip(actual, esperado)):
            _assert_close(a, e, f"{ruta}[{i}]")
    elif isinstance(esperado, bool) or esperado is None or isinstance(esperado, str):
        assert actual == esperado, f"{ruta}: {actual!r} != {esperado!r}"
    else:
        assert actual == pytest.approx(esperado, abs=FLOAT_TOLERANCE), (
            f"{ruta}: {actual!r} != {esperado!r}"
        )


@pytest.fixture(scope="session")
def production_variant(committed_metrics: dict) -> str:
    return committed_metrics["production"]["variant"]


@pytest.fixture(scope="session")
def production_dataset(production_variant: str) -> Path:
    return train_model.VARIANTS[production_variant]


@pytest.fixture(scope="session")
def production_split(production_dataset: Path):
    """Reconstruye el split de la variante de producción con la semilla registrada."""
    X, y = train_model.load_variant(production_dataset)
    return train_model.make_split(X, y)


# --- Integridad del dataset de entrada -------------------------------------


def test_el_entrenamiento_aborta_si_el_dataset_no_coincide_con_su_sha(tmp_path, monkeypatch):
    """Un dataset alterado debe detener el entrenamiento antes de escribir nada."""
    reporte_falso = tmp_path / "data_cleaning_report.md"
    reporte_falso.write_text(
        "| `data/processed/maternal_risk_clean.csv` | 6099 | `" + "0" * 64 + "` |\n"
        "| `data/processed/maternal_risk_paper.csv` | 6058 | `" + "0" * 64 + "` |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(train_model, "CLEANING_REPORT", reporte_falso)

    # La rejilla mínima no es una optimización: si la verificación faltara,
    # `main()` seguiría de largo, y con la rejilla completa este test tardaría
    # horas en fallar en vez de segundos.
    with pytest.raises(train_model.DatasetIntegrityError) as error:
        train_model.main(
            out_dir=tmp_path / "salida", param_grid=TINY_PARAM_GRID, full_checks=False
        )

    assert "no coincide" in str(error.value)
    assert not (tmp_path / "salida").exists(), "abortó tarde: ya había escrito"


def test_el_entrenamiento_aborta_si_no_hay_sha_registrado(tmp_path, monkeypatch):
    reporte_falso = tmp_path / "data_cleaning_report.md"
    reporte_falso.write_text("# Sin SHA publicado\n", encoding="utf-8")
    monkeypatch.setattr(train_model, "CLEANING_REPORT", reporte_falso)

    with pytest.raises(train_model.DatasetIntegrityError):
        train_model.main(
            out_dir=tmp_path / "salida", param_grid=TINY_PARAM_GRID, full_checks=False
        )


def test_el_sha_del_dataset_en_el_metadata_es_el_del_csv_commiteado(
    committed_metadata, production_dataset
):
    """Tres cifras que deben ser la misma: metadata, archivo y reporte de limpieza."""
    del_archivo = train_model.sha256_of_file(production_dataset)
    del_reporte = train_model.recorded_dataset_sha256(production_dataset.name)

    assert committed_metadata["dataset"]["sha256"] == del_archivo
    assert committed_metadata["dataset"]["sha256"] == del_reporte


# --- Contrato del artefacto ------------------------------------------------


def test_el_modelo_carga_y_predice_con_la_forma_esperada(committed_model, production_dataset):
    X, _ = train_model.load_variant(production_dataset)
    muestra = X.head(50)

    predicciones = committed_model.predict(muestra)
    probabilidades = committed_model.predict_proba(muestra)

    assert predicciones.shape == (50,)
    assert probabilidades.shape == (50, 3)
    assert probabilidades.sum(axis=1) == pytest.approx(1.0, abs=1e-9)


def test_las_clases_predichas_pertenecen_a_las_tres_etiquetas(committed_model, production_dataset):
    X, _ = train_model.load_variant(production_dataset)
    assert set(committed_model.predict(X)) <= RISK_LABELS


def test_el_orden_de_features_del_metadata_coincide_con_el_usado_al_entrenar(
    artifacts, production_dataset
):
    """Metadata, modelo serializado y CSV procesado declaran el mismo orden."""
    del_metadata = [f["name"] for f in artifacts.metadata["features"]]
    del_modelo = list(artifacts.model.feature_names_in_)
    del_csv = list(pd.read_csv(production_dataset, nrows=0).columns)[:8]

    assert del_metadata == EXPECTED_FEATURES
    assert del_modelo == EXPECTED_FEATURES
    assert del_csv == EXPECTED_FEATURES


def test_permutar_el_orden_de_las_features_cambia_las_predicciones(
    committed_model, production_dataset
):
    """El orden de la prueba anterior importa: no es una lista decorativa.

    Sin este test, `test_el_orden_de_features_...` podría satisfacerse con un
    orden que el modelo ignora, y el backend podría enviar el vector barajado
    sin que nada lo notara.
    """
    X, _ = train_model.load_variant(production_dataset)
    muestra = X.head(200)

    barajado = muestra.rename(
        columns={"systolic_bp_mmhg": "diastolic_bp_mmhg", "diastolic_bp_mmhg": "systolic_bp_mmhg"}
    )[EXPECTED_FEATURES]

    originales = committed_model.predict(muestra)
    permutadas = committed_model.predict(barajado)

    assert (originales != permutadas).any(), (
        "intercambiar sistólica y diastólica no cambió ninguna predicción"
    )


def test_cada_feature_del_metadata_declara_la_unidad_que_fija_ml_spec(artifacts):
    """Las unidades del metadata coinciden con la tabla de ML_SPEC.md §3."""
    del_metadata = {f["name"]: f["unit"] for f in artifacts.metadata["features"]}
    assert del_metadata == EXPECTED_UNITS

    spec = ML_SPEC.read_text(encoding="utf-8")
    for columna, unidad in EXPECTED_UNITS.items():
        filas = [line for line in spec.splitlines() if f"`{columna}`" in line and "|" in line]
        assert filas, f"ML_SPEC.md no documenta la columna {columna}"
        assert any(unidad in fila for fila in filas), (
            f"ML_SPEC.md no declara la unidad '{unidad}' para {columna}"
        )


def test_el_orden_de_clases_del_metadata_coincide_con_el_del_modelo(artifacts):
    assert artifacts.metadata["classes"] == list(artifacts.model.classes_)
    assert set(artifacts.metadata["classes"]) == RISK_LABELS


def test_el_nombre_del_joblib_contiene_la_version_del_metadata(artifacts):
    archivos = sorted(artifacts.models_dir.glob("*.joblib"))
    assert len(archivos) == 1, f"se esperaba un solo modelo serializado, hay {len(archivos)}"

    modelo = archivos[0]
    assert modelo.name == artifacts.metadata["model_file"]
    assert artifacts.metadata["model_version"] in modelo.name


def test_los_hiperparametros_del_metadata_son_los_del_modelo_serializado(artifacts):
    del_modelo = artifacts.model.named_steps["model"].get_params()
    for clave, valor in artifacts.metadata["hyperparameters"].items():
        assert del_modelo[clave] == valor, f"hiperparámetro '{clave}' desincronizado"


def test_el_resumen_de_metricas_del_metadata_coincide_con_el_json(artifacts):
    """Cierra el hueco por el que una cifra fija podría entrar solo en el metadata."""
    variante = artifacts.metrics["production"]["variant"]
    held_out = artifacts.metrics["variants"][variante]["held_out_test"]
    resumen = artifacts.metadata["metrics_summary"]

    assert resumen["source"] == "held_out_test"
    for clave in ("accuracy", "f1_macro", "precision_macro", "recall_macro"):
        assert resumen[clave] == pytest.approx(held_out[clave], abs=FLOAT_TOLERANCE)
    assert resumen["high_to_low_errors"] == held_out["high_to_low"]


def test_el_pipeline_no_contiene_un_escalador(artifacts):
    """Ancla la Decisión A al artefacto, no solo al reporte.

    Random Forest es invariante a transformaciones monótonas por columna, así
    que un escalador sería un componente más que versionar a cambio de nada.
    """
    tipos = [type(paso) for _, paso in artifacts.model.steps]
    assert StandardScaler not in tipos


# --- Entorno y versiones fijadas (Decisión F) -------------------------------


def test_la_version_instalada_de_scikit_learn_coincide_con_la_del_metadata(artifacts):
    """Cargar un modelo con otra versión puede cambiar su comportamiento en silencio."""
    assert artifacts.metadata["environment"]["scikit_learn"] == sklearn.__version__


def test_la_version_de_python_del_metadata_coincide_con_la_del_interprete(artifacts):
    assert artifacts.metadata["environment"]["python"] == platform.python_version()


@pytest.mark.parametrize("paquete", ["scikit-learn", "joblib"])
def test_requirements_fija_con_igual_exacto_scikit_learn_y_joblib(paquete, artifacts):
    """El pin debe existir, ser exacto y coincidir con lo que registra el metadata."""
    clave = paquete.replace("-", "_")
    instalada = artifacts.metadata["environment"][clave]

    lineas = [
        line.strip()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip().lower().startswith(paquete)
    ]
    assert lineas == [f"{paquete}=={instalada}"], (
        f"requirements.txt no fija {paquete} en {instalada} con '=='"
    )


# --- feature_ranges.json ---------------------------------------------------


def test_feature_ranges_concuerda_con_el_split_de_entrenamiento(artifacts, production_split):
    """Recalculado desde el CSV procesado con la semilla registrada, debe dar lo mismo."""
    X_train, _, _, _ = production_split
    recalculado = train_model.feature_ranges(X_train)

    _assert_close(artifacts.ranges["features"], recalculado["features"], "feature_ranges")
    assert artifacts.ranges["seed"] == EXPECTED_SEED


def test_feature_ranges_cubre_las_ocho_features_en_el_orden_del_metadata(artifacts):
    del_metadata = [f["name"] for f in artifacts.metadata["features"]]
    assert list(artifacts.ranges["features"]) == del_metadata == EXPECTED_FEATURES


def test_ningun_valor_de_feature_ranges_es_inventado(artifacts, production_split):
    """Cada mínimo y cada máximo ocurre realmente en su columna.

    Un valor redondo escrito a mano (p. ej. un IMC máximo de 40.0) no aparece
    en los datos y este test lo delata.
    """
    X_train, _, _, _ = production_split
    for columna, rango in artifacts.ranges["features"].items():
        valores = set(X_train[columna].tolist())
        assert rango["min"] in valores, f"{columna}: el mínimo publicado no existe en los datos"
        assert rango["max"] in valores, f"{columna}: el máximo publicado no existe en los datos"


# --- El split (punto 4 del encargo) ----------------------------------------


def test_ninguna_fila_del_conjunto_de_prueba_aparece_en_entrenamiento(
    production_split, committed_metrics, production_variant
):
    """Dos comprobaciones: por índice y por vector de features.

    La segunda es la que importa: dos filas distintas con las 8 variables
    idénticas serían una fuga aunque sus índices no se solapen.
    """
    X_train, X_test, _, _ = production_split

    assert X_train.index.intersection(X_test.index).empty

    en_entrenamiento = set(map(tuple, X_train.to_numpy().tolist()))
    solapamiento = sum(1 for fila in X_test.to_numpy().tolist() if tuple(fila) in en_entrenamiento)

    assert solapamiento == 0
    assert committed_metrics["variants"][production_variant]["split"]["overlap_exact_rows"] == 0


def test_el_split_es_estratificado(production_split, production_dataset):
    X, y = train_model.load_variant(production_dataset)
    global_pct = y.value_counts(normalize=True)

    _, _, y_train, y_test = production_split
    for etiqueta in RISK_LABELS:
        for nombre, parte in (("train", y_train), ("test", y_test)):
            desviacion = abs(parte.value_counts(normalize=True)[etiqueta] - global_pct[etiqueta])
            assert desviacion * 100 <= STRATIFICATION_TOLERANCE_PP, (
                f"{nombre}: '{etiqueta}' se desvía {desviacion * 100:.2f} pp"
            )


def test_el_split_usa_la_proporcion_registrada(
    production_split, committed_metrics, production_variant
):
    X_train, X_test, _, _ = production_split
    split = committed_metrics["variants"][production_variant]["split"]

    assert split["seed"] == EXPECTED_SEED
    assert split["test_size"] == EXPECTED_TEST_SIZE
    assert split["train_rows"] == len(X_train)
    assert split["test_rows"] == len(X_test)
    assert len(X_test) / (len(X_train) + len(X_test)) == pytest.approx(EXPECTED_TEST_SIZE, abs=1e-3)


# --- Reproducibilidad (punto 11 del encargo) -------------------------------


def test_dos_ejecuciones_con_la_misma_semilla_dan_metricas_identicas(tmp_path):
    """El determinismo se comprueba con la rejilla mínima: lo que se verifica
    es el procedimiento, no el tamaño de la búsqueda."""
    from conftest import TINY_PARAM_GRID

    primera = tmp_path / "primera"
    segunda = tmp_path / "segunda"

    train_model.main(out_dir=primera, param_grid=TINY_PARAM_GRID, full_checks=False)
    train_model.main(out_dir=segunda, param_grid=TINY_PARAM_GRID, full_checks=False)

    def _metricas(raiz: Path) -> dict:
        datos = json.loads((raiz / "reports" / "ml" / "training_metrics.json").read_text("utf-8"))
        # `generated_at` y `elapsed_seconds` son del reloj, no del modelo.
        datos.pop("generated_at")
        datos.pop("elapsed_seconds")
        return datos

    assert _metricas(primera) == _metricas(segunda)


@pytest.mark.skipif(
    os.environ.get("GYNFEM_SLOW_TESTS") != "1",
    reason="tarda ~80 min; se ejecuta bajo demanda con GYNFEM_SLOW_TESTS=1",
)
def test_dos_ejecuciones_con_todas_las_comprobaciones_dan_metricas_identicas(tmp_path):
    """El determinismo, pero ejercitando **todos** los caminos de código.

    El test rápido de arriba usa `full_checks=False`, así que no toca la CV
    anidada, la prueba de etiquetas permutadas, la curva de aprendizaje, la
    varianza de partición ni las dos ablaciones — que es justamente donde una
    fuente de aleatoriedad podría esconderse. Este sí los recorre.

    Vive aquí, y no en un cuaderno de notas, porque una verificación que no se
    puede volver a correr no es una verificación. Se ejecuta con:

        GYNFEM_SLOW_TESTS=1 pytest tests/test_train_model.py -k todas_las_comprobaciones

    La rejilla se reduce a propósito: su tamaño cambia cuántas veces se llama a
    `fit`, no qué código se ejecuta.
    """
    primera = tmp_path / "primera"
    segunda = tmp_path / "segunda"

    for destino in (primera, segunda):
        train_model.main(out_dir=destino, param_grid=REDUCED_PARAM_GRID, full_checks=True)

    def _metricas(raiz: Path) -> dict:
        datos = json.loads((raiz / "reports" / "ml" / "training_metrics.json").read_text("utf-8"))
        datos.pop("generated_at")
        datos.pop("elapsed_seconds")
        return datos

    assert _metricas(primera) == _metricas(segunda)


def test_las_metricas_publicadas_se_reproducen_al_reentrenar(
    committed_metrics, production_variant, production_split
):
    """Reentrena con los hiperparámetros registrados y recalcula el test apartado.

    Es el test que hace imposible publicar una cifra que el código no produce.
    """
    publicado = committed_metrics["variants"][production_variant]
    X_train, X_test, y_train, y_test = production_split

    modelo = train_model.build_pipeline(**publicado["search"]["best_params"])
    modelo.fit(X_train, y_train)
    recalculado = train_model.evaluate(modelo, X_test, y_test)

    _assert_close(recalculado, publicado["held_out_test"], "held_out_test")


def test_el_modelo_entregado_se_ajusto_solo_con_el_entrenamiento(artifacts):
    """El `.joblib` es el mismo modelo que se evaluó, no uno reajustado con todo.

    El test de arriba reentrena por su cuenta, así que prueba que las cifras
    son reproducibles, no que el archivo entregado sea el que las produjo. Un
    modelo reajustado sobre el dataset completo pasaría todo lo demás y habría
    visto el conjunto de prueba: sus métricas publicadas no lo describirían.
    """
    variante = artifacts.metrics["production"]["variant"]
    X, y = train_model.load_variant(train_model.VARIANTS[variante])
    X_train, X_test, y_train, _ = train_model.make_split(X, y)

    parametros = artifacts.metrics["variants"][variante]["search"]["best_params"]
    referencia = train_model.build_pipeline(**parametros).fit(X_train, y_train)

    # Tolerancia y no igualdad exacta: la suma de probabilidades entre árboles
    # en paralelo no fija el orden de las sumas de punto flotante.
    np.testing.assert_allclose(
        artifacts.model.predict_proba(X_test),
        referencia.predict_proba(X_test),
        rtol=0,
        atol=FLOAT_TOLERANCE,
    )


def test_el_dummy_es_realmente_el_de_clase_mas_frecuente(artifacts, production_split):
    """Un DummyClassifier mal configurado haría parecer mejor al Random Forest.

    Es además el test que detecta que una métrica se haya sustituido por una
    constante dentro de `evaluate()`: la accuracy del clasificador trivial tiene
    un valor obligado, la proporción de la clase mayoritaria.
    """
    _, _, _, y_test = production_split
    mayoritaria = y_test.value_counts(normalize=True).max()

    variante = artifacts.metrics["production"]["variant"]
    dummy = artifacts.metrics["variants"][variante]["reference_models"]["dummy"]
    assert dummy["accuracy"] == pytest.approx(mayoritaria, abs=1e-9)


def test_el_arbol_de_decision_de_referencia_esta_medido(committed_metrics, production_variant):
    arbol = committed_metrics["variants"][production_variant]["reference_models"]["decision_tree"]
    assert 0.0 < arbol["accuracy"] <= 1.0
    assert 0.0 < arbol["f1_macro"] <= 1.0


def test_el_reporte_commiteado_se_regenera_identico_desde_el_json(committed_metrics):
    """Editar una cifra a mano en el .md rompe este test.

    El reporte no se escribe: se renderiza desde `training_metrics.json`, que
    es lo único que emite el script. No hay lugar donde meter un número.
    """
    esperado = training_report.render(committed_metrics)
    assert TRAINING_REPORT.read_text(encoding="utf-8") == esperado


def test_el_reporte_declara_la_rejilla_realmente_usada(committed_metrics):
    """La rejilla publicada es la constante del script, no una transcripción."""
    assert committed_metrics["param_grid"] == train_model.PARAM_GRID

    reporte = TRAINING_REPORT.read_text(encoding="utf-8")
    for parametro, valores in train_model.PARAM_GRID.items():
        assert f"`{parametro}`" in reporte, f"el reporte no declara {parametro}"
        for valor in valores:
            assert f"`{valor}`" in reporte, f"el reporte no declara {parametro}={valor}"


# --- Sesgo de selección (Decisión E) ---------------------------------------


def test_las_tres_estimaciones_estan_separadas_y_etiquetadas(
    committed_metrics, production_variant
):
    """Puntaje de selección, CV anidada y test apartado son tres cifras distintas.

    Reportar `best_score_` como rendimiento es el error que la Decisión E
    existe para evitar: está sesgado al alza por haber elegido el máximo de la
    rejilla.
    """
    variante = committed_metrics["variants"][production_variant]

    seleccion = variante["search"]["hyperparameter_selection_score"]["mean"]
    anidada = variante["nested_cv"]["mean"]
    test = variante["held_out_test"]["f1_macro"]
    assert len({seleccion, anidada, test}) == 3, "las tres estimaciones no son cifras distintas"

    reporte = TRAINING_REPORT.read_text(encoding="utf-8")
    assert "puntaje de selección" in reporte.lower()
    assert "no es una estimación de rendimiento" in reporte.lower()
    assert f"{test:.4f}" in reporte, "el reporte no publica la cifra del test apartado"


def test_el_cv_de_seleccion_usa_diez_folds(committed_metrics, production_variant):
    variante = committed_metrics["variants"][production_variant]
    assert committed_metrics["cv_folds"] == EXPECTED_CV_FOLDS
    assert len(variante["cv_scores"]["scores"]) == EXPECTED_CV_FOLDS
    assert len(variante["nested_cv"]["scores"]) == EXPECTED_CV_FOLDS


# --- Sobreajuste (Decisión C) ----------------------------------------------


@pytest.mark.parametrize("variante", ["clean", "paper"])
def test_la_prueba_de_etiquetas_permutadas_colapsa_a_azar(variante, committed_metrics):
    """Con `risk_level` barajado el modelo no debe aprender nada.

    Si el puntaje se mantuviera alto, habría fuga en el split o en el pipeline,
    y la accuracy real no significaría nada.
    """
    permutacion = committed_metrics["variants"][variante]["checks"]["permutation"]

    assert permutacion["permuted_mean"] <= PERMUTATION_MAX_SCORE, (
        f"con etiquetas permutadas el modelo sigue acertando "
        f"({permutacion['permuted_mean']:.4f})"
    )
    assert permutacion["p_value"] <= PERMUTATION_MAX_P_VALUE
    # El puntaje sin permutar es la otra mitad del contraste: si no fuera
    # mucho mayor que el nulo, no habría señal que explicar.
    assert permutacion["true_score"] > permutacion["permuted_mean"] + 0.3


@pytest.mark.parametrize("variante", ["clean", "paper"])
def test_el_test_apartado_cae_dentro_de_la_banda_de_la_cv_anidada(variante, committed_metrics):
    """Banda de dos lados: el test no debe estar ni muy por debajo ni muy por encima.

    Por debajo indicaría un test desfavorable o un split degenerado; por encima,
    una partición afortunada o una fuga que la CV anidada no ve. Solo la banda
    de dos lados detecta ambos.
    """
    datos = committed_metrics["variants"][variante]
    banda = datos["checks"]["consistency_band"]

    diferencia = abs(datos["held_out_test"]["f1_macro"] - datos["nested_cv"]["mean"])
    limite = 3 * datos["nested_cv"]["std"]

    assert diferencia == pytest.approx(banda["delta"], abs=1e-9)
    assert limite == pytest.approx(banda["limit"], abs=1e-9)
    assert banda["within"] is True
    assert diferencia <= limite, (
        f"el test apartado se separa {diferencia:.4f} de la CV anidada (límite {limite:.4f})"
    )


def test_la_curva_de_aprendizaje_se_genero_para_la_variante_de_produccion(
    committed_metrics, production_variant
):
    curva = committed_metrics["learning_curve"]
    assert curva["variant"] == production_variant
    assert len(curva["train_sizes"]) == len(curva["train_scores_mean"]) == len(
        curva["test_scores_mean"]
    )
    assert len(curva["train_sizes"]) >= 5


@pytest.mark.parametrize("variante", ["clean", "paper"])
def test_el_solapamiento_train_test_esta_medido_y_publicado(variante, committed_metrics):
    """La variante `paper` conserva 1 grupo duplicado: el conteo debe ser explícito."""
    split = committed_metrics["variants"][variante]["split"]
    assert isinstance(split["overlap_exact_rows"], int)
    assert f"{split['overlap_exact_rows']}" in TRAINING_REPORT.read_text(encoding="utf-8")


# --- Decisión D: elección de la variante de producción ---------------------


def test_la_regla_de_eleccion_se_aplico_y_el_reporte_imprime_la_rama(committed_metrics):
    """La rama activada se decide por código, no por narrativa a posteriori."""
    produccion = committed_metrics["production"]

    assert produccion["rule_branch"] in {"D1", "D2", "D3", "D4"}
    assert produccion["variant"] in {"clean", "paper"}

    reporte = TRAINING_REPORT.read_text(encoding="utf-8")
    assert produccion["rule_branch"] in reporte
    assert f"{produccion['delta_f1_macro']:.6f}" in reporte


def test_la_rama_elegida_es_la_que_dicta_la_regla(committed_metrics):
    """Reaplica la regla sobre las cifras publicadas y exige el mismo resultado."""
    reaplicada = train_model.choose_production_variant(committed_metrics["variants"])

    assert reaplicada["variant"] == committed_metrics["production"]["variant"]
    assert reaplicada["rule_branch"] == committed_metrics["production"]["rule_branch"]


@pytest.mark.parametrize("variante", ["clean", "paper"])
def test_ambas_variantes_se_entrenaron_con_el_mismo_protocolo(variante, committed_metrics):
    """Decisión D: mismo split, misma semilla, misma rejilla, mismas métricas."""
    datos = committed_metrics["variants"][variante]
    assert datos["split"]["seed"] == EXPECTED_SEED
    assert datos["split"]["test_size"] == EXPECTED_TEST_SIZE
    assert datos["search"]["n_candidates"] == committed_metrics["n_candidates"]
    assert set(datos["held_out_test"]["per_class"]) == RISK_LABELS


# --- Higiene ---------------------------------------------------------------


@pytest.mark.parametrize(
    "artefacto",
    [MODEL_METADATA, FEATURE_RANGES, TRAINING_METRICS, TRAINING_REPORT],
)
def test_ningun_artefacto_generado_contiene_valores_de_name(artefacto):
    """Barrido de tokens, insensible a mayúsculas, sobre el contenido completo.

    El mensaje de fallo reporta cuántas coincidencias hubo, nunca cuáles.
    """
    coincidencias = _tokens(artefacto.read_text(encoding="utf-8")) & _name_tokens()
    assert not coincidencias, (
        f"{len(coincidencias)} token(s) de la columna `Name` aparecen en {artefacto.name}"
    )


def test_el_modelo_serializado_no_contiene_valores_de_name(committed_metadata):
    """Barrido sobre los bytes del `.joblib`, con tokens de ≥3 caracteres.

    El umbral es más laxo que el de los artefactos de texto (≥2) porque un
    pickle binario produce secuencias de 2 letras por el propio formato de
    serialización, no por contener texto. El coste de coverage es exactamente
    **1** de los 5794 valores distintos de `Name`, el único de menos de 3
    caracteres; con ≥2 el test reportaría ruido del formato como si fuera fuga.
    """
    crudo = (MODELS_DIR / committed_metadata["model_file"]).read_bytes()
    tokens = {t.lower() for t in re.findall(r"[A-Za-z']{3,}", crudo.decode("latin-1"))}
    coincidencias = tokens & _name_tokens()
    assert not coincidencias, f"{len(coincidencias)} token(s) de `Name` en el .joblib"


def test_el_entrenamiento_no_escribe_en_data(tmp_path):
    """`data/` es de solo lectura para este script."""
    from conftest import TINY_PARAM_GRID

    vigilados = [RAW_CSV, *train_model.VARIANTS.values()]
    antes = {p: train_model.sha256_of_file(p) for p in vigilados}

    train_model.main(out_dir=tmp_path, param_grid=TINY_PARAM_GRID, full_checks=False)

    assert {p: train_model.sha256_of_file(p) for p in vigilados} == antes


def test_la_suite_no_reescribe_los_artefactos_commiteados(training_out_dir):
    generados = list(training_out_dir.rglob("*"))
    assert generados, "el entrenamiento de prueba no produjo nada"

    for ruta in generados:
        assert MODELS_DIR not in ruta.parents
        assert TRAINING_METRICS.parent not in ruta.parents


def test_el_entrenamiento_de_prueba_produce_los_tres_artefactos_del_modelo(training_out_dir):
    modelos = training_out_dir / "models"
    assert (modelos / "model_metadata.json").exists()
    assert (modelos / "feature_ranges.json").exists()
    assert list(modelos.glob("*.joblib"))


def test_el_modelo_entregado_se_ajusto_solo_con_el_80_por_ciento(
    committed_metadata, committed_metrics, production_variant
):
    """Compromiso declarado en el plan: lo medido y lo entregado son el mismo objeto.

    Reajustar sobre el 100% daría un modelo marginalmente mejor, pero la
    métrica publicada dejaría de ser la de este artefacto.
    """
    split = committed_metrics["variants"][production_variant]["split"]
    assert committed_metadata["training_rows"] == split["train_rows"]
    assert committed_metadata["training_rows"] < committed_metadata["dataset"]["rows"]
