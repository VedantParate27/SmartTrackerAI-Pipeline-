import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models import Complaint, User  # noqa: E402


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def test_state_round_trip_and_revision_increment():
    empty = client.get("/app/state")
    assert empty.status_code == 200
    assert empty.json() == {"state": None, "revision": 0, "updated_at": None}

    payload = {
        "cases": [{"id": "GRV-2026-0001", "status": "Submitted"}],
        "policies": [{"id": "DOC-001", "status": "Active"}],
    }
    created = client.put("/app/state", json=payload)
    assert created.status_code == 200
    assert created.json()["state"] == payload
    assert created.json()["revision"] == 1
    assert created.json()["updated_at"]

    payload["cases"][0]["status"] = "Pending Review"
    updated = client.put("/app/state", json=payload)
    assert updated.status_code == 200
    assert updated.json()["state"] == payload
    assert updated.json()["revision"] == 2

    loaded = client.get("/app/state")
    assert loaded.status_code == 200
    assert loaded.json()["state"] == payload
    assert loaded.json()["revision"] == 2


def test_state_rejects_duplicate_ids():
    response = client.put(
        "/app/state",
        json={
            "cases": [{"id": "same"}, {"id": "SAME"}],
            "policies": [],
        },
    )
    assert response.status_code == 422


def test_local_frontend_origin_is_allowed_by_cors():
    response = client.options(
        "/app/state",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_existing_auth_complaint_and_admin_flow_still_works():
    credentials = {
        "name": "Integration Admin",
        "email": "integration-admin@example.com",
        "password": "StrongPass9!",
    }
    registered = client.post("/auth/register", json=credentials)
    assert registered.status_code == 201
    assert registered.json()["role"] == "citizen"

    logged_in = client.post(
        "/auth/login",
        json={"email": credentials["email"], "password": credentials["password"]},
    )
    assert logged_in.status_code == 200
    citizen_headers = {
        "Authorization": f"Bearer {logged_in.json()['access_token']}"
    }

    created = client.post(
        "/complaints/",
        headers=citizen_headers,
        json={
            "complaint_text": "The integration test streetlight has been out for a week.",
            "phone": "+91 9876543210",
        },
    )
    assert created.status_code == 201
    tracking_id = created.json()["tracking_id"]

    mine = client.get("/complaints/my", headers=citizen_headers)
    assert mine.status_code == 200
    assert [item["tracking_id"] for item in mine.json()] == [tracking_id]

    tracked = client.get(f"/complaints/{tracking_id}", headers=citizen_headers)
    assert tracked.status_code == 200
    assert tracked.json()["tracking_id"] == tracking_id

    with TestingSessionLocal() as db:
        user = db.query(User).filter(User.email == credentials["email"]).one()
        user.role = "admin"
        complaint_id = (
            db.query(Complaint)
            .filter(Complaint.tracking_id == tracking_id)
            .one()
            .id
        )
        db.commit()

    admin_login = client.post(
        "/auth/login",
        json={"email": credentials["email"], "password": credentials["password"]},
    )
    admin_headers = {
        "Authorization": f"Bearer {admin_login.json()['access_token']}"
    }

    all_complaints = client.get("/admin/complaints", headers=admin_headers)
    assert all_complaints.status_code == 200
    assert any(item["tracking_id"] == tracking_id for item in all_complaints.json())

    updated = client.put(
        f"/admin/complaints/{complaint_id}",
        headers=admin_headers,
        json={
            "status": "resolved",
            "priority": "high",
            "department": "Facilities & Maintenance",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "resolved"
    assert updated.json()["priority"] == "high"
    assert updated.json()["department"] == "Facilities & Maintenance"
