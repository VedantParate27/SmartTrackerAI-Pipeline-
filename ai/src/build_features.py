import os, sys
import pandas as pd
from features import featurize, validate_labels


def build(labels_csv, images_dir, out_csv="features.csv"):
    labels = pd.read_csv(labels_csv)
    rows, skipped = [], []
    for _, r in labels.iterrows():
        try:
            env = r.get("label_environment")
            env = None if pd.isna(env) else env
            validate_labels(r["label_waste_type"], r["label_severity"], env)
            row, _ = featurize(os.path.join(images_dir, r["image_file"]))
            row.update({"image_file": r["image_file"], "label_waste_type": r["label_waste_type"],
                        "label_severity": r["label_severity"], "label_environment": env})
            rows.append(row)
        except Exception as e:
            skipped.append((r["image_file"], str(e)))
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print(f"Wrote {len(rows)} rows to {out_csv}; skipped {len(skipped)}")
    for name, err in skipped:
        print(f"  skipped {name}: {err}")


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "features.csv")