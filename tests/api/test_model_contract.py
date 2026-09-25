"""Carga del modelo y validación de su contrato (`docs/ML_SPEC.md`, Sección 9.6).

Si el contrato no se puede verificar, la aplicación no arranca: nunca se
predice con un modelo dudoso. Los contratos alterados son copias en
`tmp_path`; `models/` no se escribe.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

from .api_constantes import (
    ENTRADA_NORMAL,
    FEATURE_RANGES_JSON,
    METADATA_JSON,
    MODELS_DIR,
    ORIGEN_LOCAL,
    REPO_ROOT,
    URL_BD_FICTICIA,
)


def _metadata() -> dict:
    return json.loads(METADATA_JSON.read_text(encoding="utf-8"))


def test_el_modelo_real_cumple_el_contrato(modelo_real):
    metadata = _metadata()
    orden = [f["name"] for f in sorted(metadata["features"], key=lambda f: f["position"])]

    assert list(modelo_real.feature_order) == orden
    assert list(modelo_real.classes) == metadata["classes"]
    assert modelo_real.version == metadata["model_version"]


def test_los_rangos_cargados_son_los_de_feature_ranges(modelo_real):
    rangos = json.loads(FEATURE_RANGES_JSON.read_text(encoding="utf-8"))["features"]

    assert list(modelo_real.training_ranges) == list(modelo_real.feature_order)
    for feature, (minimo, maximo) in modelo_real.training_ranges.items():
        assert (minimo, maximo) == (rangos[feature]["min"], rangos[feature]["max"])


def _intercambiar_features(m):
    m["features"][1]["position"], m["features"][2]["position"] = 2, 1


def _reordenar_clases(m):
    m["classes"] = list(reversed(m["classes"]))


def _otra_version_de_sklearn(m):
    m["environment"]["scikit_learn"] = "0.0.1"


def _archivo_de_modelo_inexistente(m):
    m["model_file"] = "no_existe.joblib"


def _feature_desconocida(m):
    m["features"][5]["name"] = "peso_kg"


def _sin_features(m):
    del m["features"]


def _posiciones_con_hueco(m):
    m["features"][7]["position"] = 9


def _clases_desconocidas(m):
    m["classes"] = ["a", "b", "c"]


def _environment_que_no_es_objeto(m):
    m["environment"] = "1.9.1"


def _modelo_fuera_del_directorio(m):
    # Existe, pero fuera de GYNFEM_MODEL_DIR: la copia está en tmp_path/modelo.
    m["model_file"] = "../fuera.joblib"


def _modelo_con_ruta_absoluta(m):
    m["model_file"] = str(MODELS_DIR / "maternal_risk_rf_v1.0.0.joblib")


#: Caso → (alteración, fragmento exclusivo del mensaje de ese motivo). Un
#: fragmento compartido por varios motivos no probaría que falló el correcto.
ALTERACIONES_DEL_METADATA = {
    "orden de features": (_intercambiar_features, "no coincide con el del modelo (feature_names_in_)"),
    "orden de clases": (_reordenar_clases, "no coinciden con las del modelo (classes_)"),
    "version de scikit-learn": (_otra_version_de_sklearn, "versión de scikit-learn"),
    "environment malformado": (_environment_que_no_es_objeto, "versión de scikit-learn"),
    "modelo inexistente": (_archivo_de_modelo_inexistente, "no existe el archivo del modelo"),
    "modelo fuera del directorio": (_modelo_fuera_del_directorio, "fuera de GYNFEM_MODEL_DIR"),
    "modelo con ruta absoluta": (_modelo_con_ruta_absoluta, "fuera de GYNFEM_MODEL_DIR"),
    "feature desconocida": (_feature_desconocida, "no son las del módulo de conversión"),
    "sin features": (_sin_features, "no declara features"),
    "posiciones con hueco": (_posiciones_con_hueco, "0..7 sin huecos"),
    "clases desconocidas": (_clases_desconocidas, "no son high risk, mid risk y low risk"),
}


@pytest.mark.parametrize("caso", list(ALTERACIONES_DEL_METADATA))
def test_metadata_alterado_impide_cargar(caso, copiar_modelo):
    from app.services.model_loader import ModelContractError, load_model

    alterar, palabra = ALTERACIONES_DEL_METADATA[caso]
    directorio = copiar_modelo(metadata=alterar)
    # Para el caso «fuera del directorio»: un modelo válido justo al lado.
    shutil.copy(MODELS_DIR / "maternal_risk_rf_v1.0.0.joblib", directorio.parent / "fuera.joblib")

    with pytest.raises(ModelContractError) as error:
        load_model(directorio)
    assert palabra in str(error.value)


def _quitar_un_rango(r):
    del r["features"]["bmi_kg_m2"]


def _rango_invertido(r):
    r["features"]["age_years"] = {"min": 47.0, "max": 15.0, "unit": "años"}


def _rango_sin_maximo(r):
    del r["features"]["heart_rate_bpm"]["max"]


def _rango_no_numerico(r):
    r["features"]["heart_rate_bpm"]["min"] = "cuarenta y cinco"


def _rango_mas_ancho_que_el_limite_fisiologico(r):
    # 250 mmHg de sistólica entrenada: el límite fisiológico provisional la rechazaría.
    r["features"]["systolic_bp_mmhg"]["max"] = 400.0


@pytest.mark.parametrize(
    "alterar, palabra",
    [
        (_quitar_un_rango, "no cubren exactamente las 8 variables"),
        (_rango_invertido, "vacío o invertido"),
        (_rango_sin_maximo, "min y max numéricos"),
        (_rango_no_numerico, "min y max numéricos"),
        (_rango_mas_ancho_que_el_limite_fisiologico, "no contiene su rango de entrenamiento"),
    ],
)
def test_feature_ranges_alterado_impide_cargar(alterar, palabra, copiar_modelo):
    from app.services.model_loader import ModelContractError, load_model

    with pytest.raises(ModelContractError) as error:
        load_model(copiar_modelo(rangos=alterar))
    assert palabra in str(error.value)


def test_json_malformado_impide_cargar(copiar_modelo):
    from app.services.model_loader import ModelContractError, load_model

    directorio = copiar_modelo()
    (directorio / "model_metadata.json").write_text("{no es json", encoding="utf-8")

    with pytest.raises(ModelContractError):
        load_model(directorio)


def test_directorio_inexistente_impide_cargar(tmp_path):
    from app.services.model_loader import ModelContractError, load_model

    with pytest.raises(ModelContractError):
        load_model(tmp_path / "no-existe")


def test_limites_fisiologicos_contienen_el_rango_de_entrenamiento(modelo_real):
    """Un límite de rechazo dentro del rango entrenado rechazaría valores que el modelo sí vio."""
    from app.services.clinical_limits import PHYSIOLOGICAL_LIMITS
    from app.services.unit_conversion import CLINICAL_FIELDS, model_to_clinical

    for campo in CLINICAL_FIELDS:
        minimo, maximo = modelo_real.training_ranges[campo.model_feature]
        limite = PHYSIOLOGICAL_LIMITS[campo.name]
        assert limite.min <= model_to_clinical(campo.model_feature, minimo), campo.name
        assert model_to_clinical(campo.model_feature, maximo) <= limite.max, campo.name


def test_create_app_falla_si_el_contrato_no_coincide(configurar, copiar_modelo):
    from app.factory import create_app
    from app.services.model_loader import ModelContractError

    directorio = copiar_modelo(metadata=_intercambiar_features)
    configurar(environment="development", cors_origins=ORIGEN_LOCAL, model_dir=str(directorio))

    with pytest.raises(ModelContractError):
        create_app()


def _importar_main(env_extra: dict[str, str], cwd) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GYNFEM_")}
    env.update(env_extra)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_arranque_real_falla_con_contrato_invalido(tmp_path, copiar_modelo):
    directorio = copiar_modelo(metadata=_reordenar_clases)
    resultado = _importar_main(
        {
            "GYNFEM_ENVIRONMENT": "development",
            "GYNFEM_CORS_ORIGINS": ORIGEN_LOCAL,
            "GYNFEM_DATABASE_URL": URL_BD_FICTICIA,
            "GYNFEM_MODEL_DIR": str(directorio),
        },
        tmp_path,
    )

    assert resultado.returncode == 1
    assert "Contrato del modelo inválido" in resultado.stderr
    assert "clases" in resultado.stderr
    assert "Traceback" not in resultado.stderr


def test_el_modelo_se_carga_una_sola_vez(configurar, monkeypatch):
    import joblib
    from fastapi.testclient import TestClient

    from app.factory import create_app

    llamadas = []
    original = joblib.load

    def contar(*args, **kwargs):
        llamadas.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(joblib, "load", contar)
    configurar(environment="development", cors_origins=ORIGEN_LOCAL)
    cliente = TestClient(create_app())
    for _ in range(3):
        assert cliente.post("/api/v1/predict", json=ENTRADA_NORMAL).status_code == 200

    assert len(llamadas) == 1


def test_model_dir_por_defecto_es_models_del_repositorio(configurar):
    from app.core.config import load_settings

    configurar(environment="development", cors_origins=ORIGEN_LOCAL)

    assert load_settings().model_dir == REPO_ROOT / "models"


def test_model_dir_relativo_se_resuelve_desde_la_raiz_del_repositorio(configurar):
    from app.core.config import load_settings

    configurar(environment="development", cors_origins=ORIGEN_LOCAL, model_dir="models")

    assert load_settings().model_dir == REPO_ROOT / "models"
