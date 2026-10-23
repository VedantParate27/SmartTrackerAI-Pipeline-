# tests/test_waste_ai_admin_review.py
# Step 4 (admin AI review + decision/routing) tests. NO test calls Gemini:
# backend.ai_client.analyze_waste_image is monkeypatched in the isolation
# fixture (same pattern as the Step-3 flow tests).
#
# Uses the shared in-memory engine/test client (test_app_state). TestClient
# runs background tasks before post() returns, which is what lets the helper
# upload an image and get a COMPLETED analysis synchronously.

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import ai_client  # noqa: E402
import waste_ai_service  # noqa: E402
from test_app_state import TestingSessionLocal, client  # noqa: E402

from models import (  # noqa: E402
    AdminDecision,
    CleanupTask,
    Complaint,
    EventLog,
    WasteAIResult,
)

JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"\x00" * 16


# ---------------------------------------------------------------------------
# Fixture + helpers
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _review_isolation(monkeypatch):
    """Fresh rows per test + AI always mocked (never Gemini)."""
    monkeypatch.setattr(ai_client, "analyze_waste_image",
                        lambda *a, **k: {"success": False, "result": None,
                                         "error": "NOT_MOCKED", "details": None, "latency_ms": 0})
    monkeypatch.setattr(ai_client, "verify_cleanup",
                        lambda *a, **k: {"success": False, "result": None,
                                         "error": "NOT_MOCKED", "details": None, "latency_ms": 0})
    monkeypatch.setattr(waste_ai_service, "SessionLocal", TestingSessionLocal)
    monkeypatch.setenv("WASTE_AI_MODE", "assist")
    yield
    with TestingSessionLocal() as db:
        db.query(EventLog).delete()
        db.query(AdminDecision).delete()
        db.query(CleanupTask).delete()
        db.query(WasteAIResult).delete()
        db.query(Complaint).delete()
        db.commit()


def _register_and_login(email, password="Password123!"):
    register = client.post("/auth/register", json={
        "name": "Admin Review User", "email": email, "password": password,
    })
    assert register.status_code == 201
    user_id = register.json()["id"]
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return user_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


def _promote(user_id, role):
    from models import User
    with TestingSessionLocal() as db:
        db.query(User).filter(User.id == user_id).one().role = role
        db.commit()


def _create_complaint(headers, text="Overflowing garbage near the park gate.", **fields) -> dict:
    response = client.post("/complaints/", headers=headers, json={"complaint_text": text, **fields})
    assert response.status_code == 201
    data = response.json()
    # The public API does not expose the internal complaint id (admin
    # endpoints are keyed by it), so resolve it here once for the tests.
    with TestingSessionLocal() as db:
        data["id"] = (db.query(Complaint.id)
                      .filter(Complaint.tracking_id == data["tracking_id"])
                      .scalar())
    return data


def _upload_image(headers, tracking_id, ai_outcome=None):
    """Upload a JPEG image; optionally make the mocked AI return ai_outcome."""
    if ai_outcome is not None:
        ai_client.analyze_waste_image = (
            lambda *a, **k: {"success": True, "result": dict(ai_outcome),
                             "error": None, "details": None, "latency_ms": 1234}
        )
    response = client.post(
        f"/complaints/{tracking_id}/image",
        headers=headers,
        files={"file": ("photo.jpg", JPEG_HEAD, "image/jpeg")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _admin_headers(email):
    """Register a separate admin user and return their auth headers."""
    admin_uid, admin_hdrs = _register_and_login(email)
    _promote(admin_uid, "admin")
    return admin_hdrs


def _decision_url(complaint):
    return f"/admin/complaints/{complaint['id']}/decision"


AI_COMPLETED_VERBATIM = {
    "image_usable": True,
    "unusable_reason": None,
    "waste_type": "sanitary",          # AI vocabulary — must come back verbatim
    "waste_type_confidence": 0.82,
    "severity": "dump_scale",          # AI vocabulary — must come back verbatim
    "severity_confidence": 0.91,
    "reasoning": "Large pile spanning several meters.",
    "follow_up_question": "Is the pile still growing?",
    "location": {"lat": 12.9716, "lng": 77.5946},
    "prior_reports_at_location": 1,
    "recurring_flag": True,
    "escalate_to_authority": True,
    "needs_human_review": False,
    "review_reasons": [],
    "disposal_guidance": None,
    "errors": [],
}

AI_COMPLETED_HUMAN_REVIEW = {
    **AI_COMPLETED_VERBATIM,
    "waste_type": "mixed",
    "severity": "moderate",
    "escalate_to_authority": False,
    "needs_human_review": True,
    "review_reasons": ["low_waste_type_confidence: 0.42"],
}


# ===========================================================================
# ADMIN REVIEW (1–10)
# ===========================================================================
def test_1_admin_can_retrieve_ai_review():
    uid, hdrs = _register_and_login("rev-citizen1@example.com")
    complaint = _create_complaint(hdrs, latitude=12.9716, longitude=77.5946)
    _upload_image(hdrs, complaint["tracking_id"], AI_COMPLETED_VERBATIM)
    _promote(uid, "admin")

    response = client.get(f"/admin/complaints/{complaint['id']}/ai-review", headers=hdrs)
    assert response.status_code == 200
    body = response.json()
    assert body["tracking_id"] == complaint["tracking_id"]
    assert body["complaint_text"]
    assert body["analysis"]["ai_status"] == "completed"
    assert body["analysis"]["waste_type"] == "sanitary"
    assert body["analysis"]["severity"] == "dump_scale"


def test_2_citizen_cannot_retrieve_ai_review():
    _, hdrs = _register_and_login("rev-citizen2@example.com")
    complaint = _create_complaint(hdrs)
    _upload_image(hdrs, complaint["tracking_id"], AI_COMPLETED_VERBATIM)

    response = client.get(f"/admin/complaints/{complaint['id']}/ai-review", headers=hdrs)
    assert response.status_code == 403


def test_3_cleaner_cannot_retrieve_ai_review():
    _, owner_hdrs = _register_and_login("rev-owner3@example.com")
    complaint = _create_complaint(owner_hdrs)
    _upload_image(owner_hdrs, complaint["tracking_id"], AI_COMPLETED_VERBATIM)

    cleaner_uid, cleaner_hdrs = _register_and_login("rev-cleaner3@example.com")
    _promote(cleaner_uid, "cleaner")

    response = client.get(f"/admin/complaints/{complaint['id']}/ai-review", headers=cleaner_hdrs)
    assert response.status_code == 403


def test_4_missing_complaint_returns_404():
    uid, hdrs = _register_and_login("rev-admin4@example.com")
    _promote(uid, "admin")

    response = client.get("/admin/complaints/999999/ai-review", headers=hdrs)
    assert response.status_code == 404


def test_5_missing_ai_result_returns_404():
    uid, hdrs = _register_and_login("rev-admin5@example.com")
    created = _create_complaint(hdrs)            # no image -> no AI result
    _promote(uid, "admin")

    # Resolve this test's own complaint id from its unique tracking_id —
    # no assumptions about which numeric ids other tests have consumed.
    with TestingSessionLocal() as db:
        complaint_id = (db.query(Complaint.id)
                        .filter(Complaint.tracking_id == created["tracking_id"])
                        .scalar())

    response = client.get(f"/admin/complaints/{complaint_id}/ai-review", headers=hdrs)
    assert response.status_code == 404


def test_6_pending_ai_result_represented_correctly():
    # Real ordering test: stub the background run so the row stays pending.
    uid, hdrs = _register_and_login("rev-owner6@example.com")
    complaint = _create_complaint(hdrs)
    monkeypatch_run = pytest.MonkeyPatch()
    monkeypatch_run.setattr(waste_ai_service, "run_ai_analysis", lambda result_id: None)
    try:
        _upload_image(hdrs, complaint["tracking_id"])
    finally:
        monkeypatch_run.undo()
    _promote(uid, "admin")

    response = client.get(f"/admin/complaints/{complaint['id']}/ai-review", headers=hdrs)
    assert response.status_code == 200
    analysis = response.json()["analysis"]
    assert analysis["ai_status"] == "pending"
    # No AI predictions are invented while pending (advisory flags carry the
    # Step-1 model default False; all AI-sourced fields stay NULL):
    assert analysis["waste_type"] is None
    assert analysis["severity"] is None
    assert analysis["waste_type_confidence"] is None
    assert analysis["reasoning"] is None
    assert analysis["disposal_guidance"] is None
    assert analysis["escalate_to_authority"] is False
    assert analysis["needs_human_review"] is False


def test_7_failed_ai_result_represented_correctly():
    uid, hdrs = _register_and_login("rev-owner7@example.com")
    complaint = _create_complaint(hdrs)
    _upload_image(hdrs, complaint["tracking_id"])   # autouse fixture mocks AI to fail
    _promote(uid, "admin")

    response = client.get(f"/admin/complaints/{complaint['id']}/ai-review", headers=hdrs)
    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["ai_status"] == "failed"
    assert body["analysis"]["waste_type"] is None
    assert isinstance(body["errors"], list) and body["errors"]
    error_blob = str(body["errors"])
    # Safe errors only: no stack traces / internals
    assert "Traceback" not in error_blob


def test_8_completed_review_returns_ai_vocabulary_verbatim():
    uid, hdrs = _register_and_login("rev-owner8@example.com")
    complaint = _create_complaint(hdrs)
    _upload_image(hdrs, complaint["tracking_id"], AI_COMPLETED_VERBATIM)
    _promote(uid, "admin")

    response = client.get(f"/admin/complaints/{complaint['id']}/ai-review", headers=hdrs)
    assert response.status_code == 200
    analysis = response.json()["analysis"]
    assert analysis["waste_type"] == "sanitary"       # not remapped to medical
    assert analysis["severity"] == "dump_scale"       # not remapped to large
    assert analysis["waste_type_confidence"] == pytest.approx(0.82)
    assert analysis["severity_confidence"] == pytest.approx(0.91)
    assert analysis["reasoning"] == AI_COMPLETED_VERBATIM["reasoning"]
    assert analysis["follow_up_question"] == "Is the pile still growing?"
    assert analysis["recurring_flag"] is True
    # prior_reports_count is BACKEND-computed (geo) at upload time, not taken
    # from the AI dict — this complaint has no coordinates, so it is 0.
    assert analysis["prior_reports_count"] == 0
    assert analysis["latency_ms"] == 1234


def test_9_review_reasons_returned_correctly():
    uid, hdrs = _register_and_login("rev-owner9@example.com")
    complaint = _create_complaint(hdrs)
    _upload_image(hdrs, complaint["tracking_id"], AI_COMPLETED_HUMAN_REVIEW)
    _promote(uid, "admin")

    response = client.get(f"/admin/complaints/{complaint['id']}/ai-review", headers=hdrs)
    assert response.status_code == 200
    body = response.json()
    assert body["review_reasons"] == ["low_waste_type_confidence: 0.42"]
    assert body["analysis"]["needs_human_review"] is True


def test_10_escalation_and_human_review_flags_remain_separate():
    uid, hdrs = _register_and_login("rev-owner10@example.com")
    complaint = _create_complaint(hdrs)
    # escalate=True, review=False
    _upload_image(hdrs, complaint["tracking_id"], AI_COMPLETED_VERBATIM)
    _promote(uid, "admin")
    review = client.get(f"/admin/complaints/{complaint['id']}/ai-review", headers=hdrs).json()
    assert review["analysis"]["escalate_to_authority"] is True
    assert review["analysis"]["needs_human_review"] is False

    # Fresh complaint: escalate=False, review=True — the flags are orthogonal
    uid2, hdrs2 = _register_and_login("rev-owner10b@example.com")
    complaint2 = _create_complaint(hdrs2)
    _upload_image(hdrs2, complaint2["tracking_id"], AI_COMPLETED_HUMAN_REVIEW)
    review2 = client.get(f"/admin/complaints/{complaint2['id']}/ai-review", headers=hdrs2)
    # owner is still a citizen — admin-only endpoint must refuse:
    assert review2.status_code == 403


# ===========================================================================
# ADMIN DECISION (11–22)
# ===========================================================================
def test_11_admin_can_submit_assign_cleaner():
    uid, owner_hdrs = _register_and_login("dec-owner11@example.com")
    complaint = _create_complaint(owner_hdrs)
    admin_hdrs = _admin_headers("dec-admin11@example.com")

    response = client.put(_decision_url(complaint), headers=admin_hdrs,
                          json={"decision": "assign_cleaner"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == "assign_cleaner"
    assert body["complaint_status"] == "in_progress"
    assert body["cleanup_task"]["task_id"].startswith("TSK-")
    assert body["cleanup_task"]["assigned_cleaner_id"] is None  # handoff, not selection
    assert body["decided_by"] > 0 and body["decided_by_name"]


def test_12_admin_can_submit_escalate_authority():
    uid, owner_hdrs = _register_and_login("dec-owner12@example.com")
    complaint = _create_complaint(owner_hdrs)
    admin_hdrs = _admin_headers("dec-admin12@example.com")

    response = client.put(_decision_url(complaint), headers=admin_hdrs,
                          json={"decision": "escalate_authority",
                                "note": "Hazardous drum leak — routing to authority."})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "escalate_authority"
    assert body["cleanup_task"] is None           # no external authority action claimed
    assert body["complaint_status"] == "pending"  # decision recorded, no fake status move


def test_13_admin_can_submit_request_information():
    uid, owner_hdrs = _register_and_login("dec-owner13@example.com")
    complaint = _create_complaint(owner_hdrs)
    admin_hdrs = _admin_headers("dec-admin13@example.com")

    response = client.put(_decision_url(complaint), headers=admin_hdrs,
                          json={"decision": "request_information",
                                "note": "Please confirm the exact block/landmark."})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "request_information"
    assert body["note"] == "Please confirm the exact block/landmark."
    assert body["complaint_status"] == "pending"  # stays open


def test_14_admin_can_submit_dismiss():
    uid, owner_hdrs = _register_and_login("dec-owner14@example.com")
    complaint = _create_complaint(owner_hdrs)
    admin_hdrs = _admin_headers("dec-admin14@example.com")

    response = client.put(_decision_url(complaint), headers=admin_hdrs,
                          json={"decision": "dismiss", "note": "Duplicate report."})
    assert response.status_code == 200
    assert response.json()["complaint_status"] == "closed"


def test_15_admin_can_submit_resolve():
    uid, owner_hdrs = _register_and_login("dec-owner15@example.com")
    complaint = _create_complaint(owner_hdrs)
    admin_hdrs = _admin_headers("dec-admin15@example.com")

    response = client.put(_decision_url(complaint), headers=admin_hdrs,
                          json={"decision": "resolve"})
    assert response.status_code == 200
    body = response.json()
    assert body["complaint_status"] == "resolved"
    assert body["cleanup_task"] is None   # no fabricated cleanup proof / task


def test_16_citizen_cannot_submit_decisions():
    _, owner_hdrs = _register_and_login("dec-owner16@example.com")
    complaint = _create_complaint(owner_hdrs)

    response = client.put(_decision_url(complaint), headers=owner_hdrs,
                          json={"decision": "dismiss"})
    assert response.status_code == 403


def test_17_cleaner_cannot_submit_decisions():
    _, owner_hdrs = _register_and_login("dec-owner17@example.com")
    complaint = _create_complaint(owner_hdrs)
    cleaner_uid, cleaner_hdrs = _register_and_login("dec-cleaner17@example.com")
    _promote(cleaner_uid, "cleaner")

    response = client.put(_decision_url(complaint), headers=cleaner_hdrs,
                          json={"decision": "assign_cleaner"})
    assert response.status_code == 403


def test_18_invalid_decision_value_rejected_422():
    uid, owner_hdrs = _register_and_login("dec-owner18@example.com")
    complaint = _create_complaint(owner_hdrs)
    admin_hdrs = _admin_headers("dec-admin18@example.com")

    response = client.put(_decision_url(complaint), headers=admin_hdrs,
                          json={"decision": "hazardous"})   # AI value, not a decision
    assert response.status_code == 422


def test_19_decision_is_persisted():
    uid, owner_hdrs = _register_and_login("dec-owner19@example.com")
    complaint = _create_complaint(owner_hdrs)
    admin_hdrs = _admin_headers("dec-admin19@example.com")

    client.put(_decision_url(complaint), headers=admin_hdrs,
               json={"decision": "escalate_authority"})
    with TestingSessionLocal() as db:
        rows = (db.query(AdminDecision)
                .filter(AdminDecision.complaint_id == complaint["id"]).all())
        assert len(rows) == 1
        assert rows[0].decision == "escalate_authority"


def test_20_decided_by_is_persisted():
    admin_uid, admin_hdrs = _register_and_login("dec-admin20@example.com")
    _promote(admin_uid, "admin")
    _, owner_hdrs = _register_and_login("dec-owner20@example.com")
    complaint = _create_complaint(owner_hdrs)

    client.put(_decision_url(complaint), headers=admin_hdrs, json={"decision": "dismiss"})
    with TestingSessionLocal() as db:
        row = (db.query(AdminDecision)
               .filter(AdminDecision.complaint_id == complaint["id"]).one())
        assert row.admin_id == admin_uid


def test_21_decided_at_is_persisted():
    uid, owner_hdrs = _register_and_login("dec-owner21@example.com")
    complaint = _create_complaint(owner_hdrs)
    admin_hdrs = _admin_headers("dec-admin21@example.com")

    response = client.put(_decision_url(complaint), headers=admin_hdrs,
                          json={"decision": "resolve"})
    assert response.json()["decided_at"]
    with TestingSessionLocal() as db:
        row = (db.query(AdminDecision)
               .filter(AdminDecision.complaint_id == complaint["id"]).one())
        assert row.created_at is not None


def test_22_admin_note_is_persisted():
    uid, owner_hdrs = _register_and_login("dec-owner22@example.com")
    complaint = _create_complaint(owner_hdrs)
    admin_hdrs = _admin_headers("dec-admin22@example.com")

    client.put(_decision_url(complaint), headers=admin_hdrs,
               json={"decision": "request_information", "note": "Need exact address."})
    with TestingSessionLocal() as db:
        row = (db.query(AdminDecision)
               .filter(AdminDecision.complaint_id == complaint["id"]).one())
        assert row.note == "Need exact address."


# ===========================================================================
# WORKFLOW (23–28)
# ===========================================================================
def test_23_assign_cleaner_does_not_mark_complaint_resolved():
    uid, owner_hdrs = _register_and_login("dec-owner23@example.com")
    complaint = _create_complaint(owner_hdrs)
    admin_hdrs = _admin_headers("dec-admin23@example.com")

    response = client.put(_decision_url(complaint), headers=admin_hdrs,
                          json={"decision": "assign_cleaner"})
    assert response.json()["complaint_status"] == "in_progress"
    with TestingSessionLocal() as db:
        c = db.query(Complaint).filter(Complaint.id == complaint["id"]).one()
        assert c.status == "in_progress"
        assert c.resolved_at is None


def test_24_assign_cleaner_does_not_create_duplicate_cleanup_tasks():
    uid, owner_hdrs = _register_and_login("dec-owner24@example.com")
    complaint = _create_complaint(owner_hdrs)
    admin_hdrs = _admin_headers("dec-admin24@example.com")

    first = client.put(_decision_url(complaint), headers=admin_hdrs,
                       json={"decision": "assign_cleaner"})
    second = client.put(_decision_url(complaint), headers=admin_hdrs,
                        json={"decision": "assign_cleaner", "note": "re-confirm"})
    assert first.status_code == 200 and second.status_code == 200
    assert (first.json()["cleanup_task"]["task_id"]
            == second.json()["cleanup_task"]["task_id"])
    with TestingSessionLocal() as db:
        tasks = (db.query(CleanupTask)
                 .filter(CleanupTask.complaint_id == complaint["id"]).all())
        assert len(tasks) == 1


def test_25_ai_result_remains_unchanged_after_admin_decision():
    uid, owner_hdrs = _register_and_login("dec-owner25@example.com")
    complaint = _create_complaint(owner_hdrs, latitude=12.9716, longitude=77.5946)
    _upload_image(owner_hdrs, complaint["tracking_id"], AI_COMPLETED_VERBATIM)

    with TestingSessionLocal() as db:
        before = (db.query(WasteAIResult)
                  .filter(WasteAIResult.complaint_id == complaint["id"])
                  .order_by(WasteAIResult.id.desc()).first())
        snapshot = (before.ai_status, before.waste_type, before.severity,
                    before.escalate_to_authority, before.needs_human_review,
                    before.review_reasons_json, before.disposal_guidance)

    admin_hdrs = _admin_headers("dec-admin25@example.com")
    client.put(_decision_url(complaint), headers=admin_hdrs,
               json={"decision": "assign_cleaner", "note": "send a crew"})
    client.put(_decision_url(complaint), headers=admin_hdrs,
               json={"decision": "dismiss"})

    with TestingSessionLocal() as db:
        after = (db.query(WasteAIResult)
                 .filter(WasteAIResult.complaint_id == complaint["id"])
                 .order_by(WasteAIResult.id.desc()).first())
        assert ((after.ai_status, after.waste_type, after.severity,
                 after.escalate_to_authority, after.needs_human_review,
                 after.review_reasons_json, after.disposal_guidance) == snapshot)


def test_26_ai_escalate_true_does_not_execute_authority_action():
    uid, owner_hdrs = _register_and_login("dec-owner26@example.com")
    complaint = _create_complaint(owner_hdrs)
    # AI recommends escalation...
    _upload_image(owner_hdrs, complaint["tracking_id"], AI_COMPLETED_VERBATIM)  # escalate=True
    admin_hdrs = _admin_headers("dec-admin26@example.com")

    # ...but nothing happens unless the ADMIN decides it.
    response = client.put(_decision_url(complaint), headers=admin_hdrs,
                          json={"decision": "assign_cleaner"})
    assert response.status_code == 200
    assert response.json()["decision"] == "assign_cleaner"
    with TestingSessionLocal() as db:
        events = (db.query(EventLog)
                  .filter(EventLog.case_id == complaint["tracking_id"]).all())
        # no escalation/authority activity exists in the vocabulary, and none
        # may be invented from the AI flag:
        assert not any("escalat" in (e.activity or "").lower() for e in events)


def test_27_admin_can_override_the_ai_recommendation():
    uid, owner_hdrs = _register_and_login("dec-owner27@example.com")
    complaint = _create_complaint(owner_hdrs)
    _upload_image(owner_hdrs, complaint["tracking_id"], AI_COMPLETED_VERBATIM)  # escalate=True
    admin_hdrs = _admin_headers("dec-admin27@example.com")

    # Admin overrides: resolves anyway (recommendation ignored, not enforced)
    response = client.put(_decision_url(complaint), headers=admin_hdrs,
                          json={"decision": "resolve", "note": "Citizen cleaned it up themselves."})
    assert response.status_code == 200
    assert response.json()["complaint_status"] == "resolved"

    # And the reverse: AI flagged nothing, admin escalates anyway
    _, owner2 = _register_and_login("dec-owner27b@example.com")
    complaint2 = _create_complaint(owner2)
    response2 = client.put(_decision_url(complaint2), headers=admin_hdrs,
                           json={"decision": "escalate_authority"})
    assert response2.status_code == 200
    assert response2.json()["decision"] == "escalate_authority"


def test_28_event_log_records_actual_admin_decision():
    uid, owner_hdrs = _register_and_login("dec-owner28@example.com")
    complaint = _create_complaint(owner_hdrs)
    _upload_image(owner_hdrs, complaint["tracking_id"], AI_COMPLETED_VERBATIM)
    admin_hdrs = _admin_headers("dec-admin28@example.com")

    client.put(_decision_url(complaint), headers=admin_hdrs,
               json={"decision": "assign_cleaner"})
    with TestingSessionLocal() as db:
        activities = [e.activity for e in
                      db.query(EventLog).filter(EventLog.case_id == complaint["tracking_id"]).all()]
        assert "admin_decision_made" in activities
        assert "dispatch_decided" in activities
        assert "ai_prediction_generated" not in activities  # review/decision never logs AI predictions


# ---------------------------------------------------------------------------
# Review endpoint embeds the latest decision (bonus coverage)
# ---------------------------------------------------------------------------
def test_review_embeds_latest_decision():
    uid, owner_hdrs = _register_and_login("rev-decision-owner@example.com")
    complaint = _create_complaint(owner_hdrs)
    _upload_image(owner_hdrs, complaint["tracking_id"])   # analysis row must exist for ai-review
    admin_hdrs = _admin_headers("rev-decision-admin@example.com")

    client.put(_decision_url(complaint), headers=admin_hdrs,
               json={"decision": "request_information", "note": "Which gate?"})

    response = client.get(f"/admin/complaints/{complaint['id']}/ai-review", headers=admin_hdrs)
    assert response.status_code == 200
    latest = response.json()["latest_decision"]
    assert latest is not None
    assert latest["decision"] == "request_information"
    assert latest["note"] == "Which gate?"
    assert latest["admin_id"] > 0
    assert latest["created_at"]
