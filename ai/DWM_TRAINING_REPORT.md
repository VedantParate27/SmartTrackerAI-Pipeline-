# DWM Training Report (Person B: data and models)

Branch base: `dwm-detection-pipeline`. Detector: `ShihoAI/yolov8s-garbage-detection` (`best_yolov8s_final.pt`).
Model card checked: classes are biological, cardboard, metal, paper, plastic, other (mAP50 39.42%).

## 1. Files

| File | Purpose |
|---|---|
| `src/collect_dwm_images.py` | Downloads all images and writes the rule-based labels |
| `dwm_labels.csv` | Final label file (same columns and label names as `labels_sample.csv`) |
| `data/features.csv` | Output of `build_features.py` (3056 rows, 41 features) |
| `src/train_dwm.py` | Trains and compares DT / RF / k-NN / NB, exports the best models |
| `src/evaluate_dwm.py` | DWM-only vs LLM-only vs hybrid on the held-out test images |
| `models/waste_type_model.joblib`, `severity_model.joblib`, `environment_model.joblib` | Exported models |
| `dwm_results/` | `training_results.txt`, confusion matrices (`cm_*.png`), tree plots (`tree_*.png`), `test_images.csv`, `eval_results*.{csv,txt}`, `label_check_sample.csv` |

Not committed: `models/best.pt` (gitignored), `data/dwm_images/` (758 MB, added to `.gitignore`), `venv/`.

Reproduce (from `ai/src`):

```
python collect_dwm_images.py ../data/dwm_images <any_path>.csv   # images only; labels are in dwm_labels.csv
python build_features.py ../dwm_labels.csv ../data/dwm_images ../data/features.csv
python train_dwm.py ../data/features.csv ../dwm_results
python evaluate_dwm.py ../dwm_results/test_images.csv ../data/dwm_images ../dwm_results/eval_results.csv [--dwm-only]
```

Environment: Python 3.13, scikit-learn 1.5.2, pandas 3.0.2, numpy 2.3.3 and joblib 1.5.2, matching the
pins in `requirements.txt` so that the `.joblib` files load.

## 2. Data and labels

3056 labelled images. Each source is identified by its file-name prefix.

| Prefix | Source | Rows | How labels were produced |
|---|---|---|---|
| `taco_` | TACO (pedropro/TACO), litter in the wild | 1481 | **Rule-based from TACO's human object annotations** (see below) |
| `wvbio_` | steveharianto/waste-garbage-management-dataset, class `biological` | 150 | Dataset class: wet / domestic |
| `wvbat_` | same, class `battery` | 150 | Dataset class: hazardous / domestic |
| `ginin_` | SpotGarbage GINI, non-garbage queries (roads, streets, buildings, people...) | 612 | none / none. 399 images with YOLO detections were visually checked; 9 showing litter were removed |
| `ginig_` | SpotGarbage GINI, images annotated as garbage | 213 | **AI-assisted visual labelling** |
| `dc_` | Datacluster Domestic Trash (India, phone photos) | 213 | **AI-assisted visual labelling** |
| `bin_` | Akhila-9849/Garbage_Bin_overflow_images | 118 | **AI-assisted visual labelling** |
| `ew_` | GIZ e-waste dataset (scrapyard photos) | 119 | **AI-assisted visual labelling** |

TACO rules (`collect_dwm_images.py`), following the definitions in the Gemini prompt and `data/waste_guidelines`:
- Category mapping: Food waste → wet; Battery, Aerosol → hazardous; Unlabeled litter → ignored; everything else
  (plastic, paper, carton, metal, glass, cigarette, shoe, rope...) → dry.
- waste_type = the group that covers at least 70% of the annotated litter area; otherwise `mixed`.
- severity = `domestic` if the image has 3 or fewer annotated objects, otherwise `moderate`.
- environment = `open_ground` if every scene background is pavement, sand/dirt, vegetation or water; otherwise blank.

**AI-assisted visual labelling (must be disclosed).** The 663 `ginig_`, `dc_`, `bin_` and `ew_` rows had no
usable labels in their source. Claude (an LLM) labelled them visually from contact sheets, using the same
category definitions as the Gemini prompt. Only images with at least one YOLO detection were labelled. 103 were
excluded as unreadable (blurry CCTV frames, cartoons, infographics), and non-waste images were labelled `none`.
`dwm_results/label_check_sample.csv` is a random 25% sample (166 rows, stratified by source). **A human must
hand-check it** (fill in `human_agrees` / `human_correction`) before these labels are presented as verified.

Final label counts (all 3056 rows):

| waste_type | n | severity | n | environment | n |
|---|---|---|---|---|---|
| dry | 1752 | domestic | 1662 | open_ground | 1759 |
| none | 655 | none | 655 | (blank) | 1189 |
| mixed | 197 | moderate | 609 | bin | 73 |
| wet | 159 | dump_scale | 130 | landfill | 35 |
| hazardous | 156 | | | | |
| e_waste | 125 | | | | |
| sanitary | 12 | | | | |

## 3. Training setup (`train_dwm.py`)

- One stratified 75/25 split by image (seed 0): 2292 train and 764 test images. The test list is saved for evaluation.
- Rows with `total_detections == 0` were dropped from training and model testing: 319 train and 117 test rows.
  That leaves 1973 train and 647 test rows.
- Each classifier was tuned with 5-fold stratified CV on the training split, scored by macro-F1. Candidates:
  Decision Tree (balanced class weights), Random Forest (300 trees, balanced), k-NN (standardised features)
  and Gaussian Naive Bayes.
- The model with the best **CV** macro-F1 was exported, so the test set was not used to choose it. Models are fitted
  on the training split only, which keeps the evaluation in section 5 honest. They were trained on a pandas
  DataFrame, so `feature_names_in_` is set.
- The environment model was trained only on rows that have an environment label (1271 train, 420 test).

## 4. Model comparison (held-out test rows with detections)

| Target | Model | CV macro-F1 | Test accuracy | Test macro-F1 |
|---|---|---|---|---|
| waste_type | Decision Tree | 0.458 | 0.609 | 0.424 |
| waste_type | **Random Forest** (exported) | **0.564** | **0.748** | **0.549** |
| waste_type | k-NN | 0.463 | 0.717 | 0.475 |
| waste_type | Naive Bayes | 0.375 | 0.479 | 0.367 |
| severity | Decision Tree | 0.471 | 0.594 | 0.499 |
| severity | **Random Forest** (exported) | **0.573** | **0.702** | **0.613** |
| severity | k-NN | 0.499 | 0.634 | 0.497 |
| severity | Naive Bayes | 0.394 | 0.488 | 0.421 |
| environment | Decision Tree | 0.440 | 0.924 | 0.626 |
| environment | Random Forest | 0.427 | 0.943 | 0.611 |
| environment | **k-NN** (exported) | **0.468** | 0.921 | 0.516 |
| environment | Naive Bayes | 0.442 | 0.836 | 0.484 |

Per-class precision and recall, plus the "confidently wrong" rate of each model at each confidence level, are in
`dwm_results/training_results.txt`. Confusion matrices are in `dwm_results/cm_*.png`.

Random Forest waste_type, per-class recall: dry 0.88, hazardous 0.80, wet 0.79, none 0.53, mixed 0.43,
e_waste 0.35, sanitary 0.00 (3 test rows). The most common error is e_waste/mixed/none being predicted as dry.

The decision tree is plotted in `dwm_results/tree_*.png` (top 4 levels). The severity tree splits first on
`px_edge_density`, then on `area_plastic`, `mean_conf` and `total_detections`.

## 5. Evaluation of the three systems (`evaluate_dwm.py`)

**Run here: DWM-only only.** No Gemini API key was available on this machine. LLM-only and hybrid need
`GOOGLE_API_KEY` and a valid `ENV_PATH` in `config.py`, which currently points to Member 3's machine. The script
caches Gemini answers, so it can be run once with the key.

DWM-only on all 764 test images:
- Outcomes: 524 answered, 123 predicted `none` (the hybrid sends these to Gemini), 117 had no detections.
- waste_type accuracy 63.4%, severity accuracy 58.9%, both correct 54.1%. Images with no detections count as wrong.

## 6. Threshold evidence (do not change `config.py` yet; set it together)

This uses the hybrid acceptance rule: both confidences ≥ t and neither prediction is `none`. Figures are over all
764 test images, from `dwm_results/eval_results_summary.txt`:

| t | Share of images DWM answers | Wrong among those (confidently wrong) |
|---|---|---|
| 0.5 | 42.5% (325) | 18.8% |
| 0.6 | 29.6% (226) | 13.7% |
| 0.7 | 19.1% (146) | 10.3% |
| 0.8 | 11.5% (88) | 8.0% |
| 0.9 | 4.1% (31) | 6.5% |

At the current placeholder of 0.7, DWM answers about 19% of images and gets 10% of those wrong; the rest go to
Gemini. "Wrong" means waste_type or severity is wrong. Severity causes most of these errors: waste_type alone is
97% correct at 0.7 (see the sweep in `training_results.txt`).

## 7. Limitations (state these in the report)

- **YOLO classes do not cover our taxonomy.** Hazardous, sanitary and e-waste have no YOLO class, so those
  predictions rely on pixel features. Sanitary has only 12 rows, and the model never predicts it.
- **Source shortcut risk.** Some classes come mostly from one source (hazardous and wet from studio-style
  single-object photos, `none` from web stock photos, e_waste from one scrapyard set). Pixel features can partly
  learn the photo style instead of the waste. Real-world accuracy on user uploads is likely lower than these
  test figures.
- **The detector may have been trained on TACO-like data**, so TACO detections may be optimistic.
- **Severity for TACO is a rule** (object count). Severity for 663 rows is AI-assisted and still needs the
  human check above.
- dump_scale (130 rows), bin (73) and landfill (35) are small classes. Treat their per-class figures with caution.
- The environment model is weak on bin and landfill: recall 0.26 and 0.18 with k-NN. `dwm_classifier.py` loads it
  automatically if `environment_model.joblib` exists. Delete that file if the environment output should not be used.
- Dataset licences: the Datacluster sample is CC BY-NC-ND (academic, non-commercial use only). TACO, GIZ and the
  bin-overflow set are CC BY 4.0. GINI has no stated licence; cite Mittal et al., UbiComp 2016.
