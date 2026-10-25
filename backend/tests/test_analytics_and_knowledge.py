# tests/test_analytics_and_knowledge.py
# Integration tests for /admin/analytics/* and /admin/policies endpoints.

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.database import _create_database_engine, get_db, run_migrations
from backend.models import User
from backend.main import app
from backend.routers.auth import create_access_token


@pytest.fixture
def api_client(tmp_path):
    test_db_path = tmp_path / "analytics_knowledge_test.db"
    engine = _create_database_engine(
        f"sqlite:///{test_db_path}",
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

    import sqlite3
    from backend.db import get_conn

    def override_get_conn():
        conn = sqlite3.connect(str(test_db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_conn] = override_get_conn

    client = TestClient(app)

    db = session_factory()
    admin = User(
        name="Admin User",
        email="admin_analytics@example.com",
        password_hash="testpass",
        role="admin",
    )
    citizen = User(
        name="Citizen User",
        email="citizen_analytics@example.com",
        password_hash="testpass",
        role="citizen",
    )
    db.add(admin)
    db.add(citizen)
    db.commit()
    db.refresh(admin)
    db.refresh(citizen)

    admin_token = create_access_token(admin.id, admin.role)
    citizen_token = create_access_token(citizen.id, citizen.role)

    yield {
        "client": client,
        "admin_token": admin_token,
        "citizen_token": citizen_token,
        "db": db,
    }

    db.close()
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_conn, None)


def test_analytics_locations_authorization(api_client):
    client = api_client["client"]
    # Unauthenticated
    resp = client.get("/admin/analytics/locations")
    assert resp.status_code == 401

    # Citizen (forbidden)
    resp = client.get(
        "/admin/analytics/locations",
        headers={"Authorization": f"Bearer {api_client['citizen_token']}"},
    )
    assert resp.status_code == 403

    # Admin (authorized)
    resp = client.get(
        "/admin/analytics/locations",
        headers={"Authorization": f"Bearer {api_client['admin_token']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "locations" in data
    assert "totals" in data
    assert "by_waste_type" in data
    assert "by_severity" in data


def test_analytics_locations_filter(api_client):
    client = api_client["client"]
    resp = client.get(
        "/admin/analytics/locations",
        headers={"Authorization": f"Bearer {api_client['admin_token']}"},
    )
    assert resp.status_code == 200
    all_locs = resp.json()["locations"]

    if all_locs:
        target_loc = all_locs[0]
        resp_filtered = client.get(
            f"/admin/analytics/locations?locations={target_loc}",
            headers={"Authorization": f"Bearer {api_client['admin_token']}"},
        )
        assert resp_filtered.status_code == 200
        filtered_locs = resp_filtered.json()["locations"]
        assert filtered_locs == [target_loc]


def test_analytics_time_estimates_authorization_and_output(api_client):
    client = api_client["client"]
    # Citizen -> 403
    resp = client.get(
        "/admin/analytics/time-estimates",
        headers={"Authorization": f"Bearer {api_client['citizen_token']}"},
    )
    assert resp.status_code == 403

    # Admin -> 200
    resp = client.get(
        "/admin/analytics/time-estimates",
        headers={"Authorization": f"Bearer {api_client['admin_token']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "cleanup_time_estimates" in data
    assert "total_records" in data
    assert "generated_at" in data
    assert isinstance(data["cleanup_time_estimates"], list)


def test_policy_knowledge_base_crud(api_client):
    client = api_client["client"]
    admin_auth = {"Authorization": f"Bearer {api_client['admin_token']}"}
    citizen_auth = {"Authorization": f"Bearer {api_client['citizen_token']}"}

    # 1. Non-admin forbidden
    resp = client.get("/admin/policies", headers=citizen_auth)
    assert resp.status_code == 403

    # 2. Admin list policies
    resp = client.get("/admin/policies", headers=admin_auth)
    assert resp.status_code == 200
    policies = resp.json()
    assert len(policies) > 0
    first_policy = policies[0]
    assert "id" in first_policy
    assert "title" in first_policy
    assert "status" in first_policy

    # 3. Filter by department and status
    resp_dept = client.get(
        f"/admin/policies?department={first_policy['department']}",
        headers=admin_auth,
    )
    assert resp_dept.status_code == 200
    assert all(p["department"] == first_policy["department"] for p in resp_dept.json())

    # 4. Search query
    resp_search = client.get(
        f"/admin/policies?search={first_policy['title'][:5]}",
        headers=admin_auth,
    )
    assert resp_search.status_code == 200
    assert any(p["id"] == first_policy["id"] for p in resp_search.json())

    # 5. Ingest new policy
    new_doc_payload = {
        "title": "Hazardous Spill Response Guideline",
        "owner": "Safety Officer",
        "department": "Sanitation & Waste",
        "policyType": "Policy",
        "jurisdiction": "Organisation-wide",
        "version": "1.0",
        "effectiveDate": "2026-11-01",
        "pages": 4,
        "supersedes": first_policy["id"],
    }
    resp_post = client.post(
        "/admin/policies",
        json=new_doc_payload,
        headers=admin_auth,
    )
    assert resp_post.status_code == 201
    created_doc = resp_post.json()
    assert created_doc["title"] == new_doc_payload["title"]
    assert created_doc["status"] == "Pending Approval"
    assert created_doc["supersedes"] == first_policy["id"]

    # 6. Activate policy
    resp_act = client.post(
        f"/admin/policies/{created_doc['id']}/activate",
        headers=admin_auth,
    )
    assert resp_act.status_code == 200
    assert resp_act.json()["status"] == "Active"

    # Verify superseded document was retired
    resp_list_after = client.get("/admin/policies", headers=admin_auth)
    superseded = next(p for p in resp_list_after.json() if p["id"] == first_policy["id"])
    assert superseded["status"] == "Retired"

    # 7. Retire policy
    resp_ret = client.post(
        f"/admin/policies/{created_doc['id']}/retire",
        headers=admin_auth,
    )
    assert resp_ret.status_code == 200
    assert resp_ret.json()["status"] == "Retired"


def test_policy_unauthorized_and_invalid_requests(api_client):
    client = api_client["client"]
    admin_auth = {"Authorization": f"Bearer {api_client['admin_token']}"}

    # 1. Unauthenticated requests
    assert client.get("/admin/policies").status_code == 401
    assert client.post("/admin/policies", json={"title": "Test"}).status_code == 401
    assert client.post("/admin/policies/1/activate").status_code == 401
    assert client.post("/admin/policies/1/retire").status_code == 401

    # 2. Invalid policy ID for activate/retire -> 404
    resp_act_404 = client.post("/admin/policies/NON_EXISTENT_ID_9999/activate", headers=admin_auth)
    assert resp_act_404.status_code == 404

    resp_ret_404 = client.post("/admin/policies/NON_EXISTENT_ID_9999/retire", headers=admin_auth)
    assert resp_ret_404.status_code == 404

    # 3. Invalid payload (missing required title) -> 422
    resp_invalid_payload = client.post("/admin/policies", json={}, headers=admin_auth)
    assert resp_invalid_payload.status_code == 422

    # 4. Invalid supersedes reference (referencing non-existent policy) -> 400
    resp_bad_supersedes = client.post(
        "/admin/policies",
        json={"title": "Valid Title", "supersedes": "NON_EXISTENT_DOC_9999"},
        headers=admin_auth,
    )
    assert resp_bad_supersedes.status_code == 400
