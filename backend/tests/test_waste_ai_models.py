# tests/test_waste_ai_models.py
# Model/migration foundation tests for the waste-AI integration.
#
# Covers:
#   1. waste_ai_results table is created.
#   2. WasteAIResult can be inserted (AI vocabulary stored VERBATIM).
#   3. WasteAIResult references Complaint (relationship navigation works).
#   4. Multiple WasteAIResult rows can belong to one Complaint (append-only).
#   5. CleanupProof AI advisory columns exist.
#   6. Existing CleanupProof human verification workflow still works
#      (proof upload + admin verify untouched; AI fields stay NULL).
#   7. Legacy-database migration adds the new table/columns idempotently.
#
# (Existing suites passing = covered by running the full backend test suite.)

import io
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import inspect as sa_inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from test_app_state import TestingSessionLocal, client, engine  # noqa: E402

from models import CleanupProof, CleanupTask, Complaint, User, WasteAIResult  # noqa: E402

# Step-6 proof uploads are magic-byte validated; test payloads use a real JPEG head.
JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"\x00" * 16

AI_RESULT_COLUMNS = {
    "id", "complaint_id", "created_at", "ai_status",
    "image_url", "image_mime_type",
    "image_usable", "unusable_reason",
    "waste_type", "waste_type_confidence",
    "severity", "severity_confidence",
    "reasoning", "follow_up_question",
    "recurring_flag", "prior_reports_count", "radius_m",
    "escalate_to_authority",
    "needs_human_review", "review_reasons_json",
    "disposal_guidance", "errors_json",
    "model_name", "model_version", "latency_ms",
}

PROOF_AI_COLUMNS = {
    "before_image_url",
    "ai_after_image_usable", "ai_unusable_reason",
    "ai_cleanup_appears_complete", "ai_confidence", "ai_reasoning",
    "ai_admin_review_recommended", "ai_processed_at", "ai_errors_json",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _create_complaint(**waste_fields) -> Complaint:
    """Insert one complaint row directly (model-level tests)."""
    with TestingSessionLocal() as db:
        complaint = Complaint(
            name="Model Test Citizen",
            email="model-test@example.com",
            complaint_text="Overflowing bins near the park gate, model-level test.",
            status="pending",
            priority="medium",
            source="citizen",
            **waste_fields,
        )
        db.add(complaint)
        db.commit()
        db.refresh(complaint)
        return complaint


# ---------------------------------------------------------------------------
# 1. waste_ai_results table is created
# ---------------------------------------------------------------------------
def test_waste_ai_results_table_created():
    inspector = sa_inspect(engine)
    assert "waste_ai_results" in inspector.get_table_names()

    db_columns = {c["name"] for c in inspector.get_columns("waste_ai_results")}
    assert db_columns == AI_RESULT_COLUMNS


# ---------------------------------------------------------------------------
# 2. WasteAIResult can be inserted (verbatim AI vocabulary round-trips)
# ---------------------------------------------------------------------------
def test_waste_ai_result_insert_round_trip():
    complaint = _create_complaint()

    with TestingSessionLocal() as db:
        result = WasteAIResult(
            complaint_id=complaint.id,
            ai_status="completed",
            image_url="/uploads/complaints/complaint_test.jpg",
            image_mime_type="image/jpeg",
            image_usable=True,
            unusable_reason=None,
            # AI vocabulary stored VERBATIM (no sanitary->medical, no mixed->bulk)
            waste_type="sanitary",
            waste_type_confidence=0.82,
            severity="dump_scale",
            severity_confidence=0.91,
            reasoning="Large accumulation across several meters with visible decomposition.",
            follow_up_question=None,
            recurring_flag=True,
            prior_reports_count=3,
            radius_m=50,
            escalate_to_authority=True,
            needs_human_review=False,
            review_reasons_json='["recurring_location: 3 prior reports"]',
            disposal_guidance=None,   # escalated cases get no guidance
            errors_json="[]",
            model_name="gemini-waste-vision",
            model_version="1.0.0",
            latency_ms=4200,
        )
        db.add(result)
        db.commit()
        db.refresh(result)
        result_id = result.id

        loaded = db.query(WasteAIResult).filter(WasteAIResult.id == result_id).one()
        assert loaded.complaint_id == complaint.id
        assert loaded.ai_status == "completed"
        assert loaded.waste_type == "sanitary"        # verbatim, unmapped
        assert loaded.severity == "dump_scale"        # verbatim, unmapped
        assert loaded.waste_type_confidence == 0.82
        assert loaded.severity_confidence == 0.91
        assert loaded.escalate_to_authority is True
        assert loaded.needs_human_review is False
        assert loaded.recurring_flag is True
        assert loaded.disposal_guidance is None
        assert loaded.created_at is not None          # utcnow default applied


def test_waste_ai_result_pending_row_inserts_with_defaults():
    """A 'pending' row (created before AI output arrives) needs only the FK."""
    complaint = _create_complaint()

    with TestingSessionLocal() as db:
        result = WasteAIResult(complaint_id=complaint.id, ai_status="pending")
        db.add(result)
        db.commit()
        db.refresh(result)

        assert result.id is not None
        assert result.waste_type is None
        assert result.severity is None
        assert result.image_usable is None
        assert result.recurring_flag is False         # server-side default
        assert result.escalate_to_authority is False
        assert result.needs_human_review is False


def test_waste_ai_result_requires_complaint():
    """complaint_id is non-nullable — a row without a complaint must fail."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    with TestingSessionLocal() as db:
        db.add(WasteAIResult(ai_status="pending"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


# ---------------------------------------------------------------------------
# 3. WasteAIResult references Complaint (relationship navigation)
# ---------------------------------------------------------------------------
def test_waste_ai_result_relationship_navigation():
    complaint = _create_complaint()

    with TestingSessionLocal() as db:
        result = WasteAIResult(
            complaint_id=complaint.id,
            ai_status="completed",
            waste_type="wet",
            waste_type_confidence=0.88,
            severity="domestic",
            severity_confidence=0.9,
            escalate_to_authority=False,
            disposal_guidance="Use the green bin; empty it daily.",
        )
        db.add(result)
        db.commit()
        db.refresh(result)

        # many -> one
        assert result.complaint.tracking_id == complaint.tracking_id
        # one -> many (re-query within THIS session; the helper's instance is detached)
        fresh = db.query(Complaint).filter(Complaint.id == complaint.id).one()
        assert len(fresh.waste_ai_results) == 1
        assert fresh.waste_ai_results[0].disposal_guidance == "Use the green bin; empty it daily."


# ---------------------------------------------------------------------------
# 4. Multiple rows per complaint (append-only history, no overwriting)
# ---------------------------------------------------------------------------
def test_multiple_waste_ai_results_append_only():
    complaint = _create_complaint()

    with TestingSessionLocal() as db:
        db.add(WasteAIResult(
            complaint_id=complaint.id, ai_status="failed",
            errors_json='["classification_failed: quota exceeded"]',
        ))
        db.commit()
        db.add(WasteAIResult(
            complaint_id=complaint.id, ai_status="completed",
            waste_type="e_waste", waste_type_confidence=0.77,
            severity="moderate", severity_confidence=0.8,
        ))
        db.commit()

        rows = (
            db.query(WasteAIResult)
            .filter(WasteAIResult.complaint_id == complaint.id)
            .order_by(WasteAIResult.created_at.asc(), WasteAIResult.id.asc())
            .all()
        )
        assert len(rows) == 2
        assert rows[0].ai_status == "failed"          # history preserved
        assert rows[1].ai_status == "completed"
        # neither row was mutated by the second insert
        assert rows[0].waste_type is None


# ---------------------------------------------------------------------------
# 5. CleanupProof AI advisory columns exist
# ---------------------------------------------------------------------------
def test_cleanup_proof_ai_columns_exist():
    inspector = sa_inspect(engine)
    db_columns = {c["name"] for c in inspector.get_columns("cleanup_proofs")}
    assert PROOF_AI_COLUMNS.issubset(db_columns)

    # advisory columns must be nullable so human-only proofs stay valid
    col_meta = {c["name"]: c for c in inspector.get_columns("cleanup_proofs")}
    for name in PROOF_AI_COLUMNS:
        assert col_meta[name]["nullable"], f"{name} must be nullable"


# ---------------------------------------------------------------------------
# 6. Existing human verification workflow still authoritative
# ---------------------------------------------------------------------------
def _register_and_login(email, password="Password123!"):
    register = client.post("/auth/register", json={
        "name": "AI Foundation User", "email": email, "password": password,
    })
    assert register.status_code == 201
    user_id = register.json()["id"]
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return user_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


def _promote(user_id, role):
    with TestingSessionLocal() as db:
        db.query(User).filter(User.id == user_id).one().role = role
        db.commit()


def test_existing_human_proof_verification_unaffected_by_ai_fields():
    _, citizen_headers = _register_and_login("ai-foundation-citizen@example.com")
    cleaner_id, cleaner_headers = _register_and_login("ai-foundation-cleaner@example.com")
    admin_id, admin_headers = _register_and_login("ai-foundation-admin@example.com")
    _promote(cleaner_id, "cleaner")
    _promote(admin_id, "admin")

    created = client.post("/complaints/", headers=citizen_headers, json={
        "complaint_text": "Wet waste accumulating near the market entrance for days.",
    })
    assert created.status_code == 201
    tracking_id = created.json()["tracking_id"]

    with TestingSessionLocal() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == tracking_id).one()
        complaint_id = complaint.id
        db.add(CleanupTask(
            complaint_id=complaint.id,
            assigned_cleaner_id=cleaner_id,
            status="assigned",
            notes="Foundation test task",
        ))
        db.commit()

    assign_state = client.get(f"/complaints/{tracking_id}", headers=cleaner_headers)
    assert assign_state.status_code == 200

    tasks = client.get("/cleaner/tasks", headers=cleaner_headers)
    assert tasks.status_code == 200
    task_id = tasks.json()[0]["task_id"]

    # Cleaner uploads an AFTER image (magic-byte validated since Step 6)
    upload = client.post(
        f"/cleaner/tasks/{task_id}/proof",
        headers=cleaner_headers,
        files={"file": ("after.jpg", io.BytesIO(JPEG_HEAD), "image/jpeg")},
    )
    assert upload.status_code == 201
    proof_id = upload.json()["id"]
    proof_data = upload.json()
    # AI advisory fields are untouched by the current upload flow (adapter comes later)
    for field in ("before_image_url", "ai_after_image_usable",
                  "ai_cleanup_appears_complete", "ai_confidence",
                  "ai_admin_review_recommended"):
        assert field not in proof_data   # not yet surfaced; row values must be NULL

    with TestingSessionLocal() as db:
        row = db.query(CleanupProof).filter(CleanupProof.id == proof_id).one()
        assert row.verification_status == "pending_verification"
        assert row.ai_after_image_usable is None
        assert row.ai_cleanup_appears_complete is None
        assert row.ai_admin_review_recommended is None
        assert row.before_image_url is None

    # Admin human verification: approve
    verified = client.post(f"/admin/proofs/{proof_id}/verify", headers=admin_headers, json={
        "approved": True, "next_status": "resolved",
    })
    assert verified.status_code == 200
    assert verified.json()["verification_status"] == "verified"
    assert verified.json()["complaint_status"] == "resolved"

    with TestingSessionLocal() as db:
        row = db.query(CleanupProof).filter(CleanupProof.id == proof_id).one()
        assert row.verification_status == "verified"   # human workflow authoritative
        assert row.verified_by == admin_id
        assert row.ai_confidence is None               # AI fields still advisory/empty

    # A verified task is terminal: no further proof can be submitted (Step-6
    # state guard). The reject path is covered by the workflow suites.
    upload2 = client.post(
        f"/cleaner/tasks/{task_id}/proof",
        headers=cleaner_headers,
        files={"file": ("after2.jpg", io.BytesIO(JPEG_HEAD), "image/jpeg")},
    )
    assert upload2.status_code == 400


# ---------------------------------------------------------------------------
# 7. Legacy-database migration adds the new table/columns idempotently
# ---------------------------------------------------------------------------
def test_migration_adds_waste_ai_table_and_proof_columns(tmp_path):
    from database import run_migrations

    db_file = tmp_path / "legacy_waste_ai.db"
    legacy = sqlite3.connect(db_file)
    legacy.executescript(
        """
        CREATE TABLE complaints (
            id INTEGER PRIMARY KEY,
            tracking_id VARCHAR(50),
            user_id INTEGER,
            name VARCHAR(100),
            email VARCHAR(150),
            complaint_text TEXT,
            status VARCHAR(30),
            priority VARCHAR(20)
        );
        CREATE TABLE cleanup_proofs (
            id INTEGER PRIMARY KEY,
            task_id INTEGER,
            image_url VARCHAR(500),
            uploaded_by INTEGER,
            uploaded_at DATETIME,
            verification_status VARCHAR(30)
        );
        """
    )
    legacy.execute(
        "INSERT INTO complaints (tracking_id, name, email, complaint_text, status, priority) "
        "VALUES ('TRK-LEGACY1', 'Legacy', 'legacy@example.com', 'legacy complaint', 'pending', 'medium')"
    )
    legacy.commit()
    legacy.close()

    from sqlalchemy import create_engine
    legacy_engine = create_engine(f"sqlite:///{db_file.as_posix()}",
                                  connect_args={"check_same_thread": False})

    run_migrations(target_engine=legacy_engine)
    run_migrations(target_engine=legacy_engine)   # idempotency: second run is a no-op

    inspector = sa_inspect(legacy_engine)
    assert "waste_ai_results" in inspector.get_table_names()
    proof_cols = {c["name"] for c in inspector.get_columns("cleanup_proofs")}
    assert PROOF_AI_COLUMNS.issubset(proof_cols)

    # legacy data preserved through the migration
    with legacy_engine.connect() as conn:
        row = conn.execute(text(
            "SELECT tracking_id, complaint_text FROM complaints WHERE tracking_id='TRK-LEGACY1'"
        )).one()
    assert row.tracking_id == "TRK-LEGACY1"
    assert row.complaint_text == "legacy complaint"

    # new table accepts a row with a real FK after migration
    from database import Base
    Base.metadata.create_all(bind=legacy_engine)
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=legacy_engine)
    with Session() as db:
        complaint = db.query(Complaint).filter(Complaint.tracking_id == "TRK-LEGACY1").one()
        db.add(WasteAIResult(complaint_id=complaint.id, ai_status="pending"))
        db.commit()
        assert db.query(WasteAIResult).count() == 1
