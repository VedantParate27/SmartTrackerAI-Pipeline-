# SmartTrackerAI — Backend Integration Contracts (Phase 3)

Audience: M1 Frontend · M3 AI/ML · M4 DWM/Testing. The backend is the contract owner.
All endpoints require `Authorization: Bearer <jwt>` unless noted. Roles: `citizen`, `cleaner`, `admin`.
Everything in this document is implemented and covered by tests in `backend/tests/test_research_layer.py`.

---

## 0. Taxonomy (breaking change for all clients)

Waste fields are now **validated against a closed vocabulary** (backend/taxonomy.py):

| Field | Allowed values |
|---|---|
| `waste_type` | `dry`, `wet`, `e_waste`, `medical`, `hazardous`, `bulk` |
| `quantity_severity` | `small`, `medium`, `large` |

Free-text values like `"E-waste"` now return **422**. Severity is 3 levels; hazard is expressed
through `waste_type` (no separate 4th severity level). Priority is **derived** by the backend
(hazardous→urgent, medical→high, large+intervention→high, large→medium, small→low, else medium)
— clients must not send priority.

---

## 1. For the AI team (M3)

The backend never generates predictions. You push **real model output**:

```
POST /admin/complaints/{complaint_id}/ai-output     (admin/service-account JWT)
{
  "waste_type_pred": "e_waste",            # optional but expected (taxonomy value)
  "severity_pred": "large",                # optional (small|medium|large)
  "intervention_required_pred": true,      # optional bool
  "confidence": 0.91,                      # optional 0..1; null => escalated as missing_prediction
  "model_name": "distilbert-waste-triage", # required
  "model_version": "1.0.0",                # required
  "threshold_used": 0.7,                   # optional, default 0.7
  "latency_ms": 240                        # optional
}
-> 201 { ..., "escalated": true|false, "escalation_reason": "low_confidence|hazardous_waste|missing_prediction" }
```

**Escalation rule (implemented in backend/triage.py, single source of truth):**
escalate iff `confidence < threshold` OR `waste_type_pred in {medical, hazardous}` OR
`confidence/waste_type missing`. The rule is unit-testable: `triage.decide_escalation(...)`.

`GET /admin/complaints/{id}/ai-output` → history of predictions (append-only; re-predictions allowed).

Seeded demo data may contain outputs with `model_name="seed_simulated_triage"` — these are
**placeholders for workflow testing, not research results**.

---

## 2. For the frontend (M1)

### Changed
- `POST /complaints/` — waste fields validated (§0); priority now derived server-side.
- Complaint responses (`/complaints/{id}`, `/complaints/my`, `/admin/queue`) now also carry:
  `triage_mode` (`manual`|`ai_assisted`|null), `review_required`, `review_reason`,
  `resolved_at`, `source` (`citizen`|`seed`).
- `PUT /admin/complaints/{id}` — setting status `resolved`/`closed` now also sets `resolved_at`.

### New — the admin AI panel (one call)
```
POST /admin/complaints/{complaint_id}/ai-decision
{
  "waste_type": "hazardous",            # the HUMAN decision (taxonomy value)
  "quantity_severity": "large",
  "intervention_required": true,
  "decision": "dispatch" | "guidance",
  "guidance_text": "...",               # required iff decision=guidance
  "notes": "...",                       # optional
  "corrections": [                      # optional, for fields with NO ai output
    {"field_name": "waste_type", "ai_value": null, "admin_value": "hazardous"}
  ]
}
-> 200 AIDecisionResponse:
{ tracking_id, triage_mode, review_completed, decision, waste_type, quantity_severity,
  intervention_required, priority, status, task_id, corrections_recorded,
  acceptance_rate_fields, resolved_at }
```
Semantics: human values are stored on the complaint; each field is compared with the latest AI
output — `human == ai` → acceptance record, `human != ai` → correction record (both stored in
`ai_corrections`); a pending mandatory review is completed and cleared; `decision=dispatch`
moves the complaint to `in_progress` (task is then created via the existing
`POST /admin/complaints/{id}/assign`); `decision=guidance` stores the guidance response and
resolves the complaint. State-machine rules still apply and can return 400.

- `GET /admin/complaints/{id}/corrections` — correction/acceptance history.
- Cleaner app: optional `POST /cleaner/tasks/{task_id}/start` — marks the task `in_progress`
  (frees the `proof_submitted → ...` statuses for the proof flow); emits `task_started`.

### Event log (admin only)
- `GET /admin/events?case_id=&activity=&actor_role=&limit=` — JSON, newest first.
- `GET /admin/events/export` — **pm4py-ready CSV** (`case:concept:name`, `concept:name`,
  `time:timestamp`, actor_id, actor_role, old_value, new_value, meta_json).

---

## 3. For the DWM team (M4)

- `GET /admin/mining/dataset` — JSON: `{fieldnames, count, rows}`; one row per complaint.
- `GET /admin/mining/dataset/export` — same rows as CSV.

**Fieldnames (24):** `complaint_id, tracking_id, waste_type, severity, intervention_required,
latitude, longitude, ward, date, hour, day_of_week, priority, triage_mode, ai_confidence,
ai_model_name, human_review_required, correction_count, cleaner_assigned, proof_attempts,
proof_verified, final_status, resolution_time_seconds, source, is_synthetic`.

**Data-quality contract:**
- `waste_type`/`severity`/`intervention_required` are the **final human-decided** values
  (not raw AI predictions — use `ai_outputs` for those).
- Missing facts are `null`, **never imputed**: un-resolved complaints have
  `resolution_time_seconds=null`; `ai_confidence=null` means no AI output exists.
- `ward` is parsed **only** from an explicit `Ward N` in `address_text` (`ward_3` format);
  coordinates are never converted into wards.
- `is_synthetic=true` ⇔ `source="seed"` — seeder output, always separable from citizen data.
- `correction_count`/acceptance evidence live in `ai_corrections` and the `ai_correction_recorded`
  events; `proof_attempts` counts all uploads; `proof_verified` is true iff ≥1 verified proof
  (null when no task exists).

**Mining targets this supports:** classification (`intervention_required` or `priority` as label),
K-Means/hierarchical clustering (numeric features: lat/long, hour, confidence, resolution time;
categorical one-hot: waste_type, ward, day_of_week), Apriori (transactions over
`waste_type, severity, ward, day_of_week/hour-bucket, triage_mode, review_required, outcome`).
No mining algorithms run in the backend — export and analyze offline.

---

## 4. Seeder (backend only)

```
python seed_data.py --complaints 600 --cleaners 6 --seed 42 [--simulate-triage]
python seed_data.py --wipe          # removes ONLY source='seed' rows
```
- Deterministic (`--seed`); realistic template texts; structured outcome distribution
  (guidance-resolved / dispatch-verified / rejection-loop / open) varying by waste type and ward.
- **Every** seeded row: `source="seed"` (→ `is_synthetic=true` in the export), synthetic emails
  (`@synthetic.local`, non-loginable), and a **full event chain** so process mining works from day one.

---

## 5. Event vocabulary (controlled — for pm4py)

`complaint_created · ai_prediction_generated · human_review_required · human_review_completed ·
admin_decision_made · dispatch_decided · guidance_decided · cleaner_assigned · cleaner_reassigned ·
task_started · proof_submitted · proof_verified · proof_rejected · complaint_resolved ·
complaint_closed` + extensions `complaint_updated`, `ai_correction_recorded`.

Event fields: `event_id, case_id (TRK id), activity, actor_id, actor_role
(citizen|ai_system|admin|cleaner|system), timestamp (UTC), old_value, new_value, meta_json`.

---

## 6. Database changes

New tables: `ai_outputs`, `ai_corrections`, `event_log`.
New `complaints` columns: `triage_mode`, `review_required`, `review_reason`, `source`,
`resolved_at` (+ `waste_context` previously undocumented).
Migration is generalized and idempotent (`database.run_migrations` adds any missing column on
any declared table at startup). Verified on a copy of the legacy DB: rows preserved, second run
is a no-op. **Frontend contract note:** `AdminQueueItem.ai_draft`/`classification` etc. remain
placeholders; real AI data now flows through the dedicated endpoints above.

**Known breaking change:** clients sending non-taxonomy waste values now get 422.
