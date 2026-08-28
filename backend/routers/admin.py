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
from models import Complaint, User, Response as ComplaintResponseModel
from schemas import (
    AdminComplaintUpdateRequest, 
    AdminQueueItem, 
    ComplaintResponse,
    ApproveResponseRequest,
    ApproveResponseResult
)

# Reuse the existing JWT authentication dependency from complaints.py.
# We do NOT duplicate any JWT / SECRET_KEY logic here — we just import the
# function that already does it.
from routers.complaints import get_current_user

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
# prefix="/admin" → every route below starts with /admin
# tags=["admin"]  → shown as a separate group on the /docs page
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
    db: Session = Depends(get_db),                   # database session
    current_user: User = Depends(get_current_user),  # the logged-in user
):
    """
    Return every complaint in the system, ordered newest first.

    - Only accessible to users with role **"admin"**.
    - Non-admin users receive **HTTP 403 Forbidden**.

    Requires a valid **JWT Bearer token** in the Authorization header.
    """

    # Step 1 — Check the role.
    # current_user is already verified (valid JWT, real user in the DB).
    # We additionally require the role to be exactly "admin".
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )

    # Step 2 — Fetch all complaints, newest first.
    # No user_id filter here — admins see everything.
    complaints = (
        db.query(Complaint)
        .order_by(Complaint.created_at.desc())   # newest complaint at the top
        .all()
    )

    # Step 3 — Return the list (may be empty if no complaints exist yet).
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
    complaint_id: int,                                    # path parameter — the DB row ID
    body: AdminComplaintUpdateRequest,                    # validated request body
    db: Session = Depends(get_db),                        # database session
    current_user: User = Depends(get_current_user),       # the logged-in user
):
    """
    Update one or more of a complaint's administrative fields.

    Updatable fields (all optional — supply only what you want to change):
    - **status** — e.g. `"in_progress"`, `"resolved"`, `"closed"`
    - **priority** — e.g. `"low"`, `"medium"`, `"high"`, `"urgent"`
    - **department** — e.g. `"Public Works"`, `"Health"`, `"Finance"`

    At least one field must be provided. Omitted fields are left unchanged.

    - Only accessible to users with role **"admin"**.
    - Non-admin users receive **HTTP 403 Forbidden**.
    - Returns **HTTP 404** if no complaint with the given ID exists.

    Requires a valid **JWT Bearer token** in the Authorization header.
    """

    # Step 1 — Check the role.
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )

    # Step 2 — Find the complaint by its database ID.
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if complaint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Complaint not found.",
        )

    # Step 3 — Apply only the fields the admin actually sent.
    # body.status is None when the admin did not include that field in the JSON.
    # We skip None values so we never accidentally overwrite a field with None.
    if body.status is not None:
        validate_status_transition(complaint.status, body.status)
        complaint.status = body.status

    if body.priority is not None:
        complaint.priority = body.priority

    if body.department is not None:
        complaint.department = body.department

    # Step 4 — Save the changes cleanly.
    try:
        db.commit()
        db.refresh(complaint)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update complaint.",
        )

    # Step 5 — Return the updated complaint.
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
    db: Session = Depends(get_db),                   # database session
    current_user: User = Depends(get_current_user),  # the logged-in user
):
    """
    Return every complaint in the system ordered newest first, serialised into
    the **AdminQueueItem** shape that maps database column names to the field
    names expected by the frontend admin queue component.

    Key differences from GET /admin/complaints:
    - `tracking_id` is exposed as **`id`**
    - `name` is exposed as **`requester_name`**
    - `email` is exposed as **`contact`**
    - `complaint_text` is exposed as **`text`**
    - `created_at` is exposed as **`submitted_at`**
    - `department` is exposed as **`assigned_department`**
    - `priority` is **title-cased** ("medium" → "Medium")
    - AI fields not yet in the database are returned as `null` / `[]`

    - Only accessible to users with role **"admin"**.
    - Non-admin users receive **HTTP 403 Forbidden**.

    Requires a valid **JWT Bearer token** in the Authorization header.
    """

    # Step 1 — Check the role.
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )

    # Step 2 — Fetch all complaints, newest first.
    complaints = (
        db.query(Complaint)
        .order_by(Complaint.created_at.desc())
        .all()
    )

    # Step 3 — Return the list.
    # FastAPI serialises each Complaint ORM object through AdminQueueItem.
    # Pydantic's alias support maps DB column names to frontend field names.
    return complaints

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
    current_user: User = Depends(get_current_user),
):
    """
    Approve a response for a specific complaint.
    
    Requires:
    - JWT Bearer token
    - Admin role
    - A valid tracking_id for the complaint
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )

    complaint = db.query(Complaint).filter(Complaint.tracking_id == id).first()
    if not complaint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Complaint not found.",
        )

    try:
        new_response = ComplaintResponseModel(
            complaint_id=complaint.id,
            response_text=request.text,
            approved_by=current_user.id
        )
        db.add(new_response)
        
        validate_status_transition(complaint.status, request.next_status)
        complaint.status = request.next_status
        
        db.commit()
        db.refresh(new_response)
        db.refresh(complaint)
        
        # Make sure datetime is converted to ISO string
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
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database commit failed."
        )
