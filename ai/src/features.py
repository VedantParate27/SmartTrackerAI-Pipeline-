import numpy as np
import cv2
from PIL import Image
from sklearn.cluster import KMeans
from config import WASTE_TYPES, SEVERITY_LEVELS, ENVIRONMENTS
from detector import detect

YOLO_CLASSES = ["biological", "cardboard", "metal", "paper", "plastic", "other"]
YOLO_TO_GROUP = {"biological": "wet", "cardboard": "dry", "metal": "dry",
                 "paper": "dry", "plastic": "dry", "other": "unknown"}
GROUPS = ["wet", "dry", "unknown"]

VALID_WASTE_LABELS = list(WASTE_TYPES)       # wet, dry, hazardous, sanitary, e_waste, mixed, none
VALID_SEVERITY_LABELS = list(SEVERITY_LEVELS)  # domestic, moderate, dump_scale, none


def pixel_features(image) -> dict:
    """Pixel-level features: colour shares, texture, k-means dominance."""
    img = Image.open(image).convert("RGB") if isinstance(image, str) else image.convert("RGB")
    small = np.array(img.resize((64, 64)))
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0].ravel(), hsv[..., 1].ravel(), hsv[..., 2].ravel()
    dark = v < 50
    gray = (~dark) & (s < 40)
    colour = ~(dark | gray)
    green = colour & (h >= 36) & (h <= 85)
    cool = colour & (h > 85) & (h < 150)
    warm = colour & ~(green | cool)
    edges = cv2.Canny(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), 100, 200)
    km = KMeans(n_clusters=3, n_init=3, random_state=0).fit(small.reshape(-1, 3))
    counts = np.bincount(km.labels_, minlength=3)
    return {
        "px_dark": float(dark.mean()), "px_gray": float(gray.mean()),
        "px_green": float(green.mean()), "px_cool": float(cool.mean()), "px_warm": float(warm.mean()),
        "px_mean_sat": float(s.mean() / 255), "px_mean_val": float(v.mean() / 255),
        "px_edge_density": float((edges > 0).mean()),
        "px_dominant_cluster_share": float(counts.max() / counts.sum()),
    }


def extract_features(detections: list) -> dict:
    row, total = {}, len(detections)
    for c in YOLO_CLASSES:
        d = [x for x in detections if x["class"] == c]
        row[f"count_{c}"] = len(d)
        row[f"area_{c}"] = min(1.0, sum(x["area"] for x in d))
        row[f"maxconf_{c}"] = max((x["conf"] for x in d), default=0.0)
    for g in GROUPS:
        d = [x for x in detections if YOLO_TO_GROUP.get(x["class"]) == g]
        row[f"count_group_{g}"] = len(d)
        row[f"area_group_{g}"] = min(1.0, sum(x["area"] for x in d))
        row[f"share_group_{g}"] = (len(d) / total) if total else 0.0
    row["total_detections"] = total
    row["total_area"] = min(1.0, sum(x["area"] for x in detections))
    row["mean_conf"] = sum(x["conf"] for x in detections) / total if total else 0.0
    row["n_distinct_classes"] = sum(1 for c in YOLO_CLASSES if row[f"count_{c}"] > 0)
    row["dominant_class_share"] = (max(row[f"count_{c}"] for c in YOLO_CLASSES) / total) if total else 0.0
    return row


def featurize(image):
    """Full feature row (41 columns) plus the raw detections."""
    detections = detect(image)["detections"]
    row = extract_features(detections)
    row.update(pixel_features(image))
    return row, detections


def validate_labels(waste_type, severity, environment=None):
    if waste_type not in VALID_WASTE_LABELS:
        raise ValueError(f"Invalid waste_type '{waste_type}'. Allowed: {VALID_WASTE_LABELS}")
    if severity not in VALID_SEVERITY_LABELS:
        raise ValueError(f"Invalid severity '{severity}'. Allowed: {VALID_SEVERITY_LABELS}")
    if environment is not None and environment not in ENVIRONMENTS:
        raise ValueError(f"Invalid environment '{environment}'. Allowed: {ENVIRONMENTS}")