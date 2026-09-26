# routers/complaints.py
# Handles complaint-related API endpoints for SmartTracker AI.
# Currently implements:
#   POST /complaints      — submit a new complaint (requires JWT login)
#   GET  /complaints/my  — list all complaints for the logged-in user

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

# python-jose lets us decode and verify the JWT the client sends
from jose import JWTError, jwt

# FastAPI's security utility for reading the "Authorization: Bearer <token>" header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Our own modules
from database import get_db
from models import Complaint, User
from routers.auth import ALGORITHM, SECRET_KEY
from schemas import ComplaintResponse, CreateComplaintRequest

# ---------------------------------------------------------------------------
# OAuth2 PASSWORD BEARER
# ---------------------------------------------------------------------------
# HTTPBearer tells FastAPI to look for an "Authorization: Bearer <token>" header.
# Unlike OAuth2PasswordBearer, it does NOT render a username/password form in
# Swagger /docs — it shows a simple text box for the raw token instead.
# auto_error=True (default) means FastAPI returns 403 automatically if the
# header is missing entirely, before our code even runs.
bearer_scheme = HTTPBearer()


# ---------------------------------------------------------------------------
# DEPENDENCY — get_current_user()
# ---------------------------------------------------------------------------
# This function is injected into protected route functions via Depends().
# It:
#   1. Reads the raw JWT string from the Authorization header
#   2. Decodes and verifies the token using our SECRET_KEY
#   3. Looks up the matching User row in the database
#   4. Returns the User object so the route can access id, name, email, etc.
#
# If anything goes wrong (missing token, bad signature, expired, unknown user)
# it raises a 401 Unauthorized error — the request is rejected before the
# route body even runs.
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),  # reads Authorization header
    db: Session = Depends(get_db),                                        # opens a DB session
) -> User:
    """
    Decode the JWT and return the authenticated User from the database.
    Raises HTTP 401 if the token is missing, invalid, expired, or the user
    no longer exists.
    """

    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: str = payload.get("sub")  # "sub" holds the user ID as a string
        if user_id_str is None:
            raise credentials_error
        user_id = int(user_id_str)
    except (JWTError, ValueError):
        raise credentials_error

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_error

    return user


def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency that ensures the authenticated user has the 'admin' role."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user


def get_current_cleaner_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency that ensures the authenticated user has the 'cleaner' or 'admin' role."""
    if current_user.role not in ("cleaner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cleaner or Admin access required.",
        )
    return current_user


# ---------------------------------------------------------------------------
# ROUTER
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/complaints", tags=["complaints"])


# ---------------------------------------------------------------------------
# POST /complaints
# ---------------------------------------------------------------------------
@router.post(
    "/",
    response_model=ComplaintResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new complaint",
)
def create_complaint(
    body: CreateComplaintRequest,             # validated request body
    db: Session = Depends(get_db),           # database session
    current_user: User = Depends(get_current_user),  # the logged-in user
):
    """
    Submit a new complaint on behalf of the authenticated user.
    Supports optional waste management classification and location fields.
    """

    new_complaint = Complaint(
        user_id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        phone=body.phone,
        complaint_text=body.complaint_text,
        waste_type=body.waste_type,
        waste_context=body.waste_context,
        quantity_severity=body.quantity_severity,
        recommended_action=body.recommended_action,
        intervention_required=body.intervention_required,
        latitude=body.latitude,
        longitude=body.longitude,
        address_text=body.address_text,
        status="pending",
        priority="medium",
    )

    db.add(new_complaint)
    try:
        db.commit()
        db.refresh(new_complaint)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create complaint.",
        )

    return new_complaint


# ---------------------------------------------------------------------------
# GET /complaints/my
# ---------------------------------------------------------------------------
@router.get(
    "/my",
    response_model=List[ComplaintResponse],
    status_code=200,
    summary="List all complaints submitted by the logged-in user",
)
def get_my_complaints(
    db: Session = Depends(get_db),                       # database session
    current_user: User = Depends(get_current_user),      # the logged-in user
):
    """
    Return every complaint that belongs to the authenticated user,
    ordered newest first.
    """

    complaints = (
        db.query(Complaint)
        .filter(Complaint.user_id == current_user.id)
        .order_by(Complaint.created_at.desc())
        .all()
    )

    return complaints


# ---------------------------------------------------------------------------
# GET /complaints/{tracking_id}
# ---------------------------------------------------------------------------
@router.get(
    "/{tracking_id}",
    response_model=ComplaintResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a complaint by tracking ID",
)
def get_complaint(
    tracking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get one complaint using its public tracking ID.
    Accessible by owner, cleaner assigned to the task, or admin.
    """

    complaint = (
        db.query(Complaint)
        .filter(Complaint.tracking_id == tracking_id)
        .first()
    )

    if complaint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Complaint not found.",
        )

    is_owner = complaint.user_id == current_user.id
    is_admin = current_user.role == "admin"
    is_assigned_cleaner = (
        complaint.cleanup_task is not None
        and complaint.cleanup_task.assigned_cleaner_id == current_user.id
    )

    if not (is_owner or is_admin or is_assigned_cleaner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not allowed to view this complaint.",
        )

    return complaint

