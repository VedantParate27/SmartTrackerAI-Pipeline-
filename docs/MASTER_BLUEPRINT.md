# SmartTrackerAI — MASTER PROJECT BLUEPRINT (Phase 3)

Version: 1.0 · 2026-09-28
Basis: Phase 1 code analysis (`backend/` = source of truth) + Phase 2 literature review (46 papers; gaps G1–G4).
Team: M1 Frontend · M2 Backend/API · M3 AI/ML · M4 Integration/DB/Testing/DWM.
Rules honored: no paper writing, no fabricated results, no novelty beyond G1–G4, realistic for 4 undergraduates, essential vs optional clearly separated.

---

## 1. FINAL PROJECT CONCEPT (plain language)

**What SmartTrackerAI becomes:** a waste-complaint platform where a **calibrated AI triage assistant** reads every incoming complaint and suggests what it is (waste type), how bad it is (severity), and what should happen (dispatch a cleaner vs. teach the citizen self-disposal). Critically, the AI also says **how sure it is** — and that certainty decides the route:

- **Sure predictions** are pre-filled for the admin, who can accept or correct them in one click (AI-assisted mode).
- **Uncertain predictions are automatically escalated** to the admin queue with a highlighted review request (confidence-gated human review).

From there the workflow runs to the ground: accepted dispatches become cleanup tasks for cleaners, cleaners upload photo proof, admins verify the proof, and the complaint closes. **Every step writes one row to an event log.** At the end of the pipeline, process mining (pm4py) turns that log into the research evidence: where time is lost, which workflow variants occur, how often proofs are rejected, and — the heart of the paper — **whether AI-assisted cases actually resolve faster and with less admin effort than manual ones**, measured on the same running system.

One sentence: **we build the loop the literature never closed — triage AI + calibrated escalation + verified field execution + process-mined evaluation, all on one instrumented system.**

### Roles
- **Citizen:** submits complaint (text + optional location). Sees tracking ID, status, and, for low-severity cases, the approved disposal guidance.
- **AI (Member 3's models):** predicts waste type, severity, intervention-required, and confidence. Recommends action text. Never acts alone — it pre-fills or escalates.
- **Admin (human-in-the-loop):** sees AI suggestion + confidence + review flag; accepts/corrects; decides dispatch vs guidance; assigns cleaner; verifies proof photos. All admin actions are logged.
- **Cleaner:** receives task with location/instructions, uploads proof photo. Their resubmission-after-rejection loop is a *designed* process variant that process mining will measure.
- **Process mining / DWM (Member 4):** owns the event log, the warehouse, the pm4py notebooks, and the analytics that turn the workflow into findings.

---

## 2. THE END-TO-END WORKFLOW (designed, not copied)

```
Citizen submits complaint (text, optional photo, GPS/address)
        │
        ▼
AI triage service (synchronous, <1 s target)
  ├─ waste_type prediction
  ├─ quantity_severity prediction
  ├─ intervention_required prediction
  ├─ recommended_action (template / RAG-generated)
  └─ confidence score (calibrated)
        │
        ▼
ESCALATION GATE  (the research core — G2)
  ├─ confidence ≥ τ AND not hazardous  → AI-assisted path: pre-fill admin decision form
  └─ confidence < τ OR hazardous       → mandatory human review, review_reason stored
        │
        ▼
ADMIN DECISION (always a human decides; AI only pre-fills)
  ├─ accept/correct waste_type, severity
  ├─ correct = stored as a correction record (feeds evaluation)
  └─ choose: DISPATCH  or  GUIDANCE
        │
   ┌────┴─────────────────────────┐
   ▼                              ▼
CLEANER TASK                  SELF-DISPOSAL GUIDANCE
 (task assigned,               (guidance response approved,
  status in_progress)           complaint resolved, no field visit)
   │
   ▼
Cleanup performed → cleaner uploads PHOTO PROOF
        │
        ▼
ADMIN VERIFIES PROOF
  ├─ verified  → complaint resolved
  └─ rejected  → task back to cleaner (resubmission loop = process variant)
        │
        ▼
COMPLAINT RESOLVED / CLOSED
        │
        ▼ (every arrow above also writes one event_log row)
EVENT LOG  →  DWM warehouse (DuckDB star schema)  →  pm4py process mining + analytics
```

**Two deliberate design decisions that improve on the naive flow you sketched:**

1. **AI never sits between citizen and admin as a blocker.** The AI runs synchronously at submission but its output is *advice attached to the complaint* (columns + an escalation flag), not a gate the complaint must pass. This keeps the system resilient (AI down ≠ platform down) and matches the Phase 2 finding (P1 Rajkumar 2025) that integration — not model quality — is where the research gap is.
2. **Guidance is a first-class resolution path.** Because `intervention_required=False` cases have no field visit, they form a natural comparison cohort for process mining (shorter loop, no proof stage). The workflow *designed* into the schema becomes the *variant analysis* the paper reports.

---

## 3. FEATURE → RESEARCH-GAP MAP

| # | Feature | Gap | Why it matters | How evaluated | Priority |
|---|---|---|---|---|---|
| F1 | AI text triage (type, severity, intervention) | G1, G4 | Entry point of the loop; enables everything else | Exp-1: accuracy/F1 vs baselines | **ESSENTIAL** |
| F2 | Confidence estimation + calibration | G2 | No located study calibrates confidence for civic triage | Exp-2: ECE, risk–coverage | **ESSENTIAL** |
| F3 | Confidence-gated escalation to admin | G2, G4 | Turns calibration into an operational policy | Exp-2 + Exp-3: review load vs error rate | **ESSENTIAL** |
| F4 | Admin accept/correct + correction storage | G4 | Corrections are ground truth for measuring AI assist value | Exp-3: acceptance rate, edit distance | **ESSENTIAL** |
| F5 | Intervention decision → cleaner task vs guidance | G1 | The operational branch no located paper studies end-to-end | Exp-4: variant analysis of both paths | **ESSENTIAL** |
| F6 | Cleaner task + photo proof + verify/reject | G1 | Verified field execution = the loop literature omits | Exp-4: rejection-loop rate, stage times | **ESSENTIAL** |
| F7 | Event log (actor, action, timestamp, case) | G3 | Prerequisite for all process-level claims | Data-quality checks; log completeness test | **ESSENTIAL** |
| F8 | Process mining (discovery, conformance, variants, timing) | G3 | Produces the workflow findings | Exp-4: fitness, precision, durations | **ESSENTIAL** |
| F9 | Manual vs AI-assisted controlled comparison | G4 | The "does it actually help?" experiment nobody ran | Exp-3: decision time, resolution time, error rate | **ESSENTIAL** |
| F10 | Prediction metadata (model version, threshold, latency) | G3, G4 | Makes results reproducible and auditable | Reproducibility check in Exp-1 | **ESSENTIAL** |
| F11 | Disposal-guidance RAG with citation check | G1 (supporting) | Better guidance quality; citation verifier already prototyped in legacy `ai/` | Manual faithfulness spot-check (small n) | Optional+ |
| F12 | Spatial hotspots (DBSCAN, severity-weighted) | DWM richness | Only if coordinates accumulate; mature methods | Exp-5 (optional): cluster stability | Optional |
| F13 | DuckDB star-schema warehouse | DWM deliverable | Feeds F8, F12; clean DWM artifact for the course | Query suite + ETL test | Optional+ |
| F14 | Active-learning loop | — | **DEMOTED**: P14 (2026) shows marginal AL value; P13 covers it | — | Optional− |
| F15 | AI proof-photo analysis | — | New model class, new dataset, no gap support | — | **DO NOT BUILD** (Phase 4 at best) |

---

## 4. AI PART — exact specification for Member 3

### Predict (4 outputs, all on the complaint text):
1. **`waste_type`** — 6 classes: dry, wet, e_waste, medical, hazardous, bulk. *Essential — drives routing and variants.*
2. **`quantity_severity`** — 3 classes: small, medium, large (+ hazardous flag folded into waste_type). *Essential — prioritization input.*
3. **`intervention_required`** — binary. *Essential — this IS the operational decision; the most research-relevant prediction.*
4. **`confidence`** — per-complaint scalar used by the escalation gate. *Essential — G2's core.*
5. `recommended_action` — *supporting*: template selection per (waste_type, intervention) pair; LLM paraphrase optional. Not a research metric.

**Unnecessary for the research:** department routing (no departments in the waste flow — cut it), sentiment/urgency from text (severity label covers it), multi-language models (add code-mixed data, not a separate model), any image model (F15).

### Model roster (all four must run on the SAME splits):
| Tier | Model | Role |
|---|---|---|
| B0 | Majority-class | Floor |
| B1 | TF-IDF (word 1–2 grams) + Logistic Regression | Classical baseline — cheap, fast, interpretable |
| B2 | TF-IDF + Linear SVM | Second classical baseline |
| M1 | Fine-tuned DistilBERT / MiniLM | Small transformer — the production candidate |
| M2 | Zero-shot LLM (free-tier Gemini, temp 0) | The "no training needed" alternative; produces **verbalized confidence** |
| M3 | Hybrid (M1 softmax + isotonic/temperature calibration) | Calibration arm for Exp-2 |

- M2 runs only if the RQ1 dataset subsample (~300 cases) is enough to compare fairly; note free-tier quota in methods.
- If time is short: B1 + M1 + M2 is the minimum defensible roster. Never report a model without a baseline.

### Deliverables from M3:
- `training/` scripts (reproducible seed, config-driven);
- `artifacts/` model registry: `model_name`, `version`, `trained_on`, `metrics.json`;
- an `/internal/evaluate` report (Exp-1 tables);
- a 50-line Python client the backend imports: `predict(text) -> {waste_type, quantity_severity, intervention_required, confidence, model_name, model_version, latency_ms}`.

---

## 5. HUMAN-IN-THE-LOOP DESIGN

**Rule: the AI never resolves; the admin never sees a blank form.**

1. **Auto path (high confidence):** confidence ≥ τ and predicted class ≠ hazardous → complaint appears in admin queue with the AI suggestion pre-filled; admin confirms with one click. Still human-approved, but measured as "AI-assisted."
2. **Escalated path (low confidence or hazardous class):** complaint is flagged `requires_review=true` with a machine-readable reason; admin must actively classify before dispatch/guidance. Measured as "human-only."
3. **τ selection is an experiment output, not a guess:** choose τ on validation data to hit a target missed-critical-error rate (e.g., hazardous misroutes ≈ 0), then report the resulting review load. The legacy code's 0.6 is replaced by this procedure.
4. **Admin sees:** complaint text, location, AI predictions + confidence + model version, review flag/reason, one-click Accept, per-field Correct dropdowns, Dispatch/Guidance decision, notes.
5. **Corrections are stored** in `ai_corrections` (see §6) — they are simultaneously (a) evaluation data for Exp-3, (b) future fine-tuning data (optional reuse), and (c) the audit trail.
6. **What we can measure because of this design:** escalation rate, review precision (share of escalated cases the admin actually changes), correction rate per class, admin decision time in both paths (from event timestamps), and the error rate of non-escalated cases (spot-checked in Exp-3 arms).

---

## 6. BACKEND/API DESIGN (Member 2)

### ALREADY EXISTS (keep — verified in Phase 1)
- Auth: register (role forced citizen), login, JWT 60 min, bcrypt, RBAC dependencies (admin, cleaner), object-level access checks.
- Complaints: create (text 10–5000), list-mine, get-by-tracking-id; TRK ids; denormalized submitter fields.
- Admin: queue, queue-item, PUT update, response approve (guidance path), **assign cleaner** (creates CleanupTask, role-validated), **verify proof** (approve/reject, transitions task+complaint).
- Cleaner: task list, task detail, **proof upload** (UUID file, served at /uploads).
- Lifecycle: `VALID_TRANSITIONS` state machine with 400 on violation; `pending → in_progress → resolved/closed`.
- Infra: idempotent `run_migrations`, CORS allow-list, static uploads, pytest suite (10 tests, passing), app_state snapshot API.

### NEEDS TO BE ADDED (all ESSENTIAL unless noted)
1. **`complaint_ai_outputs`** table: complaint_id FK, waste_type_pred, quantity_severity_pred, intervention_required_pred, confidence FLOAT, model_name, model_version, threshold_used, escalated BOOL, review_reason, latency_ms, created_at. *(One row per inference; append-only.)*
2. **`ai_corrections`** table: complaint_id, field_name, ai_value, admin_value, admin_id, created_at. *(Written by the new PATCH endpoint below.)*
3. **`PATCH /admin/complaints/{id}/ai-decision`** — admin accepts (writes corrections only where changed) + sets dispatch/guidance; enforces the escalation flag (review-required complaints cannot skip review); emits events.
4. **`ai_prediction` middleware/hook** on `POST /complaints/` — call M3 client, persist output row, set `escalated`/`review_reason`, log events. Must fail-open (AI down → complaint still created, `ai_status=unavailable`).
5. **`event_log`** table + `log_event(db, case_id, actor_id, actor_role, action, old, new, meta)` helper — called from every mutating endpoint (see §7).
6. **`case_assignments` awareness** — assignment already transitions status; just add event emission + reassignment event (currently reassign overwrites silently).
7. **Seed/fixture script** — parametrized generator (users, complaints with realistic texts, assignments, proofs, timings) to reach Exp volumes; reads complaint texts from the labeled dataset so seeds are realistic.
8. **Timing instrumentation** — the event log supplies it; no separate metrics middleware needed beyond basic request logging (Optional: p50/p95 latency middleware for Exp-3 latency claims).
9. **Config:** `TRIAGE_THRESHOLD` env; model endpoint URL; feature flags `AI_MODE=off|assist` (off = manual arm of Exp-3).

### CAN BE REMOVED/CHANGED
- **`app_state` snapshot API (routers/app_state.py)** — legacy frontend persistence blob; no role in the research. Recommend deprecating (or freeze; do not extend). Freed effort ≈ 1 week.
- **`department` column + admin PUT department updates** — unused in waste flow; keep column for backward compat, drop from UI/API surface.
- **Hardcoded `priority="medium"`** — becomes derived from (severity, intervention, hazard) with the rule documented; that rule itself becomes an auditable artifact.
- **`language` column** — keep, but no translation feature (out of scope).
- **`staff` role** — either implement as reviewer or stop advertising it; recommend keeping only citizen/cleaner/admin for clarity.

**Backward-compat rule:** migration stays idempotent (already built); every new column nullable with defaults so the 10 existing tests keep passing; add ~10 new tests (AI hook fail-open, escalation enforcement, event-log completeness, correction storage, seed determinism).

---

## 7. DATABASE + EVENT LOG DESIGN (Member 4 with M2)

### New/changed tables (beyond §6)
- `complaints`: add `triage_mode` ENUM('manual','ai_assisted') NULL, `resolved_at` DATETIME NULL (explicit completion timestamp — cleaner than inferring from proofs).
- `cleanup_tasks`: add `started_at` DATETIME NULL (cleaner "start work" button OR first proof timestamp as proxy — decide once, document).

### Event log — one row per state change
Fields (exact):
```
event_id        INTEGER PK
case_id         VARCHAR  -- complaint tracking id (process-mining case identifier)
activity        VARCHAR  -- controlled vocabulary below
actor_id        INT NULL
actor_role      VARCHAR  -- citizen|ai_system|admin|cleaner|system
timestamp       DATETIME -- UTC, single clock
old_value       VARCHAR NULL
new_value       VARCHAR NULL
meta_json       TEXT NULL -- e.g. confidence, model_version, proof_id, rejection_reason, τ
```
Activity vocabulary (controlled — this is what makes pm4py work):
`complaint_created · ai_prediction_generated · human_review_required · human_review_completed · dispatch_decided · guidance_decided · cleaner_assigned · cleaner_reassigned · task_started (optional) · proof_submitted · proof_verified · proof_rejected · complaint_resolved · complaint_closed`
Plus one non-workflow event for Exp-3 sessions: `admin_decision_made` (meta: latency_ms, ai_suggestion_accepted BOOL).

**Log-completeness invariant (test):** every complaint's event sequence must start with `complaint_created` and end with `complaint_resolved|complaint_closed`, with monotone timestamps. This test is what makes RQ3's conformance checking meaningful.

### DWM warehouse (F13, optional+)
- DuckDB file; star schema: `fact_complaint_events` (FKs: dim_date, dim_time_of_day, dim_ward[from lat/long grid], dim_waste_type, dim_actor_role, dim_status_transition) + measures (duration_seconds, correction_count, proof_attempts).
- ETL: nightly script from SQLite → DuckDB; idempotent by event_id.
- Query suite (10 named queries): stage durations by waste type; escalation rate by week; rejection-loop frequency; variant counts; resolution-time percentiles; hotspot drill-down (if F12 on).

---

## 8. DWM / PROCESS-MINING ANALYSES (Member 4)

Using **pm4py** (Python, free) on the event log; optional ProM for visuals.

1. **Process discovery** — Heuristics Miner / inductive miner → the as-executed model; visualize both designed and discovered models side by side (a headline figure).
2. **Conformance checking** — token-based replay / alignments against the designed model (the state machine); report fitness + deviations (e.g., proof_rejected loops, guidance path skipping dispatch).
3. **Variant analysis** — top-k variants; compare share of `dispatch` vs `guidance` paths; rejection-loop variants; AI-assisted vs manual cohorts (triage_mode).
4. **Performance/bottleneck analysis** — mean/median stage durations: created→decision, decision→assignment, assignment→proof, proof→verify; identify the slowest stage overall and per cohort.
5. **HITL-specific metrics** — escalation rate over time; review-required → decision latency vs auto-path latency; correction rate by predicted class; share of escalated cases that were genuinely mispredicted (from corrections).
6. **Proof-verification analytics** — rejection rate; attempts-per-task distribution; time lost to rejections (first proof → final verified).
7. **(Optional F12)** DBSCAN/HDBSCAN hotspot stability across weeks, severity-weighted vs unweighted.
8. **(Optional F13)** OLAP rollups from the warehouse feeding 1–7.

Everything above is *descriptive of our own system* — legitimate primary analysis because the artifact is ours; findings must be reported with cohort sizes and no causal language beyond the controlled Exp-3.

---

## 9. THE FOUR EXPERIMENTS (what proves the contribution)

### Exp-1 — AI model comparison (M3 leads; M4 provides splits)
- **RQ:** How accurately can waste complaints be classified into type, severity, and intervention-required, and which model family is best?
- **Input:** labeled dataset (§10), fixed splits. **IV:** model (B0, B1, B2, M1, M2). **DV:** macro-F1, per-class F1, accuracy, confusion matrices, inference latency.
- **Baseline:** B0/B1 mandatory. **Metrics:** as listed + calibration prep (store raw confidences).
- **Expected result type:** M1 > B1 on macro-F1; per-class table showing which classes confuse (e.g., wet vs dry on vague texts); hazardous/medical classes likely rare → report per-class support honestly.

### Exp-2 — Confidence calibration & escalation threshold (M3 + M2)
- **RQ:** Is the deployed model's confidence calibrated, and what threshold τ best trades missed-critical-errors against human review load?
- **Input:** Exp-1 test split with stored confidences; optionally M2 verbalized confidences for comparison. **IV:** confidence source (M1 softmax vs calibrated M3 vs M2 verbalized) and τ sweep. **DV:** ECE, Brier, risk–coverage curves, AURC; review load (% escalated) at chosen τ; missed-critical count.
- **Baseline:** random-review at same load; fixed-rate review. **Metrics:** ECE/Brier, coverage@risk, escalation rate.
- **Expected result type:** calibration curve + a defensible τ with its operating point (e.g., "τ=X yields Y% review load while catching Z of the critical errors" — numbers filled by the actual run, never prewritten).

### Exp-3 — Manual vs AI-assisted workflow (M2 + M4 run; all review)
- **RQ:** Does AI-assisted triage reduce admin decision time and time-to-resolution versus manual triage, at what correction/verification cost?
- **Input:** same seeded case set (≥120 cases balanced across waste types/severities), ≥2 admin participants (team members) × both arms (within-subject, counterbalanced order). **IV:** triage_mode (AI_MODE=off vs on). **DV:** decision time/case, total session time, resolution time (created→resolved from event log), correction count, acceptance rate, error rate (admin final class vs dataset label), p50/p95 latency of AI call.
- **Baseline:** the manual arm; optionally a rule-based (keyword) arm if time allows.
- **Metrics:** medians + distributions (Mann–Whitney or paired tests), plus process-mining cohort comparison from Exp-4.
- **Expected result type:** decision-time savings on AI-assisted arm + acceptance-rate number; honest possibility: no significant difference on resolution time (that is a publishable finding too).

### Exp-4 — Process mining / workflow analysis (M4 leads)
- **RQ:** What is the as-executed process, does it conform to the designed lifecycle, and where do variants/bottlenecks arise (esp. guidance vs dispatch paths, AI-assisted vs manual cohorts, rejection loops)?
- **Input:** event log from seeds + Exp-3 sessions (target ≥500 cases total). **IV:** cohorts (triage_mode, path type, proof rejection). **DV:** fitness, precision, variant frequencies, stage durations, rejection-loop rate.
- **Baseline:** designed model (the state machine) as reference. **Metrics:** fitness/precision (ETConformance), mean/median durations, variant counts.
- **Expected result type:** discovered model figure + conformance/deviation table + cohort timing comparisons.

### Optional Exp-5 — spatial hotspots (only if F12 activates)

---

## 10. DATASET PLAN (realistic for 4 undergraduates)

- **Target size: 2,000 labeled complaints** (minimum viable 1,200). Per class ≥150 for waste_type where possible; hazardous/medical can be ~100 each (report support honestly).
- **Composition:** ~60% authored templates × systematic slot-filling (waste type × context × phrasing register); ~25% paraphrase augmentation (back-translation/LLM rewrite, disclosed); ~15% noisy/realistic (code-mixed Hindi-English, typos, vague texts). Coordinates/timestamps generated separately by the seed script (NOT part of the labeled text dataset).
- **Labels per sample:** waste_type (6), quantity_severity (3), intervention_required (bool). Severity+intervention get explicit annotation guidelines with examples (e.g., "medical waste indoors → intervention=true").
- **Annotators:** the 4 team members, after a 1-hour calibration session on 30 shared examples. **Agreement:** pairwise Cohen's kappa on a 200-case overlap; target κ ≥ 0.7 for waste_type; disagreements adjudicated by discussion, final label = majority. Report κ in the paper — this is what makes the dataset citable.
- **Splits:** 70/15/15 stratified by waste_type × intervention_required; test set locked after Exp-1 model selection; seeds fixed; splits version-controlled.
- **Ethics/disclosure:** fully synthetic + team-authored → no personal data; disclose construction method in the paper (P1 did the same at n=1,000, so n=2,000 team-built is defensible for this level).
- **Effort estimate:** ~3–4 person-weeks total, parallelizable; the single most schedule-critical artifact (everything in Exp-1/2 and the seed script depends on it).

---

## 11. DIVISION OF WORK (4 members)

| Member | Modules owned | Exact tasks | Depends on | Deliverables |
|---|---|---|---|---|
| **M1 Frontend** | Citizen + Admin + Cleaner UI | (1) Complaint form w/ optional location; (2) **Admin queue with AI panel** (prediction, confidence badge, review flag, Accept/Correct, Dispatch/Guidance); (3) Cleaner task view + proof upload; (4) Proof verification screen with reject-reason; (5) Citizen tracking page showing status + guidance | M2's new PATCH + fields | Working UI covering full loop; 6 new screens/panels |
| **M2 Backend/API (you)** | API, workflow, event log, AI hook | §6 additions 1–9; state machine unchanged; new tests; seed script; Exp-3 session tooling (feature flag, session ids) | M3's predict client (week 3) | Extended backend; event log live; ~10 new passing tests; seed generator |
| **M3 AI/ML** | Dataset + models + calibration | §10 dataset pipeline + κ reporting; Exp-1 roster; predict client; Exp-2 calibration + τ recommendation; artifacts registry | Nothing (start week 1) | Labeled dataset v1; 3+ trained models; metrics.json; τ recommendation memo |
| **M4 Integration/DB/Testing/DWM** | Migrations, warehouse, pm4py, QA | event_log DDL + helper with M2; DuckDB ETL (F13); pm4py notebooks (discovery, conformance, variants, timing); Exp-4 report; overall QA + reproducibility pack | M2's event log (week 2–3); seeds (week 4) | pm4py analysis notebooks + figures; warehouse; test report |

**Connection points (weekly syncs):** W2 dataset schema freeze (M3↔M2) · W3 predict-client contract freeze (M3→M2) · W4 event-log vocabulary freeze (M2↔M4) · W5 UI panels against staging backend (M1↔M2) · W6 first full-loop walkthrough on seeds (all) · W7 Exp-3 dry run (all).

---

## 12. FINAL SYSTEM ARCHITECTURE

```
┌──────────────────────────────────────────────────────────────┐
│ FRONTEND (M1) — citizen · admin (AI panel) · cleaner screens │
└──────────────────────────┬───────────────────────────────────┘
                           │ REST (JWT)
┌──────────────────────────▼───────────────────────────────────┐
│ BACKEND FastAPI (M2)                                         │
│  auth · complaints · admin · cleaner routers (existing)      │
│  + ai-decision PATCH · + event-log helper · + AI hook        │
│      │ synchronous predict call (fail-open)                  │
│      │                    ┌ state machine VALID_TRANSITIONS  │
└──────┼────────────────────┼─────────────────────────────────┘
       │                    │
┌──────▼───────────┐  ┌─────▼──────────────────────────────┐
│ AI SERVICE (M3)  │  │ SQLITE (OLTP)                      │
│ B1/B2/M1/M2/M3   │  │ users · complaints(+ai fields) ·   │
│ model registry   │  │ complaint_ai_outputs · ai_corrections│
│ τ from Exp-2     │  │ cleanup_tasks · cleanup_proofs ·   │
└──────────────────┘  │ responses · EVENT_LOG              │
                      └─────────┬──────────────────────────┘
                                │ nightly ETL
                      ┌─────────▼──────────────────────────┐
                      │ DUCKDB WAREHOUSE (M4, F13)         │
                      │ star schema                        │
                      └─────────┬──────────────────────────┘
                                │
                      ┌─────────▼──────────────────────────┐
                      │ PM4PY ANALYTICS (M4)               │
                      │ discovery · conformance · variants │
                      │ timing · HITL metrics              │
                      └────────────────────────────────────┘

HUMAN TOUCHPOINTS: admin (review, accept/correct, dispatch/guidance,
verify proof) · cleaner (execute, proof) · citizen (submit, track).
AI TOUCHPOINTS: submission-time triage only; never autonomous.
```

---

## 13. WHAT WE SHOULD **NOT** BUILD

1. **AI proof-photo analysis** (F15) — new model class + dataset, zero gap support; would consume M3's entire budget. Phase 4 idea.
2. **Department routing / multi-department model** — no departments exist in the waste flow; legacy classifier's dept concept should not be ported.
3. **Sentiment/urgency-from-text modeling** — severity label already carries it.
4. **Active-learning loop** (F14) — P13 exists; P14 shows marginal value. At most: mention in future work.
5. **Mobile app, SMS/notifications, chatbot, multilingual UI** — every one is a distraction from the four experiments.
6. **Route optimization / nearest-cleaner algorithms** — optimization research is a different paper; manual assignment + reassignment logging suffices.
7. **Authentication upgrades (OAuth, refresh tokens)** — current JWT/bcrypt is adequate; security hardening is not our contribution.
8. **Microservices rewrite, Docker orchestration, k8s** — in-process AI service + FastAPI monolith is the right scale; latency budget (<1 s) is trivially met locally.
9. **Blockchain/IoT/bin sensors** — trendy, unconnected to G1–G4.
10. **Extending the app_state blob API** — deprecate.
11. **Real-deployment pilots with actual citizens** — out of scope; our claims are controlled-environment claims (say so in limitations).

---

## 14. FINAL RESEARCH CONTRIBUTION

**Main contribution (1):**
An **end-to-end, process-mining-evaluated integration of confidence-calibrated AI triage into a municipal waste-complaint resolution workflow** — the first located system in which text triage, calibrated escalation, the dispatch-vs-guidance intervention decision, verified field execution (photo proof), and workflow-level evaluation form one instrumented loop addressing G1–G4 simultaneously.

**Supporting contributions (4):**
1. **S1 (G2):** An evidence-based escalation policy — calibration analysis (ECE/risk–coverage) of model confidence on waste triage replacing an arbitrary threshold, with a documented τ-selection procedure tied to critical-error targets.
2. **S2 (G3):** An event-log schema + controlled activity vocabulary for complaint-resolution workflows with verified field execution, enabling conformance checking against the designed lifecycle (pm4py).
3. **S3 (G4):** A controlled within-system evaluation protocol (manual vs AI-assisted arms with counterbalancing, decision-time and correction metrics, Exp-3) — the "does the AI actually help the workflow?" experiment the located literature lacks.
4. **S4 (dataset):** A labeled, κ-reported, publicly describable waste-complaint dataset (2,000; 6-class type + severity + intervention) — the domain text dataset the literature lacks (waste AI is vision-dominated).

**Main research question (1):**
**RQ-Main:** In a human-in-the-loop waste-complaint resolution workflow, does confidence-based AI triage — with uncertain cases escalated to human review — measurably improve end-to-end workflow performance (decision time, resolution time, review burden) without sacrificing classification correctness, compared with fully manual triage?

**Supporting RQs (4):**
- **RQ1:** How accurately can waste complaints be classified (type, severity, intervention-required), and which model family is best? *(Exp-1)*
- **RQ2:** Is the deployed model's confidence calibrated for triage, and what escalation threshold best balances missed-critical errors against review load? *(Exp-2)*
- **RQ3:** What does the as-executed complaint workflow look like, how does it conform to the designed lifecycle, and which variants/bottlenecks dominate (incl. dispatch-vs-guidance and rejection loops)? *(Exp-4)*
- **RQ4:** How do AI-assisted and manual triage cohorts differ in decision time, correction rate, and resolution time on identical case sets? *(Exp-3)*

Every contribution above is implementable by this team with the §6/§10/§11 plan and evaluable with Exp-1–4. Nothing requires data or permissions we do not have.

---

## 15. FINAL PROJECT DESCRIPTION (the one paragraph)

SmartTrackerAI is a waste-complaint management platform in which every citizen complaint is read by a calibrated AI triage assistant that predicts waste type, severity, and whether a field cleanup or self-disposal guidance is required — attaching a confidence score that automatically routes uncertain or hazardous cases to mandatory admin review while pre-filling high-confidence cases for one-click human confirmation. Admins accept or correct the AI's suggestions (corrections are stored), dispatch cleaners or issue guidance, cleaners upload photo proof of completed cleanups, and admins verify or reject that proof; every state change is written to a structured event log, which a DuckDB warehouse and pm4py pipeline turn into process-discovery models, conformance checks against the designed lifecycle, workflow-variant and bottleneck analyses, and cohort comparisons between AI-assisted and manually triaged cases on identical seeded workloads. We build this because the literature (46 papers reviewed) studies complaint classification, LLM grievance routing, waste analytics, and government process mining separately, but has not evaluated the end-to-end, proof-verified resolution loop with calibrated human escalation (Gaps G1–G4). We will evaluate it with four experiments — model comparison, confidence calibration/escalation-threshold selection, a controlled manual-vs-AI-assisted workflow study, and process-mining analysis — on a 2,000-complaint, κ-reported labeled dataset, so that every claim in the eventual paper is backed by a measurement from the system we built, not by assertion.
