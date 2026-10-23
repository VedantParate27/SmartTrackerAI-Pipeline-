# Waste Management Module — Report

## Overview

This module extends the SmartTracker AI pipeline with an image-based
Municipal Solid Waste (MSW) capability, additive to the existing text-based
complaint pipeline. A user uploads a photo of waste; the system classifies
the waste type and severity, then either escalates to authorities (for
dump-scale or recurring cases) or provides grounded disposal guidance
directly to the citizen (for domestic/moderate cases).

## Architecture

| Component | File | Purpose |
|---|---|---|
| Image classification | `waste_classifier.py` | Gemini vision call — waste type, severity, usability, follow-up question |
| Escalation decision | `waste_pipeline.py` | Fork logic: escalate vs. disposal guidance, confidence handling |
| RAG disposal guidance | `waste_rag.py` | Hybrid retrieval + grounded generation over waste-guideline documents |
| Cleanup verification | `cleanup_verifier.py` | Before/after image comparison for cleanup proof |
| Evaluation | `waste_evaluate.py`, `waste_eval_data.py` | Labeled test suite across usability, type, severity, escalation |

## Domain design

**Waste types**: wet, dry, hazardous, sanitary, e_waste, mixed
**Severity tiers**: domestic, moderate, dump_scale
**Escalation triggers**: severity = dump_scale, OR 3+ prior reports at the
same location (recurring_flag), regardless of what any single photo shows.

## Key design decisions

- **Additive, not a replacement.** The existing text-complaint pipeline
  (classifier.py, retrieval.py, generator.py, pipeline.py) is completely
  untouched. Waste image classification is a parallel entry point sharing
  the same architectural patterns (Pydantic schema enforcement, confidence
  thresholds, RAG grounding, citation verification).
- **Image is primary evidence; text context is a modifier.** A user may
  optionally add context (e.g., "this has been here for 3 weeks"). Testing
  confirmed this context can independently raise severity (domestic → moderate)
  even when the image alone looks small-scale — matching the intended design
  that persistent/recurring problems matter regardless of single-photo scale.
- **Recurring-location escalation is independent of image content.** Even a
  small, domestic-looking photo escalates to authorities if the same location
  has 3+ prior reports, since this indicates a systemic problem the AI cannot
  see in a single image.

## Evaluation results

6-case labeled test set (see `waste_eval_results.txt`):
- Usability detection accuracy: 100.0% (6/6)
- Waste-type classification accuracy: 100.0% (6/6)
- Severity assessment accuracy: 100.0% (6/6)
- Escalation decision accuracy: 100.0% (6/6)

## Known limitations (documented honestly)

- **Small evaluation set.** 6 cases is sufficient to confirm the core logic
  works but is smaller than the 30-case classifier + dedicated adversarial
  suites (hallucination, low-confidence, no-policy) built for the text
  pipeline in Phase 3. Additional images — particularly dry, hazardous,
  sanitary, and e-waste examples, and a genuinely borderline domestic/
  moderate case — would strengthen this further.
- **Mixed-waste guideline gap (found and fixed).** Initial testing surfaced
  that moderate-severity "mixed" waste had no matching disposal guideline
  document, causing the generator to correctly report a gap — but with a
  fabricated citation tag attached to that admission. Both issues were fixed:
  a `mixed_waste.txt` guideline was added, and the disposal-guidance prompt
  was given the same citation-discipline rule already present in the main
  complaint pipeline's generator.
- **Cleanup verification: 2 of 3 failure modes validated locally.**
  Confirmed correct behavior for (1) mismatched/unrelated before-after image
  pairs, correctly refused rather than false-passed, and (2) identical/reused
  images, correctly identified as no cleanup performed. The genuine positive
  case — real before/after photos of the same location where cleanup
  actually occurred — was not tested locally due to lack of a real photo
  pair, and should be verified once the actual upload flow exists.
- **Follow-up questions are single-turn.** The system generates one
  contextual question when needed (e.g., asking to retake a blurry photo,
  or asking about recurrence) but does not yet support a multi-turn
  conversation incorporating the user's answer back into re-classification.

## Integration notes for the team

- Waste-guideline documents live in `data/waste_guidelines/`, ingested into
  a separate ChromaDB collection (`waste_guidelines`) from the main complaint
  policies, so the two RAG systems don't interfere with each other.
- `prior_reports_at_location` in `waste_pipeline.py` is a parameter the
  backend must supply (a count of previous reports at the same GPS location)
  — this AI module does not query the database itself.
- Cleanup verification currently has no persistent storage wired in; it
  should log to whatever cleanup-task table the backend maintains, following
  the same pattern as `storage.py`'s admin review queue for the text pipeline.