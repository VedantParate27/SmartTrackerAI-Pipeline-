import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import _create_database_engine, get_db, run_migrations  # noqa: E402
from models import Complaint, Location, User, cleaner_locations  # noqa: E402
from main import app  # noqa: E402
from routers.auth import create_access_token  # noqa: E402


@pytest.fixture
def location_client(tmp_path):
    engine = _create_database_engine(
        f"sqlite:///{tmp_path / 'authorization.db'}",
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
    return {
        "Authorization": f"Bearer {create_access_token(user_id, role)}",
    }


def _location_id(session_factory, slug):
    with session_factory() as db:
        return db.query(Location).filter(Location.slug == slug).one().id


def _create_complaint(session_factory, user_id, location_id=None):
    with session_factory() as db:
        complaint = Complaint(
            user_id=user_id,
            name="Citizen",
            email="citizen@example.com",
            complaint_text="Overflowing garbage near the market entrance.",
            location_id=location_id,
        )
        db.add(complaint)
        db.commit()
        return complaint.id


def test_admin_can_grant_and_revoke_cleaner_location(location_client):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin@example.com", "admin")
    cleaner_id = _create_user(
        session_factory, "Cleaner", "cleaner@example.com", "cleaner"
    )
    location_id = _location_id(session_factory, "dadar")
    headers = _headers(admin_id, "admin")

    granted = client.post(
        f"/admin/cleaners/{cleaner_id}/locations/{location_id}",
        headers=headers,
    )
    assert granted.status_code == 200
    assert granted.json()["is_active"] is True

    revoked = client.delete(
        f"/admin/cleaners/{cleaner_id}/locations/{location_id}",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["is_active"] is False


def test_non_cleaner_cannot_receive_location_permission(location_client):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin@example.com", "admin")
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen@example.com", "citizen"
    )
    location_id = _location_id(session_factory, "dadar")

    response = client.post(
        f"/admin/cleaners/{citizen_id}/locations/{location_id}",
        headers=_headers(admin_id, "admin"),
    )
    assert response.status_code == 400


def test_non_admin_cannot_grant_or_revoke_location_permission(location_client):
    client, session_factory = location_client
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen2@example.com", "citizen"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "cleaner2@example.com", "cleaner"
    )
    location_id = _location_id(session_factory, "dadar")
    complaint_id = _create_complaint(session_factory, citizen_id, location_id)

    response = client.post(
        f"/admin/cleaners/{cleaner_id}/locations/{location_id}",
        headers=_headers(citizen_id, "citizen"),
    )
    assert response.status_code == 403

    response = client.post(
        f"/admin/complaints/{complaint_id}/assign",
        headers=_headers(citizen_id, "citizen"),
        json={"cleaner_id": cleaner_id},
    )
    assert response.status_code == 403

    response = client.delete(
        f"/admin/cleaners/{cleaner_id}/locations/{location_id}",
        headers=_headers(citizen_id, "citizen"),
    )
    assert response.status_code == 403


def test_cleaner_must_be_permitted_for_location_specific_assignment(location_client):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin2@example.com", "admin")
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen3@example.com", "citizen"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "cleaner3@example.com", "cleaner"
    )
    dadar_id = _location_id(session_factory, "dadar")
    wadala_id = _location_id(session_factory, "wadala")
    complaint_id = _create_complaint(session_factory, citizen_id, wadala_id)

    grant = client.post(
        f"/admin/cleaners/{cleaner_id}/locations/{dadar_id}",
        headers=_headers(admin_id, "admin"),
    )
    assert grant.status_code == 200

    denied = client.post(
        f"/admin/complaints/{complaint_id}/assign",
        headers=_headers(admin_id, "admin"),
        json={"cleaner_id": cleaner_id},
    )
    assert denied.status_code == 403

    grant = client.post(
        f"/admin/cleaners/{cleaner_id}/locations/{wadala_id}",
        headers=_headers(admin_id, "admin"),
    )
    assert grant.status_code == 200

    assigned = client.post(
        f"/admin/complaints/{complaint_id}/assign",
        headers=_headers(admin_id, "admin"),
        json={"cleaner_id": cleaner_id},
    )
    assert assigned.status_code == 200


def test_legacy_complaint_without_location_remains_assignable(location_client):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin3@example.com", "admin")
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen4@example.com", "citizen"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "cleaner4@example.com", "cleaner"
    )
    complaint_id = _create_complaint(session_factory, citizen_id)

    assigned = client.post(
        f"/admin/complaints/{complaint_id}/assign",
        headers=_headers(admin_id, "admin"),
        json={"cleaner_id": cleaner_id},
    )
    assert assigned.status_code == 200


def test_repeated_grant_does_not_duplicate_active_permission(location_client):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin5@example.com", "admin")
    cleaner_id = _create_user(
        session_factory, "Cleaner", "cleaner5@example.com", "cleaner"
    )
    location_id = _location_id(session_factory, "dadar")
    url = f"/admin/cleaners/{cleaner_id}/locations/{location_id}"
    headers = _headers(admin_id, "admin")

    assert client.post(url, headers=headers).status_code == 200
    second_grant = client.post(url, headers=headers)
    assert second_grant.status_code == 200
    assert second_grant.json()["is_active"] is True

    with session_factory() as db:
        permissions = db.execute(
            cleaner_locations.select().where(
                cleaner_locations.c.cleaner_id == cleaner_id,
                cleaner_locations.c.location_id == location_id,
            )
        ).all()
        assert len(permissions) == 1
        assert permissions[0].is_active is True


def test_grant_after_revoke_reactivates_same_permission(location_client):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin6@example.com", "admin")
    cleaner_id = _create_user(
        session_factory, "Cleaner", "cleaner6@example.com", "cleaner"
    )
    location_id = _location_id(session_factory, "dadar")
    url = f"/admin/cleaners/{cleaner_id}/locations/{location_id}"
    headers = _headers(admin_id, "admin")

    assert client.post(url, headers=headers).status_code == 200
    assert client.delete(url, headers=headers).status_code == 200
    assert client.post(url, headers=headers).status_code == 200

    with session_factory() as db:
        permissions = db.execute(
            cleaner_locations.select().where(
                cleaner_locations.c.cleaner_id == cleaner_id,
                cleaner_locations.c.location_id == location_id,
            )
        ).all()
        assert len(permissions) == 1
        assert permissions[0].is_active is True


def test_repeated_revoke_is_successful_and_remains_inactive(location_client):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin7@example.com", "admin")
    cleaner_id = _create_user(
        session_factory, "Cleaner", "cleaner7@example.com", "cleaner"
    )
    location_id = _location_id(session_factory, "dadar")
    url = f"/admin/cleaners/{cleaner_id}/locations/{location_id}"
    headers = _headers(admin_id, "admin")

    assert client.post(url, headers=headers).status_code == 200
    assert client.delete(url, headers=headers).json()["is_active"] is False
    repeated_revoke = client.delete(url, headers=headers)
    assert repeated_revoke.status_code == 200
    assert repeated_revoke.json()["is_active"] is False

    with session_factory() as db:
        permission = db.execute(
            cleaner_locations.select().where(
                cleaner_locations.c.cleaner_id == cleaner_id,
                cleaner_locations.c.location_id == location_id,
            )
        ).one()
        assert permission.is_active is False


def test_assignment_rejects_inactive_complaint_location(location_client):
    client, session_factory = location_client
    admin_id = _create_user(session_factory, "Admin", "admin8@example.com", "admin")
    citizen_id = _create_user(
        session_factory, "Citizen", "citizen8@example.com", "citizen"
    )
    cleaner_id = _create_user(
        session_factory, "Cleaner", "cleaner8@example.com", "cleaner"
    )
    location_id = _location_id(session_factory, "dadar")
    complaint_id = _create_complaint(session_factory, citizen_id, location_id)

    with session_factory() as db:
        db.query(Location).filter(Location.id == location_id).update(
            {"is_active": False}
        )
        db.commit()

    response = client.post(
        f"/admin/complaints/{complaint_id}/assign",
        headers=_headers(admin_id, "admin"),
        json={"cleaner_id": cleaner_id},
    )
    assert response.status_code == 400
