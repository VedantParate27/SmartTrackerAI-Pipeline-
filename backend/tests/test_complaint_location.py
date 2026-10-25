# tests/test_complaint_location.py
# Complaint location input + response support.
#
# Isolated temporary-SQLite setup (same pattern as test_location_authorization.py):
# every test gets its own throwaway database, so the real smarttracker.db is
# never touched. run_migrations() seeds the initial locations
# (dadar / wadala / kalyan-dombivli) into that temporary database.

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.database import _create_database_engine, get_db, run_migrations  # noqa: E402
from backend.models import Complaint, Location, User  # noqa: E402
from backend.main import app  # noqa: E402
from backend.routers.auth import create_access_token  # noqa: E402


@pytest.fixture
def complaint_client(tmp_path):
    engine = _create_database_engine(
        f"sqlite:///{tmp_path / 'complaint_location.db'}",
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


def _complaint_body(**extra):
    payload = {
        "complaint_text": "Wet waste is piling up beside the main gate.",
    }
    payload.update(extra)
    return payload


def test_create_complaint_with_active_location_persists_and_returns_location_id(
    complaint_client,
):
    client, session_factory = complaint_client
    citizen_id = _create_user(
        session_factory, "Citizen", "loc-citizen@example.com", "citizen"
    )
    location_id = _location_id(session_factory, "dadar")

    response = client.post(
        "/complaints/",
        headers=_headers(citizen_id, "citizen"),
        json=_complaint_body(location_id=location_id),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["location_id"] == location_id

    with session_factory() as db:
        complaint = (
            db.query(Complaint)
            .filter(Complaint.tracking_id == body["tracking_id"])
            .one()
        )
        assert complaint.location_id == location_id
        assert complaint.location.slug == "dadar"


def test_create_complaint_rejects_nonexistent_location(complaint_client):
    client, session_factory = complaint_client
    citizen_id = _create_user(
        session_factory, "Citizen", "missing@example.com", "citizen"
    )

    response = client.post(
        "/complaints/",
        headers=_headers(citizen_id, "citizen"),
        json=_complaint_body(location_id=999999),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Location not found."

    with session_factory() as db:
        assert db.query(Complaint).count() == 0


def test_create_complaint_rejects_inactive_location(complaint_client):
    client, session_factory = complaint_client
    citizen_id = _create_user(
        session_factory, "Citizen", "inactive@example.com", "citizen"
    )
    location_id = _location_id(session_factory, "wadala")
    _deactivate_location(session_factory, location_id)

    response = client.post(
        "/complaints/",
        headers=_headers(citizen_id, "citizen"),
        json=_complaint_body(location_id=location_id),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Location is not active."

    with session_factory() as db:
        assert db.query(Complaint).count() == 0


def test_create_complaint_without_location_stays_backward_compatible(complaint_client):
    client, session_factory = complaint_client
    citizen_id = _create_user(
        session_factory, "Citizen", "legacy@example.com", "citizen"
    )

    response = client.post(
        "/complaints/",
        headers=_headers(citizen_id, "citizen"),
        json=_complaint_body(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["location_id"] is None

    with session_factory() as db:
        complaint = (
            db.query(Complaint)
            .filter(Complaint.tracking_id == body["tracking_id"])
            .one()
        )
        assert complaint.location_id is None


def test_create_complaint_with_explicit_null_location_stays_backward_compatible(
    complaint_client,
):
    client, session_factory = complaint_client
    citizen_id = _create_user(
        session_factory, "Citizen", "nulled@example.com", "citizen"
    )

    response = client.post(
        "/complaints/",
        headers=_headers(citizen_id, "citizen"),
        json=_complaint_body(location_id=None),
    )

    assert response.status_code == 201
    assert response.json()["location_id"] is None


def test_location_is_not_inferred_from_coordinates_or_address(complaint_client):
    """Coordinates/address must never silently become a location reference."""
    client, session_factory = complaint_client
    citizen_id = _create_user(
        session_factory, "Citizen", "geo@example.com", "citizen"
    )
    location_id = _location_id(session_factory, "kalyan-dombivli")

    response = client.post(
        "/complaints/",
        headers=_headers(citizen_id, "citizen"),
        json=_complaint_body(
            latitude=19.0178,
            longitude=72.8478,
            address_text="Near the market gate, Dadar",
        ),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["location_id"] is None
    assert body["latitude"] == 19.0178
    assert body["address_text"] == "Near the market gate, Dadar"

    with session_factory() as db:
        complaint = (
            db.query(Complaint)
            .filter(Complaint.tracking_id == body["tracking_id"])
            .one()
        )
        assert complaint.location_id is None
        assert complaint.location_id != location_id


def test_response_includes_location_id_on_read_endpoints(complaint_client):
    client, session_factory = complaint_client
    citizen_id = _create_user(
        session_factory, "Citizen", "reader@example.com", "citizen"
    )
    location_id = _location_id(session_factory, "dadar")
    headers = _headers(citizen_id, "citizen")

    created = client.post(
        "/complaints/",
        headers=headers,
        json=_complaint_body(location_id=location_id),
    )
    assert created.status_code == 201
    tracking_id = created.json()["tracking_id"]

    mine = client.get("/complaints/my", headers=headers)
    assert mine.status_code == 200
    assert mine.json()[0]["location_id"] == location_id

    tracked = client.get(f"/complaints/{tracking_id}", headers=headers)
    assert tracked.status_code == 200
    assert tracked.json()["location_id"] == location_id
