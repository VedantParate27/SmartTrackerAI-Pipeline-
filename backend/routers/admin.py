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
from models import Complaint, User, Response as ComplaintResponseModel, CleanupTask, CleanupProof, utcnow, AIOutput, AICorrection
from schemas import (
    AdminComplaintUpdateRequest, 
    AdminQueueItem, 
    ComplaintResponse,
    ApproveResponseRequest,
    ApproveResponseResult,
    AssignCleanerRequest,
    AssignCleanerResponse,
    VerifyProofRequest,
    VerifyProofResult,
    AIDecisionRequest,
    AIDecisionResponse,
    AICorrectionResponse,
)

from routers.complaints import get_current_user, get_current_admin_user
from routers.eventlog import log_event
from taxonomy import compute_priority

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
        old_status = complaint.status
        validate_status_transition(complaint.status, body.status)
        complaint.status = body.status
        log_event(
            db,
            case_id=complaint.tracking_id,
            activity=("complaint_resolved" if body.status == "resolved"
                      else "complaint_closed" if body.status == "closed"
                      else "complaint_updated"),
            actor_id=current_user.id,
            actor_role="admin",
            old_value=old_status,
            new_value=body.status,
        )
        if body.status in ("resolved", "closed"):
            complaint.resolved_at = utcnow()

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
        
        old_status = complaint.status
        complaint.status = request.next_status
        if request.next_status in ("resolved", "closed"):
            complaint.resolved_at = utcnow()

        log_event(
            db,
            case_id=complaint.tracking_id,
            activity=("guidance_decided" if request.next_status == "resolved"
                      else "admin_decision_made"),
            actor_id=current_user.id,
            actor_role="admin",
            old_value=old_status,
            new_value=request.next_status,
            meta={"response_id": new_response.id},
        )
        if request.next_status == "resolved":
            log_event(
                db,
                case_id=complaint.tracking_id,
                activity="complaint_resolved",
                actor_id=current_user.id,
                actor_role="admin",
                old_value=old_status,
                new_value="resolved",
            )
        
        db.commit()
        db.refresh(new_response)
        db.refresh(complaint)
        
        approved_at_str = (
            new_response.approved_at.isoformat() 
            if hasattr(new_response.approved_at, "isoformat") 
            else str(new_response.approved_at)
        )

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database commit failed."
        )

    return ApproveResponseResult(
        tracking_id=complaint.tracking_id,
        response_text=new_response.response_text,
        approved_by=current_user.name,
        approved_at=approved_at_str,
        status=complaint.status
    )


# ---------------------------------------------------------------------------
# HUMAN-IN-THE-LOOP: accept/correct AI prediction + dispatch/guidance decision
# ---------------------------------------------------------------------------
def _stringify(value):
    """Normalize prediction/decision values into comparable strings."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@router.post(
    "/complaints/{complaint_id}/ai-decision",
    response_model=AIDecisionResponse,
    status_code=status.HTTP_200_OK,
    summary="[Admin] Accept or correct the AI triage and dispatch a cleaner or issue guidance",
)
def record_ai_decision(
    complaint_id: int,
    body: AIDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Human-in-the-loop endpoint (G2/G4 evidence).

    One call performs:
      1. storing the human-decided waste fields on the complaint;
      2. recording every correction (human value != AI value) and every
         accepted field (human value == AI value) in ai_corrections;
      3. completing a mandatory human review if one was flagged;
      4. the dispatch-or-guidance decision (state machine still enforced).
    The AI never reaches this path by itself — a human always decides here.
    """
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if complaint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found.")

    # 1. Human-decided fields + derived priority (rule from taxonomy)
    complaint.waste_type = body.waste_type
    complaint.quantity_severity = body.quantity_severity
    complaint.intervention_required = body.intervention_required
    complaint.priority = compute_priority(
        body.quantity_severity, body.waste_type, body.intervention_required
    )

    # 2. Latest AI output (if any) for accept/correct comparison
    latest_ai = (
        db.query(AIOutput)
        .filter(AIOutput.complaint_id == complaint.id)
        .order_by(AIOutput.predicted_at.desc())
        .first()
    )
    if latest_ai is not None and complaint.triage_mode is None:
        complaint.triage_mode = "ai_assisted"

    corrections = {
        "waste_type": (latest_ai.waste_type_pred if latest_ai else None, body.waste_type),
        "quantity_severity": (latest_ai.severity_pred if latest_ai else None, body.quantity_severity),
        "intervention_required": (
            latest_ai.intervention_required_pred if latest_ai else None,
            body.intervention_required,
        ),
    }

    corrections_recorded = 0
    accepted_fields = 0
    for field_name, (ai_value, human_value) in corrections.items():
        if human_value is None:
            continue  # nothing decided for this field; do not fabricate
        ai_str = _stringify(ai_value)
        human_str = _stringify(human_value)
        is_correction = ai_str is not None and ai_str != human_str
        is_acceptance = ai_str is not None and ai_str == human_str
        if not (is_correction or is_acceptance):
            # No AI output for this field: store the human decision only if
            # the caller explicitly supplied it via body.corrections.
            explicit = next(
                (c for c in body.corrections if c.field_name == field_name), None
            )
            if explicit is None:
                continue
            ai_str = explicit.ai_value

        db.add(
            AICorrection(
                complaint_id=complaint.id,
                field_name=field_name,
                ai_value=ai_str,
                admin_value=human_str,
                admin_id=current_user.id,
            )
        )
        if is_correction:
            corrections_recorded += 1
            log_event(
                db,
                case_id=complaint.tracking_id,
                activity="ai_correction_recorded",
                actor_id=current_user.id,
                actor_role="admin",
                old_value=ai_str,
                new_value=human_str,
                meta={"field": field_name},
            )
        elif is_acceptance:
            accepted_fields += 1

    # 3. Mandatory human review completed?
    review_completed = False
    if complaint.review_required:
        complaint.review_required = False
        complaint.review_reason = None
        review_completed = True
        log_event(
            db,
            case_id=complaint.tracking_id,
            activity="human_review_completed",
            actor_id=current_user.id,
            actor_role="admin",
            new_value="reviewed",
            meta={
                "corrections": corrections_recorded,
                "accepted_fields": accepted_fields,
                "decision": body.decision,
            },
        )

    log_event(
        db,
        case_id=complaint.tracking_id,
        activity="admin_decision_made",
        actor_id=current_user.id,
        actor_role="admin",
        new_value=body.decision,
        meta={"corrections": corrections_recorded, "accepted_fields": accepted_fields},
    )

    # 4. Dispatch or guidance (existing state machine still guards transitions)
    task_id = None
    resolved_at_str = None
    if body.decision == "dispatch":
        log_event(
            db,
            case_id=complaint.tracking_id,
            activity="dispatch_decided",
            actor_id=current_user.id,
            actor_role="admin",
            new_value="dispatch",
        )
        if complaint.status != "in_progress":
            validate_status_transition(complaint.status, "in_progress")
            complaint.status = "in_progress"
    else:  # guidance
        if complaint.status != "resolved":
            validate_status_transition(complaint.status, "resolved")
            complaint.status = "resolved"
        complaint.resolved_at = utcnow()
        resolved_at_str = complaint.resolved_at.isoformat()
        response_row = ComplaintResponseModel(
            complaint_id=complaint.id,
            response_text=(body.guidance_text or "").strip(),
            approved_by=current_user.id,
        )
        db.add(response_row)
        log_event(
            db,
            case_id=complaint.tracking_id,
            activity="guidance_decided",
            actor_id=current_user.id,
            actor_role="admin",
            new_value="guidance",
            meta={"response_id": response_row.id},
        )
        log_event(
            db,
            case_id=complaint.tracking_id,
            activity="complaint_resolved",
            actor_id=current_user.id,
            actor_role="admin",
            old_value="pending",
            new_value="resolved",
        )

    try:
        db.commit()
        db.refresh(complaint)
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record AI decision.",
        )

    if body.decision == "dispatch":
        task = db.query(CleanupTask).filter(CleanupTask.complaint_id == complaint.id).first()
        task_id = task.task_id if task else None

    return AIDecisionResponse(
        tracking_id=complaint.tracking_id,
        triage_mode=complaint.triage_mode or "manual",
        review_completed=review_completed,
        decision=body.decision,
        waste_type=complaint.waste_type,
        quantity_severity=complaint.quantity_severity,
        intervention_required=complaint.intervention_required,
        priority=complaint.priority,
        status=complaint.status,
        task_id=task_id,
        corrections_recorded=corrections_recorded,
        acceptance_rate_fields=accepted_fields,
        resolved_at=resolved_at_str,
    )


@router.get(
    "/complaints/{complaint_id}/corrections",
    response_model=list[AICorrectionResponse],
    summary="[Admin] List stored AI accept/correct records for a complaint",
)
def list_ai_corrections(
    complaint_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_admin_user),
):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if complaint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found.")
    return (
        db.query(AICorrection)
        .filter(AICorrection.complaint_id == complaint_id)
        .order_by(AICorrection.created_at.asc())
        .all()
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
    is_reassignment = task is not None and task.assigned_cleaner_id not in (None, cleaner.id)
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

    log_event(
        db,
        case_id=complaint.tracking_id,
        activity="cleaner_reassigned" if is_reassignment else "cleaner_assigned",
        actor_id=current_user.id,
        actor_role="admin",
        new_value=str(cleaner.id),
        meta={"task_id": task.task_id, "cleaner_name": cleaner.name, "notes": body.notes},
    )

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
        if next_comp_status in ("resolved", "closed"):
            complaint.resolved_at = now
        log_event(
            db,
            case_id=complaint.tracking_id,
            activity="proof_verified",
            actor_id=current_user.id,
            actor_role="admin",
            old_value="pending_verification",
            new_value="verified",
            meta={"proof_id": proof.id, "complaint_status": complaint.status},
        )
    else:
        proof.verification_status = "rejected"
        proof.rejection_reason = body.rejection_reason
        task.status = "rejected"
        log_event(
            db,
            case_id=complaint.tracking_id,
            activity="proof_rejected",
            actor_id=current_user.id,
            actor_role="admin",
            old_value="pending_verification",
            new_value="rejected",
            meta={"proof_id": proof.id, "rejection_reason": body.rejection_reason},
        )

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

