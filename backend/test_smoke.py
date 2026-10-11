"""
Smoke test: exercises the authenticated complaint lifecycle against the
development database.
Run: python -m pytest test_smoke.py -q   (or) python test_smoke.py
"""
from uuid import uuid4

from fastapi.testclient import TestClient
from database import get_db
from main import app
from models import User

client = TestClient(app)


def test_full_flow():
    citizen = {
        "name": "Smoke Test Citizen",
        "email": f"smoke-citizen-{uuid4().hex}@example.com",
        "password": "SmokeTestPass9!",
    }
    r = client.post("/auth/register", json=citizen)
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "citizen"

    r = client.post(
        "/auth/login",
        json={"email": citizen["email"], "password": citizen["password"]},
    )
    assert r.status_code == 200, r.text
    citizen_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # The authenticated citizen submits a new complaint.
    r = client.post(
        "/complaints/",
        headers=citizen_headers,
        json={"complaint_text": "Wrong item delivered to the community center."},
    )
    assert r.status_code == 201, r.text
    complaint_id = r.json()["tracking_id"]
    assert r.json()["status"] == "pending"

    # The citizen checks the complaint status.
    r = client.get(f"/complaints/{complaint_id}", headers=citizen_headers)
    assert r.status_code == 200, r.text
    assert r.json()["tracking_id"] == complaint_id

    admin = {
        "name": "Smoke Test Admin",
        "email": f"smoke-admin-{uuid4().hex}@example.com",
        "password": "SmokeTestPass9!",
    }
    r = client.post("/auth/register", json=admin)
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "citizen"

    # Promote only this test user through the active test database session.
    # The subsequent admin calls still authenticate through the normal JWT path.
    db_dependency = app.dependency_overrides.get(get_db, get_db)
    db = next(db_dependency())
    try:
        db.query(User).filter(User.email == admin["email"]).one().role = "admin"
        db.commit()
    finally:
        db.close()

    # Authenticate the test admin account.
    r = client.post(
        "/auth/login",
        json={"email": admin["email"], "password": admin["password"]},
    )
    assert r.status_code == 200, r.text
    admin_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # The admin sees the complaint in the queue.
    r = client.get("/admin/queue", headers=admin_headers)
    assert r.status_code == 200, r.text
    ids = [row["tracking_id"] for row in r.json()]
    assert complaint_id in ids

    # The admin approves a response using the authenticated admin identity.
    r = client.post(
        f"/admin/responses/{complaint_id}/approve",
        headers=admin_headers,
        json={
            "text": "Replacement item dispatched.",
            "next_status": "resolved",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"

    # Confirm the citizen can see the resolved status.
    r = client.get(f"/complaints/{complaint_id}", headers=citizen_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"

    print("Smoke test passed: register -> login -> submit -> queue -> approve -> resolved")


if __name__ == "__main__":
    test_full_flow()
