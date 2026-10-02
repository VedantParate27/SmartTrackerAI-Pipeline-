# tests/test_waste_ai_complaint_flow.py
# Step 3 (waste-AI complaint flow) tests. NO test calls Gemini:
# backend.ai_client.analyze_waste_image is monkeypatched everywhere.
#
# Uses the shared in-memory engine/test client (test_app_state) and real
# FastAPI BackgroundTasks — the TestClient executes background tasks after
# the response, which is exactly the production behavior under test.

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

from models import Complaint, WasteAIResult  # noqa: E402

JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"\x00" * 16
PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
WEBP_HEAD = b"RIFF\x24\x00\x00\x00WEBP" + b"\x00" * 16


def _png_bytes(size: int = 100) -> bytes:
    return PNG_HEAD + b"\x00" * max(0, size - len(PNG_HEAD))


def _jpeg_bytes(size: int = 100) -> bytes:
    return JPEG_HEAD + b"\x00" * max(0, size - len(JPEG_HEAD))


def _webp_bytes(size: int = 100) -> bytes:
    return WEBP_HEAD + b"\x00" * max(0, size - len(WEBP_HEAD))


def _register_and_login(email, password="Password123!"):
    register = client.post("/auth/register", json={
        "name": "AI Flow User", "email": email, "password": password,
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


def _create_complaint(headers, text="Overflowing bins near the market.", **fields) -> dict:
    payload = {"complaint_text": text, **fields}
    response = client.post("/complaints/", headers=headers, json=payload)
    assert response.status_code == 201
    return response.json()


AI_RESULT_OK = {
    "image_usable": True,
    "unusable_reason": None,
    "waste_type": "sanitary",
    "waste_type_confidence": 0.82,
    "severity": "dump_scale",
    "severity_confidence": 0.91,
    "reasoning": "Large pile spanning several meters, visible decomposition.",
    "follow_up_question": None,
    "location": {"lat": 12.9716, "lng": 77.5946},
    "prior_reports_at_location": 2,
    "recurring_flag": False,
    "escalate_to_authority": True,
    "needs_human_review": False,
    "review_reasons": [],
    "disposal_guidance": None,
    "errors": [],
}

AI_RESULT_LOWCONF = {
    "image_usable": True,
    "unusable_reason": None,
    "waste_type": "mixed",
    "waste_type_confidence": 0.42,
    "severity": "moderate",
    "severity_confidence": 0.5,
    "reasoning": "Ambiguous pile.",
    "follow_up_question": "Has this been accumulating over time?",
    "location": None,
    "prior_reports_at_location": 0,
    "recurring_flag": False,
    "escalate_to_authority": False,
    "needs_human_review": True,
    "review_reasons": ["low_waste_type_confidence: 0.42", "low_severity_confidence: 0.50"],
    "disposal_guidance": "Use the blue bin for dry recyclables after rinsing.",
    "errors": [],
}


@pytest.fixture(autouse=True)
def _flow_isolation(monkeypatch):
    """Fresh complaint/waste_ai_results rows per test + AI always mocked.

    Also re-points the background service at the shared in-memory test engine
    (production uses the real file-backed SessionLocal).
    """
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
        db.query(WasteAIResult).delete()
        db.query(Complaint).delete()
        db.commit()


# ---------------------------------------------------------------------------
# 1. complaint without image still works
# ---------------------------------------------------------------------------
def test_complaint_without_image_still_works():
    _, headers = _register_and_login("flow-noimage@example.com")
    created = _create_complaint(headers)
    assert created["status"] == "pending"
    assert created.get("ai_status") is None           # no analysis ever ran
    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == created["tracking_id"]).one()
        assert db.query(WasteAIResult).filter(WasteAIResult.complaint_id == complaint.id).count() == 0


# ---------------------------------------------------------------------------
# 2-4. valid JPEG / PNG / WEBP accepted
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("content,filename,mime", [
    (_jpeg_bytes(), "a.jpg", "image/jpeg"),
    (_png_bytes(), "b.png", "image/png"),
    (_webp_bytes(), "c.webp", "image/webp"),
])
def test_valid_image_formats_accepted(content, filename, mime, monkeypatch):
    # These tests cover upload validation + storage, so the AI run is stubbed
    # out (TestClient executes background tasks before post() returns; the
    # pending->completed transition is covered by dedicated tests below).
    monkeypatch.setattr(waste_ai_service, "run_ai_analysis", lambda result_id: None)
    _, headers = _register_and_login(f"flow-{mime.split('/')[1]}@example.com")
    created = _create_complaint(headers)
    uploaded = client.post(f"/complaints/{created['tracking_id']}/image",
                           headers=headers,
                           files={"file": (filename, io.BytesIO(content), mime)})
    assert uploaded.status_code == 200
    body = uploaded.json()
    assert body["ai_status"] == "pending"
    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == created["tracking_id"]).one()
        results = (db.query(WasteAIResult)
                   .filter(WasteAIResult.complaint_id == complaint.id).all())
        assert len(results) == 1
        assert results[0].ai_status == "pending"
        assert results[0].image_url.startswith("/uploads/complaints/complaint_")
        assert results[0].image_mime_type == mime
        assert results[0].waste_type is None      # no invented predictions while pending
        assert results[0].severity is None


# ---------------------------------------------------------------------------
# 5/6/7. invalid MIME, invalid magic bytes, oversized image
# ---------------------------------------------------------------------------
def test_invalid_mime_rejected():
    _, headers = _register_and_login("flow-badmime@example.com")
    created = _create_complaint(headers)
    response = client.post(f"/complaints/{created['tracking_id']}/image",
                           headers=headers,
                           files={"file": ("x.gif", io.BytesIO(_png_bytes()), "image/gif")})
    assert response.status_code == 422
    assert response.json()["detail"] == image_utils.ERR_IMAGE_UNSUPPORTED_TYPE


def test_invalid_magic_bytes_rejected():
    _, headers = _register_and_login("flow-badmagic@example.com")
    created = _create_complaint(headers)
    response = client.post(f"/complaints/{created['tracking_id']}/image",
                           headers=headers,
                           files={"file": ("x.png", io.BytesIO(b"GIF89a" + b"\x00" * 20), "image/png")})
    assert response.status_code == 422
    assert response.json()["detail"] == image_utils.ERR_IMAGE_UNSUPPORTED_TYPE


def test_oversized_image_rejected():
    _, headers = _register_and_login("flow-oversize@example.com")
    created = _create_complaint(headers)
    big = _png_bytes() + b"\x00" * (image_utils.MAX_IMAGE_BYTES)  # just over the cap
    response = client.post(f"/complaints/{created['tracking_id']}/image",
                           headers=headers,
                           files={"file": ("big.png", io.BytesIO(big), "image/png")})
    assert response.status_code == 422
    assert response.json()["detail"] == image_utils.ERR_IMAGE_TOO_LARGE


# ---------------------------------------------------------------------------
# 8. image stored with UUID filename, not user filename
# ---------------------------------------------------------------------------
def test_image_stored_with_uuid_filename(monkeypatch):
    monkeypatch.setattr(waste_ai_service, "run_ai_analysis", lambda result_id: None)
    _, headers = _register_and_login("flow-uuid@example.com")
    created = _create_complaint(headers)
    uploaded = client.post(f"/complaints/{created['tracking_id']}/image",
                           headers=headers,
                           files={"file": ("../../etc/passwd.png", io.BytesIO(_png_bytes()), "image/png")})
    assert uploaded.status_code == 200
    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == created["tracking_id"]).one()
        row = db.query(WasteAIResult).filter(WasteAIResult.complaint_id == complaint.id).one()
        name = row.image_url.rsplit("/", 1)[1]
        assert name.startswith("complaint_") and name.endswith(".png")
        assert ".." not in name and "/" not in name
        # file actually exists in the complaints namespace
        assert (image_utils.COMPLAINT_IMAGE_DIR / name).is_file()


# ---------------------------------------------------------------------------
# 9/10. complaint created before AI execution; pending row created
# ---------------------------------------------------------------------------
def test_pending_result_created_and_complaint_unaffected_by_slow_ai(monkeypatch):
    """Tasks 9+10: the pending row AND the complaint exist BEFORE the AI runs.

    TestClient executes background tasks to completion inside post(), so the
    ordering proof is made by a recorder substituted for the real AI run: it
    observes the database state at the moment the AI would have been invoked.
    """
    _, headers = _register_and_login("flow-pending@example.com")
    created = _create_complaint(headers)

    observed = {}

    def recorder(result_id):
        with TestingSessionLocal() as db:
            row = db.query(WasteAIResult).filter(WasteAIResult.id == result_id).one()
            complaint = db.query(Complaint).filter(Complaint.id == row.complaint_id).one()
            observed["ai_status_at_ai_time"] = row.ai_status
            observed["complaint_status_at_ai_time"] = complaint.status
            observed["image_url"] = row.image_url

    monkeypatch.setattr(waste_ai_service, "run_ai_analysis", recorder)
    uploaded = client.post(f"/complaints/{created['tracking_id']}/image",
                           headers=headers,
                           files={"file": ("p.png", io.BytesIO(_png_bytes()), "image/png")})
    assert uploaded.status_code == 200
    assert uploaded.json()["ai_status"] == "pending"

    # At AI-invocation time the complaint existed and the result was pending
    assert observed["ai_status_at_ai_time"] == "pending"
    assert observed["complaint_status_at_ai_time"] == "pending"
    assert observed["image_url"].startswith("/uploads/complaints/complaint_")

    # Row remains pending because the (stubbed) AI never executed
    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == created["tracking_id"]).one()
        row = db.query(WasteAIResult).filter(WasteAIResult.complaint_id == complaint.id).one()
        assert row.ai_status == "pending"
        assert complaint.status == "pending"


# ---------------------------------------------------------------------------
# 11/12/16/17. background AI success → completed; vocabulary verbatim; flags separate
# ---------------------------------------------------------------------------
def test_background_ai_success_completes_result(monkeypatch):
    _, headers = _register_and_login("flow-success@example.com")
    created = _create_complaint(headers)
    captured = {}

    def fake_ai(image_bytes, mime_type="image/jpeg", additional_context=None,
                location=None, prior_reports_at_location=0):
        captured.update({
            "mime": mime_type, "context": additional_context, "location": location,
            "prior": prior_reports_at_location, "bytes_head": bytes(image_bytes[:8]),
        })
        return {"success": True, "result": dict(AI_RESULT_OK), "error": None,
                "details": None, "latency_ms": 4321}

    monkeypatch.setattr(ai_client, "analyze_waste_image", fake_ai)
    uploaded = client.post(f"/complaints/{created['tracking_id']}/image",
                           headers=headers,
                           files={"file": ("s.png", io.BytesIO(_png_bytes()), "image/png")})
    assert uploaded.status_code == 200

    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == created["tracking_id"]).one()
        row = db.query(WasteAIResult).filter(WasteAIResult.complaint_id == complaint.id).one()
        assert row.ai_status == "completed"
        assert row.waste_type == "sanitary"
        assert row.severity == "dump_scale"
        assert row.waste_type_confidence == 0.82
        assert row.severity_confidence == 0.91
        assert row.escalate_to_authority is True
        assert row.needs_human_review is False
        assert row.review_reasons_json == "[]"
        assert row.errors_json == "[]"
        assert row.disposal_guidance is None
        assert row.latency_ms == 4321
        # complaint carries no AI predictions
        assert complaint.waste_type is None

    # AI received the complaint's context/coords and the stored PNG bytes
    assert captured["mime"] == "image/png"
    assert captured["bytes_head"].startswith(b"\x89PNG")


def test_escalate_and_review_flags_stay_separate(monkeypatch):
    """escalate_to_authority=True with needs_human_review=False must persist as-is."""
    _, headers = _register_and_login("flow-flags@example.com")
    created = _create_complaint(headers)
    monkeypatch.setattr(ai_client, "analyze_waste_image",
                        lambda *a, **k: {"success": True, "result": dict(AI_RESULT_OK),
                                         "error": None, "details": None, "latency_ms": 10})
    client.post(f"/complaints/{created['tracking_id']}/image", headers=headers,
                files={"file": ("f.png", io.BytesIO(_png_bytes()), "image/png")})
    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == created["tracking_id"]).one()
        row = db.query(WasteAIResult).filter(WasteAIResult.complaint_id == complaint.id).one()
        assert row.escalate_to_authority is True
        assert row.needs_human_review is False       # orthogonal, exactly as the AI said


def test_low_confidence_case_persists_review_reasons(monkeypatch):
    _, headers = _register_and_login("flow-lowconf@example.com")
    created = _create_complaint(headers)
    monkeypatch.setattr(ai_client, "analyze_waste_image",
                        lambda *a, **k: {"success": True, "result": dict(AI_RESULT_LOWCONF),
                                         "error": None, "details": None, "latency_ms": 7})
    client.post(f"/complaints/{created['tracking_id']}/image", headers=headers,
                files={"file": ("l.png", io.BytesIO(_png_bytes()), "image/png")})
    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == created["tracking_id"]).one()
        row = db.query(WasteAIResult).filter(WasteAIResult.complaint_id == complaint.id).one()
        assert row.ai_status == "completed"
        assert row.waste_type == "mixed"
        assert row.needs_human_review is True
        reasons = json.loads(row.review_reasons_json)
        assert "low_waste_type_confidence: 0.42" in reasons
        assert row.disposal_guidance == AI_RESULT_LOWCONF["disposal_guidance"]


# ---------------------------------------------------------------------------
# 13/14/15. sanitary / mixed / dump_scale remain unmapped (explicit vocabulary tests)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("field,value", [
    ("waste_type", "sanitary"),
    ("waste_type", "mixed"),
    ("severity", "dump_scale"),
])
def test_ai_vocabulary_remains_verbatim(monkeypatch, field, value):
    _, headers = _register_and_login(f"flow-vocab-{field}-{value}@example.com")
    created = _create_complaint(headers)
    payload = dict(AI_RESULT_OK)
    payload[field] = value
    monkeypatch.setattr(ai_client, "analyze_waste_image",
                        lambda *a, **k: {"success": True, "result": payload,
                                         "error": None, "details": None, "latency_ms": 1})
    client.post(f"/complaints/{created['tracking_id']}/image", headers=headers,
                files={"file": ("v.png", io.BytesIO(_png_bytes()), "image/png")})
    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == created["tracking_id"]).one()
        row = db.query(WasteAIResult).filter(WasteAIResult.complaint_id == complaint.id).one()
        assert getattr(row, field) == value
        # legacy vocabulary never invented
        assert row.waste_type not in ("medical", "bulk", "small", "medium", "large")


# ---------------------------------------------------------------------------
# 18/19. AI failure → failed status; complaint survives
# ---------------------------------------------------------------------------
def test_ai_failure_marks_failed_but_complaint_survives(monkeypatch):
    _, headers = _register_and_login("flow-fail@example.com")
    created = _create_complaint(headers)
    monkeypatch.setattr(ai_client, "analyze_waste_image",
                        lambda *a, **k: {"success": False, "result": None,
                                         "error": "AI_TIMEOUT", "details": "exceeded 120s",
                                         "latency_ms": 120000})
    uploaded = client.post(f"/complaints/{created['tracking_id']}/image", headers=headers,
                           files={"file": ("x.png", io.BytesIO(_png_bytes()), "image/png")})
    assert uploaded.status_code == 200     # complaint already created; no error to citizen

    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == created["tracking_id"]).one()
        assert complaint.status == "pending"
        row = db.query(WasteAIResult).filter(WasteAIResult.complaint_id == complaint.id).one()
        assert row.ai_status == "failed"
        errors = json.loads(row.errors_json)
        assert errors[0]["error"] == "AI_TIMEOUT"
        assert row.waste_type is None and row.severity is None
        assert row.latency_ms == 120000

    # citizen can still read their complaint; it proceeds through the manual flow
    tracked = client.get(f"/complaints/{created['tracking_id']}", headers=headers)
    assert tracked.status_code == 200
    assert tracked.json()["ai_status"] == "failed"


def test_ai_exception_never_breaks_background_task(monkeypatch):
    """Even an unexpected exception inside the AI run must fail-open cleanly."""
    _, headers = _register_and_login("flow-exception@example.com")
    created = _create_complaint(headers)

    def explode(*a, **k):
        raise RuntimeError("subprocess exploded")

    monkeypatch.setattr(ai_client, "analyze_waste_image", explode)
    uploaded = client.post(f"/complaints/{created['tracking_id']}/image", headers=headers,
                           files={"file": ("e.png", io.BytesIO(_png_bytes()), "image/png")})
    assert uploaded.status_code == 200
    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == created["tracking_id"]).one()
        row = db.query(WasteAIResult).filter(WasteAIResult.complaint_id == complaint.id).one()
        assert row.ai_status == "failed"
        assert "AI_RUN_EXCEPTION" in row.errors_json


# ---------------------------------------------------------------------------
# 20/21/22. recurrence inputs
# ---------------------------------------------------------------------------
def test_recurrence_count_and_radius_passed_and_stored(monkeypatch):
    email = "flow-geo@example.com"
    _, headers = _register_and_login(email)

    # Neighbor complaint FIRST so its id is lower (only EARLIER complaints count)
    _, neighbor_headers = _register_and_login("flow-geo-neighbor@example.com")
    _create_complaint(neighbor_headers, latitude=12.9717, longitude=77.5946)

    created = _create_complaint(
        headers,
        latitude=12.9716, longitude=77.5946, address_text="MG Road, Ward 1",
    )

    captured = {}

    def fake_ai(image_bytes, mime_type="image/jpeg", additional_context=None,
                location=None, prior_reports_at_location=0):
        captured["prior"] = prior_reports_at_location
        captured["location"] = location
        return {"success": True, "result": dict(AI_RESULT_OK), "error": None,
                "details": None, "latency_ms": 5}

    monkeypatch.setattr(ai_client, "analyze_waste_image", fake_ai)
    client.post(f"/complaints/{created['tracking_id']}/image", headers=headers,
                files={"file": ("g.png", io.BytesIO(_png_bytes()), "image/png")})

    assert captured["prior"] == 1
    assert captured["location"] == {"lat": 12.9716, "lng": 77.5946}

    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == created["tracking_id"]).one()
        row = db.query(WasteAIResult).filter(WasteAIResult.complaint_id == complaint.id).one()
        assert row.prior_reports_count == 1
        assert row.radius_m == 50          # default radius


def test_missing_coordinates_pass_recurrence_zero(monkeypatch):
    _, headers = _register_and_login("flow-nogeo@example.com")
    created = _create_complaint(headers)   # no latitude/longitude
    captured = {}

    def fake_ai(image_bytes, mime_type="image/jpeg", additional_context=None,
                location=None, prior_reports_at_location=0):
        captured["prior"] = prior_reports_at_location
        captured["location"] = location
        return {"success": True, "result": dict(AI_RESULT_OK), "error": None,
                "details": None, "latency_ms": 5}

    monkeypatch.setattr(ai_client, "analyze_waste_image", fake_ai)
    client.post(f"/complaints/{created['tracking_id']}/image", headers=headers,
                files={"file": ("n.png", io.BytesIO(_png_bytes()), "image/png")})
    assert captured["prior"] == 0
    assert captured["location"] is None
    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == created["tracking_id"]).one()
        row = db.query(WasteAIResult).filter(WasteAIResult.complaint_id == complaint.id).one()
        assert row.prior_reports_count == 0


# ---------------------------------------------------------------------------
# 23. latency stored
# ---------------------------------------------------------------------------
def test_latency_persisted(monkeypatch):
    _, headers = _register_and_login("flow-latency@example.com")
    created = _create_complaint(headers)
    monkeypatch.setattr(ai_client, "analyze_waste_image",
                        lambda *a, **k: {"success": True, "result": dict(AI_RESULT_OK),
                                         "error": None, "details": None, "latency_ms": 12345})
    client.post(f"/complaints/{created['tracking_id']}/image", headers=headers,
                files={"file": ("t.png", io.BytesIO(_png_bytes()), "image/png")})
    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == created["tracking_id"]).one()
        row = db.query(WasteAIResult).filter(WasteAIResult.complaint_id == complaint.id).one()
        assert row.latency_ms == 12345


# ---------------------------------------------------------------------------
# 24-27. ai-analysis endpoint
# ---------------------------------------------------------------------------
def test_ai_analysis_endpoint_returns_latest_result(monkeypatch):
    _, headers = _register_and_login("flow-analysis@example.com")
    created = _create_complaint(headers)
    monkeypatch.setattr(ai_client, "analyze_waste_image",
                        lambda *a, **k: {"success": True, "result": dict(AI_RESULT_OK),
                                         "error": None, "details": None, "latency_ms": 9})
    client.post(f"/complaints/{created['tracking_id']}/image", headers=headers,
                files={"file": ("a1.png", io.BytesIO(_png_bytes()), "image/png")})

    response = client.get(f"/complaints/{created['tracking_id']}/ai-analysis", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["ai_status"] == "completed"
    assert body["waste_type"] == "sanitary"
    assert body["severity"] == "dump_scale"
    assert body["escalate_to_authority"] is True
    assert body["image_url"].startswith("/uploads/complaints/complaint_")
    assert body["complaint_id"] > 0


def test_previous_ai_result_remains_after_reanalysis(monkeypatch):
    _, headers = _register_and_login("flow-rehistory@example.com")
    created = _create_complaint(headers)

    monkeypatch.setattr(ai_client, "analyze_waste_image",
                        lambda *a, **k: {"success": True, "result": dict(AI_RESULT_LOWCONF),
                                         "error": None, "details": None, "latency_ms": 3})
    client.post(f"/complaints/{created['tracking_id']}/image", headers=headers,
                files={"file": ("r1.png", io.BytesIO(_png_bytes()), "image/png")})

    monkeypatch.setattr(ai_client, "analyze_waste_image",
                        lambda *a, **k: {"success": True, "result": dict(AI_RESULT_OK),
                                         "error": None, "details": None, "latency_ms": 4})
    client.post(f"/complaints/{created['tracking_id']}/image", headers=headers,
                files={"file": ("r2.png", io.BytesIO(_png_bytes()), "image/png")})

    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == created["tracking_id"]).one()
        rows = (db.query(WasteAIResult)
                .filter(WasteAIResult.complaint_id == complaint.id)
                .order_by(WasteAIResult.created_at.asc(), WasteAIResult.id.asc()).all())
        assert len(rows) == 2
        assert rows[0].waste_type == "mixed"      # first analysis preserved
        assert rows[1].waste_type == "sanitary"   # latest analysis

    # endpoint returns the LATEST
    response = client.get(f"/complaints/{created['tracking_id']}/ai-analysis", headers=headers)
    assert response.json()["waste_type"] == "sanitary"


def test_unauthorized_user_cannot_access_analysis():
    owner, owner_headers = _register_and_login("flow-owner@example.com")
    created = _create_complaint(owner_headers)
    stranger, stranger_headers = _register_and_login("flow-stranger@example.com")
    _ = stranger
    response = client.get(f"/complaints/{created['tracking_id']}/ai-analysis",
                          headers=stranger_headers)
    assert response.status_code in (403, 404)


def test_admin_can_access_analysis(monkeypatch):
    owner, owner_headers = _register_and_login("flow-admin-access@example.com")
    created = _create_complaint(owner_headers)
    admin_id, admin_headers = _register_and_login("flow-admin@example.com")
    _promote(admin_id, "admin")

    monkeypatch.setattr(ai_client, "analyze_waste_image",
                        lambda *a, **k: {"success": True, "result": dict(AI_RESULT_OK),
                                         "error": None, "details": None, "latency_ms": 6})
    client.post(f"/complaints/{created['tracking_id']}/image", headers=owner_headers,
                files={"file": ("adm.png", io.BytesIO(_png_bytes()), "image/png")})

    response = client.get(f"/complaints/{created['tracking_id']}/ai-analysis",
                          headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["ai_status"] == "completed"


def test_ai_analysis_404_when_no_analysis():
    _, headers = _register_and_login("flow-noanalysis@example.com")
    created = _create_complaint(headers)
    response = client.get(f"/complaints/{created['tracking_id']}/ai-analysis", headers=headers)
    assert response.status_code == 404


def test_ai_analysis_requires_authentication():
    _, headers = _register_and_login("flow-noauth@example.com")
    created = _create_complaint(headers)
    response = client.get(f"/complaints/{created['tracking_id']}/ai-analysis")
    assert response.status_code in (401, 403)


def _login_headers_of(email):
    login = client.post("/auth/login", json={"email": email, "password": "Password123!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Image upload authorization + ownership
# ---------------------------------------------------------------------------
def test_stranger_cannot_upload_image_to_complaint():
    _, owner_headers = _register_and_login("flow-img-owner@example.com")
    created = _create_complaint(owner_headers)
    _, stranger_headers = _register_and_login("flow-img-stranger@example.com")
    response = client.post(f"/complaints/{created['tracking_id']}/image",
                           headers=stranger_headers,
                           files={"file": ("s.png", io.BytesIO(_png_bytes()), "image/png")})
    assert response.status_code == 403
