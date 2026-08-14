# routers/admin.py
# Handles admin-only API endpoints for SmartTracker AI.
# Currently implements:
#   GET /admin/complaints                    — view all complaints (admin only)
#   PUT /admin/complaints/{complaint_id}     — update status/priority/department

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

# Our own modules
from database import get_db
from models import Complaint, User
from schemas import AdminComplaintUpdateRequest, ComplaintResponse

# Reuse the existing JWT authentication dependency from complaints.py.
# We do NOT duplicate any JWT / SECRET_KEY logic here — we just import the
# function that already does it.
from routers.complaints import get_current_user


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
        complaint.status = body.status

    if body.priority is not None:
        complaint.priority = body.priority

    if body.department is not None:
        complaint.department = body.department

    # Step 4 — Save the changes.
    # SQLAlchemy tracks which attributes changed on the complaint object.
    # db.commit() writes only those changes to the SQLite file.
    # db.refresh() reloads the row so updated_at (set by onupdate=utcnow)
    # is reflected in the object we return.
    db.commit()
    db.refresh(complaint)

    # Step 5 — Return the updated complaint.
    return complaint
