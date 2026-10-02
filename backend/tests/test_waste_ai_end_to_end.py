# tests/test_waste_ai_end_to_end.py
# STEP 8: End-to-End Backend Integration Tests for SmartTracker AI.
#
# Proves that the complete backend workflow works as one connected system
# across Citizen, Waste AI, Admin, Cleaner, Cleanup AI, and Final Admin Verification.
#
# NO test calls real Gemini: backend.ai_client.analyze_waste_image and
# backend.ai_client.verify_cleanup are mocked with deterministic responses.

import io
import json
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
    User,
    WasteAIResult,
)

# Valid magic byte header sequences for test image payloads
JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"\x00" * 16
PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _jpeg_bytes(size: int = 100) -> bytes:
    return JPEG_HEAD + b"\x00" * max(0, size - len(JPEG_HEAD))


def _png_bytes(size: int = 100) -> bytes:
    return PNG_HEAD + b"\x00" * max(0, size - len(PNG_HEAD))


@pytest.fixture(autouse=True)
def _e2e_isolation(monkeypatch):
    """Isolate DB per test and mock AI calls deterministically."""
    monkeypatch.setattr(
        ai_client,
        "analyze_waste_image",
        lambda *a, **k: {
            "success": False,
            "result": None,
            "error": "NOT_MOCKED",
            "details": None,
            "latency_ms": 0,
        },
    )
    monkeypatch.setattr(
        ai_client,
        "verify_cleanup",
        lambda *a, **k: {
            "success": False,
            "result": None,
            "error": "NOT_MOCKED",
            "details": None,
            "latency_ms": 0,
        },
    )
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
        db.query(User).filter(User.email.like("e2e-%")).delete()
        db.query(User).filter(User.email.like("%-cit@example.com")).delete()
        db.query(User).filter(User.email.like("%-adm@example.com")).delete()
        db.query(User).filter(User.email.like("%-cln@example.com")).delete()
        db.commit()


def _register_and_login(email, role="citizen", password="Password123!"):
    register = client.post(
        "/auth/register",
        json={"name": f"User {email}", "email": email, "password": password},
    )
    assert register.status_code == 201, register.text
    user_id = register.json()["id"]

    if role != "citizen":
        with TestingSessionLocal() as db:
            db.query(User).filter(User.id == user_id).one().role = role
            db.commit()

    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return user_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


# ===========================================================================
# 1. MAIN HAPPY-PATH INTEGRATION TEST & DATABASE CHAIN ASSERTIONS
# ===========================================================================
def test_e2e_main_happy_path_lifecycle(monkeypatch):
    """Full lifecycle: Citizen complaint -> Waste AI -> Admin review & decision ->
    Cleaner assignment -> Cleaner start & proof upload -> Cleanup AI verification ->
    Admin final verification -> Complaint resolved.
    Also validates all database chain relationships and status transitions.
    """
    # A. Setup roles
    cit_id, cit_hdrs = _register_and_login("e2e-citizen@example.com", "citizen")
    adm_id, adm_hdrs = _register_and_login("e2e-admin@example.com", "admin")
    cln_id, cln_hdrs = _register_and_login("e2e-cleaner@example.com", "cleaner")

    # B. Citizen creates complaint
    create_res = client.post(
        "/complaints/",
        headers=cit_hdrs,
        json={
            "complaint_text": "Large dry waste dump obstructing walkway.",
            "latitude": 19.0760,
            "longitude": 72.8777,
            "address_text": "Main Street Market",
        },
    )
    assert create_res.status_code == 201, create_res.text
    tracking_id = create_res.json()["tracking_id"]

    with TestingSessionLocal() as db:
        complaint_db = (
            db.query(Complaint).filter(Complaint.tracking_id == tracking_id).one()
        )
        complaint_id = complaint_db.id
        assert complaint_db.status == "pending"

    # D & E. Citizen uploads valid JPEG waste image with deterministic Waste AI mock
    waste_ai_payload = {
        "image_usable": True,
        "unusable_reason": None,
        "waste_type": "dry",
        "waste_type_confidence": 0.92,
        "severity": "moderate",
        "severity_confidence": 0.88,
        "reasoning": "Test integration result",
        "follow_up_question": None,
        "recurring_flag": False,
        "escalate_to_authority": False,
        "needs_human_review": False,
        "review_reasons": [],
        "disposal_guidance": "Dispose through dry-waste collection.",
        "errors": [],
    }

    monkeypatch.setattr(
        ai_client,
        "analyze_waste_image",
        lambda *a, **k: {
            "success": True,
            "result": dict(waste_ai_payload),
            "error": None,
            "details": None,
            "latency_ms": 120,
        },
    )

    img_res = client.post(
        f"/complaints/{tracking_id}/image",
        headers=cit_hdrs,
        files={"file": ("waste.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )
    assert img_res.status_code == 200, img_res.text
    # HTTP response returns pending at upload moment; background task completes immediately after
    assert img_res.json()["ai_status"] == "pending"

    # F, G, H. Verify WasteAIResult in DB and vocabulary verbatim
    with TestingSessionLocal() as db:
        ai_row = (
            db.query(WasteAIResult)
            .filter(WasteAIResult.complaint_id == complaint_id)
            .one()
        )
        assert ai_row.ai_status == "completed"
        assert ai_row.waste_type == "dry"
        assert ai_row.waste_type_confidence == pytest.approx(0.92)
        assert ai_row.severity == "moderate"
        assert ai_row.severity_confidence == pytest.approx(0.88)
        assert ai_row.disposal_guidance == "Dispose through dry-waste collection."
        before_image_url = ai_row.image_url
        assert before_image_url.startswith("/uploads/complaints/complaint_")

    # J. Admin retrieves AI review
    rev_res = client.get(
        f"/admin/complaints/{complaint_id}/ai-review", headers=adm_hdrs
    )
    assert rev_res.status_code == 200, rev_res.text
    assert rev_res.json()["analysis"]["ai_status"] == "completed"
    assert rev_res.json()["analysis"]["waste_type"] == "dry"
    assert rev_res.json()["analysis"]["severity"] == "moderate"

    # K & L. Admin decision: assign_cleaner
    dec_res = client.put(
        f"/admin/complaints/{complaint_id}/decision",
        headers=adm_hdrs,
        json={"decision": "assign_cleaner", "note": "Dispatch team for cleanup"},
    )
    assert dec_res.status_code == 200, dec_res.text
    task_id = dec_res.json()["cleanup_task"]["task_id"]

    with TestingSessionLocal() as db:
        dec_row = (
            db.query(AdminDecision)
            .filter(AdminDecision.complaint_id == complaint_id)
            .one()
        )
        assert dec_row.decision == "assign_cleaner"
        assert dec_row.admin_id == adm_id

        task_db = db.query(CleanupTask).filter(CleanupTask.task_id == task_id).one()
        assert task_db.status == "assigned"
        assert task_db.assigned_cleaner_id is None
        # Complaint status is updated to in_progress, but complaint is NOT resolved
        complaint_chk = (
            db.query(Complaint).filter(Complaint.id == complaint_id).one()
        )
        assert complaint_chk.status == "in_progress"
        assert complaint_chk.resolved_at is None

    # M & N. Admin assigns cleaner via existing assignment endpoint
    assign_res = client.post(
        f"/admin/complaints/{complaint_id}/assign",
        headers=adm_hdrs,
        json={"cleaner_id": cln_id, "notes": "Please clean before 5 PM"},
    )
    assert assign_res.status_code == 200, assign_res.text
    assert assign_res.json()["assigned_cleaner_id"] == cln_id

    # P. Cleaner starts task
    start_res = client.post(f"/cleaner/tasks/{task_id}/start", headers=cln_hdrs)
    assert start_res.status_code == 200, start_res.text
    assert start_res.json()["status"] == "in_progress"

    # Q & R. Cleaner uploads cleanup proof with mocked Cleanup AI verification
    cleanup_ai_payload = {
        "after_image_usable": True,
        "unusable_reason": None,
        "cleanup_appears_complete": True,
        "confidence": 0.95,
        "reasoning": "Test cleanup appears complete.",
        "admin_review_recommended": False,
    }

    monkeypatch.setattr(
        ai_client,
        "verify_cleanup",
        lambda *a, **k: {
            "success": True,
            "result": dict(cleanup_ai_payload),
            "error": None,
            "details": None,
            "latency_ms": 150,
        },
    )

    proof_upload_res = client.post(
        f"/cleaner/tasks/{task_id}/proof",
        headers=cln_hdrs,
        files={"file": ("proof.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )
    assert proof_upload_res.status_code == 201, proof_upload_res.text
    proof_id = proof_upload_res.json()["id"]

    # S, T, U. Verify CleanupProof fields & CleanupTask status in_progress -> proof_submitted
    with TestingSessionLocal() as db:
        task_chk = db.query(CleanupTask).filter(CleanupTask.task_id == task_id).one()
        assert task_chk.status == "proof_submitted"

        proof_db = db.query(CleanupProof).filter(CleanupProof.id == proof_id).one()
        assert proof_db.verification_status == "pending_verification"
        assert proof_db.ai_cleanup_appears_complete is True
        assert proof_db.ai_confidence == pytest.approx(0.95)
        assert proof_db.ai_reasoning == "Test cleanup appears complete."
        after_image_url = proof_db.image_url
        assert after_image_url.startswith("/uploads/proof_")

        # Database Chain Assertions:
        assert proof_db.before_image_url == before_image_url
        assert proof_db.before_image_url != proof_db.image_url
        assert proof_db.task_id == task_chk.id
        assert task_chk.complaint_id == complaint_id

    # V. Admin retrieves task proof review
    admin_proof_res = client.get(
        f"/admin/tasks/{task_id}/proof", headers=adm_hdrs
    )
    assert admin_proof_res.status_code == 200, admin_proof_res.text
    proofs_list = admin_proof_res.json()["proofs"]
    assert len(proofs_list) == 1
    assert proofs_list[0]["ai_cleanup_appears_complete"] is True

    # W & X. Admin performs final proof verification
    verify_res = client.post(
        f"/admin/proofs/{proof_id}/verify",
        headers=adm_hdrs,
        json={"approved": True, "next_status": "resolved"},
    )
    assert verify_res.status_code == 200, verify_res.text
    assert verify_res.json()["verification_status"] == "verified"
    assert verify_res.json()["complaint_status"] == "resolved"

    # Final DB checks
    with TestingSessionLocal() as db:
        proof_fin = db.query(CleanupProof).filter(CleanupProof.id == proof_id).one()
        assert proof_fin.verification_status == "verified"
        assert proof_fin.verified_by == adm_id

        task_fin = db.query(CleanupTask).filter(CleanupTask.task_id == task_id).one()
        assert task_fin.status == "verified"

        complaint_fin = (
            db.query(Complaint).filter(Complaint.id == complaint_id).one()
        )
        assert complaint_fin.status == "resolved"
        assert complaint_fin.resolved_at is not None

        # Y. Verify relevant EventLog entries
        events = [
            e.activity
            for e in db.query(EventLog)
            .filter(EventLog.case_id == tracking_id)
            .order_by(EventLog.timestamp.asc())
            .all()
        ]
        assert "complaint_created" in events
        assert "admin_decision_made" in events
        assert "cleaner_assigned" in events
        assert "task_started" in events
        assert "proof_submitted" in events
        assert "proof_verified" in events
        assert "complaint_resolved" in events


# ===========================================================================
# 2. WASTE AI FAILURE INTEGRATION TEST
# ===========================================================================
def test_e2e_waste_ai_failure_flow(monkeypatch):
    """Citizen creates complaint -> uploads valid image -> Waste AI fails.
    Verify: complaint remains, WasteAIResult status=failed, error info stored,
    complaint NOT deleted, no fake predictions invented, manual workflow works.
    """
    _, cit_hdrs = _register_and_login("waste-fail-cit@example.com", "citizen")
    _, adm_hdrs = _register_and_login("waste-fail-adm@example.com", "admin")

    create_res = client.post(
        "/complaints/",
        headers=cit_hdrs,
        json={"complaint_text": "Garbage near public park."},
    )
    tracking_id = create_res.json()["tracking_id"]

    # Mock Waste AI failure
    monkeypatch.setattr(
        ai_client,
        "analyze_waste_image",
        lambda *a, **k: {
            "success": False,
            "result": None,
            "error": "AI_TIMEOUT",
            "details": "Subprocess timed out after 120s",
            "latency_ms": 120000,
        },
    )

    upload_res = client.post(
        f"/complaints/{tracking_id}/image",
        headers=cit_hdrs,
        files={"file": ("waste.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    assert upload_res.status_code == 200
    assert upload_res.json()["ai_status"] == "pending"

    with TestingSessionLocal() as db:
        complaint = (
            db.query(Complaint).filter(Complaint.tracking_id == tracking_id).one()
        )
        assert complaint.status == "pending"
        ai_result = (
            db.query(WasteAIResult)
            .filter(WasteAIResult.complaint_id == complaint.id)
            .one()
        )
        assert ai_result.ai_status == "failed"
        assert ai_result.waste_type is None
        assert ai_result.severity is None
        errors = json.loads(ai_result.errors_json)
        assert errors[0]["error"] == "AI_TIMEOUT"

    # Admin can still retrieve review and make manual decision
    review_res = client.get(
        f"/admin/complaints/{complaint.id}/ai-review", headers=adm_hdrs
    )
    assert review_res.status_code == 200
    assert review_res.json()["analysis"]["ai_status"] == "failed"

    dec_res = client.put(
        f"/admin/complaints/{complaint.id}/decision",
        headers=adm_hdrs,
        json={"decision": "dismiss", "note": "Manual review dismiss"},
    )
    assert dec_res.status_code == 200
    assert dec_res.json()["complaint_status"] == "closed"


# ===========================================================================
# 3. CLEANUP AI FAILURE INTEGRATION TEST
# ===========================================================================
def test_e2e_cleanup_ai_failure_flow(monkeypatch):
    """Complaint -> Admin decision -> Cleaner assignment -> Cleaner starts ->
    Cleaner uploads proof -> Cleanup AI fails.
    Verify: CleanupProof remains, CleanupTask remains proof_submitted, AI error stored,
    CleanupTask & CleanupProof NOT verified, Complaint NOT resolved, Admin can still review & verify.
    """
    cit_id, cit_hdrs = _register_and_login("clean-fail-cit@example.com", "citizen")
    adm_id, adm_hdrs = _register_and_login("clean-fail-adm@example.com", "admin")
    cln_id, cln_hdrs = _register_and_login("clean-fail-cln@example.com", "cleaner")

    create_res = client.post(
        "/complaints/",
        headers=cit_hdrs,
        json={"complaint_text": "Spilled garbage bags."},
    )
    tracking_id = create_res.json()["tracking_id"]

    # Upload complaint BEFORE image so before_image_url is populated for cleanup verification
    monkeypatch.setattr(
        ai_client,
        "analyze_waste_image",
        lambda *a, **k: {
            "success": True,
            "result": {
                "image_usable": True,
                "waste_type": "dry",
                "severity": "moderate",
                "recurring_flag": False,
                "escalate_to_authority": False,
                "needs_human_review": False,
                "review_reasons": [],
                "errors": [],
            },
            "error": None,
            "details": None,
            "latency_ms": 10,
        },
    )
    client.post(
        f"/complaints/{tracking_id}/image",
        headers=cit_hdrs,
        files={"file": ("before.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )

    with TestingSessionLocal() as db:
        complaint_id = (
            db.query(Complaint.id)
            .filter(Complaint.tracking_id == tracking_id)
            .scalar()
        )

    # Admin decision + assign
    client.put(
        f"/admin/complaints/{complaint_id}/decision",
        headers=adm_hdrs,
        json={"decision": "assign_cleaner"},
    )
    client.post(
        f"/admin/complaints/{complaint_id}/assign",
        headers=adm_hdrs,
        json={"cleaner_id": cln_id},
    )

    with TestingSessionLocal() as db:
        task = db.query(CleanupTask).filter(CleanupTask.complaint_id == complaint_id).one()
        task_id = task.task_id

    # Cleaner starts
    client.post(f"/cleaner/tasks/{task_id}/start", headers=cln_hdrs)

    # Mock Cleanup AI failure
    monkeypatch.setattr(
        ai_client,
        "verify_cleanup",
        lambda *a, **k: {
            "success": False,
            "result": None,
            "error": "AI_EXEC_ERROR",
            "details": "Model failed to run",
            "latency_ms": 50,
        },
    )

    proof_res = client.post(
        f"/cleaner/tasks/{task_id}/proof",
        headers=cln_hdrs,
        files={"file": ("after.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )
    assert proof_res.status_code == 201
    proof_id = proof_res.json()["id"]

    with TestingSessionLocal() as db:
        proof_db = db.query(CleanupProof).filter(CleanupProof.id == proof_id).one()
        assert proof_db.verification_status == "pending_verification"
        assert proof_db.ai_cleanup_appears_complete is None
        assert "AI_EXEC_ERROR" in proof_db.ai_errors_json

        task_db = db.query(CleanupTask).filter(CleanupTask.task_id == task_id).one()
        assert task_db.status == "proof_submitted"

        complaint_db = (
            db.query(Complaint).filter(Complaint.id == complaint_id).one()
        )
        assert complaint_db.status == "in_progress"

    # Admin can still retrieve proof and verify manually
    review_res = client.get(f"/admin/tasks/{task_id}/proof", headers=adm_hdrs)
    assert review_res.status_code == 200

    verify_res = client.post(
        f"/admin/proofs/{proof_id}/verify",
        headers=adm_hdrs,
        json={"approved": True, "next_status": "resolved"},
    )
    assert verify_res.status_code == 200
    assert verify_res.json()["verification_status"] == "verified"


# ===========================================================================
# 4. REJECTED PROOF INTEGRATION TEST
# ===========================================================================
def test_e2e_rejected_proof_flow(monkeypatch):
    """Complaint -> Cleaner assigned -> Cleaner starts -> Proof uploaded ->
    Cleanup AI complete -> Admin rejects proof.
    Verify: CleanupProof = rejected, CleanupTask = rejected, Complaint != resolved,
    proof preserved in database.
    """
    _, cit_hdrs = _register_and_login("rej-proof-cit@example.com", "citizen")
    _, adm_hdrs = _register_and_login("rej-proof-adm@example.com", "admin")
    cln_id, cln_hdrs = _register_and_login("rej-proof-cln@example.com", "cleaner")

    create_res = client.post(
        "/complaints/",
        headers=cit_hdrs,
        json={"complaint_text": "Debris pile near the walkway."},
    )
    tracking_id = create_res.json()["tracking_id"]
    with TestingSessionLocal() as db:
        complaint_id = (
            db.query(Complaint.id)
            .filter(Complaint.tracking_id == tracking_id)
            .scalar()
        )

    client.put(
        f"/admin/complaints/{complaint_id}/decision",
        headers=adm_hdrs,
        json={"decision": "assign_cleaner"},
    )
    client.post(
        f"/admin/complaints/{complaint_id}/assign",
        headers=adm_hdrs,
        json={"cleaner_id": cln_id},
    )

    with TestingSessionLocal() as db:
        task_id = (
            db.query(CleanupTask.task_id)
            .filter(CleanupTask.complaint_id == complaint_id)
            .scalar()
        )

    client.post(f"/cleaner/tasks/{task_id}/start", headers=cln_hdrs)

    monkeypatch.setattr(
        ai_client,
        "verify_cleanup",
        lambda *a, **k: {
            "success": True,
            "result": {
                "after_image_usable": True,
                "unusable_reason": None,
                "cleanup_appears_complete": True,
                "confidence": 0.9,
                "reasoning": "Looks clean",
                "admin_review_recommended": False,
            },
            "error": None,
            "details": None,
            "latency_ms": 100,
        },
    )

    proof_res = client.post(
        f"/cleaner/tasks/{task_id}/proof",
        headers=cln_hdrs,
        files={"file": ("after.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    proof_id = proof_res.json()["id"]

    # Admin rejects proof
    reject_res = client.post(
        f"/admin/proofs/{proof_id}/verify",
        headers=adm_hdrs,
        json={"approved": False, "rejection_reason": "Debris still visible on left side."},
    )
    assert reject_res.status_code == 200
    assert reject_res.json()["verification_status"] == "rejected"
    assert reject_res.json()["task_status"] == "rejected"

    with TestingSessionLocal() as db:
        proof_db = db.query(CleanupProof).filter(CleanupProof.id == proof_id).one()
        assert proof_db.verification_status == "rejected"
        assert proof_db.rejection_reason == "Debris still visible on left side."

        task_db = db.query(CleanupTask).filter(CleanupTask.task_id == task_id).one()
        assert task_db.status == "rejected"

        complaint_db = (
            db.query(Complaint).filter(Complaint.id == complaint_id).one()
        )
        assert complaint_db.status == "in_progress"
        assert complaint_db.resolved_at is None


# ===========================================================================
# 5. AUTHORIZATION INTEGRATION TESTS
# ===========================================================================
def test_e2e_cross_role_authorization_restrictions():
    """Verify cross-role restrictions:
    - Citizen MUST NOT: access admin AI review, make admin decisions, view cleaner tasks, upload proof, verify proof.
    - Cleaner MUST NOT: access another cleaner's task, start another's task, upload proof for another's task, verify proof.
    - Admin MUST BE ABLE TO: review AI, make decisions, assign cleaner, review proof, verify proof.
    """
    cit_id, cit_hdrs = _register_and_login("auth-cit@example.com", "citizen")
    adm_id, adm_hdrs = _register_and_login("auth-adm@example.com", "admin")
    cln1_id, cln1_hdrs = _register_and_login("auth-cln1@example.com", "cleaner")
    cln2_id, cln2_hdrs = _register_and_login("auth-cln2@example.com", "cleaner")

    create_res = client.post(
        "/complaints/", headers=cit_hdrs, json={"complaint_text": "Auth test complaint message"}
    )
    tracking_id = create_res.json()["tracking_id"]
    with TestingSessionLocal() as db:
        complaint_id = (
            db.query(Complaint.id)
            .filter(Complaint.tracking_id == tracking_id)
            .scalar()
        )

    # 1. Citizen authorization checks
    assert (
        client.get(
            f"/admin/complaints/{complaint_id}/ai-review", headers=cit_hdrs
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/admin/complaints/{complaint_id}/decision",
            headers=cit_hdrs,
            json={"decision": "dismiss"},
        ).status_code
        == 403
    )
    assert client.get("/cleaner/tasks", headers=cit_hdrs).status_code == 403

    # Admin makes decision and assigns Cleaner 1
    assert (
        client.put(
            f"/admin/complaints/{complaint_id}/decision",
            headers=adm_hdrs,
            json={"decision": "assign_cleaner"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/admin/complaints/{complaint_id}/assign",
            headers=adm_hdrs,
            json={"cleaner_id": cln1_id},
        ).status_code
        == 200
    )

    with TestingSessionLocal() as db:
        task_id = (
            db.query(CleanupTask.task_id)
            .filter(CleanupTask.complaint_id == complaint_id)
            .scalar()
        )

    # 2. Cleaner 2 authorization checks against Cleaner 1's task
    assert (
        client.get(f"/cleaner/tasks/{task_id}", headers=cln2_hdrs).status_code == 403
    )
    assert (
        client.post(f"/cleaner/tasks/{task_id}/start", headers=cln2_hdrs).status_code
        == 403
    )
    assert (
        client.post(
            f"/cleaner/tasks/{task_id}/proof",
            headers=cln2_hdrs,
            files={"file": ("p.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
        ).status_code
        == 403
    )

    # Cleaner 1 starts task and uploads proof
    assert (
        client.post(f"/cleaner/tasks/{task_id}/start", headers=cln1_hdrs).status_code
        == 200
    )
    proof_res = client.post(
        f"/cleaner/tasks/{task_id}/proof",
        headers=cln1_hdrs,
        files={"file": ("p.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )
    assert proof_res.status_code == 201
    proof_id = proof_res.json()["id"]

    # Cleaner 1 cannot perform admin verification on their own proof
    assert (
        client.post(
            f"/admin/proofs/{proof_id}/verify",
            headers=cln1_hdrs,
            json={"approved": True},
        ).status_code
        == 403
    )

    # 3. Admin authorization checks
    assert (
        client.get(f"/admin/tasks/{task_id}/proof", headers=adm_hdrs).status_code
        == 200
    )
    assert (
        client.post(
            f"/admin/proofs/{proof_id}/verify",
            headers=adm_hdrs,
            json={"approved": True},
        ).status_code
        == 200
    )


# ===========================================================================
# 6. IMAGE VALIDATION INTEGRATION
# ===========================================================================
def test_e2e_image_validation_formats_and_rejection(monkeypatch):
    """Test JPEG, PNG format validation and invalid payload rejection."""
    monkeypatch.setattr(waste_ai_service, "run_ai_analysis", lambda result_id: None)
    _, cit_hdrs = _register_and_login("imgval-citizen@example.com", "citizen")

    # Valid JPEG
    c1_res = client.post(
        "/complaints/", headers=cit_hdrs, json={"complaint_text": "JPEG test for valid format"}
    )
    assert c1_res.status_code == 201, c1_res.text
    c1 = c1_res.json()["tracking_id"]
    r1 = client.post(
        f"/complaints/{c1}/image",
        headers=cit_hdrs,
        files={"file": ("valid.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )
    assert r1.status_code == 200

    # Valid PNG
    c2_res = client.post(
        "/complaints/", headers=cit_hdrs, json={"complaint_text": "PNG test for valid format"}
    )
    assert c2_res.status_code == 201, c2_res.text
    c2 = c2_res.json()["tracking_id"]
    r2 = client.post(
        f"/complaints/{c2}/image",
        headers=cit_hdrs,
        files={"file": ("valid.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    assert r2.status_code == 200

    # Invalid payload (bad magic bytes masquerading as image/jpeg)
    c3_res = client.post(
        "/complaints/", headers=cit_hdrs, json={"complaint_text": "Bad image test for format validation"}
    )
    assert c3_res.status_code == 201, c3_res.text
    c3 = c3_res.json()["tracking_id"]
    r3 = client.post(
        f"/complaints/{c3}/image",
        headers=cit_hdrs,
        files={"file": ("fake.jpg", io.BytesIO(b"this is plain text"), "image/jpeg")},
    )
    assert r3.status_code == 422


# ===========================================================================
# 7. RECURRENCE INTEGRATION
# ===========================================================================
def test_e2e_recurrence_computation(monkeypatch):
    """Create complaint #1 at (19.000000, 73.000000).
    Create complaint #2 at nearby (19.000100, 73.000100).
    Upload image for complaint #2.
    Verify backend computes prior_reports_count > 0.
    """
    _, cit1_hdrs = _register_and_login("rec-cit1@example.com", "citizen")
    _, cit2_hdrs = _register_and_login("rec-cit2@example.com", "citizen")

    # Complaint #1
    client.post(
        "/complaints/",
        headers=cit1_hdrs,
        json={
            "complaint_text": "First dumping incident near market",
            "latitude": 19.000000,
            "longitude": 73.000000,
        },
    )

    # Complaint #2 (nearby)
    c2_res = client.post(
        "/complaints/",
        headers=cit2_hdrs,
        json={
            "complaint_text": "Second dumping incident at same spot",
            "latitude": 19.000100,
            "longitude": 73.000100,
        },
    )
    tracking_id2 = c2_res.json()["tracking_id"]

    monkeypatch.setattr(
        ai_client,
        "analyze_waste_image",
        lambda *a, **k: {
            "success": True,
            "result": {
                "image_usable": True,
                "waste_type": "dry",
                "severity": "moderate",
                "recurring_flag": True,
                "escalate_to_authority": False,
                "needs_human_review": False,
                "review_reasons": [],
                "errors": [],
            },
            "error": None,
            "details": None,
            "latency_ms": 100,
        },
    )

    client.post(
        f"/complaints/{tracking_id2}/image",
        headers=cit2_hdrs,
        files={"file": ("c2.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )

    with TestingSessionLocal() as db:
        complaint2 = (
            db.query(Complaint).filter(Complaint.tracking_id == tracking_id2).one()
        )
        row2 = (
            db.query(WasteAIResult)
            .filter(WasteAIResult.complaint_id == complaint2.id)
            .one()
        )
        assert row2.prior_reports_count > 0
        assert row2.prior_reports_count == 1


# ===========================================================================
# 8. ADMIN OVERRIDE INTEGRATION
# ===========================================================================
def test_e2e_admin_override_ai_recommendation(monkeypatch):
    """Verify that AI recommendations do not control admin decisions:
    1. AI: escalate_to_authority = true -> Admin decision: assign_cleaner (honored).
    2. AI: escalate_to_authority = false -> Admin decision: escalate_authority (honored).
    """
    _, cit_hdrs = _register_and_login("override-cit@example.com", "citizen")
    _, adm_hdrs = _register_and_login("override-adm@example.com", "admin")

    # Case 1: AI says escalate, Admin assigns cleaner
    c1 = client.post(
        "/complaints/", headers=cit_hdrs, json={"complaint_text": "Waste pile 1 at station"}
    ).json()["tracking_id"]

    monkeypatch.setattr(
        ai_client,
        "analyze_waste_image",
        lambda *a, **k: {
            "success": True,
            "result": {
                "image_usable": True,
                "waste_type": "hazardous",
                "severity": "dump_scale",
                "escalate_to_authority": True,
                "needs_human_review": False,
                "review_reasons": [],
                "errors": [],
            },
            "error": None,
            "details": None,
            "latency_ms": 80,
        },
    )
    client.post(
        f"/complaints/{c1}/image",
        headers=cit_hdrs,
        files={"file": ("w1.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )

    with TestingSessionLocal() as db:
        id1 = db.query(Complaint.id).filter(Complaint.tracking_id == c1).scalar()

    d1 = client.put(
        f"/admin/complaints/{id1}/decision",
        headers=adm_hdrs,
        json={"decision": "assign_cleaner", "note": "Handling locally via cleaner"},
    )
    assert d1.status_code == 200
    assert d1.json()["decision"] == "assign_cleaner"

    # Case 2: AI says do not escalate, Admin escalates anyway
    c2 = client.post(
        "/complaints/", headers=cit_hdrs, json={"complaint_text": "Waste pile 2 at corner"}
    ).json()["tracking_id"]

    monkeypatch.setattr(
        ai_client,
        "analyze_waste_image",
        lambda *a, **k: {
            "success": True,
            "result": {
                "image_usable": True,
                "waste_type": "dry",
                "severity": "domestic",
                "escalate_to_authority": False,
                "needs_human_review": False,
                "review_reasons": [],
                "errors": [],
            },
            "error": None,
            "details": None,
            "latency_ms": 80,
        },
    )
    client.post(
        f"/complaints/{c2}/image",
        headers=cit_hdrs,
        files={"file": ("w2.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )

    with TestingSessionLocal() as db:
        id2 = db.query(Complaint.id).filter(Complaint.tracking_id == c2).scalar()

    d2 = client.put(
        f"/admin/complaints/{id2}/decision",
        headers=adm_hdrs,
        json={"decision": "escalate_authority", "note": "Admin manual escalation"},
    )
    assert d2.status_code == 200
    assert d2.json()["decision"] == "escalate_authority"


# ===========================================================================
# 9. HISTORY / APPEND-ONLY PRESERVATION
# ===========================================================================
def test_e2e_append_only_history_preservation(monkeypatch):
    """Verify append-only semantics across WasteAIResult, AdminDecision, and CleanupProof."""
    _, cit_hdrs = _register_and_login("hist-cit@example.com", "citizen")
    _, adm_hdrs = _register_and_login("hist-adm@example.com", "admin")
    cln_id, cln_hdrs = _register_and_login("hist-cln@example.com", "cleaner")

    create_res = client.post(
        "/complaints/", headers=cit_hdrs, json={"complaint_text": "Append only test complaint"}
    )
    tracking_id = create_res.json()["tracking_id"]
    with TestingSessionLocal() as db:
        complaint_id = (
            db.query(Complaint.id)
            .filter(Complaint.tracking_id == tracking_id)
            .scalar()
        )

    # 1. Re-uploading waste image creates multiple WasteAIResult rows
    monkeypatch.setattr(
        ai_client,
        "analyze_waste_image",
        lambda *a, **k: {
            "success": True,
            "result": {
                "image_usable": True,
                "waste_type": "dry",
                "severity": "domestic",
                "escalate_to_authority": False,
                "needs_human_review": False,
                "review_reasons": [],
                "errors": [],
            },
            "error": None,
            "details": None,
            "latency_ms": 50,
        },
    )
    client.post(
        f"/complaints/{tracking_id}/image",
        headers=cit_hdrs,
        files={"file": ("img1.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )
    client.post(
        f"/complaints/{tracking_id}/image",
        headers=cit_hdrs,
        files={"file": ("img2.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )

    with TestingSessionLocal() as db:
        ai_rows = (
            db.query(WasteAIResult)
            .filter(WasteAIResult.complaint_id == complaint_id)
            .all()
        )
        assert len(ai_rows) == 2

    # 2. Making multiple admin decisions creates multiple AdminDecision rows
    client.put(
        f"/admin/complaints/{complaint_id}/decision",
        headers=adm_hdrs,
        json={"decision": "request_information", "note": "Need more info"},
    )
    client.put(
        f"/admin/complaints/{complaint_id}/decision",
        headers=adm_hdrs,
        json={"decision": "assign_cleaner", "note": "Proceeding with cleaner"},
    )

    with TestingSessionLocal() as db:
        dec_rows = (
            db.query(AdminDecision)
            .filter(AdminDecision.complaint_id == complaint_id)
            .all()
        )
        assert len(dec_rows) == 2
        assert [d.decision for d in dec_rows] == [
            "request_information",
            "assign_cleaner",
        ]

    # Assign cleaner and start task
    client.post(
        f"/admin/complaints/{complaint_id}/assign",
        headers=adm_hdrs,
        json={"cleaner_id": cln_id},
    )

    with TestingSessionLocal() as db:
        task_id = (
            db.query(CleanupTask.task_id)
            .filter(CleanupTask.complaint_id == complaint_id)
            .scalar()
        )

    client.post(f"/cleaner/tasks/{task_id}/start", headers=cln_hdrs)

    # 3. Rejecting proof and resubmitting creates multiple CleanupProof rows
    monkeypatch.setattr(
        ai_client,
        "verify_cleanup",
        lambda *a, **k: {
            "success": True,
            "result": {
                "after_image_usable": True,
                "unusable_reason": None,
                "cleanup_appears_complete": True,
                "confidence": 0.8,
                "reasoning": "Ok",
                "admin_review_recommended": False,
            },
            "error": None,
            "details": None,
            "latency_ms": 50,
        },
    )

    p1 = client.post(
        f"/cleaner/tasks/{task_id}/proof",
        headers=cln_hdrs,
        files={"file": ("p1.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    ).json()["id"]

    client.post(
        f"/admin/proofs/{p1}/verify",
        headers=adm_hdrs,
        json={"approved": False, "rejection_reason": "Incomplete cleanup"},
    )

    p2 = client.post(
        f"/cleaner/tasks/{task_id}/proof",
        headers=cln_hdrs,
        files={"file": ("p2.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    ).json()["id"]

    with TestingSessionLocal() as db:
        proof_rows = (
            db.query(CleanupProof)
            .join(CleanupTask, CleanupProof.task_id == CleanupTask.id)
            .filter(CleanupTask.task_id == task_id)
            .all()
        )
        assert len(proof_rows) == 2
        statuses = {p.id: p.verification_status for p in proof_rows}
        assert statuses[p1] == "rejected"
        assert statuses[p2] == "pending_verification"


# ===========================================================================
# 10. NO PREMATURE RESOLUTION ASSERTIONS
# ===========================================================================
def test_e2e_no_premature_resolution(monkeypatch):
    """Verify that cleaner assignment, starting task, uploading proof, or AI completion
    do NOT resolve the complaint prematurely.
    """
    _, cit_hdrs = _register_and_login("prem-cit@example.com", "citizen")
    _, adm_hdrs = _register_and_login("prem-adm@example.com", "admin")
    cln_id, cln_hdrs = _register_and_login("prem-cln@example.com", "cleaner")

    create_res = client.post(
        "/complaints/", headers=cit_hdrs, json={"complaint_text": "Premature res test complaint"}
    )
    tracking_id = create_res.json()["tracking_id"]
    with TestingSessionLocal() as db:
        complaint_id = (
            db.query(Complaint.id)
            .filter(Complaint.tracking_id == tracking_id)
            .scalar()
        )

    # Step 1: Decision assign_cleaner
    client.put(
        f"/admin/complaints/{complaint_id}/decision",
        headers=adm_hdrs,
        json={"decision": "assign_cleaner"},
    )
    with TestingSessionLocal() as db:
        assert (
            db.query(Complaint).filter(Complaint.id == complaint_id).one().status
            != "resolved"
        )

    # Step 2: Admin assigns cleaner
    client.post(
        f"/admin/complaints/{complaint_id}/assign",
        headers=adm_hdrs,
        json={"cleaner_id": cln_id},
    )
    with TestingSessionLocal() as db:
        assert (
            db.query(Complaint).filter(Complaint.id == complaint_id).one().status
            != "resolved"
        )

    with TestingSessionLocal() as db:
        task_id = (
            db.query(CleanupTask.task_id)
            .filter(CleanupTask.complaint_id == complaint_id)
            .scalar()
        )

    # Step 3: Cleaner starts task
    client.post(f"/cleaner/tasks/{task_id}/start", headers=cln_hdrs)
    with TestingSessionLocal() as db:
        assert (
            db.query(Complaint).filter(Complaint.id == complaint_id).one().status
            != "resolved"
        )

    # Step 4: Cleaner uploads proof + AI says complete
    monkeypatch.setattr(
        ai_client,
        "verify_cleanup",
        lambda *a, **k: {
            "success": True,
            "result": {
                "after_image_usable": True,
                "unusable_reason": None,
                "cleanup_appears_complete": True,
                "confidence": 0.99,
                "reasoning": "Totally clean",
                "admin_review_recommended": False,
            },
            "error": None,
            "details": None,
            "latency_ms": 50,
        },
    )

    client.post(
        f"/cleaner/tasks/{task_id}/proof",
        headers=cln_hdrs,
        files={"file": ("p.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )
    with TestingSessionLocal() as db:
        assert (
            db.query(Complaint).filter(Complaint.id == complaint_id).one().status
            != "resolved"
        )
