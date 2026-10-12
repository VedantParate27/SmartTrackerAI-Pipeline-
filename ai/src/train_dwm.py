"""
Trains and compares Decision Tree, Random Forest, k-NN and Naive Bayes on the feature table.

Usage: python train_dwm.py <features_csv> <results_dir>

- One stratified 75/25 train/test split by image (seed 0). The test image list is saved as
  <results_dir>/test_images.csv for evaluate_dwm.py.
- Rows with total_detections == 0 are dropped (they never reach the model, they go to Gemini).
- Hyperparameters are tuned with 5-fold stratified CV on the training split; the model with the
  best CV macro-F1 is exported to ai/models/<target>_model.joblib (fitted on the training split only).
- The environment model is trained only on rows that have an environment label.
"""
import os, sys
import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split, GridSearchCV, StratifiedKFold
from sklearn.tree import DecisionTreeClassifier, plot_tree
from sklearn.ensemble import RandomForestClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, f1_score, classification_report, ConfusionMatrixDisplay
from dwm_classifier import MODELS_DIR

SEED = 0
TEST_SIZE = 0.25
TARGETS = {"waste_type": "label_waste_type", "severity": "label_severity", "environment": "label_environment"}
NON_FEATURES = ["image_file", *TARGETS.values()]
THRESHOLDS = [0.5, 0.6, 0.7, 0.8, 0.9]
CANDIDATES = {
    "decision_tree": (DecisionTreeClassifier(class_weight="balanced", random_state=SEED),
                      {"max_depth": [3, 4, 5, 6, 8, 10, None], "min_samples_leaf": [1, 3, 5, 10]}),
    "random_forest": (RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=SEED),
                      {"max_depth": [None, 10], "min_samples_leaf": [1, 3]}),
    "knn": (make_pipeline(StandardScaler(), KNeighborsClassifier()),
            {"kneighborsclassifier__n_neighbors": [3, 5, 7, 11, 15, 21],
             "kneighborsclassifier__weights": ["uniform", "distance"]}),
    "naive_bayes": (GaussianNB(), {"var_smoothing": np.logspace(-9, -3, 7)}),
}


def confident_wrong(y_true, pred, conf):
    lines = []
    for t in THRESHOLDS:
        m = conf >= t
        err = (pred[m] != y_true[m]).mean() if m.any() else float("nan")
        lines.append(f"    conf>={t:.1f}: coverage {m.mean():.1%} ({m.sum()}), wrong among confident {err:.1%}")
    return lines


def train_target(name, col, train, test, features, out, log):
    tr, te = train[train[col].notna()], test[test[col].notna()]
    log += [f"\n{'=' * 70}\nTARGET: {name}  (train {len(tr)}, test {len(te)})", "Train class counts:",
            tr[col].value_counts().to_string(), "Test class counts:", te[col].value_counts().to_string()]
    cv = StratifiedKFold(5, shuffle=True, random_state=SEED)
    fitted = {}
    for model_name, (est, grid) in CANDIDATES.items():
        gs = GridSearchCV(est, grid, cv=cv, scoring="f1_macro", n_jobs=-1).fit(tr[features], tr[col])
        m = gs.best_estimator_
        proba = m.predict_proba(te[features])
        pred, conf = m.classes_[proba.argmax(1)], proba.max(1)
        y = te[col].to_numpy()
        fitted[model_name] = (gs.best_score_, m)
        log += [f"\n--- {model_name}  best params {gs.best_params_}",
                f"  CV macro-F1 (train): {gs.best_score_:.3f}",
                f"  Test accuracy: {accuracy_score(y, pred):.3f}   Test macro-F1: {f1_score(y, pred, average='macro'):.3f}",
                classification_report(y, pred, zero_division=0), "  Confidently wrong (test):",
                *confident_wrong(y, pred, conf)]
        fig, ax = plt.subplots(figsize=(7, 6))
        ConfusionMatrixDisplay.from_predictions(y, pred, labels=m.classes_, ax=ax, colorbar=False,
                                                xticks_rotation=45)
        ax.set_title(f"{name} - {model_name}")
        fig.tight_layout()
        fig.savefig(os.path.join(out, f"cm_{name}_{model_name}.png"), dpi=120)
        plt.close(fig)

    tree = fitted["decision_tree"][1]
    fig, ax = plt.subplots(figsize=(28, 12))
    plot_tree(tree, max_depth=3, feature_names=features, class_names=list(tree.classes_), filled=True,
              fontsize=8, ax=ax)
    ax.set_title(f"Decision tree for {name} (top 4 levels of depth {tree.get_depth()})")
    fig.savefig(os.path.join(out, f"tree_{name}.png"), dpi=100, bbox_inches="tight")
    plt.close(fig)

    best = max(fitted, key=lambda k: fitted[k][0])
    joblib.dump(fitted[best][1], os.path.join(MODELS_DIR, f"{name}_model.joblib"))
    log.append(f"\n>>> Exported {best} as {name}_model.joblib (best CV macro-F1 {fitted[best][0]:.3f})")
    return fitted[best][1]


def threshold_sweep(waste_model, sev_model, test, features, log):
    """Same acceptance rule as hybrid_classifier: both confidences >= threshold and neither prediction is none."""
    X = test[features]
    pw, ps = waste_model.predict_proba(X), sev_model.predict_proba(X)
    w, wc = waste_model.classes_[pw.argmax(1)], pw.max(1)
    s, sc = sev_model.classes_[ps.argmax(1)], ps.max(1)
    yw, ys = test["label_waste_type"].to_numpy(), test["label_severity"].to_numpy()
    log.append(f"\n{'=' * 70}\nHYBRID ACCEPTANCE SWEEP (test rows with detections: {len(test)})")
    for t in [0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
        acc = (wc >= t) & (sc >= t) & (w != "none") & (s != "none")
        if not acc.any():
            log.append(f"  threshold {t:.1f}: DWM answers 0 rows")
            continue
        log.append(f"  threshold {t:.1f}: DWM answers {acc.mean():.1%} ({acc.sum()}); on those: "
                   f"waste_type acc {(w[acc] == yw[acc]).mean():.1%}, severity acc {(s[acc] == ys[acc]).mean():.1%}, "
                   f"both correct {((w[acc] == yw[acc]) & (s[acc] == ys[acc])).mean():.1%}")


def main(features_csv, out):
    os.makedirs(out, exist_ok=True)
    df = pd.read_csv(features_csv)
    features = [c for c in df.columns if c not in NON_FEATURES]
    train_idx, test_idx = train_test_split(df.index, test_size=TEST_SIZE, stratify=df["label_waste_type"],
                                           random_state=SEED)
    df.loc[test_idx, NON_FEATURES].to_csv(os.path.join(out, "test_images.csv"), index=False)
    train, test = df.loc[train_idx], df.loc[test_idx]
    log = [f"Feature table: {len(df)} rows, {len(features)} features",
           f"Split: {len(train)} train / {len(test)} test images",
           f"Dropped (total_detections == 0): {(train.total_detections == 0).sum()} train, "
           f"{(test.total_detections == 0).sum()} test"]
    train, test = train[train.total_detections > 0], test[test.total_detections > 0]
    models = {name: train_target(name, col, train, test, features, out, log) for name, col in TARGETS.items()}
    threshold_sweep(models["waste_type"], models["severity"], test, features, log)
    with open(os.path.join(out, "training_results.txt"), "w") as f:
        f.write("\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
