"""
Smoke test: exercises every route once against the seeded db.
Run: python -m pytest test_smoke.py -q   (or) python test_smoke.py
"""
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_full_flow():
    # customer (id=1) submits a new complaint
    r = client.post("/complaints", json={"user_id": 1, "complaint_text": "Wrong item delivered."})
    assert r.status_code == 201, r.text
    complaint_id = r.json()["id"]
    assert r.json()["status"] == "submitted"

    # run the AI pipeline (stubbed)
    r = client.post(f"/complaints/{complaint_id}/process")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "awaiting_review"

    # customer checks status
    r = client.get(f"/complaints/{complaint_id}")
    assert r.status_code == 200
    assert r.json()["id"] == complaint_id

    # admin sees it in the queue
    r = client.get("/admin/queue")
    assert r.status_code == 200
    ids = [row["id"] for row in r.json()]
    assert complaint_id in ids

    # admin (id=2) approves
    r = client.post(
        f"/admin/responses/{complaint_id}/approve",
        json={"admin_id": 2, "final_response": "Replacement item dispatched."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"

    # confirm resolved
    r = client.get(f"/complaints/{complaint_id}")
    assert r.json()["status"] == "resolved"

    print("Smoke test passed: submit -> process -> queue -> approve -> resolved")


if __name__ == "__main__":
    test_full_flow()
