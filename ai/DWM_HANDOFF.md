# DWM Layer Handoff (SmartTracker AI, waste image module)

Branch: `dwm-detection-pipeline`
Written by: Member 3 (AI). For: the teammate who labels images and trains the models.

## 1. What this is

The waste image module used to rely only on Gemini vision. We are adding a
data-mining (DWM) layer as the main logic, with Gemini kept as automatic backup.

```
image
  -> YOLOv8s (pretrained, used only as a FEATURE EXTRACTOR)
  -> feature row (41 columns: YOLO stats + pixel features)
  -> classifiers trained on OUR labels (decision tree / RF / k-NN / Naive Bayes)
  -> confident?  yes -> use the DWM answer
                 no  -> fall back to Gemini
```

The inference pipeline is finished and wired in. **The trained models do not
exist yet. Producing them is your job.** Until they exist, every image
automatically falls back to Gemini, so nothing is broken in the meantime
(verified: `waste_evaluate.py` scores 5/5 in that state).

## 2. Files (all in `ai/src/`)

| File | Purpose |
|---|---|
| `detector.py` | Runs YOLOv8s on an image, returns detections |
| `features.py` | Turns detections + pixels into the 41-column feature row |
| `build_features.py` | Builds a feature table from labelled images |
| `dwm_classifier.py` | Loads the trained models, predicts, returns confidence |
| `hybrid_classifier.py` | DWM first, Gemini fallback. `waste_pipeline.py` imports `classify_hybrid` |
| `config.py` | `ENVIRONMENTS`, `DWM_CONFIDENCE_THRESHOLD` (0.7 is a placeholder) |

`ai/labels_sample.csv` shows the label file format. Open it and copy its
header exactly for your full label file.

## 3. Setup

1. Clone the repo and check out `dwm-detection-pipeline`.
2. Create a virtual environment and run `pip install -r ai/requirements.txt`.
3. Create `ai/.env` with `GOOGLE_API_KEY=...` (not committed; ask Member 3 for the key).
4. **YOLO weights are NOT in the repo** (`ai/models/*.pt` is gitignored; AGPL-3.0 licence).
   Get `best_yolov8s_final.pt` from the Hugging Face repo
   `ShihoAI/yolov8s-garbage-detection`, rename it to `best.pt`, and place it at `ai/models/best.pt`.
   Classes: biological, cardboard, metal, paper, plastic, other. Reported mAP50 is only about 39%.
5. The waste guideline RAG needs the ChromaDB collection `waste_guidelines` ingested
   (6 guideline files in `data/waste_guidelines`). The Gemini fallback path uses this.

## 4. Labels to create

Labels come from OUR taxonomy, not YOLO's. The CSV has these columns, in this order:

    image_file,label_waste_type,label_severity,label_environment

- `label_waste_type`: wet, dry, hazardous, sanitary, e_waste, mixed, none
- `label_severity`: domestic, moderate, dump_scale, none
- `label_environment`: bin, open_ground, landfill

In `labels_sample.csv`, the `none` example (dog.jpeg) leaves `label_environment`
empty. It is NOT verified that `build_features.py` or your training code handles an
empty environment. Check this before training: either handle the blank, or train the
environment model only on rows that have a value.

Include `none` examples (no waste visible); the system must be able to say "nothing here".

Practical advice:
- Aim for a reasonable number of images per class. Rare classes (hazardous,
  sanitary, e_waste) will be weak no matter what, because YOLO has no class for them.
- Do not train on rows where YOLO found zero detections. Those rows are mostly
  empty features and teach the model nothing (see section 6).

## 5. Your tasks, in order

1. Label images and save the label CSV in the same format as `labels_sample.csv`.
2. Run `build_features.py` to produce the feature table. Check the script header
   for its exact inputs and outputs; do not assume.
3. Train and compare Decision Tree, Random Forest, k-NN and Naive Bayes for
   `waste_type` and for `severity`. Use a proper train/test split and report
   accuracy plus a confusion matrix.
4. **Train on a pandas DataFrame with column names**, so `feature_names_in_` is
   set. `dwm_classifier.py` relies on it to keep feature order consistent.
5. Export the chosen models as `waste_type_model.joblib` and
   `severity_model.joblib` into `ai/models/`. Check `dwm_classifier.py` for the
   exact filenames and the loading logic before exporting.
6. Recalibrate `DWM_CONFIDENCE_THRESHOLD` in `config.py`. 0.7 is a placeholder.
7. Evaluate three systems on the same held-out images: **DWM-only, LLM-only, hybrid.**

## 6. Known findings (measured by Member 3)

- YOLO reads food scraps as plastic or metal. It produced no `biological`
  detections on our test images.
- YOLO detected nothing on the landfill photo, even at confidence 0.05.
- Hazardous, sanitary and e-waste have no YOLO class, so the classifiers lean
  on pixel features for them. Expect weaker results.
- The fallback only triggers on LOW confidence, zero detections, a predicted
  `none`, typed user context, or an error. A **confidently wrong** DWM answer
  never falls back. This must be measured separately in your evaluation: report
  how often high-confidence predictions are wrong, not only overall accuracy.
- `full_bin.jpeg` is marked `known_ambiguous` in `waste_eval_data.py`; Gemini
  flips between dry/mixed and moderate/domestic on it across runs.

## 7. What is NOT verified

- No trained DWM model has been run end to end. Only the fallback path is tested.
- The 0.7 threshold has no evidence behind it yet.
- The cleanup verifier has been tested on mismatched and identical images only,
  not on a real before/after cleanup pair.
- Eval sets are small, so treat percentages with caution.

## 8. When you finish

Commit your models' training script and notes (not `best.pt`, not `.env`, not
`.db`, not large feature CSVs). Push to a branch and tell Member 3 so the
branch can be merged via pull request.