# tests/test_research_layer.py
# Tests for the Phase-3 research layer:
#   1.  complaint creation still works (+ event logged)
#   2.  AI output can be stored (ingest endpoint)
#   3.  low-confidence complaint is marked for human review
#   4.  hazardous complaint is escalated
#   5.  admin can accept/correct AI prediction (ai-decision endpoint)
#   6.  dispatch path works
#   7.  guidance path works
#   8.  event log is generated (incl. process-mining export shape)
#   9.  mining dataset/export contains the required fields
#   10. seeded records can be generated (marked synthetic)
#   11. existing workflow still passes (covered by the other suites, but the
#       core invariants are re-asserted here against the migrated schema)

import io
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from test_app_state import TestingSessionLocal, client  # noqa: E402

from models import AICorrection, AIOutput, Complaint, EventLog, User  # noqa: E402
from triage import decide_escalation  # noqa: E402
from taxonomy import compute_priority  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _register_and_login(email, password="Password123!"):
    register = client.post("/auth/register", json={
        "name": "Test User", "email": email, "password": password,
    })
    assert register.status_code == 201
    user_id = register.json()["id"]
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return user_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


def _promote_to_admin(user_id):
    with TestingSessionLocal() as db:
        db.query(User).filter(User.id == user_id).one().role = "admin"
        db.commit()


def _create_complaint(headers, **overrides):
    payload = {
        "complaint_text": "Overflowing garbage bins near the market need collection.",
        **overrides,
    }
    response = client.post("/complaints/", headers=headers, json=payload)
    assert response.status_code == 201
    return response.json()


def _complaint_db_id(tracking_id):
    with TestingSessionLocal() as db:
        return db.query(Complaint).filter(Complaint.tracking_id == tracking_id).one().id


# ---------------------------------------------------------------------------
# 1. Complaint creation still works + priority derivation + event
# ---------------------------------------------------------------------------
def test_complaint_creation_still_works_and_logs_event():
    _, headers = _register_and_login("research-create@example.com")

    created = _create_complaint(headers, waste_type="wet", quantity_severity="large",
                                intervention_required=True)
    assert created["status"] == "pending"
    assert created["priority"] == "high"          # large + intervention -> high
    assert created["source"] == "citizen"

    with TestingSessionLocal() as db:
        events = (
            db.query(EventLog)
            .filter(EventLog.case_id == created["tracking_id"])
            .all()
        )
        assert any(e.activity == "complaint_created" for e in events)


def test_priority_rule_urgent_for_hazardous():
    assert compute_priority("large", "hazardous", True) == "urgent"
    assert compute_priority("small", "hazardous", False) == "urgent"   # type beats severity
    assert compute_priority("small", "medical", True) == "high"
    assert compute_priority("small", "dry", False) == "low"
    assert compute_priority(None, None, None) == "medium"


# ---------------------------------------------------------------------------
# 2-4. AI ingest + escalation gate
# ---------------------------------------------------------------------------
def test_ai_output_storage_and_low_confidence_escalation():
    _, citizen_headers = _register_and_login("research-ai@example.com")
    admin_id, admin_headers = _register_and_login("research-ai-admin@example.com")
    _promote_to_admin(admin_id)

    created = _create_complaint(citizen_headers)
    complaint_id = _complaint_db_id(created["tracking_id"])

    # Low-confidence prediction -> must be escalated for human review
    ingest = client.post(f"/admin/complaints/{complaint_id}/ai-output", headers=admin_headers, json={
        "waste_type_pred": "wet",
        "severity_pred": "medium",
        "intervention_required_pred": True,
        "confidence": 0.42,
        "model_name": "test-model",
        "model_version": "1.0",
        "threshold_used": 0.7,
        "latency_ms": 120,
    })
    assert ingest.status_code == 201
    data = ingest.json()
    assert data["escalated"] is True
    assert data["escalation_reason"] == "low_confidence"

    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.id == complaint_id).one()
        assert complaint.review_required is True
        assert complaint.review_reason == "low_confidence"
        assert complaint.triage_mode == "ai_assisted"
        assert db.query(AIOutput).filter(AIOutput.complaint_id == complaint_id).count() == 1

    # Event log captured the prediction + the review requirement
    with TestingSessionLocal() as db:
        activities = {
            e.activity for e in db.query(EventLog).filter(EventLog.case_id == created["tracking_id"]).all()
        }
        assert "ai_prediction_generated" in activities
        assert "human_review_required" in activities


def test_hazardous_complaint_is_escalated_even_with_high_confidence():
    _, citizen_headers = _register_and_login("research-haz@example.com")
    admin_id, admin_headers = _register_and_login("research-haz-admin@example.com")
    _promote_to_admin(admin_id)

    created = _create_complaint(citizen_headers)
    complaint_id = _complaint_db_id(created["tracking_id"])

    ingest = client.post(f"/admin/complaints/{complaint_id}/ai-output", headers=admin_headers, json={
        "waste_type_pred": "hazardous",
        "severity_pred": "large",
        "intervention_required_pred": True,
        "confidence": 0.99,
        "model_name": "test-model",
        "model_version": "1.0",
    })
    assert ingest.status_code == 201
    assert ingest.json()["escalated"] is True
    assert ingest.json()["escalation_reason"] == "hazardous_waste"


def test_high_confidence_non_hazardous_is_not_escalated():
    assert decide_escalation(0.95, "dry", threshold=0.7) == (False, None)
    assert decide_escalation(None, "dry") == (True, "missing_prediction")
    assert decide_escalation(0.5, "wet", threshold=0.7) == (True, "low_confidence")
    assert decide_escalation(0.95, "medical", threshold=0.7) == (True, "hazardous_waste")


def test_ai_ingest_requires_admin():
    _, citizen_headers = _register_and_login("research-noadmin@example.com")
    created = _create_complaint(citizen_headers)
    complaint_id = _complaint_db_id(created["tracking_id"])

    forbidden = client.post(f"/admin/complaints/{complaint_id}/ai-output", headers=citizen_headers, json={
        "confidence": 0.9, "model_name": "m", "model_version": "1",
    })
    assert forbidden.status_code == 403


def test_ai_ingest_rejects_invalid_taxonomy_values():
    _, citizen_headers = _register_and_login("research-tax@example.com")
    admin_id, admin_headers = _register_and_login("research-tax-admin@example.com")
    _promote_to_admin(admin_id)

    created = _create_complaint(citizen_headers)
    complaint_id = _complaint_db_id(created["tracking_id"])

    bad = client.post(f"/admin/complaints/{complaint_id}/ai-output", headers=admin_headers, json={
        "waste_type_pred": "nuclear",   # not in the taxonomy
        "confidence": 0.9,
        "model_name": "m",
        "model_version": "1",
    })
    assert bad.status_code == 422


# ---------------------------------------------------------------------------
# 5-7. Human-in-the-loop decisions (accept/correct, dispatch, guidance)
# ---------------------------------------------------------------------------
def _prepare_triaged_complaint(citizen_email, admin_email, confidence, waste="e_waste"):
    _, citizen_headers = _register_and_login(citizen_email)
    admin_id, admin_headers = _register_and_login(admin_email)
    _promote_to_admin(admin_id)
    created = _create_complaint(citizen_headers)
    complaint_id = _complaint_db_id(created["tracking_id"])
    ingest = client.post(f"/admin/complaints/{complaint_id}/ai-output", headers=admin_headers, json={
        "waste_type_pred": waste,
        "severity_pred": "large",
        "intervention_required_pred": True,
        "confidence": confidence,
        "model_name": "test-model",
        "model_version": "1.0",
    })
    assert ingest.status_code == 201
    return complaint_id, admin_headers


def test_admin_accept_and_correct_with_dispatch_path():
    complaint_id, admin_headers = _prepare_triaged_complaint(
        "research-acc@example.com", "research-acc-admin@example.com", confidence=0.9
    )

    decision = client.post(f"/admin/complaints/{complaint_id}/ai-decision", headers=admin_headers, json={
        "waste_type": "e_waste",             # same as AI -> acceptance
        "quantity_severity": "large",        # same as AI -> acceptance
        "intervention_required": True,       # same as AI -> acceptance
        "decision": "dispatch",
        "corrections": [],
    })
    assert decision.status_code == 200
    data = decision.json()
    assert data["decision"] == "dispatch"
    assert data["review_completed"] is False           # high confidence -> no review was required
    assert data["acceptance_rate_fields"] == 3         # all three accepted
    assert data["corrections_recorded"] == 0
    assert data["status"] == "in_progress"
    assert data["task_id"] is None                     # task created via assign endpoint
    assert data["triage_mode"] == "ai_assisted"

    with TestingSessionLocal() as db:
        corrections = db.query(AICorrection).filter(AICorrection.complaint_id == complaint_id).all()
        assert len(corrections) == 3
        assert all(c.ai_value == c.admin_value for c in corrections)


def test_admin_correction_recorded_and_review_completed():
    complaint_id, admin_headers = _prepare_triaged_complaint(
        "research-corr@example.com", "research-corr-admin@example.com", confidence=0.4
    )

    decision = client.post(f"/admin/complaints/{complaint_id}/ai-decision", headers=admin_headers, json={
        "waste_type": "hazardous",            # AI said e_waste -> correction
        "quantity_severity": "large",
        "intervention_required": True,
        "decision": "dispatch",
        "corrections": [{"field_name": "waste_type", "ai_value": "e_waste", "admin_value": "hazardous"}],
    })
    assert decision.status_code == 200
    data = decision.json()
    assert data["corrections_recorded"] == 1
    assert data["acceptance_rate_fields"] == 2
    assert data["review_completed"] is True    # low-confidence review mandatory and now completed
    assert data["priority"] == "urgent"        # corrected to hazardous

    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.id == complaint_id).one()
        assert complaint.review_required is False      # review completed and cleared
        correction = (
            db.query(AICorrection)
            .filter(AICorrection.complaint_id == complaint_id,
                    AICorrection.field_name == "waste_type")
            .one()
        )
        assert correction.ai_value == "e_waste"
        assert correction.admin_value == "hazardous"


def test_guidance_path_resolves_complaint():
    _, citizen_headers = _register_and_login("research-guide@example.com")
    admin_id, admin_headers = _register_and_login("research-guide-admin@example.com")
    _promote_to_admin(admin_id)

    created = _create_complaint(citizen_headers, waste_type="dry",
                                quantity_severity="small", intervention_required=False)
    complaint_id = _complaint_db_id(created["tracking_id"])

    decision = client.post(f"/admin/complaints/{complaint_id}/ai-decision", headers=admin_headers, json={
        "waste_type": "dry",
        "quantity_severity": "small",
        "intervention_required": False,
        "decision": "guidance",
        "guidance_text": "Please place the dry waste in the nearest municipal dry-waste bin.",
    })
    assert decision.status_code == 200
    data = decision.json()
    assert data["decision"] == "guidance"
    assert data["status"] == "resolved"
    assert data["resolved_at"] is not None

    tracked = client.get(f"/complaints/{created['tracking_id']}", headers=citizen_headers)
    assert tracked.json()["status"] == "resolved"

    with TestingSessionLocal() as db:
        activities = {
            e.activity for e in db.query(EventLog).filter(EventLog.case_id == created["tracking_id"]).all()
        }
        assert "guidance_decided" in activities
        assert "complaint_resolved" in activities


def test_guidance_requires_text():
    complaint_id, admin_headers = _prepare_triaged_complaint(
        "research-gt@example.com", "research-gt-admin@example.com", confidence=0.9
    )
    bad = client.post(f"/admin/complaints/{complaint_id}/ai-decision", headers=admin_headers, json={
        "waste_type": "dry", "quantity_severity": "small",
        "intervention_required": False,
        "decision": "guidance",   # missing guidance_text -> 422
    })
    assert bad.status_code == 422


# ---------------------------------------------------------------------------
# 8. Event log completeness + process-mining export
# ---------------------------------------------------------------------------
def test_event_log_export_is_pm4py_ready():
    _, citizen_headers = _register_and_login("research-events@example.com")
    created = _create_complaint(citizen_headers, waste_type="wet")

    export = client.get("/admin/events/export")  # unauthenticated
    assert export.status_code in (401, 403)

    admin_id, admin_headers = _register_and_login("research-events-admin@example.com")
    _promote_to_admin(admin_id)

    export = client.get("/admin/events/export", headers=admin_headers)
    assert export.status_code == 200
    body = export.text
    assert "case:concept:name" in body
    assert "concept:name" in body
    assert "time:timestamp" in body
    assert created["tracking_id"] in body
    assert "complaint_created" in body


# ---------------------------------------------------------------------------
# 9. Mining dataset export
# ---------------------------------------------------------------------------
def test_mining_dataset_contains_required_fields():
    _, citizen_headers = _register_and_login("research-mining@example.com")
    admin_id, admin_headers = _register_and_login("research-mining-admin@example.com")
    _promote_to_admin(admin_id)

    _create_complaint(citizen_headers, waste_type="bulk", quantity_severity="large",
                      intervention_required=True, address_text="MG Road, Ward 1")

    dataset = client.get("/admin/mining/dataset", headers=admin_headers)
    assert dataset.status_code == 200
    payload = dataset.json()
    required = {
        "complaint_id", "waste_type", "severity", "intervention_required",
        "latitude", "longitude", "ward", "date", "hour", "day_of_week",
        "triage_mode", "ai_confidence", "human_review_required",
        "cleaner_assigned", "proof_attempts", "proof_verified",
        "resolution_time_seconds", "final_status", "is_synthetic",
    }
    assert required.issubset(set(payload["fieldnames"]))
    assert payload["count"] >= 1
    row = payload["rows"][-1]
    assert row["waste_type"] == "bulk"
    assert row["ward"] == "ward_1"            # parsed only from explicit Ward mention
    assert row["is_synthetic"] is False
    assert row["resolution_time_seconds"] is None   # not resolved -> NULL, never fabricated

    csv_export = client.get("/admin/mining/dataset/export", headers=admin_headers)
    assert csv_export.status_code == 200
    assert "complaint_id,tracking_id,waste_type" in csv_export.text


# ---------------------------------------------------------------------------
# 10. Seeder
# ---------------------------------------------------------------------------
def test_seeder_generates_marked_synthetic_data_and_wipes_it():
    from seed_data import clear_seeded_data, seed_database

    summary = seed_database(number_of_complaints=25, number_of_cleaners=2, seed=7)
    assert summary["complaints"] == 25
    assert summary["tasks"] > 0
    assert summary["proofs"] > 0
    assert summary["events"] > 0

    admin_id, admin_headers = _register_and_login("research-seed-admin@example.com")
    _promote_to_admin(admin_id)
    dataset = client.get("/admin/mining/dataset", headers=admin_headers).json()
    seeded_rows = [row for row in dataset["rows"] if row["is_synthetic"]]
    assert len(seeded_rows) == 25
    # Seeded rows carry full event chains for process mining
    assert all(row["source"] == "seed" for row in seeded_rows)
    # Every seeded complaint has a complaint_created event
    with TestingSessionLocal() as db:
        for row in seeded_rows:
            assert (
                db.query(EventLog)
                .filter(EventLog.case_id == row["tracking_id"],
                        EventLog.activity == "complaint_created")
                .count()
                == 1
            )

    removed = clear_seeded_data()
    assert removed == 25
    dataset_after = client.get("/admin/mining/dataset", headers=admin_headers).json()
    assert all(row["is_synthetic"] is False for row in dataset_after["rows"])


# ---------------------------------------------------------------------------
# 11. Existing invariants on the migrated schema
# ---------------------------------------------------------------------------
def test_existing_invariants_on_migrated_schema():
    _, citizen_headers = _register_and_login("research-invariant@example.com")

    # Tracking + ownership access rules intact
    created = _create_complaint(citizen_headers)
    tracked = client.get(f"/complaints/{created['tracking_id']}", headers=citizen_headers)
    assert tracked.status_code == 200
    assert tracked.json()["triage_mode"] is None       # untouched citizen row: not yet triaged
    assert tracked.json()["review_required"] is False

    # Anonymous access to protected research endpoints is rejected
    assert client.get("/admin/mining/dataset").status_code in (401, 403)
    assert client.get("/admin/events").status_code in (401, 403)
