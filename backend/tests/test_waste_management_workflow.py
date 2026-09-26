import io
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from test_app_state import TestingSessionLocal, app, client  # noqa: E402
from models import User, Complaint, CleanupTask, CleanupProof  # noqa: E402



def test_full_waste_management_end_to_end_workflow():
    # 1. Register Citizen, Cleaner, and Admin
    citizen_reg = client.post("/auth/register", json={
        "name": "Citizen User",
        "email": "citizen@example.com",
        "password": "Password123!",
    })
    assert citizen_reg.status_code == 201

    cleaner_reg = client.post("/auth/register", json={
        "name": "Cleaner User",
        "email": "cleaner@example.com",
        "password": "Password123!",
    })
    assert cleaner_reg.status_code == 201
    cleaner_id = cleaner_reg.json()["id"]

    # Manually promote cleaner and create admin in DB session
    with TestingSessionLocal() as db:
        cleaner_user = db.query(User).filter(User.id == cleaner_id).one()
        cleaner_user.role = "cleaner"

        admin_user = User(
            name="Admin User",
            email="admin@example.com",
            password_hash=cleaner_user.password_hash,
            role="admin",
        )
        db.add(admin_user)
        db.commit()
        admin_id = admin_user.id

    # 2. Log in all three users
    citizen_login = client.post("/auth/login", json={"email": "citizen@example.com", "password": "Password123!"})
    assert citizen_login.status_code == 200
    citizen_token = citizen_login.json()["access_token"]
    citizen_headers = {"Authorization": f"Bearer {citizen_token}"}

    cleaner_login = client.post("/auth/login", json={"email": "cleaner@example.com", "password": "Password123!"})
    assert cleaner_login.status_code == 200
    cleaner_token = cleaner_login.json()["access_token"]
    cleaner_headers = {"Authorization": f"Bearer {cleaner_token}"}

    admin_login = client.post("/auth/login", json={"email": "admin@example.com", "password": "Password123!"})
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 3. Citizen submits a Waste Complaint with location and classification
    complaint_payload = {
        "complaint_text": "Discarded CRT monitor and battery waste near public park entrance.",
        "phone": "+91 9876543210",
        "waste_type": "E-waste",
        "waste_context": "Outdoor public park, accumulated near entrance",
        "quantity_severity": "large",
        "recommended_action": "Specialized electronic waste recycling collection required.",
        "intervention_required": True,
        "latitude": 12.9716,
        "longitude": 77.5946,
        "address_text": "Central Park Gate 2, MG Road",
    }
    created = client.post("/complaints/", headers=citizen_headers, json=complaint_payload)
    assert created.status_code == 201
    comp_data = created.json()
    tracking_id = comp_data["tracking_id"]
    assert comp_data["status"] == "pending"
    assert comp_data["waste_type"] == "E-waste"
    assert comp_data["latitude"] == 12.9716

    with TestingSessionLocal() as db:
        complaint_db = db.query(Complaint).filter(Complaint.tracking_id == tracking_id).one()
        complaint_id = complaint_db.id

    # 4. Admin inspects queue and single item
    queue_res = client.get("/admin/queue", headers=admin_headers)
    assert queue_res.status_code == 200
    assert any(item["tracking_id"] == tracking_id for item in queue_res.json())

    single_queue_res = client.get(f"/admin/queue/{tracking_id}", headers=admin_headers)
    assert single_queue_res.status_code == 200
    assert single_queue_res.json()["tracking_id"] == tracking_id
    assert single_queue_res.json()["waste_type"] == "E-waste"

    # 5. Admin assigns complaint to cleaner
    assign_res = client.post(
        f"/admin/complaints/{complaint_id}/assign",
        headers=admin_headers,
        json={"cleaner_id": cleaner_id, "notes": "Handle with safety gloves for e-waste."},
    )
    assert assign_res.status_code == 200
    assign_data = assign_res.json()
    task_id = assign_data["task_id"]
    assert assign_data["status"] == "assigned"
    assert assign_data["assigned_cleaner_id"] == cleaner_id

    # Verify complaint status updated to in_progress
    tracked_comp = client.get(f"/complaints/{tracking_id}", headers=citizen_headers)
    assert tracked_comp.status_code == 200
    assert tracked_comp.json()["status"] == "in_progress"

    # 6. Cleaner views assigned tasks and task detail
    tasks_res = client.get("/cleaner/tasks", headers=cleaner_headers)
    assert tasks_res.status_code == 200
    assert len(tasks_res.json()) == 1
    assert tasks_res.json()[0]["task_id"] == task_id
    assert tasks_res.json()[0]["latitude"] == 12.9716

    task_detail = client.get(f"/cleaner/tasks/{task_id}", headers=cleaner_headers)
    assert task_detail.status_code == 200
    assert task_detail.json()["task_id"] == task_id
    assert task_detail.json()["waste_type"] == "E-waste"

    # 7. Cleaner uploads cleanup proof photo
    dummy_image = io.BytesIO(b"fake image bytes")
    files = {"file": ("proof_photo.jpg", dummy_image, "image/jpeg")}
    upload_res = client.post(
        f"/cleaner/tasks/{task_id}/proof",
        headers=cleaner_headers,
        files=files,
    )
    assert upload_res.status_code == 201
    proof_data = upload_res.json()
    proof_id = proof_data["id"]
    assert proof_data["verification_status"] == "pending_verification"
    assert "/uploads/proof_" in proof_data["image_url"]

    # Verify task detail shows uploaded proof
    task_after_upload = client.get(f"/cleaner/tasks/{task_id}", headers=cleaner_headers)
    assert task_after_upload.json()["status"] == "proof_submitted"
    assert len(task_after_upload.json()["proofs"]) == 1

    # 8. Admin verifies proof photo
    verify_res = client.post(
        f"/admin/proofs/{proof_id}/verify",
        headers=admin_headers,
        json={"approved": True, "next_status": "resolved"},
    )
    assert verify_res.status_code == 200
    verify_data = verify_res.json()
    assert verify_data["verification_status"] == "verified"
    assert verify_data["task_status"] == "verified"
    assert verify_data["complaint_status"] == "resolved"

    # 9. Verify final complaint state for citizen
    final_comp = client.get(f"/complaints/{tracking_id}", headers=citizen_headers)
    assert final_comp.status_code == 200
    assert final_comp.json()["status"] == "resolved"


def test_approve_response_error_handling_preservation():
    # Setup admin & complaint
    with TestingSessionLocal() as db:
        user = User(name="Admin Error", email="admin-err@example.com", password_hash="hash", role="admin")
        comp = Complaint(name="Civ", email="civ@example.com", complaint_text="Broken trash bin in neighborhood", status="closed")
        db.add(user)
        db.add(comp)
        db.commit()
        db.refresh(user)
        db.refresh(comp)
        tracking_id = comp.tracking_id

    login = client.post("/auth/login", json={"email": "admin-err@example.com", "password": "hash"})
    # Mock passlib match by overriding or using standard login for existing test user
    # Or register properly via auth:
    reg = client.post("/auth/register", json={"name": "Admin Err2", "email": "admin-err2@example.com", "password": "Password123!"})
    assert reg.status_code == 201
    with TestingSessionLocal() as db:
        u = db.query(User).filter(User.email == "admin-err2@example.com").one()
        u.role = "admin"
        c = db.query(Complaint).filter(Complaint.tracking_id == tracking_id).one()
        db.commit()

    log2 = client.post("/auth/login", json={"email": "admin-err2@example.com", "password": "Password123!"})
    adm_headers = {"Authorization": f"Bearer {log2.json()['access_token']}"}

    # Attempt invalid transition from 'closed' -> 'in_progress'
    invalid_approve = client.post(
        f"/admin/responses/{tracking_id}/approve",
        headers=adm_headers,
        json={"text": "Reopening closed case", "next_status": "in_progress"},
    )
    # Should return 400 Bad Request, NOT 500
    assert invalid_approve.status_code == 400
    assert "Invalid status transition" in invalid_approve.json()["detail"]


def test_proof_rejection_and_resubmission_flow():
    # 1. Register Citizen, Cleaner, and Admin
    cit_reg = client.post("/auth/register", json={"name": "Rej Cit", "email": "rej-cit@example.com", "password": "Password123!"})
    clean_reg = client.post("/auth/register", json={"name": "Rej Clean", "email": "rej-clean@example.com", "password": "Password123!"})
    adm_reg = client.post("/auth/register", json={"name": "Rej Adm", "email": "rej-adm@example.com", "password": "Password123!"})
    cleaner_id = clean_reg.json()["id"]

    with TestingSessionLocal() as db:
        c_user = db.query(User).filter(User.id == cleaner_id).one()
        c_user.role = "cleaner"
        a_user = db.query(User).filter(User.id == adm_reg.json()["id"]).one()
        a_user.role = "admin"
        db.commit()

    cit_token = client.post("/auth/login", json={"email": "rej-cit@example.com", "password": "Password123!"}).json()["access_token"]
    clean_token = client.post("/auth/login", json={"email": "rej-clean@example.com", "password": "Password123!"}).json()["access_token"]
    adm_token = client.post("/auth/login", json={"email": "rej-adm@example.com", "password": "Password123!"}).json()["access_token"]

    cit_headers = {"Authorization": f"Bearer {cit_token}"}
    clean_headers = {"Authorization": f"Bearer {clean_token}"}
    adm_headers = {"Authorization": f"Bearer {adm_token}"}

    # 2. Submit complaint & assign cleaner
    comp = client.post("/complaints/", headers=cit_headers, json={
        "complaint_text": "Medical waste syringe discarded in alley.",
        "waste_type": "Medical waste",
        "intervention_required": True
    }).json()
    tracking_id = comp["tracking_id"]

    with TestingSessionLocal() as db:
        comp_id = db.query(Complaint).filter(Complaint.tracking_id == tracking_id).one().id

    assign = client.post(f"/admin/complaints/{comp_id}/assign", headers=adm_headers, json={"cleaner_id": cleaner_id}).json()
    task_id = assign["task_id"]

    # 3. Cleaner uploads Proof 1
    file1 = {"file": ("proof1.jpg", io.BytesIO(b"blurry image"), "image/jpeg")}
    upload1 = client.post(f"/cleaner/tasks/{task_id}/proof", headers=clean_headers, files=file1).json()
    proof1_id = upload1["id"]

    # 4. Admin rejects Proof 1
    rej_res = client.post(f"/admin/proofs/{proof1_id}/verify", headers=adm_headers, json={
        "approved": False,
        "rejection_reason": "Image is blurry and site is not cleared."
    })
    assert rej_res.status_code == 200
    rej_data = rej_res.json()
    assert rej_data["verification_status"] == "rejected"
    assert rej_data["task_status"] == "rejected"
    assert rej_data["complaint_status"] == "in_progress"

    # 5. Cleaner uploads Proof 2 (Resubmission)
    file2 = {"file": ("proof2.jpg", io.BytesIO(b"clear image"), "image/jpeg")}
    upload2 = client.post(f"/cleaner/tasks/{task_id}/proof", headers=clean_headers, files=file2).json()
    proof2_id = upload2["id"]
    assert upload2["verification_status"] == "pending_verification"

    # Task status becomes proof_submitted again
    task_after = client.get(f"/cleaner/tasks/{task_id}", headers=clean_headers).json()
    assert task_after["status"] == "proof_submitted"
    # Both proofs are present in history
    assert len(task_after["proofs"]) == 2
    assert task_after["proofs"][0]["verification_status"] == "rejected"
    assert task_after["proofs"][1]["verification_status"] == "pending_verification"


def test_self_disposal_guidance_path():
    reg = client.post("/auth/register", json={"name": "Self Cit", "email": "self-cit@example.com", "password": "Password123!"})
    adm_reg = client.post("/auth/register", json={"name": "Self Adm", "email": "self-adm@example.com", "password": "Password123!"})

    with TestingSessionLocal() as db:
        a_user = db.query(User).filter(User.id == adm_reg.json()["id"]).one()
        a_user.role = "admin"
        db.commit()

    cit_token = client.post("/auth/login", json={"email": "self-cit@example.com", "password": "Password123!"}).json()["access_token"]
    adm_token = client.post("/auth/login", json={"email": "self-adm@example.com", "password": "Password123!"}).json()["access_token"]

    cit_headers = {"Authorization": f"Bearer {cit_token}"}
    adm_headers = {"Authorization": f"Bearer {adm_token}"}

    # Submit minor complaint requiring no intervention
    comp = client.post("/complaints/", headers=cit_headers, json={
        "complaint_text": "Single candy wrapper on sidewalk.",
        "waste_type": "Dry waste",
        "quantity_severity": "small",
        "recommended_action": "Please dispose of wrapper in the nearest dry waste bin.",
        "intervention_required": False
    }).json()
    tracking_id = comp["tracking_id"]
    assert comp["status"] == "pending"

    # Admin approves guidance response directly resolving complaint without cleaner task
    appr = client.post(f"/admin/responses/{tracking_id}/approve", headers=adm_headers, json={
        "text": "Guidance provided: Please dispose in nearest bin.",
        "next_status": "resolved"
    })
    assert appr.status_code == 200
    assert appr.json()["status"] == "resolved"

    comp_final = client.get(f"/complaints/{tracking_id}", headers=cit_headers).json()
    assert comp_final["status"] == "resolved"


def test_role_boundary_enforcement():
    c1 = client.post("/auth/register", json={"name": "B Cit", "email": "b-cit@example.com", "password": "Password123!"}).json()
    cl1 = client.post("/auth/register", json={"name": "B Clean1", "email": "b-clean1@example.com", "password": "Password123!"}).json()
    cl2 = client.post("/auth/register", json={"name": "B Clean2", "email": "b-clean2@example.com", "password": "Password123!"}).json()
    adm = client.post("/auth/register", json={"name": "B Adm", "email": "b-adm@example.com", "password": "Password123!"}).json()

    with TestingSessionLocal() as db:
        db.query(User).filter(User.id == cl1["id"]).one().role = "cleaner"
        db.query(User).filter(User.id == cl2["id"]).one().role = "cleaner"
        db.query(User).filter(User.id == adm["id"]).one().role = "admin"
        db.commit()

    cit_headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'email': 'b-cit@example.com', 'password': 'Password123!'}).json()['access_token']}"}
    cl1_headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'email': 'b-clean1@example.com', 'password': 'Password123!'}).json()['access_token']}"}
    cl2_headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'email': 'b-clean2@example.com', 'password': 'Password123!'}).json()['access_token']}"}
    adm_headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'email': 'b-adm@example.com', 'password': 'Password123!'}).json()['access_token']}"}

    # 1. Citizen cannot access cleaner task list
    assert client.get("/cleaner/tasks", headers=cit_headers).status_code == 403

    # 2. Citizen cannot upload proof
    assert client.post("/cleaner/tasks/TSK-fake/proof", headers=cit_headers, files={"file": ("f.jpg", io.BytesIO(b"1"), "image/jpeg")}).status_code == 403

    # 3. Cleaner cannot access admin queue
    assert client.get("/admin/queue", headers=cl1_headers).status_code == 403

    # 4. Admin cannot assign task to non-cleaner (e.g. citizen ID)
    comp = client.post("/complaints/", headers=cit_headers, json={"complaint_text": "Boundary test complaint text"}).json()
    with TestingSessionLocal() as db:
        comp_db_id = db.query(Complaint).filter(Complaint.tracking_id == comp["tracking_id"]).one().id

    assign_to_citizen = client.post(f"/admin/complaints/{comp_db_id}/assign", headers=adm_headers, json={"cleaner_id": c1["id"]})
    assert assign_to_citizen.status_code == 400
    assert "Only users with role 'cleaner'" in assign_to_citizen.json()["detail"]

    # Assign to legitimate cleaner 1
    assign_cl1 = client.post(f"/admin/complaints/{comp_db_id}/assign", headers=adm_headers, json={"cleaner_id": cl1["id"]})
    assert assign_cl1.status_code == 200
    task_id = assign_cl1.json()["task_id"]

    # 5. Cleaner 2 cannot access Cleaner 1's task detail
    assert client.get(f"/cleaner/tasks/{task_id}", headers=cl2_headers).status_code == 403

    # Cleaner 1 can access task detail
    assert client.get(f"/cleaner/tasks/{task_id}", headers=cl1_headers).status_code == 200

