# tests/test_admin_location_management.py
# Admin complaint-location management: PATCH /admin/complaints/{id}/location
#
# The endpoint links (or unlinks) a complaint to a Location. The rules it must
# enforce:
#   * a non-null target location must exist (404) and be active (400);
#   * when the complaint already has a cleanup task with an assigned cleaner,
#     that cleaner must hold an ACTIVE grant for the requested location (403)
#     — otherwise the change would lock the cleaner out of the task they are
#     already working on;
#   * a complaint with no assigned cleaner may be linked to any active
#     location;
#   * clearing the link with location_id=null stays allowed and never needs a
#     grant (clearing only relaxes the location rules);
#   * the endpoint is admin-only and never changes assignments or grants.
#
# Isolated temporary-SQLite setup (same pattern as
# test_location_authorization.py): every test gets its own throwaway database,
# so the real smarttracker.db is never touched.

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.database import _create_database_engine, get_db, run_migrations  # noqa: E402
from backend.models import (  # noqa: E402
    CleanupTask,
    Complaint,
    EventLog,
    Location,
    User,
    cleaner_locations,
)
from backend.main import app  # noqa: E402
from backend.routers.auth import create_access_token  # noqa: E402


@pytest.fixture
def location_client(tmp_path):
    engine = _create_database_engine(
        f"sqlite:///{tmp_path / 'admin_location_management.db'}",
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


def _create_complaint(session_factory, user_id, location_id=None):
    with session_factory() as db:
        complaint = Complaint(
            user_id=user_id,
            name="Citizen",
            email="citizen@example.com",
            complaint_text="Garbage pile near the market entrance.",
            location_id=location_id,
        )
        db.add(complaint)
        db.commit()
        return complaint.id


def _assign_task(session_factory, complaint_id, cleaner_id):
    with session_factory() as db:
        task = CleanupTask(
            complaint_id=complaint_id,
            assigned_cleaner_id=cleaner_id,
            status="assigned",
        )
        db.add(task)
        db.commit()
        return task.id


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


def _complaint_location(session_factory, complaint_id):
    with session_factory() as db:
        return db.query(Complaint).filter(Complaint.id == complaint_id).one().location_id


def _patch_location(client, complaint_id, location_id, headers):
    return client.patch(
        f"/admin/complaints/{complaint_id}/location",
        headers=headers,
        json={"location_id": location_id},
    )


# ---------------------------------------------------------------------------
# Authorised change
# ---------------------------------------------------------------------------

def test_location_change_is_allowed_when_the_assigned_cleaner_has_an_active_grant(
    location_client,
):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin@example.com", "admin")
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen@example.com", "citizen"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "cleaner@example.com", "cleaner"
    )
    dadar_id = _location_id(session_factory, "dadar")
    wadala_id = _location_id(session_factory, "wadala")
    complaint_id = _create_complaint(session_factory, citizen_id, dadar_id)
    _assign_task(session_factory, complaint_id, cleaner_id)
    _grant(session_factory, cleaner_id, wadala_id)

    response = _patch_location(
        client, complaint_id, wadala_id, _headers(admin_id, "admin")
    )

    assert response.status_code == 200, response.text
    assert response.json()["location_id"] == wadala_id
    assert _complaint_location(session_factory, complaint_id) == wadala_id


def test_location_change_is_allowed_when_the_complaint_has_no_assigned_cleaner(
    location_client,
):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin2@example.com", "admin")
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen2@example.com", "citizen"
    )
    dadar_id = _location_id(session_factory, "dadar")
    complaint_id = _create_complaint(session_factory, citizen_id)

    response = _patch_location(
        client, complaint_id, dadar_id, _headers(admin_id, "admin")
    )

    assert response.status_code == 200, response.text
    assert response.json()["location_id"] == dadar_id
    assert _complaint_location(session_factory, complaint_id) == dadar_id


def test_location_change_is_allowed_for_a_task_without_an_assigned_cleaner(
    location_client,
):
    """A task row exists but no cleaner is assigned to it yet."""
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin3@example.com", "admin")
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen3@example.com", "citizen"
    )
    dadar_id = _location_id(session_factory, "dadar")
    complaint_id = _create_complaint(session_factory, citizen_id)
    _assign_task(session_factory, complaint_id, None)

    response = _patch_location(
        client, complaint_id, dadar_id, _headers(admin_id, "admin")
    )

    assert response.status_code == 200, response.text
    assert _complaint_location(session_factory, complaint_id) == dadar_id


# ---------------------------------------------------------------------------
# Rejected change — the assigned cleaner may not work in the target location
# ---------------------------------------------------------------------------

def test_location_change_is_rejected_when_the_assigned_cleaner_has_no_grant(
    location_client,
):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin4@example.com", "admin")
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen4@example.com", "citizen"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "cleaner4@example.com", "cleaner"
    )
    dadar_id = _location_id(session_factory, "dadar")
    wadala_id = _location_id(session_factory, "wadala")
    complaint_id = _create_complaint(session_factory, citizen_id, dadar_id)
    _assign_task(session_factory, complaint_id, cleaner_id)

    response = _patch_location(
        client, complaint_id, wadala_id, _headers(admin_id, "admin")
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "The cleaner assigned to this complaint is not permitted to work in "
        "the requested location."
    )
    # The complaint keeps its original location — nothing was changed.
    assert _complaint_location(session_factory, complaint_id) == dadar_id


def test_location_change_is_rejected_when_the_grant_is_inactive(location_client):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin5@example.com", "admin")
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen5@example.com", "citizen"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "cleaner5@example.com", "cleaner"
    )
    dadar_id = _location_id(session_factory, "dadar")
    wadala_id = _location_id(session_factory, "wadala")
    complaint_id = _create_complaint(session_factory, citizen_id, dadar_id)
    _assign_task(session_factory, complaint_id, cleaner_id)
    _grant(session_factory, cleaner_id, wadala_id, is_active=False)

    response = _patch_location(
        client, complaint_id, wadala_id, _headers(admin_id, "admin")
    )

    assert response.status_code == 403
    assert _complaint_location(session_factory, complaint_id) == dadar_id


def test_location_change_is_rejected_when_the_grant_is_for_another_location(
    location_client,
):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin6@example.com", "admin")
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen6@example.com", "citizen"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "cleaner6@example.com", "cleaner"
    )
    dadar_id = _location_id(session_factory, "dadar")
    wadala_id = _location_id(session_factory, "wadala")
    kalyan_id = _location_id(session_factory, "kalyan-dombivli")
    complaint_id = _create_complaint(session_factory, citizen_id, dadar_id)
    _assign_task(session_factory, complaint_id, cleaner_id)
    _grant(session_factory, cleaner_id, dadar_id)

    response = _patch_location(
        client, complaint_id, kalyan_id, _headers(admin_id, "admin")
    )

    assert response.status_code == 403
    assert _complaint_location(session_factory, complaint_id) == dadar_id


# ---------------------------------------------------------------------------
# Rejected change — the target location itself is not usable
# ---------------------------------------------------------------------------

def test_location_change_is_rejected_for_an_inactive_target_location(
    location_client,
):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin7@example.com", "admin")
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen7@example.com", "citizen"
    )
    dadar_id = _location_id(session_factory, "dadar")
    complaint_id = _create_complaint(session_factory, citizen_id)
    _deactivate_location(session_factory, dadar_id)

    response = _patch_location(
        client, complaint_id, dadar_id, _headers(admin_id, "admin")
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Location is not active."
    assert _complaint_location(session_factory, complaint_id) is None


def test_location_change_to_a_nonexistent_location_returns_404(location_client):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin8@example.com", "admin")
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen8@example.com", "citizen"
    )
    complaint_id = _create_complaint(session_factory, citizen_id)

    response = _patch_location(
        client, complaint_id, 999999, _headers(admin_id, "admin")
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Location not found."


def test_location_change_on_an_unknown_complaint_returns_404(location_client):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin9@example.com", "admin")
    dadar_id = _location_id(session_factory, "dadar")

    response = _patch_location(
        client, 999999, dadar_id, _headers(admin_id, "admin")
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Complaint not found."


# ---------------------------------------------------------------------------
# Clearing the location
# ---------------------------------------------------------------------------

def test_clearing_the_location_is_allowed_without_a_grant(location_client):
    """location_id=null only relaxes the rules, so it needs no grant."""
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin10@example.com", "admin")
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen10@example.com", "citizen"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "cleaner10@example.com", "cleaner"
    )
    dadar_id = _location_id(session_factory, "dadar")
    complaint_id = _create_complaint(session_factory, citizen_id, dadar_id)
    _assign_task(session_factory, complaint_id, cleaner_id)

    response = _patch_location(
        client, complaint_id, None, _headers(admin_id, "admin")
    )

    assert response.status_code == 200, response.text
    assert response.json()["location_id"] is None
    assert _complaint_location(session_factory, complaint_id) is None


# ---------------------------------------------------------------------------
# Authorization and side effects
# ---------------------------------------------------------------------------

def test_location_change_requires_the_admin_role(location_client):
    client, session_factory = location_client
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen11@example.com", "citizen"
    )
    dadar_id = _location_id(session_factory, "dadar")
    complaint_id = _create_complaint(session_factory, citizen_id)

    response = _patch_location(
        client, complaint_id, dadar_id, _headers(citizen_id, "citizen")
    )

    assert response.status_code == 403
    assert _complaint_location(session_factory, complaint_id) is None


def test_rejected_location_change_does_not_touch_the_assignment(location_client):
    """A rejected change must not reassign the cleaner or grant a permission."""
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin12@example.com", "admin")
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen12@example.com", "citizen"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "cleaner12@example.com", "cleaner"
    )
    dadar_id = _location_id(session_factory, "dadar")
    wadala_id = _location_id(session_factory, "wadala")
    complaint_id = _create_complaint(session_factory, citizen_id, dadar_id)
    task_id = _assign_task(session_factory, complaint_id, cleaner_id)

    response = _patch_location(
        client, complaint_id, wadala_id, _headers(admin_id, "admin")
    )
    assert response.status_code == 403

    with session_factory() as db:
        task = db.query(CleanupTask).filter(CleanupTask.id == task_id).one()
        assert task.assigned_cleaner_id == cleaner_id
        permissions = db.execute(
            cleaner_locations.select().where(
                cleaner_locations.c.cleaner_id == cleaner_id,
            )
        ).all()
        assert permissions == []


def test_successful_location_change_is_recorded_in_the_event_log(location_client):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin13@example.com", "admin")
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen13@example.com", "citizen"
    )
    dadar_id = _location_id(session_factory, "dadar")
    wadala_id = _location_id(session_factory, "wadala")
    complaint_id = _create_complaint(session_factory, citizen_id, dadar_id)

    with session_factory() as db:
        tracking_id = (
            db.query(Complaint).filter(Complaint.id == complaint_id).one().tracking_id
        )

    response = _patch_location(
        client, complaint_id, wadala_id, _headers(admin_id, "admin")
    )
    assert response.status_code == 200, response.text

    with session_factory() as db:
        events = (
            db.query(EventLog)
            .filter(
                EventLog.case_id == tracking_id,
                EventLog.activity == "complaint_updated",
            )
            .all()
        )
    assert len(events) == 1
    assert events[0].old_value == str(dadar_id)
    assert events[0].new_value == str(wadala_id)
    assert events[0].actor_role == "admin"
