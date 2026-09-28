# routers/cleaner.py
# Handles cleaner-specific API endpoints for Waste Management AI.
#
# Phase-3 additions: task_started event (timestamps the field-execution stage
# for process mining) and event logging on proof upload. Everything else is
# the existing, tested workflow.

import os
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from database import get_db
from models import CleanupProof, CleanupTask, User, utcnow
from routers.complaints import get_current_cleaner_user
from routers.eventlog import log_event
from schemas import CleanerTaskResponse, CleanupProofResponse

router = APIRouter(prefix="/cleaner", tags=["cleaner"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def build_cleaner_task_response(task: CleanupTask) -> CleanerTaskResponse:
    complaint = task.complaint
    proof_responses = []
    for proof in task.proofs:
        proof_responses.append(
            CleanupProofResponse(
                id=proof.id,
                task_id=proof.task_id,
                image_url=proof.image_url,
                uploaded_by=proof.uploaded_by,
                uploaded_at=proof.uploaded_at.isoformat() if hasattr(proof.uploaded_at, "isoformat") else str(proof.uploaded_at),
                verification_status=proof.verification_status,
                verified_by=proof.verified_by,
                verified_at=proof.verified_at.isoformat() if proof.verified_at and hasattr(proof.verified_at, "isoformat") else (str(proof.verified_at) if proof.verified_at else None),
                rejection_reason=proof.rejection_reason,
            )
        )

    assigned_at_str = (
        task.assigned_at.isoformat()
        if hasattr(task.assigned_at, "isoformat")
        else str(task.assigned_at)
    )
    completed_at_str = (
        task.completed_at.isoformat()
        if task.completed_at and hasattr(task.completed_at, "isoformat")
        else (str(task.completed_at) if task.completed_at else None)
    )

    return CleanerTaskResponse(
        task_id=task.task_id,
        tracking_id=complaint.tracking_id,
        status=task.status,
        assigned_at=assigned_at_str,
        completed_at=completed_at_str,
        notes=task.notes,
        complaint_text=complaint.complaint_text,
        waste_type=complaint.waste_type,
        quantity_severity=complaint.quantity_severity,
        recommended_action=complaint.recommended_action,
        latitude=complaint.latitude,
        longitude=complaint.longitude,
        address_text=complaint.address_text,
        proofs=proof_responses,
    )


def _get_task_checked(db: Session, task_id: str, current_user: User) -> CleanupTask:
    """Shared lookup + object-level authorization for cleaner task endpoints."""
    task = db.query(CleanupTask).filter(CleanupTask.task_id == task_id).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        )
    if current_user.role != "admin" and task.assigned_cleaner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this task.",
        )
    return task


# ---------------------------------------------------------------------------
# GET /cleaner/tasks
# ---------------------------------------------------------------------------
@router.get(
    "/tasks",
    response_model=List[CleanerTaskResponse],
    status_code=status.HTTP_200_OK,
    summary="[Cleaner] List assigned cleanup tasks",
)
def get_cleaner_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_cleaner_user),
):
    """Return tasks assigned to the authenticated cleaner."""
    query = db.query(CleanupTask)
    if current_user.role != "admin":
        query = query.filter(CleanupTask.assigned_cleaner_id == current_user.id)
    tasks = query.order_by(CleanupTask.assigned_at.desc()).all()

    return [build_cleaner_task_response(t) for t in tasks]


# ---------------------------------------------------------------------------
# GET /cleaner/tasks/{task_id}
# ---------------------------------------------------------------------------
@router.get(
    "/tasks/{task_id}",
    response_model=CleanerTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="[Cleaner] Get cleanup task details by task ID",
)
def get_cleaner_task_detail(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_cleaner_user),
):
    """Return task details including location coordinates and instructions."""
    task = _get_task_checked(db, task_id, current_user)
    return build_cleaner_task_response(task)


# ---------------------------------------------------------------------------
# POST /cleaner/tasks/{task_id}/start   (NEW — field-execution timestamp)
# ---------------------------------------------------------------------------
@router.post(
    "/tasks/{task_id}/start",
    response_model=CleanerTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="[Cleaner] Mark a task as started (field-execution timestamp)",
)
def start_cleanup_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_cleaner_user),
):
    """Record that the cleaner began the cleanup. Optional but recommended:
    it gives process mining an explicit field-execution start time; otherwise
    the first proof upload is the only field-stage signal."""
    task = _get_task_checked(db, task_id, current_user)

    if task.status == "assigned":
        task.status = "in_progress"
    elif task.status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task cannot be started from status '{task.status}'.",
        )

    log_event(
        db,
        case_id=task.complaint.tracking_id,
        activity="task_started",
        actor_id=current_user.id,
        actor_role="cleaner",
        old_value="assigned",
        new_value="in_progress",
    )

    try:
        db.commit()
        db.refresh(task)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start task.",
        )

    return build_cleaner_task_response(task)


# ---------------------------------------------------------------------------
# POST /cleaner/tasks/{task_id}/proof
# ---------------------------------------------------------------------------
@router.post(
    "/tasks/{task_id}/proof",
    response_model=CleanupProofResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[Cleaner] Upload cleanup proof photo",
)
async def upload_cleanup_proof(
    task_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_cleaner_user),
):
    """Upload a proof photo file for an assigned cleanup task."""
    task = _get_task_checked(db, task_id, current_user)

    ext = os.path.splitext(file.filename)[1] if file.filename else ".jpg"
    filename = f"proof_{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    contents = await file.read()
    with open(filepath, "wb") as f:
        f.write(contents)

    image_url = f"/uploads/{filename}"

    proof = CleanupProof(
        task_id=task.id,
        image_url=image_url,
        uploaded_by=current_user.id,
        verification_status="pending_verification",
    )
    db.add(proof)
    task.status = "proof_submitted"

    log_event(
        db,
        case_id=task.complaint.tracking_id,
        activity="proof_submitted",
        actor_id=current_user.id,
        actor_role="cleaner",
        old_value=task.status,
        new_value="proof_submitted",
        meta={"proof_id": proof.id, "image_url": image_url},
    )

    try:
        db.commit()
        db.refresh(proof)
        db.refresh(task)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save cleanup proof.",
        )

    return CleanupProofResponse(
        id=proof.id,
        task_id=proof.task_id,
        image_url=proof.image_url,
        uploaded_by=proof.uploaded_by,
        uploaded_at=proof.uploaded_at.isoformat() if hasattr(proof.uploaded_at, "isoformat") else str(proof.uploaded_at),
        verification_status=proof.verification_status,
        verified_by=proof.verified_by,
        verified_at=proof.verified_at.isoformat() if proof.verified_at and hasattr(proof.verified_at, "isoformat") else (str(proof.verified_at) if proof.verified_at else None),
        rejection_reason=proof.rejection_reason,
    )
