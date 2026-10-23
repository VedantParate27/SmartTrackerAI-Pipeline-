# tests/test_task_timestamps.py
# Cleanup-task lifecycle timestamps (Step 5).
#
# Covers:
#   - started_at is recorded on the first genuine start and never reset
#   - the first proof-upload timestamp is derived from the proof history and
#     is never overwritten by later uploads
#   - proof submission alone never verifies a task
#   - the admin-verification workflow (and its completed_at meaning) is intact
#
# Isolated temporary-SQLite setup (same pattern as test_location_authorization.py
# and test_location_statistics.py): every test gets its own throwaway database,
# so the real smarttracker.db is never touched.

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import ai_client  # noqa: E402
import waste_ai_service  # noqa: E402
from database import _create_database_engine, get_db, run_migrations  # noqa: E402
from models import CleanupProof, CleanupTask, Complaint, User  # noqa: E402
from main import app  # noqa: E402
from routers.auth import create_access_token  # noqa: E402

# Proof uploads are magic-byte validated; use a real JPEG head.
JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"\x00" * 16


@pytest.fixture
def task_client(tmp_path, monkeypatch):
    engine = _create_database_engine(
        f"sqlite:///{tmp_path / 'task_timestamps.db'}",
        connect_args={"check_same_thread": False},
    )
    run_migrations(target_engine=engine)
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db

    # The background cleanup-AI verification must never touch the real
    # database and must never spawn a subprocess during tests.
    monkeypatch.setattr(
        waste_ai_service, "SessionLocal", session_factory, raising=True
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

    client = TestClient(app)
    try:
        yield client, session_factory
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        client.close()
        engine.dispose()


def _create_user(session_factory, name, email, role):
    with session_factory() as db:
        user = User(
            name=name,
            email=email,
            password_hash="hash",
            role=role,
        )
        db.add(user)
        db.commit()
        return user.id


def _headers(user_id, role):
    return {"Authorization": f"Bearer {create_access_token(user_id, role)}"}


def _create_task(session_factory, cleaner_id, status="assigned", started_at=None):
    with session_factory() as db:
        complaint = Complaint(
            user_id=None,
            name="Citizen",
            email="citizen@example.com",
            complaint_text="Wet waste left beside the collection point.",
            status="in_progress",
        )
        db.add(complaint)
        db.flush()
        task = CleanupTask(
            complaint_id=complaint.id,
            assigned_cleaner_id=cleaner_id,
            status=status,
            started_at=started_at,
        )
        db.add(task)
        db.commit()
        return task.task_id


def _task_row(session_factory, task_id):
    with session_factory() as db:
        db.expire_all()
        return db.query(CleanupTask).filter(CleanupTask.task_id == task_id).one()


def _proof_rows(session_factory, task_id):
    with session_factory() as db:
        db.expire_all()
        return (
            db.query(CleanupProof)
            .filter(CleanupProof.task_id == _task_row(session_factory, task_id).id)
            .order_by(CleanupProof.uploaded_at.asc())
            .all()
        )


def _start(client, headers, task_id):
    return client.post(f"/cleaner/tasks/{task_id}/start", headers=headers)


def _upload_proof(client, headers, task_id, filename="after.jpg"):
    return client.post(
        f"/cleaner/tasks/{task_id}/proof",
        headers=headers,
        files={"file": (filename, JPEG_HEAD, "image/jpeg")},
    )


# ---------------------------------------------------------------------------
# started_at
# ---------------------------------------------------------------------------
def test_first_start_sets_started_at(task_client):
    client, session_factory = task_client
    cleaner_id = _create_user(
        session_factory, "Cleaner", "start-cleaner@example.com", "cleaner"
    )
    headers = _headers(cleaner_id, "cleaner")
    task_id = _create_task(session_factory, cleaner_id)

    assert _task_row(session_factory, task_id).started_at is None

    response = _start(client, headers, task_id)
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"
    assert response.json()["started_at"] is not None

    row = _task_row(session_factory, task_id)
    assert row.started_at is not None
    assert row.status == "in_progress"


def test_repeated_start_does_not_reset_started_at(task_client):
    client, session_factory = task_client
    cleaner_id = _create_user(
        session_factory, "Cleaner", "repeat-cleaner@example.com", "cleaner"
    )
    headers = _headers(cleaner_id, "cleaner")
    task_id = _create_task(session_factory, cleaner_id)

    assert _start(client, headers, task_id).status_code == 200
    first_started_at = _task_row(session_factory, task_id).started_at
    assert first_started_at is not None

    for _ in range(3):
        response = _start(client, headers, task_id)
        assert response.status_code == 200
        assert response.json()["started_at"] == first_started_at.isoformat()

    row = _task_row(session_factory, task_id)
    assert row.started_at == first_started_at
    assert row.status == "in_progress"


def test_legacy_in_progress_task_gets_started_at_once_on_its_next_start(task_client):
    """A task already in_progress but without started_at gets it exactly once."""
    client, session_factory = task_client
    cleaner_id = _create_user(
        session_factory, "Cleaner", "legacy-cleaner@example.com", "cleaner"
    )
    headers = _headers(cleaner_id, "cleaner")
    task_id = _create_task(session_factory, cleaner_id, status="in_progress")

    assert _task_row(session_factory, task_id).started_at is None

    assert _start(client, headers, task_id).status_code == 200
    first_started_at = _task_row(session_factory, task_id).started_at
    assert first_started_at is not None

    assert _start(client, headers, task_id).status_code == 200
    assert _task_row(session_factory, task_id).started_at == first_started_at


def test_started_at_stays_null_when_the_task_is_never_started(task_client):
    """No start request -> no started_at. Nothing is inferred or back-filled."""
    client, session_factory = task_client
    cleaner_id = _create_user(
        session_factory, "Cleaner", "nostart-cleaner@example.com", "cleaner"
    )
    headers = _headers(cleaner_id, "cleaner")
    task_id = _create_task(session_factory, cleaner_id)

    assert _upload_proof(client, headers, task_id).status_code == 201

    row = _task_row(session_factory, task_id)
    assert row.started_at is None
    assert row.completed_at is None


def test_start_keeps_the_existing_authorization_and_status_rules(task_client):
    client, session_factory = task_client
    owner_id = _create_user(
        session_factory, "Cleaner", "owner-cleaner@example.com", "cleaner"
    )
    other_id = _create_user(
        session_factory, "Other", "other-cleaner@example.com", "cleaner"
    )
    admin_id = _create_user(
        session_factory, "Admin", "start-admin@example.com", "admin"
    )
    task_id = _create_task(session_factory, owner_id)

    # Another cleaner may not start somebody else's task.
    denied = _start(client, _headers(other_id, "cleaner"), task_id)
    assert denied.status_code == 403
    assert _task_row(session_factory, task_id).started_at is None

    # An admin may.
    assert _start(client, _headers(admin_id, "admin"), task_id).status_code == 200
    assert _task_row(session_factory, task_id).started_at is not None

    # A verified task can no longer be started.
    with session_factory() as db:
        db.query(CleanupTask).filter(
            CleanupTask.task_id == task_id
        ).update({"status": "verified"})
        db.commit()
    rejected = _start(client, _headers(owner_id, "cleaner"), task_id)
    assert rejected.status_code == 400


# ---------------------------------------------------------------------------
# first proof upload
# ---------------------------------------------------------------------------
def test_first_proof_upload_time_is_recorded(task_client):
    client, session_factory = task_client
    cleaner_id = _create_user(
        session_factory, "Cleaner", "proof-cleaner@example.com", "cleaner"
    )
    headers = _headers(cleaner_id, "cleaner")
    task_id = _create_task(session_factory, cleaner_id)

    _start(client, headers, task_id)
    started_at = _task_row(session_factory, task_id).started_at

    response = _upload_proof(client, headers, task_id)
    assert response.status_code == 201

    task = _task_row(session_factory, task_id)
    proofs = _proof_rows(session_factory, task_id)
    assert len(proofs) == 1
    assert proofs[0].uploaded_at is not None

    detail = client.get(f"/cleaner/tasks/{task_id}", headers=headers)
    assert detail.status_code == 200
    first_proof_at = detail.json()["first_proof_uploaded_at"]
    assert first_proof_at is not None
    assert first_proof_at == proofs[0].uploaded_at.isoformat()
    # The proof cannot have been uploaded before the work started.
    assert first_proof_at >= started_at.isoformat()


def test_later_proof_uploads_do_not_overwrite_the_first_proof_timestamp(task_client):
    client, session_factory = task_client
    cleaner_id = _create_user(
        session_factory, "Cleaner", "multi-cleaner@example.com", "cleaner"
    )
    headers = _headers(cleaner_id, "cleaner")
    task_id = _create_task(session_factory, cleaner_id)

    _start(client, headers, task_id)
    assert _upload_proof(client, headers, task_id, "first.jpg").status_code == 201

    first_proof_at = client.get(
        f"/cleaner/tasks/{task_id}", headers=headers
    ).json()["first_proof_uploaded_at"]
    assert first_proof_at is not None

    # A second (resubmission) proof must not move the first-proof timestamp.
    assert _upload_proof(client, headers, task_id, "second.jpg").status_code == 201

    proofs = _proof_rows(session_factory, task_id)
    assert len(proofs) == 2
    assert proofs[0].uploaded_at < proofs[1].uploaded_at

    detail = client.get(f"/cleaner/tasks/{task_id}", headers=headers)
    assert detail.json()["first_proof_uploaded_at"] == first_proof_at
    assert detail.json()["first_proof_uploaded_at"] == proofs[0].uploaded_at.isoformat()


def test_proof_submission_alone_does_not_verify_the_task(task_client):
    client, session_factory = task_client
    cleaner_id = _create_user(
        session_factory, "Cleaner", "noverify-cleaner@example.com", "cleaner"
    )
    admin_id = _create_user(
        session_factory, "Admin", "noverify-admin@example.com", "admin"
    )
    headers = _headers(cleaner_id, "cleaner")
    task_id = _create_task(session_factory, cleaner_id)

    _start(client, headers, task_id)
    response = _upload_proof(client, headers, task_id)
    assert response.status_code == 201

    task = _task_row(session_factory, task_id)
    assert task.status == "proof_submitted"
    assert task.completed_at is None

    proof = _proof_rows(session_factory, task_id)[0]
    assert proof.verification_status == "pending_verification"
    assert proof.verified_by is None
    assert proof.verified_at is None

    # The admin review view shows an unverified proof as pending.
    review = client.get(
        f"/admin/tasks/{task_id}/proof", headers=_headers(admin_id, "admin")
    )
    assert review.status_code == 200
    assert review.json()["task_status"] == "proof_submitted"
    assert review.json()["completed_at"] is None
    assert review.json()["proofs"][0]["verification_status"] == "pending_verification"


# ---------------------------------------------------------------------------
# admin verification (unchanged behaviour)
# ---------------------------------------------------------------------------
def test_admin_verification_behaviour_is_unchanged(task_client):
    client, session_factory = task_client
    cleaner_id = _create_user(
        session_factory, "Cleaner", "verify-cleaner@example.com", "cleaner"
    )
    admin_id = _create_user(
        session_factory, "Admin", "verify-admin@example.com", "admin"
    )
    cleaner_headers = _headers(cleaner_id, "cleaner")
    admin_headers = _headers(admin_id, "admin")
    task_id = _create_task(session_factory, cleaner_id)

    _start(client, cleaner_headers, task_id)
    started_at = _task_row(session_factory, task_id).started_at
    _upload_proof(client, cleaner_headers, task_id)
    proof_id = _proof_rows(session_factory, task_id)[0].id

    verified = client.post(
        f"/admin/proofs/{proof_id}/verify",
        headers=admin_headers,
        json={"approved": True},
    )
    assert verified.status_code == 200
    assert verified.json()["verification_status"] == "verified"

    task = _task_row(session_factory, task_id)
    assert task.status == "verified"
    assert task.completed_at is not None
    # completed_at is the admin-verification time, not the physical finish.
    assert task.completed_at >= started_at

    proof = _proof_rows(session_factory, task_id)[0]
    assert proof.verification_status == "verified"
    assert proof.verified_by == admin_id
    assert proof.verified_at is not None

    # The first-proof timestamp is untouched by the verification.
    detail = client.get(f"/cleaner/tasks/{task_id}", headers=cleaner_headers)
    assert detail.json()["first_proof_uploaded_at"] == proof.uploaded_at.isoformat()
    assert detail.json()["completed_at"] == task.completed_at.isoformat()
    assert detail.json()["started_at"] == started_at.isoformat()


def test_admin_review_exposes_the_task_timeline(task_client):
    client, session_factory = task_client
    cleaner_id = _create_user(
        session_factory, "Cleaner", "review-cleaner@example.com", "cleaner"
    )
    admin_id = _create_user(
        session_factory, "Admin", "review-admin@example.com", "admin"
    )
    cleaner_headers = _headers(cleaner_id, "cleaner")
    admin_headers = _headers(admin_id, "admin")
    task_id = _create_task(session_factory, cleaner_id)

    _start(client, cleaner_headers, task_id)
    _upload_proof(client, cleaner_headers, task_id)

    review = client.get(f"/admin/tasks/{task_id}/proof", headers=admin_headers)
    assert review.status_code == 200
    payload = review.json()
    assert payload["started_at"] is not None
    assert payload["first_proof_uploaded_at"] is not None
    assert payload["completed_at"] is None
    assert payload["started_at"] <= payload["first_proof_uploaded_at"]
