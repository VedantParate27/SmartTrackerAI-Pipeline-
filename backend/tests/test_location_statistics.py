# tests/test_location_statistics.py
# Location-wise statistics API (Task 5).
#
# Isolated temporary-SQLite setup (same pattern as test_location_authorization.py):
# every test gets its own throwaway database, so the real smarttracker.db is
# never touched. run_migrations() seeds the initial locations
# (dadar / wadala / kalyan-dombivli) into that temporary database.

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.database import _create_database_engine, get_db, run_migrations  # noqa: E402
from backend.models import CleanupProof, CleanupTask, Complaint, Location, User  # noqa: E402
from backend.main import app  # noqa: E402
from backend.routers.auth import create_access_token  # noqa: E402


@pytest.fixture
def stats_client(tmp_path):
    engine = _create_database_engine(
        f"sqlite:///{tmp_path / 'location_statistics.db'}",
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


def _location_id(session_factory, slug):
    with session_factory() as db:
        return db.query(Location).filter(Location.slug == slug).one().id


def _deactivate_location(session_factory, location_id):
    with session_factory() as db:
        db.query(Location).filter(Location.id == location_id).update(
            {"is_active": False}
        )
        db.commit()


def _create_complaint(session_factory, user_id, location_id=None, status="pending"):
    with session_factory() as db:
        complaint = Complaint(
            user_id=user_id,
            name="Citizen",
            email="citizen@example.com",
            complaint_text="Overflowing garbage near the market entrance.",
            location_id=location_id,
            status=status,
        )
        db.add(complaint)
        db.commit()
        return complaint.id


def _create_task(
    session_factory,
    complaint_id,
    cleaner_id=None,
    status="assigned",
    completed_at=None,
):
    with session_factory() as db:
        task = CleanupTask(
            complaint_id=complaint_id,
            assigned_cleaner_id=cleaner_id,
            status=status,
            completed_at=completed_at,
        )
        db.add(task)
        db.commit()
        return task.id


def _create_proof(
    session_factory,
    task_id,
    uploader_id,
    verification_status="pending_verification",
    verified_by=None,
    verified_at=None,
):
    with session_factory() as db:
        proof = CleanupProof(
            task_id=task_id,
            image_url="/uploads/proof_test.jpg",
            uploaded_by=uploader_id,
            verification_status=verification_status,
            verified_by=verified_by,
            verified_at=verified_at,
        )
        db.add(proof)
        db.commit()
        return proof.id


def _stats_for(client, headers, location_id):
    response = client.get(
        f"/admin/locations/{location_id}/statistics", headers=headers
    )
    assert response.status_code == 200
    return response.json()


# ---------------------------------------------------------------------------
# Response contract
# ---------------------------------------------------------------------------
def test_statistics_response_exposes_the_agreed_fields(stats_client):
    client, session_factory = stats_client
    admin_id = _create_user(
        session_factory, "Admin", "stats-admin@example.com", "admin"
    )
    headers = _headers(admin_id, "admin")
    location_id = _location_id(session_factory, "dadar")

    payload = _stats_for(client, headers, location_id)

    for field in (
        "location_id",
        "location_name",
        "location_slug",
        "is_active",
        "complaints_reported",
        "tasks_assigned",
        "tasks_verified",
        "proofs_submitted",
        "proofs_verified",
    ):
        assert field in payload, f"missing field: {field}"

    assert payload["location_id"] == location_id
    assert payload["location_name"] == "Dadar"
    assert payload["location_slug"] == "dadar"
    assert payload["is_active"] is True


# ---------------------------------------------------------------------------
# Counting rules
# ---------------------------------------------------------------------------
def test_complaints_reported_counts_distinct_linked_complaints(stats_client):
    client, session_factory = stats_client
    admin_id = _create_user(
        session_factory, "Admin", "counts-admin@example.com", "admin"
    )
    citizen_id = _create_user(
        session_factory, "Citizen", "counts-citizen@example.com", "citizen"
    )
    headers = _headers(admin_id, "admin")
    dadar_id = _location_id(session_factory, "dadar")
    wadala_id = _location_id(session_factory, "wadala")

    _create_complaint(session_factory, citizen_id, dadar_id)
    _create_complaint(session_factory, citizen_id, dadar_id, status="resolved")
    _create_complaint(session_factory, citizen_id, wadala_id)
    # A location-less (legacy) complaint belongs to no location.
    _create_complaint(session_factory, citizen_id, None)

    payload = _stats_for(client, headers, dadar_id)
    assert payload["complaints_reported"] == 2
    assert payload["resolved_complaints"] == 1
    assert payload["open_complaints"] == 1

    other = _stats_for(client, headers, wadala_id)
    assert other["complaints_reported"] == 1


def test_tasks_assigned_requires_a_non_null_assigned_cleaner(stats_client):
    client, session_factory = stats_client
    admin_id = _create_user(
        session_factory, "Admin", "task-admin@example.com", "admin"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "task-cleaner@example.com", "cleaner"
    )
    citizen_id = _create_user(
        session_factory, "Citizen", "task-citizen@example.com", "citizen"
    )
    headers = _headers(admin_id, "admin")
    dadar_id = _location_id(session_factory, "dadar")

    assigned_complaint = _create_complaint(session_factory, citizen_id, dadar_id)
    unassigned_complaint = _create_complaint(session_factory, citizen_id, dadar_id)

    _create_task(session_factory, assigned_complaint, cleaner_id, status="assigned")
    _create_task(session_factory, unassigned_complaint, None, status="assigned")

    payload = _stats_for(client, headers, dadar_id)
    assert payload["tasks_assigned"] == 1


def test_tasks_verified_requires_verified_status_and_completion_timestamp(stats_client):
    client, session_factory = stats_client
    admin_id = _create_user(
        session_factory, "Admin", "verified-admin@example.com", "admin"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "verified-cleaner@example.com", "cleaner"
    )
    citizen_id = _create_user(
        session_factory, "Citizen", "verified-citizen@example.com", "citizen"
    )
    headers = _headers(admin_id, "admin")
    dadar_id = _location_id(session_factory, "dadar")
    now = datetime.now(timezone.utc)

    verified_complaint = _create_complaint(session_factory, citizen_id, dadar_id)
    verified_without_ts = _create_complaint(session_factory, citizen_id, dadar_id)
    in_progress_complaint = _create_complaint(session_factory, citizen_id, dadar_id)

    _create_task(
        session_factory, verified_complaint, cleaner_id, status="verified",
        completed_at=now,
    )
    # 'verified' status but no completion timestamp -> not a verified task.
    _create_task(
        session_factory, verified_without_ts, cleaner_id, status="verified",
        completed_at=None,
    )
    # completed_at set but not verified -> not a verified task.
    _create_task(
        session_factory, in_progress_complaint, cleaner_id, status="proof_submitted",
        completed_at=now,
    )

    payload = _stats_for(client, headers, dadar_id)
    assert payload["tasks_verified"] == 1


def test_proofs_submitted_counts_every_proof_regardless_of_state(stats_client):
    client, session_factory = stats_client
    admin_id = _create_user(
        session_factory, "Admin", "proof-admin@example.com", "admin"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "proof-cleaner@example.com", "cleaner"
    )
    citizen_id = _create_user(
        session_factory, "Citizen", "proof-citizen@example.com", "citizen"
    )
    headers = _headers(admin_id, "admin")
    dadar_id = _location_id(session_factory, "dadar")

    complaint_id = _create_complaint(session_factory, citizen_id, dadar_id)
    task_id = _create_task(
        session_factory, complaint_id, cleaner_id, status="proof_submitted"
    )

    _create_proof(session_factory, task_id, cleaner_id)  # pending_verification
    _create_proof(
        session_factory, task_id, cleaner_id, verification_status="rejected"
    )

    payload = _stats_for(client, headers, dadar_id)
    assert payload["proofs_submitted"] == 2
    assert payload["proofs_verified"] == 0


def test_proofs_verified_requires_authoritative_human_verification(stats_client):
    client, session_factory = stats_client
    admin_id = _create_user(
        session_factory, "Admin", "human-admin@example.com", "admin"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "human-cleaner@example.com", "cleaner"
    )
    citizen_id = _create_user(
        session_factory, "Citizen", "human-citizen@example.com", "citizen"
    )
    headers = _headers(admin_id, "admin")
    dadar_id = _location_id(session_factory, "dadar")
    now = datetime.now(timezone.utc)

    human_verified = _create_complaint(session_factory, citizen_id, dadar_id)
    unverified = _create_complaint(session_factory, citizen_id, dadar_id)
    system_verified = _create_complaint(session_factory, citizen_id, dadar_id)

    task_a = _create_task(
        session_factory, human_verified, cleaner_id, status="verified",
        completed_at=now,
    )
    task_b = _create_task(
        session_factory, unverified, cleaner_id, status="proof_submitted"
    )
    task_c = _create_task(
        session_factory, system_verified, cleaner_id, status="verified",
        completed_at=now,
    )

    # Human-verified proof: status + verifier + timestamp.
    _create_proof(
        session_factory, task_a, cleaner_id,
        verification_status="verified",
        verified_by=admin_id,
        verified_at=now,
    )
    # Submitted but never verified -> not verified collection.
    _create_proof(session_factory, task_b, cleaner_id)
    # Flagged 'verified' but without a human verifier -> not authoritative.
    _create_proof(
        session_factory, task_c, cleaner_id,
        verification_status="verified",
        verified_by=None,
        verified_at=now,
    )

    payload = _stats_for(client, headers, dadar_id)
    assert payload["proofs_submitted"] == 3
    assert payload["proofs_verified"] == 1


def test_multiple_proofs_do_not_multiply_task_or_complaint_counts(stats_client):
    client, session_factory = stats_client
    admin_id = _create_user(
        session_factory, "Admin", "dup-admin@example.com", "admin"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "dup-cleaner@example.com", "cleaner"
    )
    citizen_id = _create_user(
        session_factory, "Citizen", "dup-citizen@example.com", "citizen"
    )
    headers = _headers(admin_id, "admin")
    dadar_id = _location_id(session_factory, "dadar")
    now = datetime.now(timezone.utc)

    complaint_id = _create_complaint(session_factory, citizen_id, dadar_id)
    task_id = _create_task(
        session_factory, complaint_id, cleaner_id, status="verified",
        completed_at=now,
    )

    for _ in range(3):
        _create_proof(
            session_factory, task_id, cleaner_id,
            verification_status="verified",
            verified_by=admin_id,
            verified_at=now,
        )

    payload = _stats_for(client, headers, dadar_id)
    assert payload["complaints_reported"] == 1
    assert payload["tasks_assigned"] == 1
    assert payload["tasks_verified"] == 1
    assert payload["proofs_submitted"] == 3
    assert payload["proofs_verified"] == 3


# ---------------------------------------------------------------------------
# Endpoint behaviour
# ---------------------------------------------------------------------------
def test_inactive_locations_remain_visible_in_historical_statistics(stats_client):
    client, session_factory = stats_client
    admin_id = _create_user(
        session_factory, "Admin", "inactive-admin@example.com", "admin"
    )
    citizen_id = _create_user(
        session_factory, "Citizen", "inactive-citizen@example.com", "citizen"
    )
    headers = _headers(admin_id, "admin")
    dadar_id = _location_id(session_factory, "dadar")

    _create_complaint(session_factory, citizen_id, dadar_id)
    _deactivate_location(session_factory, dadar_id)

    single = _stats_for(client, headers, dadar_id)
    assert single["is_active"] is False
    assert single["complaints_reported"] == 1

    listing = client.get("/admin/locations/statistics", headers=headers)
    assert listing.status_code == 200
    slugs = [item["location_slug"] for item in listing.json()]
    assert "dadar" in slugs
    assert "wadala" in slugs
    assert "kalyan-dombivli" in slugs

    dadar_row = next(
        item for item in listing.json() if item["location_slug"] == "dadar"
    )
    assert dadar_row["is_active"] is False
    assert dadar_row["complaints_reported"] == 1


def test_canonical_paths_and_legacy_aliases_return_the_same_payload(stats_client):
    client, session_factory = stats_client
    admin_id = _create_user(
        session_factory, "Admin", "alias-admin@example.com", "admin"
    )
    headers = _headers(admin_id, "admin")
    dadar_id = _location_id(session_factory, "dadar")

    single = client.get(
        f"/admin/locations/{dadar_id}/statistics", headers=headers
    )
    assert single.status_code == 200
    legacy_single = client.get(
        f"/admin/locations/{dadar_id}/stats", headers=headers
    )
    assert legacy_single.status_code == 200
    assert legacy_single.json() == single.json()

    listing = client.get("/admin/locations/statistics", headers=headers)
    assert listing.status_code == 200
    legacy_listing = client.get("/admin/locations/stats/all", headers=headers)
    assert legacy_listing.status_code == 200
    assert legacy_listing.json() == listing.json()


def test_location_crud_route_still_reads_a_single_location(stats_client):
    """The statistics route must not shadow GET /admin/locations/{location_id}."""
    client, session_factory = stats_client
    admin_id = _create_user(
        session_factory, "Admin", "shadow-admin@example.com", "admin"
    )
    headers = _headers(admin_id, "admin")
    dadar_id = _location_id(session_factory, "dadar")

    response = client.get(f"/admin/locations/{dadar_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["slug"] == "dadar"

    # A literal non-numeric id is a genuine 404/422 from the CRUD route, not
    # a silent capture by the statistics route.
    assert client.get("/admin/locations/not-an-id", headers=headers).status_code == 422


def test_statistics_requires_admin_role(stats_client):
    client, session_factory = stats_client
    citizen_id = _create_user(
        session_factory, "Citizen", "stats-citizen@example.com", "citizen"
    )
    headers = _headers(citizen_id, "citizen")
    dadar_id = _location_id(session_factory, "dadar")

    assert client.get("/admin/locations/statistics", headers=headers).status_code == 403
    assert (
        client.get(
            f"/admin/locations/{dadar_id}/statistics", headers=headers
        ).status_code
        == 403
    )


def test_unknown_location_returns_404(stats_client):
    client, session_factory = stats_client
    admin_id = _create_user(
        session_factory, "Admin", "missing-admin@example.com", "admin"
    )
    headers = _headers(admin_id, "admin")

    response = client.get("/admin/locations/999999/statistics", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Location not found."
