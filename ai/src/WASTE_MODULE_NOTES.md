## Waste Image Classification Evaluation

Evaluated on a 6-case labeled test set covering both good images (domestic,
dump-scale, moderate/mixed) and unusable images (unrelated subject, blurry,
no waste present), saved in `waste_eval_results.txt`.

- Usability detection accuracy: 100.0% (6/6)
- Waste-type classification accuracy: 100.0% (6/6)
- Severity assessment accuracy: 100.0% (6/6)
- Escalation decision accuracy: 100.0% (6/6)

This evaluation also surfaced and led to a fix for two real issues during
development: a missing "mixed" waste-type guideline document (moderate-
severity mixed waste had no disposal guidance to retrieve), and a fabricated
citation bug in the disposal-guidance prompt (the model cited a non-existent
source when explaining a genuine information gap) — both fixed and verified
before this final evaluation run.