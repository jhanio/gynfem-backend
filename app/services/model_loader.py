"""Carga del modelo y validación de su contrato (`docs/ML_SPEC.md`, Sección 9.6).

Se ejecuta una sola vez, al construir la aplicación. Si el contrato no se puede
verificar, lanza `ModelContractError` y la aplicación no arranca: nunca se
predice con un modelo cuyo contrato no se comprobó.

Qué se comprueba:

- `model_metadata.json` y `feature_ranges.json` existen y son JSON válido;
- el archivo del modelo está dentro del directorio configurado;
- la versión de scikit-learn instalada es la registrada en el metadata;
- las posiciones de las features son 0..7 sin huecos, sus nombres son los del
  módulo de conversión, y su orden es exactamente `feature_names_in_` del modelo;
- las clases del metadata son las del modelo (`classes_`), en el mismo orden, y
  son las tres conocidas;
- `feature_ranges.json` cubre las 8 features con `min < max`, y cada límite
  fisiológico contiene el rango de entrenamiento.

`joblib.load` des-serializa un pickle, que puede ejecutar código: solo se lee
del directorio que configura el operador (`GYNFEM_MODEL_DIR`), nunca de algo
que envíe un cliente.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import joblib
import sklearn

from app.services.clinical_limits import PHYSIOLOGICAL_LIMITS
from app.services.unit_conversion import CLINICAL_FIELDS, model_to_clinical

METADATA_FILE = "model_metadata.json"
RANGES_FILE = "feature_ranges.json"

#: Clases que el servicio sabe traducir a nivel de riesgo.
KNOWN_CLASSES = frozenset({"high risk", "mid risk", "low risk"})


class ModelContractError(Exception):
    """El artefacto del modelo no cumple su contrato."""


@dataclass(frozen=True)
class LoadedModel:
    directory: Path
    pipeline: Any
    version: str
    #: Orden exacto de las columnas que espera el modelo.
    feature_order: tuple[str, ...]
    #: Orden de las columnas de `predict_proba`. No es el de severidad.
    classes: tuple[str, ...]
    #: Rango de entrenamiento por feature, en unidades del dataset.
    training_ranges: dict[str, tuple[float, float]]


def load_model(model_dir: Path) -> LoadedModel:
    model_dir = Path(model_dir)
    metadata = _leer_json(model_dir / METADATA_FILE)
    rangos = _leer_json(model_dir / RANGES_FILE)

    version = metadata.get("model_version")
    _exigir(isinstance(version, str) and bool(version), "el metadata no declara model_version")
    entorno = metadata.get("environment")
    _exigir(
        isinstance(entorno, dict) and entorno.get("scikit_learn") == sklearn.__version__,
        "la versión de scikit-learn instalada no es la registrada en el metadata",
    )
    orden = _orden_de_features(metadata)
    clases = _clases(metadata)
    pipeline = _cargar_pipeline(model_dir, metadata)

    _exigir(
        list(getattr(pipeline, "feature_names_in_", [])) == list(orden),
        "el orden de features del metadata no coincide con el del modelo (feature_names_in_)",
    )
    _exigir(
        list(getattr(pipeline, "classes_", [])) == list(clases),
        "las clases del metadata no coinciden con las del modelo (classes_), en valor u orden",
    )
    return LoadedModel(
        directory=model_dir,
        pipeline=pipeline,
        version=version,
        feature_order=orden,
        classes=clases,
        training_ranges=_rangos(rangos, orden),
    )


def _fallar(motivo: str) -> NoReturn:
    raise ModelContractError(f"Contrato del modelo inválido: {motivo}.")


def _exigir(condicion: bool, motivo: str) -> None:
    if not condicion:
        _fallar(motivo)


def _leer_json(ruta: Path) -> dict:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _fallar(f"no existe {ruta.name}")
    except (OSError, ValueError):
        _fallar(f"{ruta.name} no es JSON legible")
    _exigir(isinstance(datos, dict), f"{ruta.name} no es un objeto JSON")
    return datos


def _orden_de_features(metadata: dict) -> tuple[str, ...]:
    features = metadata.get("features")
    _exigir(isinstance(features, list) and features, "el metadata no declara features")
    try:
        por_posicion = sorted(features, key=lambda f: f["position"])
        posiciones = [f["position"] for f in por_posicion]
        nombres = tuple(f["name"] for f in por_posicion)
    except (KeyError, TypeError):
        _fallar("cada feature del metadata debe tener name y position")
    _exigir(
        posiciones == list(range(len(CLINICAL_FIELDS))),
        "las posiciones de las features deben ser 0..7 sin huecos",
    )
    esperados = {campo.model_feature for campo in CLINICAL_FIELDS}
    _exigir(
        set(nombres) == esperados,
        "las variables del metadata no son las del módulo de conversión",
    )
    return nombres


def _clases(metadata: dict) -> tuple[str, ...]:
    clases = metadata.get("classes")
    _exigir(
        isinstance(clases, list) and set(clases) == KNOWN_CLASSES and len(clases) == 3,
        "las clases del metadata no son high risk, mid risk y low risk",
    )
    return tuple(clases)


def _cargar_pipeline(model_dir: Path, metadata: dict) -> Any:
    ruta = (model_dir / str(metadata.get("model_file", ""))).resolve()
    _exigir(
        ruta.parent == model_dir.resolve(),
        "el archivo del modelo declarado en el metadata está fuera de GYNFEM_MODEL_DIR",
    )
    _exigir(ruta.is_file(), "no existe el archivo del modelo declarado en el metadata")
    try:
        return joblib.load(ruta)
    except Exception:
        _fallar("el archivo del modelo no se pudo cargar")


def _rangos(rangos: dict, orden: tuple[str, ...]) -> dict[str, tuple[float, float]]:
    por_feature = rangos.get("features")
    _exigir(
        isinstance(por_feature, dict) and set(por_feature) == set(orden),
        "los rangos de feature_ranges.json no cubren exactamente las 8 variables",
    )
    resultado: dict[str, tuple[float, float]] = {}
    for campo in sorted(CLINICAL_FIELDS, key=lambda c: orden.index(c.model_feature)):
        rango = por_feature[campo.model_feature]
        try:
            minimo, maximo = float(rango["min"]), float(rango["max"])
        except (KeyError, TypeError, ValueError):
            _fallar(f"feature_ranges.json debe dar min y max numéricos para {campo.model_feature}")
        _exigir(minimo < maximo, f"rango de entrenamiento vacío o invertido en {campo.model_feature}")
        limite = PHYSIOLOGICAL_LIMITS[campo.name]
        _exigir(
            limite.min <= model_to_clinical(campo.model_feature, minimo)
            and model_to_clinical(campo.model_feature, maximo) <= limite.max,
            f"el límite fisiológico de {campo.name} no contiene su rango de entrenamiento",
        )
        resultado[campo.model_feature] = (minimo, maximo)
    return resultado
