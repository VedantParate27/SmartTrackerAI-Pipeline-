import pytest
from datetime import datetime, timezone
from backend.models import Complaint, CleanupTask, CleanupProof, WasteAIResult, User
from backend.routers.cleaner import build_cleaner_task_response
from backend.schemas import CleanerTaskResponse

def test_build_cleaner_task_response_with_original_image():
    complaint = Complaint(
        id=901,
        tracking_id="TRK-IMG-001",
        name="Test Citizen",
        email="citizen@test.com",
        complaint_text="Piles of plastic on street corner",
        waste_type="dry",
        manual_address="Station Road, Ward 4",
        status="in_progress",
    )
    task = CleanupTask(
        id=501,
        task_id="TSK-501",
        complaint_id=901,
        assigned_cleaner_id=2,
        status="in_progress",
        assigned_at=datetime.now(timezone.utc),
    )
    task.complaint = complaint
    task.proofs = []

    ai_result = WasteAIResult(
        complaint_id=901,
        image_url="uploads/complaints/test_img.jpg",
    )
    complaint.waste_ai_results = [ai_result]

    resp = build_cleaner_task_response(task)
    assert isinstance(resp, CleanerTaskResponse)
    assert resp.image_url == "uploads/complaints/test_img.jpg"
    assert resp.image_path == "uploads/complaints/test_img.jpg"
    assert resp.location_display == "Station Road, Ward 4"

def test_build_cleaner_task_response_gps_coordinates_only():
    complaint = Complaint(
        id=902,
        tracking_id="TRK-GPS-002",
        name="Test Citizen",
        email="citizen@test.com",
        complaint_text="Illegal dumping in field",
        latitude=19.1234,
        longitude=72.8765,
        address_text=None,
        manual_address=None,
        status="in_progress",
    )
    task = CleanupTask(
        id=502,
        task_id="TSK-502",
        complaint_id=902,
        assigned_cleaner_id=2,
        status="assigned",
        assigned_at=datetime.now(timezone.utc),
    )
    task.complaint = complaint
    task.proofs = []

    resp = build_cleaner_task_response(task)
    assert resp.latitude == 19.1234
    assert resp.longitude == 72.8765
    assert resp.location_display == "GPS (19.1234, 72.8765)"

def test_build_cleaner_task_response_no_location():
    complaint = Complaint(
        id=903,
        tracking_id="TRK-NOLOC-003",
        name="Test Citizen",
        email="citizen@test.com",
        complaint_text="Trash spotted",
        latitude=None,
        longitude=None,
        address_text=None,
        manual_address=None,
        status="pending",
    )
    task = CleanupTask(
        id=503,
        task_id="TSK-503",
        complaint_id=903,
        assigned_cleaner_id=2,
        status="assigned",
        assigned_at=None,
    )
    task.complaint = complaint
    task.proofs = []

    resp = build_cleaner_task_response(task)
    assert resp.location_display == "Location not available"
    assert resp.assigned_at is None

def test_build_cleaner_task_response_legacy_proofs_and_null_timestamps():
    complaint = Complaint(
        id=904,
        tracking_id="TRK-PROOF-004",
        name="Test Citizen",
        email="citizen@test.com",
        complaint_text="Overflowing bin",
        status="completed",
        image_path="backend\\uploads\\complaints\\test_legacy.jpg",
    )
    proof = CleanupProof(
        id=88,
        task_id=504,
        image_url=None,
        image_path="backend\\uploads\\cleanup_proofs\\proof_legacy.png",
        uploaded_by=None,
        uploaded_at=None,
        verification_status="pending_verification",
    )
    task = CleanupTask(
        id=504,
        task_id=None,
        complaint_id=904,
        assigned_cleaner_id=2,
        status="completed",
        assigned_at=None,
    )
    task.complaint = complaint
    task.proofs = [proof]

    resp = build_cleaner_task_response(task)
    assert resp.task_id == "TSK-504"
    assert resp.assigned_at is None
    assert resp.image_url == "backend/uploads/complaints/test_legacy.jpg"
    assert len(resp.proofs) == 1
    assert resp.proofs[0].uploaded_by is None
    assert resp.proofs[0].image_url == "backend/uploads/cleanup_proofs/proof_legacy.png"
    assert resp.proofs[0].uploaded_at is None

