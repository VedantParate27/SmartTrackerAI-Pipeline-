# tests/test_cleaner_location_access.py
# Cleaner task access vs. location grants.
#
# Regression coverage for the revoked-permission authorization gap: a cleaner
# whose location grant was revoked must lose access to the already-assigned,
# location-specific task (listing, viewing, starting, proof upload), while
# location-less legacy tasks stay accessible.
#
# Isolated temporary-SQLite setup (same pattern as test_location_authorization.py):
# every test gets its own throwaway database, so the real smarttracker.db is
# never touched.

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import _create_database_engine, get_db, run_migrations  # noqa: E402
from models import (  # noqa: E402
    CleanupTask,
    Complaint,
    Location,
    User,
    cleaner_locations,
)
from main import app  # noqa: E402
from routers.auth import create_access_token  # noqa: E402

JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"\x00" * 16


@pytest.fixture
def access_client(tmp_path):
    engine = _create_database_engine(
        f"sqlite:///{tmp_path / 'cleaner_location_access.db'}",
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


def _location_id(session_factory, slug="dadar"):
    with session_factory() as db:
        return db.query(Location).filter(Location.slug == slug).one().id


def _grant(session_factory, cleaner_id, location_id, is_active=True):
    with session_factory() as db:
        db.execute(
            cleaner_locations.insert().values(
                cleaner_id=cleaner_id,
                location_id=location_id,
                is_active=is_active,
            )
        )
        db.commit()


def _create_task(session_factory, cleaner_id, location_id=None):
    """A task for a complaint that optionally carries a location."""
    with session_factory() as db:
        complaint = Complaint(
            user_id=None,
            name="Citizen",
            email="citizen@example.com",
            complaint_text="Wet waste left beside the gate.",
            status="in_progress",
            location_id=location_id,
        )
        db.add(complaint)
        db.flush()
        task = CleanupTask(
            complaint_id=complaint.id,
            assigned_cleaner_id=cleaner_id,
            status="assigned",
        )
        db.add(task)
        db.commit()
        return task.task_id


def _upload_proof(client, headers, task_id):
    return client.post(
        f"/cleaner/tasks/{task_id}/proof",
        headers=headers,
        files={"file": ("after.jpg", JPEG_HEAD, "image/jpeg")},
    )


# ---------------------------------------------------------------------------
# Access with an active grant
# ---------------------------------------------------------------------------
def test_active_grant_permits_access_to_an_assigned_task(access_client):
    client, session_factory = access_client
    cleaner_id = _create_user(
        session_factory, "Cleaner", "active-cleaner@example.com", "cleaner"
    )
    location_id = _location_id(session_factory)
    _grant(session_factory, cleaner_id, location_id, is_active=True)
    task_id = _create_task(session_factory, cleaner_id, location_id)
    headers = _headers(cleaner_id, "cleaner")

    detail = client.get(f"/cleaner/tasks/{task_id}", headers=headers)
    assert detail.status_code == 200

    listing = client.get("/cleaner/tasks", headers=headers)
    assert listing.status_code == 200
    assert [t["task_id"] for t in listing.json()] == [task_id]

    started = client.post(f"/cleaner/tasks/{task_id}/start", headers=headers)
    assert started.status_code == 200

    proof = _upload_proof(client, headers, task_id)
    assert proof.status_code == 201


# ---------------------------------------------------------------------------
# Revoked / inactive grant
# ---------------------------------------------------------------------------
def test_revoked_grant_blocks_access_to_an_already_assigned_task(access_client):
    client, session_factory = access_client
    admin_id = _create_user(
        session_factory, "Admin", "revoke-admin@example.com", "admin"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "revoked-cleaner@example.com", "cleaner"
    )
    location_id = _location_id(session_factory)
    _grant(session_factory, cleaner_id, location_id, is_active=True)
    task_id = _create_task(session_factory, cleaner_id, location_id)
    cleaner_headers = _headers(cleaner_id, "cleaner")
    admin_headers = _headers(admin_id, "admin")

    # Sanity: access works while the grant is active.
    assert client.get(f"/cleaner/tasks/{task_id}", headers=cleaner_headers).status_code == 200

    revoked = client.delete(
        f"/admin/cleaners/{cleaner_id}/locations/{location_id}", headers=admin_headers
    )
    assert revoked.status_code == 200

    # The revoked grant no longer authorizes the task.
    detail = client.get(f"/cleaner/tasks/{task_id}", headers=cleaner_headers)
    assert detail.status_code == 403
    assert "revoked" in detail.json()["detail"].lower()

    started = client.post(f"/cleaner/tasks/{task_id}/start", headers=cleaner_headers)
    assert started.status_code == 403

    proof = _upload_proof(client, cleaner_headers, task_id)
    assert proof.status_code == 403

    # The task disappears from the cleaner's list as well.
    listing = client.get("/cleaner/tasks", headers=cleaner_headers)
    assert listing.status_code == 200
    assert listing.json() == []

    # The admin view is unaffected.
    admin_listing = client.get("/cleaner/tasks", headers=admin_headers)
    assert admin_listing.status_code == 200
    assert task_id in [t["task_id"] for t in admin_listing.json()]


def test_inactive_grant_does_not_authorize_access(access_client):
    """An is_active=False grant row is not a permission."""
    client, session_factory = access_client
    cleaner_id = _create_user(
        session_factory, "Cleaner", "inactive-cleaner@example.com", "cleaner"
    )
    location_id = _location_id(session_factory)
    _grant(session_factory, cleaner_id, location_id, is_active=False)
    task_id = _create_task(session_factory, cleaner_id, location_id)
    headers = _headers(cleaner_id, "cleaner")

    assert client.get(f"/cleaner/tasks/{task_id}", headers=headers).status_code == 403
    assert client.post(f"/cleaner/tasks/{task_id}/start", headers=headers).status_code == 403
    assert _upload_proof(client, headers, task_id).status_code == 403
    assert client.get("/cleaner/tasks", headers=headers).json() == []


def test_missing_grant_does_not_authorize_access(access_client):
    client, session_factory = access_client
    cleaner_id = _create_user(
        session_factory, "Cleaner", "nogrant-cleaner@example.com", "cleaner"
    )
    location_id = _location_id(session_factory)
    task_id = _create_task(session_factory, cleaner_id, location_id)
    headers = _headers(cleaner_id, "cleaner")

    assert client.get(f"/cleaner/tasks/{task_id}", headers=headers).status_code == 403


# ---------------------------------------------------------------------------
# Legacy location-less tasks
# ---------------------------------------------------------------------------
def test_location_less_legacy_task_remains_accessible(access_client):
    client, session_factory = access_client
    cleaner_id = _create_user(
        session_factory, "Cleaner", "legacy-cleaner@example.com", "cleaner"
    )
    task_id = _create_task(session_factory, cleaner_id, location_id=None)
    headers = _headers(cleaner_id, "cleaner")

    detail = client.get(f"/cleaner/tasks/{task_id}", headers=headers)
    assert detail.status_code == 200

    listing = client.get("/cleaner/tasks", headers=headers)
    assert [t["task_id"] for t in listing.json()] == [task_id]

    assert client.post(f"/cleaner/tasks/{task_id}/start", headers=headers).status_code == 200


def test_location_less_task_stays_accessible_after_a_grant_is_revoked(access_client):
    """Revoking a grant for one location never blocks legacy work."""
    client, session_factory = access_client
    admin_id = _create_user(
        session_factory, "Admin", "mixed-admin@example.com", "admin"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "mixed-cleaner@example.com", "cleaner"
    )
    location_id = _location_id(session_factory)
    _grant(session_factory, cleaner_id, location_id, is_active=True)
    legacy_task_id = _create_task(session_factory, cleaner_id, location_id=None)
    located_task_id = _create_task(session_factory, cleaner_id, location_id)

    client.delete(
        f"/admin/cleaners/{cleaner_id}/locations/{location_id}",
        headers=_headers(admin_id, "admin"),
    )

    headers = _headers(cleaner_id, "cleaner")
    assert client.get(f"/cleaner/tasks/{legacy_task_id}", headers=headers).status_code == 200
    assert client.get(f"/cleaner/tasks/{located_task_id}", headers=headers).status_code == 403

    listing = client.get("/cleaner/tasks", headers=headers).json()
    assert [t["task_id"] for t in listing] == [legacy_task_id]


# ---------------------------------------------------------------------------
# Other cleaner's task
# ---------------------------------------------------------------------------
def test_cleaner_cannot_access_another_cleaners_task(access_client):
    client, session_factory = access_client
    owner_id = _create_user(
        session_factory, "Owner", "owner-cleaner@example.com", "cleaner"
    )
    other_id = _create_user(
        session_factory, "Other", "other-cleaner@example.com", "cleaner"
    )
    location_id = _location_id(session_factory)
    _grant(session_factory, owner_id, location_id, is_active=True)
    task_id = _create_task(session_factory, owner_id, location_id)
    other_headers = _headers(other_id, "cleaner")

    assert client.get(f"/cleaner/tasks/{task_id}", headers=other_headers).status_code == 403
    assert (
        client.post(f"/cleaner/tasks/{task_id}/start", headers=other_headers).status_code
        == 403
    )
    assert _upload_proof(client, other_headers, task_id).status_code == 403
    assert client.get("/cleaner/tasks", headers=other_headers).json() == []


# ---------------------------------------------------------------------------
# Admin grant/revoke endpoints unchanged
# ---------------------------------------------------------------------------
def test_admin_grant_and_revoke_endpoints_are_unchanged(access_client):
    client, session_factory = access_client
    admin_id = _create_user(
        session_factory, "Admin", "grant-admin@example.com", "admin"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "grant-cleaner@example.com", "cleaner"
    )
    location_id = _location_id(session_factory)
    admin_headers = _headers(admin_id, "admin")

    granted = client.post(
        f"/admin/cleaners/{cleaner_id}/locations/{location_id}", headers=admin_headers
    )
    assert granted.status_code == 200

    # Idempotent grant.
    assert (
        client.post(
            f"/admin/cleaners/{cleaner_id}/locations/{location_id}", headers=admin_headers
        ).status_code
        == 200
    )
    with session_factory() as db:
        rows = db.execute(
            cleaner_locations.select().where(
                cleaner_locations.c.cleaner_id == cleaner_id,
                cleaner_locations.c.location_id == location_id,
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].is_active is True

    revoked = client.delete(
        f"/admin/cleaners/{cleaner_id}/locations/{location_id}", headers=admin_headers
    )
    assert revoked.status_code == 200

    # Idempotent revoke.
    assert (
        client.delete(
            f"/admin/cleaners/{cleaner_id}/locations/{location_id}", headers=admin_headers
        ).status_code
        == 200
    )
    with session_factory() as db:
        rows = db.execute(
            cleaner_locations.select().where(
                cleaner_locations.c.cleaner_id == cleaner_id,
                cleaner_locations.c.location_id == location_id,
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].is_active is False

    # Re-granting restores the access.
    assert (
        client.post(
            f"/admin/cleaners/{cleaner_id}/locations/{location_id}", headers=admin_headers
        ).status_code
        == 200
    )
    with session_factory() as db:
        rows = db.execute(
            cleaner_locations.select().where(
                cleaner_locations.c.cleaner_id == cleaner_id,
                cleaner_locations.c.location_id == location_id,
            )
        ).all()
        assert rows[0].is_active is True
