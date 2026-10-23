# tests/test_waste_ai_cleanup_flow.py
# Steps 5-7 (cleaner workflow + cleanup-proof AI verification + admin final
# verification) tests. NO test calls Gemini: backend.ai_client.verify_cleanup
# and analyze_waste_image are mocked (autouse fixture + per-test overrides,
# same restore semantics as the Step-3/4 suites).
#
# Uses the shared in-memory engine/test client (test_app_state). TestClient
# runs background tasks before the request returns, so a proof upload can be
# followed by direct assertions on the persisted AI verification result.

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import ai_client  # noqa: E402
import image_utils  # noqa: E402
import waste_ai_service  # noqa: E402
from test_app_state import TestingSessionLocal, client  # noqa: E402

from models import (  # noqa: E402
    AdminDecision,
    CleanupProof,
    CleanupTask,
    Complaint,
    EventLog,
    WasteAIResult,
)

JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"\x00" * 16
PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
WEBP_HEAD = b"RIFF\x24\x00\x00\x00WEBP" + b"\x00" * 16
GIF_HEAD = b"GIF89a" + b"\x00" * 16


# ---------------------------------------------------------------------------
# Fixture + helpers
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _cleanup_flow_isolation(monkeypatch):
    """AI always mocked (never Gemini) + background service on the test engine."""
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
        db.query(CleanupProof).delete()
        db.query(CleanupTask).delete()
        db.query(AdminDecision).delete()
        db.query(WasteAIResult).delete()
        db.query(Complaint).delete()
        db.commit()


def _register_and_login(email, password="Password123!"):
    register = client.post("/auth/register", json={
        "name": "Cleanup Flow User", "email": email, "password": password,
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


def _mock_cleanup(outcome=None, calls=None):
    """Point ai_client.verify_cleanup at a canned outcome (None = failure)."""
    def fake(*args, **kwargs):
        if calls is not None:
            calls.append({"args": args, "kwargs": kwargs})
        if outcome is None:
            return {"success": False, "result": None, "error": "AI_TIMEOUT",
                    "details": "cleanup AI timed out", "latency_ms": 5}
        return {"success": True, "result": dict(outcome), "error": None,
                "details": None, "latency_ms": 321}
    ai_client.verify_cleanup = fake


def _create_complaint(headers, **fields) -> dict:
    payload = {"complaint_text": "Overflowing garbage near the park gate.", **fields}
    response = client.post("/complaints/", headers=headers, json=payload)
    assert response.status_code == 201
    data = response.json()
    with TestingSessionLocal() as db:
        data["id"] = (db.query(Complaint.id)
                      .filter(Complaint.tracking_id == data["tracking_id"]).scalar())
    return data


def _upload_complaint_image(headers, tracking_id):
    """Citizen BEFORE image (background analyze mocked to fail — fine here)."""
    response = client.post(
        f"/complaints/{tracking_id}/image",
        headers=headers,
        files={"file": ("before.jpg", JPEG_HEAD, "image/jpeg")},
    )
    assert response.status_code == 200, response.text


def _before_image_url(complaint_id) -> str | None:
    with TestingSessionLocal() as db:
        latest = (db.query(WasteAIResult)
                  .filter(WasteAIResult.complaint_id == complaint_id)
                  .order_by(WasteAIResult.created_at.desc(), WasteAIResult.id.desc())
                  .first())
        return latest.image_url if latest else None


def _make_task(prefix, with_before_image=True):
    """Citizen complaint (+BEFORE image) + assigned CleanupTask via DB insert."""
    cit_uid, cit_hdrs = _register_and_login(f"{prefix}-cit@example.com")
    complaint = _create_complaint(cit_hdrs)
    if with_before_image:
        _upload_complaint_image(cit_hdrs, complaint["tracking_id"])
    cleaner_uid, cleaner_hdrs = _register_and_login(f"{prefix}-clean@example.com")
    _promote(cleaner_uid, "cleaner")
    admin_uid, admin_hdrs = _register_and_login(f"{prefix}-adm@example.com")
    _promote(admin_uid, "admin")

    with TestingSessionLocal() as db:
        complaint_row = db.query(Complaint).filter(Complaint.id == complaint["id"]).one()
        complaint_row.status = "in_progress"   # mirror the real post-assignment state
        task = CleanupTask(
            complaint_id=complaint["id"],
            assigned_cleaner_id=cleaner_uid,
            status="assigned",
            notes="Step 5 test task",
        )
        db.add(task)
        db.commit()
        task_id = task.task_id

    return {
        "citizen_uid": cit_uid, "citizen_hdrs": cit_hdrs,
        "cleaner_uid": cleaner_uid, "cleaner_hdrs": cleaner_hdrs,
        "admin_hdrs": admin_hdrs,
        "complaint": complaint, "task_id": task_id,
        "before_url": _before_image_url(complaint["id"]) if with_before_image else None,
    }


def _upload_proof(headers, task_id, payload=JPEG_HEAD, mime="image/jpeg", filename="after.jpg"):
    return client.post(
        f"/cleaner/tasks/{task_id}/proof",
        headers=headers,
        files={"file": (filename, payload, mime)},
    )


def _start_task(headers, task_id):
    return client.post(f"/cleaner/tasks/{task_id}/start", headers=headers)


def _proof_row(proof_id) -> CleanupProof:
    with TestingSessionLocal() as db:
        db.expire_all()
        return db.query(CleanupProof).filter(CleanupProof.id == proof_id).one()


def _task_row(task_id) -> CleanupTask:
    with TestingSessionLocal() as db:
        db.expire_all()
        return db.query(CleanupTask).filter(CleanupTask.task_id == task_id).one()


def _complaint_row(complaint_id) -> Complaint:
    with TestingSessionLocal() as db:
        db.expire_all()
        return db.query(Complaint).filter(Complaint.id == complaint_id).one()


CLEANUP_OK = {
    "after_image_usable": True,
    "unusable_reason": None,
    "cleanup_appears_complete": True,
    "confidence": 0.95,
    "reasoning": "Waste is gone; the ground is clear.",
    "admin_review_recommended": False,
}


# ===========================================================================
# STEP 5 — CLEANER WORKFLOW
# ===========================================================================
def test_1_step4_handoff_creates_task_with_status_assigned():
    ctx = _make_task("s5-handoff", with_before_image=False)
    # Real Step-4 + assignment flow on a fresh complaint:
    uid, hdrs = _register_and_login("s5-handoff2-cit@example.com")
    complaint = _create_complaint(hdrs)
    admin_uid, admin_hdrs = _register_and_login("s5-handoff2-adm@example.com")
    _promote(admin_uid, "admin")

    decision = client.put(f"/admin/complaints/{complaint['id']}/decision",
                          headers=admin_hdrs, json={"decision": "assign_cleaner"})
    assert decision.status_code == 200
    assert decision.json()["cleanup_task"]["status"] == "assigned"   # handoff state

    cleaner_uid, _ = _register_and_login("s5-handoff2-clean@example.com")
    _promote(cleaner_uid, "cleaner")
    assigned = client.post(f"/admin/complaints/{complaint['id']}/assign",
                           headers=admin_hdrs, json={"cleaner_id": cleaner_uid})
    assert assigned.status_code == 200
    assert assigned.json()["status"] == "assigned"
    assert assigned.json()["assigned_cleaner_id"] == cleaner_uid
    # Reuse, not duplicate: the task created by the decision is the one assigned.
    assert _task_row(decision.json()["cleanup_task"]["task_id"]).assigned_cleaner_id == cleaner_uid


def test_2_assigned_cleaner_can_view_their_task():
    ctx = _make_task("s5-view")
    tasks = client.get("/cleaner/tasks", headers=ctx["cleaner_hdrs"])
    assert tasks.status_code == 200
    mine = [t for t in tasks.json() if t["task_id"] == ctx["task_id"]]
    assert len(mine) == 1
    detail = client.get(f"/cleaner/tasks/{ctx['task_id']}", headers=ctx["cleaner_hdrs"])
    assert detail.status_code == 200
    assert detail.json()["task_id"] == ctx["task_id"]


def test_3_other_cleaner_cannot_view_the_task():
    ctx = _make_task("s5-view2")
    other_uid, other_hdrs = _register_and_login("s5-view2-other@example.com")
    _promote(other_uid, "cleaner")
    assert client.get(f"/cleaner/tasks/{ctx['task_id']}", headers=other_hdrs).status_code == 403
    listing = client.get("/cleaner/tasks", headers=other_hdrs)
    assert all(t["task_id"] != ctx["task_id"] for t in listing.json())


def test_4_citizen_cannot_access_cleaner_task_endpoints():
    ctx = _make_task("s5-cit")
    assert client.get("/cleaner/tasks", headers=ctx["citizen_hdrs"]).status_code == 403
    assert client.get(f"/cleaner/tasks/{ctx['task_id']}",
                      headers=ctx["citizen_hdrs"]).status_code == 403


def test_5_assigned_cleaner_can_start_task():
    ctx = _make_task("s5-start", with_before_image=False)
    response = _start_task(ctx["cleaner_hdrs"], ctx["task_id"])
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"


def test_6_other_cleaner_cannot_start_task():
    ctx = _make_task("s5-start2", with_before_image=False)
    other_uid, other_hdrs = _register_and_login("s5-start2-other@example.com")
    _promote(other_uid, "cleaner")
    assert _start_task(other_hdrs, ctx["task_id"]).status_code == 403


def test_7_citizen_cannot_start_task():
    ctx = _make_task("s5-start3", with_before_image=False)
    assert _start_task(ctx["citizen_hdrs"], ctx["task_id"]).status_code == 403


def test_8_assigned_to_in_progress_transition():
    ctx = _make_task("s5-trans", with_before_image=False)
    assert _task_row(ctx["task_id"]).status == "assigned"
    _start_task(ctx["cleaner_hdrs"], ctx["task_id"])
    assert _task_row(ctx["task_id"]).status == "in_progress"


def test_9_invalid_status_jump_rejected():
    ctx = _make_task("s5-jump")
    _start_task(ctx["cleaner_hdrs"], ctx["task_id"])          # -> in_progress
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])        # -> proof_submitted
    # Starting from proof_submitted is not a valid transition:
    response = _start_task(ctx["cleaner_hdrs"], ctx["task_id"])
    assert response.status_code == 400
    assert _task_row(ctx["task_id"]).status == "proof_submitted"


# ===========================================================================
# STEP 6 — PROOF UPLOAD
# ===========================================================================
def test_10_assigned_cleaner_can_upload_jpeg():
    ctx = _make_task("s6-jpeg")
    response = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"],
                             JPEG_HEAD, "image/jpeg", "a.jpg")
    assert response.status_code == 201, response.text
    assert response.json()["image_url"].startswith("/uploads/proof_")
    assert response.json()["image_url"].endswith(".jpg")


def test_11_assigned_cleaner_can_upload_png():
    ctx = _make_task("s6-png")
    response = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"],
                             PNG_HEAD, "image/png", "a.png")
    assert response.status_code == 201
    assert response.json()["image_url"].endswith(".png")


def test_12_assigned_cleaner_can_upload_webp():
    ctx = _make_task("s6-webp")
    response = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"],
                             WEBP_HEAD, "image/webp", "a.webp")
    assert response.status_code == 201
    assert response.json()["image_url"].endswith(".webp")


def test_13_invalid_mime_rejected():
    ctx = _make_task("s6-badmime")
    response = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"],
                             PNG_HEAD, "image/gif", "a.png")
    assert response.status_code == 422


def test_14_invalid_magic_bytes_rejected():
    ctx = _make_task("s6-badmagic")
    response = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"],
                             GIF_HEAD, "image/png", "a.png")
    assert response.status_code == 422


def test_15_oversized_image_rejected():
    ctx = _make_task("s6-big")
    big = JPEG_HEAD + b"\x00" * (image_utils.MAX_IMAGE_BYTES + 1)
    response = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"],
                             big, "image/jpeg", "big.jpg")
    assert response.status_code == 422


def test_16_other_cleaner_cannot_upload_proof():
    ctx = _make_task("s6-other")
    other_uid, other_hdrs = _register_and_login("s6-other2-clean@example.com")
    _promote(other_uid, "cleaner")
    assert _upload_proof(other_hdrs, ctx["task_id"]).status_code == 403


def test_17_citizen_cannot_upload_proof():
    ctx = _make_task("s6-cit")
    assert _upload_proof(ctx["citizen_hdrs"], ctx["task_id"]).status_code == 403


def test_18_proof_created_correctly():
    ctx = _make_task("s6-create")
    response = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    assert response.status_code == 201
    row = _proof_row(response.json()["id"])
    assert row.task_id == _task_row(ctx["task_id"]).id
    assert row.uploaded_by == ctx["cleaner_uid"]
    assert row.verification_status == "pending_verification"
    assert row.verified_by is None and row.verified_at is None


def test_19_before_image_reference_is_correct():
    ctx = _make_task("s6-before")           # complaint HAS a before image
    response = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    assert response.status_code == 201
    row = _proof_row(response.json()["id"])
    assert row.before_image_url == ctx["before_url"]
    assert row.before_image_url != row.image_url


def test_20_after_image_stored_correctly():
    ctx = _make_task("s6-store")
    response = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"],
                             JPEG_HEAD, "image/jpeg", "after.jpg")
    assert response.status_code == 201
    image_url = response.json()["image_url"]
    filename = image_url.rsplit("/", 1)[1]
    assert filename.startswith("proof_")          # UUID name, never client-controlled
    assert (image_utils.UPLOADS_DIR / filename).is_file()


def test_21_task_becomes_proof_submitted():
    ctx = _make_task("s6-status")
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    assert _task_row(ctx["task_id"]).status == "proof_submitted"


# ===========================================================================
# STEP 6.6 — CLEANUP AI VERIFICATION (background, fail-open)
# ===========================================================================
def test_22_ai_success_stores_all_ai_fields():
    ctx = _make_task("s6-ai-ok")
    _mock_cleanup(CLEANUP_OK)
    response = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    assert response.status_code == 201
    row = _proof_row(response.json()["id"])
    assert row.ai_after_image_usable is True
    assert row.ai_unusable_reason is None
    assert row.ai_cleanup_appears_complete is True
    assert row.ai_confidence == pytest.approx(0.95)
    assert row.ai_reasoning == CLEANUP_OK["reasoning"]
    assert row.ai_admin_review_recommended is False
    assert row.ai_processed_at is not None
    assert row.ai_errors_json is None
    assert row.verification_status == "pending_verification"   # human decision untouched


def test_23_ai_failure_preserves_proof_and_task():
    ctx = _make_task("s6-ai-fail")
    _mock_cleanup(None)                                   # AI fails
    response = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    assert response.status_code == 201
    proof_id = response.json()["id"]
    row = _proof_row(proof_id)
    assert row is not None                                # proof survives
    assert row.verification_status == "pending_verification"
    assert row.ai_cleanup_appears_complete is None        # nothing fabricated
    assert "AI_TIMEOUT" in row.ai_errors_json
    assert _task_row(ctx["task_id"]).status == "proof_submitted"   # task usable


def test_24_ai_failure_does_not_verify_proof_or_resolve_complaint():
    ctx = _make_task("s6-ai-fail2")
    _mock_cleanup(None)
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    assert _proof_row(_proof_rows(ctx)[0].id).verification_status == "pending_verification"
    assert _complaint_row(ctx["complaint"]["id"]).status == "in_progress"


def _proof_rows(ctx):
    with TestingSessionLocal() as db:
        db.expire_all()
        task = db.query(CleanupTask).filter(CleanupTask.task_id == ctx["task_id"]).one()
        return list(task.proofs)


def test_25_low_confidence_sets_admin_review_recommendation():
    ctx = _make_task("s6-ai-low")
    _mock_cleanup({**CLEANUP_OK, "confidence": 0.4, "admin_review_recommended": None})
    response = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    row = _proof_row(response.json()["id"])
    assert row.ai_confidence == pytest.approx(0.4)
    assert row.ai_admin_review_recommended is True        # confidence < 0.7 rule


def test_26_ai_result_does_not_change_task_to_verified():
    ctx = _make_task("s6-ai-notverified")
    _mock_cleanup(CLEANUP_OK)                             # AI "recommends completion"
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    assert _task_row(ctx["task_id"]).status == "proof_submitted"   # NOT verified


def test_27_ai_result_does_not_resolve_complaint():
    ctx = _make_task("s6-ai-notresolved")
    _mock_cleanup(CLEANUP_OK)
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    assert _complaint_row(ctx["complaint"]["id"]).status == "in_progress"


def test_28_ai_subprocess_errors_stored_safely():
    ctx = _make_task("s6-ai-exit")
    def fake(*args, **kwargs):
        return {"success": False, "result": None, "error": "AI_EXIT_3",
                "details": "AI import failed", "latency_ms": 9}
    ai_client.verify_cleanup = fake
    response = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    row = _proof_row(response.json()["id"])
    assert "AI_EXIT_3" in row.ai_errors_json
    assert "Traceback" not in (row.ai_errors_json or "")   # controlled detail only
    assert row.ai_processed_at is not None


def test_29_background_ai_invoked_with_before_and_after_images():
    ctx = _make_task("s6-ai-args")
    calls = []
    _mock_cleanup(CLEANUP_OK, calls)
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    assert len(calls) == 1
    before_bytes, after_bytes = calls[0]["args"][0], calls[0]["args"][1]
    assert before_bytes[:3] == b"\xff\xd8\xff"            # real BEFORE bytes read from disk
    assert after_bytes[:3] == b"\xff\xd8\xff"             # real AFTER bytes read from disk
    assert calls[0]["kwargs"]["before_mime"] == "image/jpeg"
    assert calls[0]["kwargs"]["after_mime"] == "image/jpeg"


# ===========================================================================
# STEP 7 — ADMIN REVIEW + FINAL VERIFICATION
# ===========================================================================
def test_30_admin_can_view_proof_review():
    ctx = _make_task("s7-view")
    _mock_cleanup(CLEANUP_OK)
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    response = client.get(f"/admin/tasks/{ctx['task_id']}/proof", headers=ctx["admin_hdrs"])
    assert response.status_code == 200
    body = response.json()
    assert body["tracking_id"] == ctx["complaint"]["tracking_id"]
    assert body["task_status"] == "proof_submitted"
    assert body["complaint_text"]
    assert len(body["proofs"]) == 1
    proof = body["proofs"][0]
    assert proof["image_url"].startswith("/uploads/proof_")
    assert proof["before_image_url"] == ctx["before_url"]
    assert proof["ai_cleanup_appears_complete"] is True
    assert proof["ai_confidence"] == pytest.approx(0.95)
    assert proof["ai_reasoning"] == CLEANUP_OK["reasoning"]
    assert proof["ai_admin_review_recommended"] is False
    assert proof["ai_errors"] is None


def test_31_citizen_cannot_view_admin_proof_review():
    ctx = _make_task("s7-view2")
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    response = client.get(f"/admin/tasks/{ctx['task_id']}/proof",
                          headers=ctx["citizen_hdrs"])
    assert response.status_code == 403


def test_32_cleaner_cannot_perform_final_verification():
    ctx = _make_task("s7-cleanver")
    upload = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    proof_id = upload.json()["id"]
    response = client.post(f"/admin/proofs/{proof_id}/verify",
                           headers=ctx["cleaner_hdrs"], json={"approved": True})
    assert response.status_code == 403


def test_33_admin_can_verify_proof():
    ctx = _make_task("s7-verify")
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    proof_id = _proof_rows(ctx)[0].id
    response = client.post(f"/admin/proofs/{proof_id}/verify",
                           headers=ctx["admin_hdrs"],
                           json={"approved": True, "next_status": "resolved"})
    assert response.status_code == 200
    assert response.json()["verification_status"] == "verified"
    assert response.json()["verified_at"]


def test_34_admin_can_reject_proof():
    ctx = _make_task("s7-reject")
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    proof_id = _proof_rows(ctx)[0].id
    response = client.post(f"/admin/proofs/{proof_id}/verify",
                           headers=ctx["admin_hdrs"],
                           json={"approved": False, "rejection_reason": "Waste still visible."})
    assert response.status_code == 200
    assert response.json()["verification_status"] == "rejected"


def test_35_verified_proof_changes_task_to_verified():
    ctx = _make_task("s7-taskver")
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    proof_id = _proof_rows(ctx)[0].id
    client.post(f"/admin/proofs/{proof_id}/verify", headers=ctx["admin_hdrs"],
                json={"approved": True})
    assert _task_row(ctx["task_id"]).status == "verified"
    assert _proof_row(proof_id).verification_status == "verified"


def test_36_rejected_proof_changes_task_to_rejected():
    ctx = _make_task("s7-taskrej")
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    proof_id = _proof_rows(ctx)[0].id
    client.post(f"/admin/proofs/{proof_id}/verify", headers=ctx["admin_hdrs"],
                json={"approved": False, "rejection_reason": "not clean"})
    assert _task_row(ctx["task_id"]).status == "rejected"
    assert _proof_row(proof_id).verification_status == "rejected"


def test_37_verified_proof_resolves_complaint_through_lifecycle():
    ctx = _make_task("s7-resolve")
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    proof_id = _proof_rows(ctx)[0].id
    response = client.post(f"/admin/proofs/{proof_id}/verify", headers=ctx["admin_hdrs"],
                           json={"approved": True, "next_status": "resolved"})
    assert response.status_code == 200
    assert response.json()["complaint_status"] == "resolved"
    assert _complaint_row(ctx["complaint"]["id"]).resolved_at is not None


def test_38_rejected_proof_does_not_resolve_complaint():
    ctx = _make_task("s7-notresolve")
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    proof_id = _proof_rows(ctx)[0].id
    client.post(f"/admin/proofs/{proof_id}/verify", headers=ctx["admin_hdrs"],
                json={"approved": False, "rejection_reason": "retry needed"})
    assert _complaint_row(ctx["complaint"]["id"]).status == "in_progress"


def test_39_cleaner_cannot_approve_own_proof():
    ctx = _make_task("s7-selfapprove")
    upload = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    proof_id = upload.json()["id"]
    # The very cleaner who uploaded attempts to verify their own proof:
    response = client.post(f"/admin/proofs/{proof_id}/verify",
                           headers=ctx["cleaner_hdrs"], json={"approved": True})
    assert response.status_code == 403
    assert _proof_row(proof_id).verification_status == "pending_verification"


# ===========================================================================
# HISTORY / APPEND-ONLY
# ===========================================================================
def test_40_rejected_proof_remains_in_database():
    ctx = _make_task("s8-history")
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    proof1_id = _proof_rows(ctx)[0].id
    client.post(f"/admin/proofs/{proof1_id}/verify", headers=ctx["admin_hdrs"],
                json={"approved": False, "rejection_reason": "blurry"})
    row = _proof_row(proof1_id)
    assert row.verification_status == "rejected"
    assert row.rejection_reason == "blurry"


def test_41_new_proof_does_not_overwrite_historical_proof():
    ctx = _make_task("s8-history2")
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    proof1_id = _proof_rows(ctx)[0].id
    client.post(f"/admin/proofs/{proof1_id}/verify", headers=ctx["admin_hdrs"],
                json={"approved": False, "rejection_reason": "blurry"})
    # Resubmission (existing architecture supports it after rejection):
    second = _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    assert second.status_code == 201
    proofs = _proof_rows(ctx)
    assert len(proofs) == 2
    statuses = {p.id: p.verification_status for p in proofs}
    assert statuses[proof1_id] == "rejected"                      # history intact
    assert statuses[second.json()["id"]] == "pending_verification"
    assert _task_row(ctx["task_id"]).status == "proof_submitted"
    # Admin review surfaces both attempts, oldest first:
    review = client.get(f"/admin/tasks/{ctx['task_id']}/proof", headers=ctx["admin_hdrs"])
    assert [p["id"] for p in review.json()["proofs"]] == [proof1_id, second.json()["id"]]


def test_42_waste_ai_result_history_remains_unchanged():
    ctx = _make_task("s8-wasteai")            # complaint image -> one WasteAIResult
    with TestingSessionLocal() as db:
        before = (db.query(WasteAIResult)
                  .filter(WasteAIResult.complaint_id == ctx["complaint"]["id"])
                  .order_by(WasteAIResult.id.asc()).all())
        snapshot = [(r.id, r.ai_status, r.waste_type, r.image_url) for r in before]

    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    client.post(f"/admin/proofs/{_proof_rows(ctx)[0].id}/verify",
                headers=ctx["admin_hdrs"], json={"approved": True})

    with TestingSessionLocal() as db:
        after = (db.query(WasteAIResult)
                 .filter(WasteAIResult.complaint_id == ctx["complaint"]["id"])
                 .order_by(WasteAIResult.id.asc()).all())
        assert [(r.id, r.ai_status, r.waste_type, r.image_url) for r in after] == snapshot


# ===========================================================================
# EVENT LOGGING
# ===========================================================================
def _activities(tracking_id):
    with TestingSessionLocal() as db:
        return [e.activity for e in
                db.query(EventLog).filter(EventLog.case_id == tracking_id).all()]


def test_43_workflow_events_recorded_with_existing_vocabulary():
    ctx = _make_task("s9-events", with_before_image=False)
    _start_task(ctx["cleaner_hdrs"], ctx["task_id"])
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    proof_id = _proof_rows(ctx)[0].id
    client.post(f"/admin/proofs/{proof_id}/verify", headers=ctx["admin_hdrs"],
                json={"approved": True})
    activities = _activities(ctx["complaint"]["tracking_id"])
    assert "task_started" in activities
    assert "proof_submitted" in activities
    assert "proof_verified" in activities
    assert "complaint_resolved" in activities


def test_44_failed_ai_verification_not_logged_as_success():
    ctx = _make_task("s9-events2")
    _mock_cleanup(None)                                   # AI fails
    _upload_proof(ctx["cleaner_hdrs"], ctx["task_id"])
    activities = _activities(ctx["complaint"]["tracking_id"])
    assert "proof_submitted" in activities                # the human upload is real
    assert "proof_verified" not in activities             # AI failure is NOT a verification
