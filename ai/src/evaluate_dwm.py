"""
Compares DWM-only, LLM-only (Gemini) and hybrid on the held-out test images.

Usage: python evaluate_dwm.py <test_images_csv> <images_dir> <results_csv> [--dwm-only]

- <test_images_csv> is the test_images.csv written by train_dwm.py.
- Gemini results are cached in <results_csv>; re-running only calls Gemini for images without a result.
- --dwm-only skips Gemini (no API key needed) and reports the DWM-only system.
- Hybrid uses the same rule as hybrid_classifier.classify_hybrid (no user context): DWM answer if it
  succeeds and both confidences >= DWM_CONFIDENCE_THRESHOLD, otherwise the Gemini answer.
"""
import io, os, sys, time, mimetypes
import pandas as pd
from PIL import Image
from dwm_classifier import classify_with_dwm
from config import DWM_CONFIDENCE_THRESHOLD

SWEEP = [0.5, 0.6, 0.7, 0.8, 0.9]


def run_dwm(image_bytes):
    """Returns (waste, severity, waste_conf, severity_conf, outcome)."""
    try:
        r = classify_with_dwm(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
        return r["waste_type"], r["severity"], r["waste_type_confidence"], r["severity_confidence"], "ok"
    except RuntimeError as e:
        if str(e) == "dwm_predicted_none":
            return "none", "none", None, None, "predicted_none"
        return None, None, None, None, str(e)


def hybrid_row(r, t):
    if r.dwm_outcome == "ok" and r.dwm_waste_conf >= t and r.dwm_severity_conf >= t:
        return r.dwm_waste, r.dwm_severity, "dwm"
    return r.llm_waste, r.llm_severity, "llm_fallback"


def score(name, df, w, s):
    ok_w, ok_s = (w == df.label_waste_type), (s == df.label_severity)
    return (f"{name:<10} answered {w.notna().mean():6.1%}   waste_type acc {ok_w.mean():6.1%}   "
            f"severity acc {ok_s.mean():6.1%}   both correct {(ok_w & ok_s).mean():6.1%}")


def main(test_csv, images_dir, results_csv, dwm_only):
    test = pd.read_csv(test_csv)
    cached = pd.read_csv(results_csv).set_index("image_file") if os.path.exists(results_csv) else None
    rows = []
    for i, t in enumerate(test.itertuples(), 1):
        path = os.path.join(images_dir, t.image_file)
        with open(path, "rb") as f:
            image_bytes = f.read()
        w, s, wc, sc, outcome = run_dwm(image_bytes)
        row = {"image_file": t.image_file, "label_waste_type": t.label_waste_type, "label_severity": t.label_severity,
               "dwm_waste": w, "dwm_severity": s, "dwm_waste_conf": wc, "dwm_severity_conf": sc,
               "dwm_outcome": outcome, "llm_waste": None, "llm_severity": None}
        if cached is not None and t.image_file in cached.index and pd.notna(cached.at[t.image_file, "llm_waste"]):
            row["llm_waste"] = cached.at[t.image_file, "llm_waste"]
            row["llm_severity"] = cached.at[t.image_file, "llm_severity"]
        elif not dwm_only:
            from waste_classifier import classify_waste_image
            try:
                mime = mimetypes.guess_type(path)[0] or "image/jpeg"
                r = classify_waste_image(image_bytes, mime_type=mime)
                row["llm_waste"], row["llm_severity"] = r["waste_type"], r["severity"]
            except Exception as e:
                print(f"  Gemini failed on {t.image_file}: {e}")
            time.sleep(4)
        rows.append(row)
        print(f"{i}/{len(test)} {t.image_file}: dwm={outcome}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(results_csv, index=False)

    lines = [f"Test images: {len(df)}", "DWM outcome counts:", df.dwm_outcome.value_counts().to_string(), "",
             score("DWM-only", df, df.dwm_waste, df.dwm_severity)]
    if df.llm_waste.notna().all():
        lines.append(score("LLM-only", df, df.llm_waste, df.llm_severity))
        for t in SWEEP:
            h = pd.DataFrame([hybrid_row(r, t) for r in df.itertuples()], columns=["w", "s", "src"])
            routed = h.src == "dwm"
            wrong = ((h.w != df.label_waste_type) | (h.s != df.label_severity))[routed]
            marker = "  <- config threshold" if t == DWM_CONFIDENCE_THRESHOLD else ""
            lines += [score(f"Hybrid@{t:.1f}", df, h.w, h.s) + marker,
                      f"{'':<10} routed to DWM {routed.mean():6.1%} ({routed.sum()}); confidently wrong among those "
                      f"{wrong.mean() if routed.any() else float('nan'):6.1%}"]
    else:
        lines.append(f"LLM-only / hybrid: not scored, {df.llm_waste.isna().sum()} images have no Gemini result "
                     f"(run without --dwm-only and a GOOGLE_API_KEY).")
    ok = df.dwm_outcome == "ok"
    lines.append("\nDWM answers that would pass each threshold (both confidences >= t):")
    for t in SWEEP:
        p = ok & (df.dwm_waste_conf >= t) & (df.dwm_severity_conf >= t)
        wrong = ((df.dwm_waste != df.label_waste_type) | (df.dwm_severity != df.label_severity))[p]
        lines.append(f"  t={t:.1f}: {p.mean():6.1%} of images ({p.sum()}), wrong among those "
                     f"{wrong.mean() if p.any() else float('nan'):6.1%}")
    print("\n".join(lines))
    with open(os.path.splitext(results_csv)[0] + "_summary.txt", "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], "--dwm-only" in sys.argv)
