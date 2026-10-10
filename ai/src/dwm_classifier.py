import os
import joblib
import pandas as pd
from features import featurize

MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
PATHS = {k: os.path.join(MODELS_DIR, f"{k}_model.joblib") for k in ("waste_type", "severity", "environment")}
_loaded = {}


def models_available() -> bool:
    return os.path.exists(PATHS["waste_type"]) and os.path.exists(PATHS["severity"])


def _predict(name, row):
    if name not in _loaded:
        _loaded[name] = joblib.load(PATHS[name])
    m = _loaded[name]
    proba = m.predict_proba(row[list(m.feature_names_in_)])[0]
    return str(m.classes_[proba.argmax()]), float(proba.max())


def classify_with_dwm(image) -> dict:
    """image: path or PIL image. Raises if models are missing or nothing is detected."""
    if not models_available():
        raise RuntimeError("dwm_model_not_available")
    features, detections = featurize(image)
    if not detections:
        raise RuntimeError("no_detections")
    row = pd.DataFrame([features])
    waste, waste_conf = _predict("waste_type", row)
    sev, sev_conf = _predict("severity", row)
    if waste == "none" or sev == "none":
        raise RuntimeError("dwm_predicted_none")  # let Gemini confirm before rejecting an image
    env, env_conf = (None, None)
    if os.path.exists(PATHS["environment"]):
        env, env_conf = _predict("environment", row)
    return {
        "image_usable": True, "unusable_reason": None,
        "waste_type": waste, "waste_type_confidence": waste_conf,
        "severity": sev, "severity_confidence": sev_conf,
        "environment": env, "environment_confidence": env_conf,
        "reasoning": f"DWM model from {len(detections)} detected object(s) plus pixel features.",
        "follow_up_question": None,
    }