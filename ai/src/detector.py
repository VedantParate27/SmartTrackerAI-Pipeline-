from ultralytics import YOLO
import os

MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "best.pt")
_model = None


def detect(image, conf: float = 0.25) -> dict:
    """image: file path or PIL image."""
    global _model
    if _model is None:
        _model = YOLO(MODEL_PATH)
    result = _model(image, conf=conf, verbose=False)[0]
    h, w = result.orig_shape
    detections = []
    for box, cls, score in zip(result.boxes.xyxy.tolist(), result.boxes.cls.tolist(), result.boxes.conf.tolist()):
        x1, y1, x2, y2 = box
        detections.append({
            "class": result.names[int(cls)],
            "conf": float(score),
            "area": max(0.0, (x2 - x1) * (y2 - y1) / (w * h)),
        })
    return {"detections": detections, "classes": list(result.names.values())}