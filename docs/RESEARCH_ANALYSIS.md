# SmartTrackerAI-Pipeline — Technical & Research-Direction Analysis

Date of analysis: 2026-09-28
Scope: full repository review; `backend/` treated as the single source of truth, as instructed.
Verification performed: read every backend file, all AI-module source, current frontend source, git history; ran the backend test suite locally — **10/10 tests pass**.

---

## 1. Overall system purpose (what the code actually says)

Two distinct generations of the project coexist in the repo:

- **Current system (`backend/`, commit `6103b43` "Complete waste management backend workflow"):** a FastAPI + SQLite REST API for **municipal waste-complaint management** with four roles (citizen, cleaner, staff, admin), a state-machine complaint lifecycle, cleaner assignment, photo-proof upload, and admin verification. Its database schema (`complaints` table) has waste-specific fields: `waste_type`, `waste_context`, `quantity_severity`, `recommended_action`, `intervention_required`, `latitude`, `longitude`, `address_text`.
- **Legacy AI module (`ai/`):** an *unintegrated* Gemini-based pipeline for **generic e-commerce customer-support complaints** (categories: billing/technical/delivery/refund/account/other). It is NOT about waste, is NOT imported by the backend, and writes to its own separate SQLite database (`admin_review.db`).
- **Legacy frontend (`frontend/`, current `main` branch):** a TanStack Start "grievance routing & resolution" UI covering only the original 5 endpoints. It has **no waste fields, no map, no cleaner screens, no assignment UI, no proof-verification UI**.

So the honest statement of current purpose is: **a working waste-complaint workflow API whose intelligence (classification, recommendation) exists only as database columns that callers must fill in themselves.**

---

## 2. Complete current workflow (verified in code + tests)

1. Citizen registers (`POST /auth/register`, role forced to `citizen`) and logs in (`POST /auth/login` → JWT HS256, 60 min, bcrypt hashing).
2. Citizen submits a complaint (`POST /complaints/`) with text (10–5000 chars) and *optionally* waste fields and coordinates. Status is hardcoded `pending`, priority hardcoded `medium`. **No AI runs here.**
3. Admin views the queue (`GET /admin/queue`), and assigns a cleaner (`POST /admin/complaints/{id}/assign`) — this creates a `CleanupTask` (status `assigned`, unique `TSK-…` id) and moves the complaint to `in_progress`.
4. Cleaner lists tasks (`GET /cleaner/tasks`), opens task detail with location/instructions (`GET /cleaner/tasks/{task_id}`), uploads a proof photo (`POST /cleaner/tasks/{task_id}/proof`, UUID-named file served from `/uploads/`). Task → `proof_submitted`.
5. Admin verifies or rejects the proof (`POST /admin/proofs/{proof_id}/verify`): approve → task `verified`, complaint → `resolved` (or `closed`); reject → task `rejected`, complaint stays `in_progress`, cleaner can resubmit (proof history is preserved).
6. Alternative path (no intervention needed): admin approves a guidance response (`POST /admin/responses/{id}/approve`) → a `Response` row is stored and the complaint becomes `resolved` directly ("self-disposal guidance" path — the test `test_self_disposal_guidance_path` demonstrates it).
7. All transitions are guarded by `VALID_TRANSITIONS` (pending → in_progress → resolved/closed; closed is terminal) — enforced server-side with 400 on violations.

### Who fills in the intelligence?
The waste fields are **passed through** from the API client. The schema documents the intended semantics (e.g., `quantity_severity`: small/medium/large/hazardous; `intervention_required` decides whether a cleaner task is created or self-disposal guidance is given), but **no code computes them**. In the current implementation a citizen (or the frontend) would have to send `waste_type` and `recommended_action` themselves — and the current frontend doesn't even send them.

---

## 3. Inventory of components

### 3.1 AI / ML / NLP components
| Component | Status | Where |
|---|---|---|
| Waste-type text classification | **NOT FOUND IN CURRENT IMPLEMENTATION** (fields exist, no model) | — |
| Generic customer-support LLM classifier (Gemini, structured JSON output, confidence, retry across models) | Implemented but **legacy/unintegrated**; categories are billing/technical/delivery/refund/account/other | `ai/src/classifier.py` |
| Hybrid retrieval: ChromaDB (all-MiniLM-L6-v2) + BM25 (rank-bm25) + Reciprocal Rank Fusion + cross-encoder rerank (ms-marco-MiniLM-L-6-v2) | Implemented but legacy/unintegrated; corpus = 4 placeholder customer-support policy `.txt` files | `ai/src/retrieval.py`, `ingest.py` |
| Grounded draft-response generation + rule-based citation verification (`[Source: file]` regex check) | Implemented but legacy/unintegrated | `ai/src/generator.py`, `verification.py` |
| Human-in-the-loop escalation: confidence < 0.6 or low retrieval score or unverified citations → `needs_human_review` + reasons | Implemented in the AI module only; backend has a `Response.approve` endpoint but never receives AI output | `ai/src/pipeline.py`, `backend/routers/admin.py` |
| Evaluation harnesses: 20 labeled classifier cases (1 known-ambiguous excluded), 10 retrieval cases, stress tests (empty input, prompt injection, non-English, 500+ words), threshold calibration script | Implemented (legacy module); **no recorded/committed results** | `ai/src/evaluate*.py`, `stress_test*.py`, `calibrate_relevance.py` |
| Waste/proof image recognition | **NOT FOUND IN CURRENT IMPLEMENTATION** | — |
| Language detection / multilingual NLP | **NOT FOUND IN CURRENT IMPLEMENTATION** (only a stored `language` column defaulting to `en`; the AI module has one Hindi stress case) | — |

Important quirks found (useful, honest material for a paper's "limitations" section):
- `ai/src/config.py` hardcodes `PROJECT_ROOT = C:\Users\SwakeetMali\smarttracker-ai` — the module is not portable without edits.
- The AI module's own README and root README both state it is a placeholder needing reconciliation with `backend/`.
- The Gemini model names in `config.py` (`gemini-3.5-flash-lite`, `gemini-3.6-flash`) are free-tier quota-limited (README: ~20 req/day/model).

### 3.2 Data Warehousing / Mining components
- **All analytics: NOT FOUND IN CURRENT IMPLEMENTATION.** No statistics endpoints, no dashboards beyond counts computed client-side in the admin UI, no clustering, no association rules, no time-series, no star schema, no ETL, no OLAP.
- What *does* exist is raw material for DWM: relational schema with 6 tables, timestamped lifecycle events (`created_at`, `assigned_at`, `completed_at`, `verified_at`, `approved_at`), role/actor columns, geo-coordinates, waste-type and severity fields — i.e., a clean event log waiting to be extracted.

### 3.3 Software Engineering components
- Layered monolith: routers (auth/complaints/admin/cleaner/app_state) → SQLAlchemy ORM → SQLite; Pydantic v2 request/response validation; FastAPI auto-docs (`/docs`).
- Security: bcrypt hashing, JWT with `sub`/`role`/`exp`, constant-time login failure (email-enumeration resistance), self-promotion blocked at registration (`role` ignored → `citizen`), three RBAC dependency guards, object-level authorization (owner / assigned-cleaner / admin checks), CORS allow-list from env.
- Schema evolution: idempotent `run_migrations()` that adds missing columns/tables to existing SQLite files without data loss (covered by a dedicated test on a legacy DB with a pre-existing row).
- Single-row `app_state_snapshots` API (validated JSON blob, revision counter, duplicate-ID and 5 MB limits) that persists the frontend prototype's SRS entities that have no relational tables yet — an explicit interim persistence design, documented in code.
- Testing: **10 pytest tests, all passing**: end-to-end workflow (citizen→assign→proof→verify→resolved), proof rejection + resubmission history, self-disposal path, invalid state transition returns 400, role-boundary matrix (citizen vs cleaner vs cleaner2 vs admin), legacy-DB migration idempotency, app-state round trip + duplicate rejection + CORS preflight, auth+complaint+admin integration.
- CI/CD, linting for backend, load tests, monitoring: NOT FOUND IN CURRENT IMPLEMENTATION.

---

## 4. Database schema (source of truth: `backend/models.py`)

| Table | Key fields | Notes |
|---|---|---|
| `users` | id, name, email (unique), password_hash, role (`citizen`/`cleaner`/`staff`/`admin`), department, created_at | staff role exists but has no dedicated endpoints |
| `complaints` | id, `tracking_id` (`TRK-xxxxxxxx` unique), user_id FK, name/email/phone (denormalized), complaint_text, language, priority, status, department, **waste_type, waste_context, quantity_severity, recommended_action, intervention_required**, latitude, longitude, address_text, created_at, updated_at | waste/location fields nullable — the AI gap |
| `responses` | id, complaint_id FK, response_text, approved_by FK, approved_at | admin-approved citizen-facing replies |
| `cleanup_tasks` | id, `task_id` (`TSK-xxxxxxxx` unique), complaint_id FK (unique 1:1), assigned_cleaner_id FK, status (`assigned`/`in_progress`/`proof_submitted`/`verified`/`rejected`), assigned_at, completed_at, notes | |
| `cleanup_proofs` | id, task_id FK, image_url, uploaded_by FK, uploaded_at, verification_status (`pending_verification`/`verified`/`rejected`), verified_by, verified_at, rejection_reason | full proof history kept |
| `app_state_snapshots` | id=1, payload JSON, revision, updated_at | frontend prototype persistence |

### API endpoint inventory (current backend)
- `GET /`, `GET /health`
- `POST /auth/register`, `POST /auth/login`
- `POST /complaints/`, `GET /complaints/my`, `GET /complaints/{tracking_id}`
- `GET /admin/complaints`, `PUT /admin/complaints/{id}`, `GET /admin/queue`, `GET /admin/queue/{tracking_id}`, `POST /admin/responses/{id}/approve`, `POST /admin/complaints/{id}/assign`, `POST /admin/proofs/{proof_id}/verify`
- `GET /cleaner/tasks`, `GET /cleaner/tasks/{task_id}`, `POST /cleaner/tasks/{task_id}/proof`
- `GET /app/state`, `PUT /app/state`

### Measurable outputs / metrics already available
- Backend: pytest suite (10 tests) — can report pass rate, and later coverage/mutation score.
- AI module: evaluation *harnesses* exist, but **no committed numeric results** — any accuracy figure in a paper would have to come from experiments you run yourselves. NOT FOUND: recorded accuracies, dataset statistics, latency measurements, user-study data.

---

## 5. Feature status classification

### A. Actually implemented (backend, verified by tests)
Auth/JWT/bcrypt/RBAC; complaint CRUD subset; tracking IDs; state-machine lifecycle with 400-guard; admin queue + updates; response approval; cleaner assignment (role-checked); cleanup task lifecycle; proof upload + verify/reject + resubmission history; file storage with UUID names; static upload serving; CORS config; idempotent migrations; app-state snapshot API; dev admin seeding; 10 passing tests.

### B. Partially implemented
1. **Waste intelligence** — schema and workflow semantics exist (`intervention_required` decides cleaner-vs-guidance path; tests demonstrate both paths), but nothing computes the fields; frontend never sends them. This is the single biggest gap and the biggest opportunity.
2. **AI triage pipeline** — fully coded in `ai/` but for the *wrong domain* (customer support), unintegrated, non-portable config path, no recorded evaluation results.
3. **Frontend** — functional for the legacy grievance flow (5 endpoints), but does not cover waste fields, map, cleaner, or proof-verification screens; `AdminQueueItem` carries AI fields (`classification`, `ai_draft`, `evidence`) as always-empty placeholders.
4. **Location** — lat/long + address stored and shown to cleaners; no geocoding, no map rendering, no distance/zone logic, no spatial queries.

### C. Planned / missing (nothing in code)
Automatic waste classification; disposal-recommendation engine; priority computation (hardcoded `medium`); department auto-routing (`department` stays null in the waste flow); auto/nearest cleaner assignment (admin hand-picks); hotspot analytics; any data warehouse; duplicate-complaint detection (`duplicate_of` field exists in the legacy schema shape only, always null); notifications; image verification of proof photos; multi-language complaint processing; performance/load benchmarks; deployment story.

### D. Outdated artifacts (do not cite as current features)
- `ai/` module (customer-support domain, separate DB, hardcoded path) — legacy Phase-2 work.
- Current `frontend/` screens (grievance UI; branch history shows it predates the waste redesign).
- Remote branches `Before-Connection_1`, `Database`, `phase2-ai-improvements` — not `main`.

---

## 6. Can this become a genuine research contribution?

Yes — but **not** by describing the software. The contribution must come from measuring and improving the loop the backend already models. Three facts make a real research angle possible:

1. The system already encodes a **two-path triage decision** (`intervention_required` → cleaner task vs self-disposal guidance) and a **human-in-the-loop verification chain** (proof review, response approval, state machine). That is exactly the structure human-in-the-loop AI research studies — you just have no model feeding it yet.
2. The backend already produces a **timestamped, role-attributed event log** (submit → assign → proof → verify, with rejections) — exactly the input process mining and queue-time analytics need.
3. The legacy AI module contains **a real, non-trivial retrieval architecture (hybrid BM25+vector+RRF+cross-encoder) and a calibration script that found threshold scores overlap** — a concrete, honest empirical finding you can build a rigorous evaluation around after retraining it for the waste domain.

What is *not* a contribution: restating the CRUD API, or claiming AI features that the repository does not contain.

---

## 7. Candidate research contributions per subject

### AI
- **Waste-complaint text classification** into your existing schema's labels (`waste_type`, `quantity_severity`, binary `intervention_required`) with **calibrated confidence driving the `needs_human_review` escalation**. The confidence-threshold mechanism already exists in code; the research is whether self-assessed LLM confidence is trustworthy enough to route work away from humans, versus a fine-tuned small model with proper calibration.
- **Grounded disposal-guidance RAG over a small corpus** of municipal disposal rules (dry/wet/e-waste/medical/hazardous), comparing retrieval configurations and measuring citation groundedness with the already-written verifier.
- **Selective prediction / risk–coverage analysis** of the human-review threshold: plot coverage vs error as the 0.6 threshold moves; find the operating point.

### DWM
- **Process mining on the system's own event log**: discover the real process model, check conformance against the `VALID_TRANSITIONS` state machine, analyze variants (cleaner path vs guidance path vs rejected-proof loops) and per-stage cycle times (assign→proof, proof→verify).
- **Spatio-temporal hotspot mining**: DBSCAN/HDBSCAN clustering + kernel density over complaint coordinates; weekly/seasonal patterns; ward-level roll-ups.
- **Association/decision mining**: which (waste_type, context, severity, time, location) combinations predict `intervention_required = true` and proof rejection.
- **A small data warehouse**: star schema (fact_complaint_events; dims: time, location/ward, waste_type, actor/role, status) with ETL from SQLite, feeding both the AI evaluation and process mining.

### SE
- **Empirical evaluation of the human-in-the-loop workflow**: does AI-assisted triage (pre-filled waste fields + drafted guidance) reduce admin decision time and time-to-resolution versus manual triage, in a controlled simulation/user study with the real API?
- **Executable RBAC conformance + mutation testing**: the role-boundary test matrix as an executable specification of the security requirements; measure test strength via mutation testing of the permission matrix.
- **Architecture case study**: monolith + LLM sidecar integration pattern, with the integration gap (three unconnected stores) documented as the empirical subject; idempotent-migration approach for zero-downtime SQLite schema evolution.

---

## 8. Proposed research topics (all supportable by the current system + planned additions)

Legend for difficulty: L = low, M = moderate, H = high (for a 3rd-year CE student).

---

### T1. "LLM-Assisted Triage of Municipal Waste Complaints: Is Self-Assessed Confidence Trustworthy for Human-Review Escalation?" (AI)
- **Research problem:** The system's escalation gate (`confidence < 0.6` → human review) currently trusts an LLM's self-reported confidence. No evidence exists that this confidence is calibrated for waste-complaint text.
- **Research gap:** LLM self-confidence calibration is mostly studied on general benchmarks, not on domain-specific civic-complaint routing where misrouting has operational cost (wrong disposal guidance vs unnecessary truck dispatch).
- **Research question:** RQ1 — How accurate is an LLM zero-shot classifier for waste type/severity/intervention? RQ2 — Is its self-assessed confidence calibrated (ECE), and does threshold-based escalation beat random/fixed-rate human review?
- **Contribution:** A labeled waste-complaint dataset + calibration analysis + an evidence-based escalation threshold replacing the current guess of 0.6.
- **Experiment:** Label N≈1,500–3,000 complaints (authored + augmented + optionally anonymized real ones); run zero-shot LLM vs baselines; compute accuracy/macro-F1/ECE; sweep threshold; risk–coverage curves.
- **Dataset needed:** your own labeled corpus (see §10.1); optionally seed from public waste-management corpora if licensing permits.
- **Baselines:** keyword/rule baseline; TF-IDF + LogisticRegression/SVM; fine-tuned DistilBERT/IndicBERT; majority-class.
- **Metrics:** accuracy, macro-F1, per-class F1, confusion matrix, ECE/Brier, coverage@threshold, review precision/recall.
- **Expected results (hypotheses, not claims):** fine-tuned small model beats zero-shot LLM on macro-F1; LLM confidence is overconfident on rare classes (hazardous/medical); escalation threshold far from 0.6.
- **Difficulty:** M (dataset construction is the bottleneck; modeling itself is standard).

### T2. "Grounded Disposal-Guidance Generation for a Small Policy Corpus: Hybrid Retrieval and Citation Verification in a Civic Chatbot" (AI)
- **Research problem:** Citizens need correct disposal guidance; hallucinated guidance is harmful; retrieval must work over a *tiny* corpus (dozens of rules), where dense retrieval is known to behave oddly.
- **Research gap:** RAG literature targets large corpora; small-corpus municipal guidance with citation verification is underexplored, and your calibration script already showed score overlap between correct/wrong matches — a genuine empirical hook.
- **Research question:** Does hybrid BM25+vector+RRF (+cross-encoder) beat either method alone on small-corpus retrieval, and can an automatic citation verifier catch ungrounded claims?
- **Contribution:** Controlled comparison + groundedness measurement using the repo's existing verifier, on a corpus you author from municipal solid-waste rules.
- **Experiment:** Build 30–80 disposal rules; 50–100 query set with expected-rule labels; ablate retrieval configs (BM25-only, vector-only, RRF, RRF+rerank); measure hit@k/MRR; run generation and measure citation validity + human-judged faithfulness on a sample.
- **Dataset:** self-authored rules + labeled queries (feasible for undergrads; disclose authorship).
- **Baselines:** BM25-only, vector-only, RRF, RRF+cross-encoder (all already implemented — the ablation is nearly free).
- **Metrics:** hit@1/3, MRR, citation validity rate, faithfulness rating, latency.
- **Expected results (hypotheses):** hybrid wins on keyword-heavy queries (bin codes, waste names); cross-encoder matters little at this corpus size — a publishable negative/positive finding either way.
- **Difficulty:** M.

### T3. "Process Mining a Municipal Waste-Complaint Workflow: Conformance Checking of an AI-Assisted Lifecycle" (DWM)
- **Research problem:** The documented lifecycle (`VALID_TRANSITIONS`) and the real executed process may diverge (rejected proofs, reassignments, guidance shortcuts).
- **Research gap:** Process mining is usually applied to hospital/banking logs; civic waste workflows with photo-proof verification are rare; you can generate the log from your own instrumented system.
- **Research question:** What process variants emerge in simulated/pilot operation, do they conform to the specified state machine, and which stages dominate cycle time?
- **Contribution:** Event-log schema + discovered models (Alpha/Heuristics/Inductive miner via `pm4py`) + conformance metrics + variant analysis pre/post AI triage.
- **Experiment:** Add an `event_log` table (actor, action, entity, timestamp) — small change; run a seeded population + pilot; mine models; compute fitness/conformance; compare variants.
- **Dataset:** system-generated event log (this is legitimate primary data — you created the system); size target ≥ 500 cases.
- **Baselines/comparisons:** specified model vs discovered model; pre- vs post-AI-triage cohorts.
- **Metrics:** fitness, precision (ETConformance), variant counts, mean stage durations, rejection-loop frequency.
- **Expected results (hypotheses):** most deviations cluster in proof resubmission loops; AI triage shortens the pre-assignment segment (must be measured, not assumed).
- **Difficulty:** L–M (tooling exists; the engineering is the event log + seeds).

### T4. "Spatio-Temporal Hotspot Mining of Citizen Waste Reports" (DWM)
- **Research problem:** Municipalities need *where/when* to pre-position cleanup capacity; the system already stores coordinates and timestamps.
- **Research gap:** Hotspot studies usually use municipal open data alone; a citizen-report stream with severity labels enables severity-weighted hotspot analysis — few undergraduate-scale studies combine both.
- **Research question:** Can DBSCAN/HDBSCAN + kernel density on complaint coordinates identify stable weekly hotspots, and does `quantity_severity` weighting change the identified clusters?
- **Contribution:** Hotspot pipeline + ward-level temporal analysis integrated into the existing DB (a `analytics/` service + notebook).
- **Experiment:** Seed synthetic-but-realistic coordinates (or use open municipal data if legally usable); run clustering with parameter sweeps; stability analysis across weeks; optional forecast (weekly counts, STL decomposition).
- **Dataset:** seeded/pilot coordinates; disclose synthesis clearly.
- **Baselines:** grid-count heatmaps vs DBSCAN vs HDBSCAN; unweighted vs severity-weighted.
- **Metrics:** cluster stability (Jaccard across weeks), silhouette, coverage of "hazardous" reports inside hotspots.
- **Expected results (hypotheses):** severity weighting merges small clusters into fewer actionable zones.
- **Difficulty:** L–M.

### T5. "Does AI Triage Reduce Resolution Time? An Empirical Study of Human-in-the-Loop Complaint Management" (SE + AI)
- **Research problem:** The system adds AI triage and auto-drafted guidance in front of human admins; whether that actually reduces admin workload/resolution time is an empirical question.
- **Research gap:** HITL studies rarely measure end-to-end workflow time on a *running system* with a state machine and proof verification; most are annotation studies.
- **Research question:** RQ1 — Does pre-filled classification reduce admin time-to-assign? RQ2 — Does auto-drafted guidance reduce response-editing time without hurting correctness? RQ3 — What is the extra verification cost of wrong AI suggestions?
- **Contribution:** A controlled experiment protocol using your real API: two cohorts of simulated admin sessions (with/without AI suggestions), same case load, measure task time, edit distance on drafts, error rates; plus API latency overhead of the AI step.
- **Experiment:** within-subject design, ≥ 2 admins × ≥ 30 cases per arm; log all interactions; optionally Locust load test to isolate AI latency overhead.
- **Dataset:** seeded case set + interaction logs from sessions.
- **Baselines:** manual triage; rule-based triage (keyword) as a second arm.
- **Metrics:** time-to-first-action, time-to-resolution, draft acceptance rate (edit distance), error rate (wrong disposal guidance), system latency p50/p95.
- **Expected results (hypotheses):** meaningful time savings on the assignment step; acceptance rate of drafts is the interesting variable — it may be low, which is a finding.
- **Difficulty:** M (study design discipline needed; no new modeling).

### T6. "From Requirements to Executable Authorization: Mutation-Tested RBAC in a Civic Complaint API" (SE)
- **Research problem:** RBAC requirements (citizen/cleaner/admin boundaries) are security-critical; test suites often look thorough while being weak.
- **Research gap:** undergraduate-level empirical SE studies on RBAC test adequacy via mutation testing are scarce and very doable.
- **Research question:** What proportion of RBAC mutants does the current suite kill, and which requirement clauses are under-tested?
- **Contribution:** A mapping from SRS requirements → the existing role-boundary tests → mutation score; improved tests for gaps found.
- **Experiment:** instrument `get_current_admin_user` / `get_current_cleaner_user` / object-level checks with mutants (e.g., `mutmut`); run suite; analyze surviving mutants; add tests; re-measure.
- **Dataset:** not applicable (code-based study).
- **Baselines:** line coverage vs mutation score as adequacy indicators.
- **Metrics:** mutation score, coverage, tests added, killed/surviving mutant categories.
- **Expected results (hypotheses):** high line coverage with lower mutation score on permission edge cases (e.g., staff role currently unguarded in endpoints).
- **Difficulty:** L–M.

### T7. "A Lightweight Data Warehouse for Complaint Analytics in Resource-Constrained Civic Systems" (DWM)
- **Research problem:** SQLite OLTP data is not query-friendly for analytics; municipalities with tiny infrastructure need a minimal DW.
- **Research gap:** DW literature assumes enterprise stacks; a SQLite→DuckDB star-schema pipeline with OLAP queries serving both hotspot and process-mining studies is a compact, practical contribution.
- **Research question:** Can a 5-table star schema (fact_complaint_events; dims: date/time, ward/location, waste_type, actor/role, status) answer the analytics needs (hotspots, cycle time, variant mix) with < 10 queries and no server?
- **Contribution:** schema + ETL script + documented query suite + an example dashboard feeding T3/T4.
- **Experiment:** implement ETL; run representative OLAP queries (drill-down ward→zone, rolling weekly counts, stage-duration rollups); document refresh strategy.
- **Dataset:** your event/complaint data (seeded + pilot).
- **Baselines:** raw SQLite queries vs warehouse queries (clarity/maintainability comparison, plus query-time benchmarks at realistic scale).
- **Metrics:** query set completeness, refresh time, benchmark timings, correctness vs hand-written SQL on OLTP.
- **Expected results (hypotheses):** warehouse simplifies analytics and scales fine to 10⁵–10⁶ rows on a laptop.
- **Difficulty:** L.

### T8. "Closing the Loop: An AI-Assisted, Process-Mined Waste-Complaint Management Platform" (integrated AI + DWM + SE)
- The synthesis paper: system + T1 (classifier with calibrated escalation) + T3 (event-log process mining as the evaluation instrument) + T5 (empirical workflow study) — one coherent research problem: **"In a human-in-the-loop waste-complaint system, does AI-assisted triage measurably improve the process — and how do we know?"** (see §9).

---

## 9. One integrated paper or three separate papers?

**Recommendation: ONE integrated core paper, with optional small satellite write-ups only if your syllabus demands per-subject deliverables.**

Reasoning from the code, not from the fact that there are three subjects:
- The three subject areas are **not independent contributions** here. The DWM work (event log, hotspots, DW) has no standalone algorithmic novelty — its value is as the *evaluation instrument* for the AI change. The SE work (empirical workflow study, test adequacy) likewise studies *the same loop* the AI sits in. Pulling them apart yields one thin AI paper, one descriptive DWM paper ("we clustered our own seeded data"), and one small SE paper — each weak alone, strong together.
- Technically they form one causal chain: classifier output → `intervention_required` → assignment → proof → verification → event log → process-mining evaluation → empirical workload study. That is a single research problem with three analytical lenses, i.e., a textbook integrated-paper structure: Architecture/SE section, AI method section, DWM evaluation section.
- Practical safeguard: if your subjects require separate submissions, keep **one shared experimental setup and dataset**, and let each paper take one lens with honest cross-referencing — do not split the contribution into three pretended novelties.

---

## 10. What must be ADDED to the project to make research legitimate

Priority order (1–3 are prerequisites for almost every topic):

1. **A labeled waste-complaint dataset (the critical missing asset).** 1,500–3,000 complaint texts labeled with `waste_type` (e.g., dry/wet/e-waste/medical/hazardous/bulk), `quantity_severity` (small/medium/large/hazardous), and `intervention_required` (bool). Construction protocol: author a seed set from municipal SWM rules; augment (paraphrase, code-mixed Hindi-English variants, noisy text); have 2–3 teammates annotate independently; report inter-annotator agreement (Cohen's kappa) and resolve disputes — this makes the dataset citable and honest. Disclose that part/all data is constructed.
2. **Integrate a classifier into `POST /complaints/`** (in-process scikit-learn/transformers model or a small sidecar service), storing outputs (`predicted_waste_type`, `confidence`, `model_version`, `intervention_suggested`) in the complaints row or a `complaint_ai_outputs` table. Persisting model version + confidence is what makes later evaluation and ablation possible.
3. **An `event_log` table + logging middleware** (actor_id, action, entity_type, entity_id, timestamp, meta JSON). ~a day of work; unlocks T3, T5, T7.
4. **Evaluation harness in the backend repo** that runs the classifier on the held-out test set and writes a results JSON (accuracy, macro-F1, confusion matrix, ECE) — reuse the pattern already present in `ai/src/evaluate.py`.
5. **Baseline models**: TF-IDF + LogisticRegression/SVM and a fine-tuned DistilBERT-class model, so the LLM is compared, not asserted.
6. **Seed-data generator** (script producing realistic users/complaints/tasks/events, geo-distributed over a city grid) to reach the case volumes mining needs.
7. **Disposal-guidance corpus + RAG evaluation** (T2): 30–80 rules from published municipal SWM guidelines (public rules are facts, cite them as sources — do not cite us), 50–100 labeled queries.
8. **Analytics service / notebooks**: DBSCAN/HDBSCAN hotspot pipeline, weekly time-series, association-rule mining on structured fields; a DuckDB star-schema ETL.
9. **Optional image component** (only if time permits): an *assistive* proof-photo checker (blur/duplicate/empty-bin heuristics with a pretrained model) — clearly framed as decision support for the human verifier, never as autonomous fraud detection.
10. **Ops/benchmarking**: Locust load-test script + latency middleware (p50/p95 per endpoint) to support the SE empirical claims and the "lightweight stack" argument.

Explicit non-goals (do not claim these anywhere): deployed municipal usage, real user studies with actual citizens, production accuracy numbers, security audit, scalable image fraud detection.

---

## 11. Explicit "NOT FOUND IN CURRENT IMPLEMENTATION" register

- Waste-type classification (any model, rule, or LLM call in the request path)
- Disposal-recommendation *generation* (field exists; content is caller-supplied)
- Priority computation (hardcoded `"medium"`)
- Department auto-routing (stays `null` in the waste flow)
- Automatic/nearest cleaner assignment (admin hand-picks by ID)
- Geocoding, map rendering, distance computation, spatial indexing
- Any analytics, data mining, dashboards, star schema, ETL, OLAP
- Image analysis of proof photos (upload + human verify only)
- Duplicate-complaint detection (`duplicate_of` only in legacy schema shape, always null)
- Notifications, email/SMS
- Recorded AI evaluation results (harnesses exist; no committed numbers)
- Backend CI, linting config for backend, load tests, monitoring
- Multilingual processing beyond storing an ISO code (AI module has one Hindi stress case, unintegrated)

---

## 12. MY RECOMMENDED RESEARCH DIRECTION

**Direction: "Evidence-based AI triage for a human-in-the-loop waste-complaint system — evaluated by process mining on the system's own event log."**

Concretely, the most realistic path for a 3rd-year team, in build order:

1. **Build the labeled dataset and a small, honest classifier** (TF-IDF baseline + one fine-tuned small transformer; LLM zero-shot as comparison), wired into complaint submission with persisted confidence and model version. Replace the guessed 0.6 escalation threshold with an evidence-based one from risk–coverage analysis. *(AI core — T1.)*
2. **Instrument the workflow** (`event_log` table) and **seed/pilot** the system to ≥ 500 cases. Use `pm4py` to discover the real process, check conformance against `VALID_TRANSITIONS`, and compare the cleaner-path vs guidance-path variants and pre/post-AI-triage cycle times. *(DWM core — T3, with T4/T7 as optional enrichments if time allows.)*
3. **Run a small controlled study** of admin triage with vs without AI suggestions on the real API (time-to-decision, draft acceptance, error rate), plus mutation-tested RBAC as the SE rigor component. *(SE core — T5 + T6.)*
4. Write it as **one integrated paper** (structure per §9) with a fully honest limitations section: constructed dataset, no field deployment, free-tier LLM, unintegrated legacy module documented as such.

Why this is the right direction: every claim it makes is *measurable with artifacts you will actually have* (a labeled dataset, stored predictions, an event log, session logs, a mutation score) — which is exactly what separates a research paper from a project report. And every component it needs either already exists in the repo (state machine, RBAC, proof loop, retrieval code to adapt, evaluation harness patterns) or is a bounded addition from the §10 list.
