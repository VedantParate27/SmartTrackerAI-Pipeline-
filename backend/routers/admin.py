# routers/admin.py
# Handles admin-only API endpoints for SmartTracker AI.
# Currently implements:
#   GET /admin/complaints                    — view all complaints (admin only)
#   PUT /admin/complaints/{complaint_id}     — update status/priority/department
#   GET /admin/queue                         — admin complaint queue (frontend-compatible shape)
#   POST /admin/responses/{id}/approve       — approve response and update status

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

# Our own modules
from database import get_db
from models import Complaint, User, Response as ComplaintResponseModel, CleanupTask, CleanupProof, utcnow
from schemas import (
    AdminComplaintUpdateRequest, 
    AdminQueueItem, 
    ComplaintResponse,
    ApproveResponseRequest,
    ApproveResponseResult,
    AssignCleanerRequest,
    AssignCleanerResponse,
    VerifyProofRequest,
    VerifyProofResult
)

from routers.complaints import get_current_user, get_current_admin_user

# ---------------------------------------------------------------------------
# LIFECYCLE RULES
# ---------------------------------------------------------------------------
VALID_TRANSITIONS = {
    "pending": {"pending", "in_progress", "resolved", "closed"},
    "in_progress": {"in_progress", "resolved", "closed"},
    "resolved": {"resolved", "closed"},
    "closed": {"closed"}
}

def validate_status_transition(current_status: str, next_status: str):
    """
    Ensure the complaint only moves forward through the allowed lifecycle.
    Raises HTTP 400 Bad Request if the transition is invalid.
    """
    allowed = VALID_TRANSITIONS.get(current_status, set())
    if next_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status transition from '{current_status}' to '{next_status}'."
        )

# ---------------------------------------------------------------------------
# ROUTER
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# GET /admin/complaints
# ---------------------------------------------------------------------------
@router.get(
    "/complaints",
    response_model=List[ComplaintResponse],
    status_code=status.HTTP_200_OK,
    summary="[Admin] List all complaints in the system",
)
def get_all_complaints(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Return every complaint in the system, ordered newest first."""
    complaints = (
        db.query(Complaint)
        .order_by(Complaint.created_at.desc())
        .all()
    )
    return complaints


# ---------------------------------------------------------------------------
# PUT /admin/complaints/{complaint_id}
# ---------------------------------------------------------------------------
@router.put(
    "/complaints/{complaint_id}",
    response_model=ComplaintResponse,
    status_code=status.HTTP_200_OK,
    summary="[Admin] Update status, priority, or department of a complaint",
)
def update_complaint(
    complaint_id: int,
    body: AdminComplaintUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Update one or more of a complaint's administrative fields."""
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if complaint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Complaint not found.",
        )

    if body.status is not None:
        validate_status_transition(complaint.status, body.status)
        complaint.status = body.status

    if body.priority is not None:
        complaint.priority = body.priority

    if body.department is not None:
        complaint.department = body.department

    try:
        db.commit()
        db.refresh(complaint)
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update complaint.",
        )

    return complaint


# ---------------------------------------------------------------------------
# GET /admin/queue
# ---------------------------------------------------------------------------
@router.get(
    "/queue",
    response_model=List[AdminQueueItem],
    status_code=status.HTTP_200_OK,
    summary="[Admin] List complaints in the admin queue (frontend-compatible shape)",
)
def get_admin_queue(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Return every complaint in the system ordered newest first."""
    complaints = (
        db.query(Complaint)
        .order_by(Complaint.created_at.desc())
        .all()
    )
    return complaints


# ---------------------------------------------------------------------------
# GET /admin/queue/{tracking_id}
# ---------------------------------------------------------------------------
@router.get(
    "/queue/{tracking_id}",
    response_model=AdminQueueItem,
    status_code=status.HTTP_200_OK,
    summary="[Admin] Get a single complaint queue item by tracking ID",
)
def get_admin_queue_item(
    tracking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Return a single complaint queue item matching tracking ID."""
    complaint = (
        db.query(Complaint)
        .filter(Complaint.tracking_id == tracking_id)
        .first()
    )
    if complaint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Complaint not found in admin queue.",
        )
    return complaint


# ---------------------------------------------------------------------------
# POST /admin/responses/{id}/approve
# ---------------------------------------------------------------------------
@router.post(
    "/responses/{id}/approve",
    response_model=ApproveResponseResult,
    status_code=status.HTTP_200_OK,
    summary="[Admin] Approve a response and update complaint status",
)
def approve_response(
    id: str,
    request: ApproveResponseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Approve a response for a specific complaint."""
    complaint = db.query(Complaint).filter(Complaint.tracking_id == id).first()
    if not complaint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Complaint not found.",
        )

    validate_status_transition(complaint.status, request.next_status)

    try:
        new_response = ComplaintResponseModel(
            complaint_id=complaint.id,
            response_text=request.text,
            approved_by=current_user.id
        )
        db.add(new_response)
        
        complaint.status = request.next_status
        
        db.commit()
        db.refresh(new_response)
        db.refresh(complaint)
        
        approved_at_str = (
            new_response.approved_at.isoformat() 
            if hasattr(new_response.approved_at, "isoformat") 
            else str(new_response.approved_at)
        )
        
        return ApproveResponseResult(
            tracking_id=complaint.tracking_id,
            response_text=new_response.response_text,
            approved_by=current_user.name,
            approved_at=approved_at_str,
            status=complaint.status
        )
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database commit failed."
        )


# ---------------------------------------------------------------------------
# POST /admin/complaints/{complaint_id}/assign
# ---------------------------------------------------------------------------
@router.post(
    "/complaints/{complaint_id}/assign",
    response_model=AssignCleanerResponse,
    status_code=status.HTTP_200_OK,
    summary="[Admin] Assign a complaint to a cleaner",
)
def assign_cleaner(
    complaint_id: int,
    body: AssignCleanerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Assign a complaint to a cleaner and set complaint status to in_progress."""
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Complaint not found.",
        )

    cleaner = db.query(User).filter(User.id == body.cleaner_id).first()
    if not cleaner or cleaner.role != "cleaner":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only users with role 'cleaner' can be assigned to cleanup tasks.",
        )


    task = db.query(CleanupTask).filter(CleanupTask.complaint_id == complaint.id).first()
    if not task:
        task = CleanupTask(
            complaint_id=complaint.id,
            assigned_cleaner_id=cleaner.id,
            status="assigned",
            notes=body.notes,
        )
        db.add(task)
    else:
        task.assigned_cleaner_id = cleaner.id
        task.status = "assigned"
        if body.notes is not None:
            task.notes = body.notes

    if complaint.status != "in_progress":
        validate_status_transition(complaint.status, "in_progress")
        complaint.status = "in_progress"

    try:
        db.commit()
        db.refresh(task)
        db.refresh(complaint)
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to assign cleaner.",
        )

    assigned_at_str = (
        task.assigned_at.isoformat()
        if hasattr(task.assigned_at, "isoformat")
        else str(task.assigned_at)
    )

    return AssignCleanerResponse(
        task_id=task.task_id,
        tracking_id=complaint.tracking_id,
        assigned_cleaner_id=cleaner.id,
        cleaner_name=cleaner.name,
        status=task.status,
        assigned_at=assigned_at_str,
    )


# ---------------------------------------------------------------------------
# POST /admin/proofs/{proof_id}/verify
# ---------------------------------------------------------------------------
@router.post(
    "/proofs/{proof_id}/verify",
    response_model=VerifyProofResult,
    status_code=status.HTTP_200_OK,
    summary="[Admin] Verify or reject a cleaner's submitted proof",
)
def verify_proof(
    proof_id: int,
    body: VerifyProofRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Verify or reject a submitted cleanup proof and update task/complaint status."""
    proof = db.query(CleanupProof).filter(CleanupProof.id == proof_id).first()
    if not proof:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proof not found.",
        )

    task = proof.task
    complaint = task.complaint

    now = utcnow()
    proof.verified_by = current_user.id
    proof.verified_at = now

    if body.approved:
        proof.verification_status = "verified"
        task.status = "verified"
        task.completed_at = now

        next_comp_status = body.next_status or "resolved"
        if complaint.status != next_comp_status:
            validate_status_transition(complaint.status, next_comp_status)
            complaint.status = next_comp_status
    else:
        proof.verification_status = "rejected"
        proof.rejection_reason = body.rejection_reason
        task.status = "rejected"

    try:
        db.commit()
        db.refresh(proof)
        db.refresh(task)
        db.refresh(complaint)
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify proof.",
        )

    return VerifyProofResult(
        proof_id=proof.id,
        task_id=task.task_id,
        tracking_id=complaint.tracking_id,
        verification_status=proof.verification_status,
        task_status=task.status,
        complaint_status=complaint.status,
        verified_at=now.isoformat(),
    )

