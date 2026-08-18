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

    # We define a reusable 401 error here so we return the same response
    # in every failure case — we don't want to hint at WHY authentication failed.
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Step 1 — Extract the raw token string from the credentials object.
    # HTTPAuthorizationCredentials has two attributes:
    #   .scheme      → the scheme word ("Bearer") — we don't need to check this
    #   .credentials → the actual token string after "Bearer "
    token = credentials.credentials

    # Step 2 — Decode the JWT
    # jwt.decode() checks the signature AND the expiry time automatically.
    # If either check fails it raises a JWTError, which we catch below.
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: str = payload.get("sub")  # "sub" holds the user ID as a string
        if user_id_str is None:
            raise credentials_error
        user_id = int(user_id_str)  # convert "1" → 1
    except (JWTError, ValueError):
        raise credentials_error

    # Step 2 — Fetch the user from the database
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        # Token was valid but the account was deleted — still refuse access
        raise credentials_error

    return user


# ---------------------------------------------------------------------------
# ROUTER
# ---------------------------------------------------------------------------
# prefix="/complaints" → every route below starts with /complaints
# tags=["complaints"]  → shown as a group on the /docs page
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

    The client only needs to supply:
    - **complaint_text**: The full complaint message (required)
    - **phone**: An optional contact phone number

    Everything else (name, email, tracking ID, status, priority) is
    set automatically by the server.

    Requires a valid **JWT Bearer token** in the Authorization header.
    """

    # Step 1 — Build the Complaint row
    # We pull name and email from the authenticated user's profile so
    # the client cannot impersonate someone else.
    new_complaint = Complaint(
        user_id=current_user.id,                   # link to the users table
        name=current_user.name,                    # taken from the JWT user
        email=current_user.email,                  # taken from the JWT user
        phone=body.phone,                          # optional, may be None
        complaint_text=body.complaint_text,        # the main complaint body
        # tracking_id is generated by the model's default lambda (TRK-xxxxxxxx)
        status="pending",                          # always starts as pending
        priority="medium",                         # default priority
        # department is None until an admin classifies the complaint
    )

    # Step 2 — Save to the database
    db.add(new_complaint)       # stage the new row
    db.commit()                 # write it to the SQLite file
    db.refresh(new_complaint)   # reload to get DB-assigned values (id, tracking_id, created_at)

    # Step 3 — Return the response
    # FastAPI serialises new_complaint through ComplaintResponse automatically.
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

    - Returns an **empty list** (not an error) if the user has no complaints.
    - The client cannot request another user's complaints — the user ID is
      always taken from the JWT, never from the request.

    Requires a valid **JWT Bearer token** in the Authorization header.
    """

    # Query the complaints table for rows where user_id matches the
    # authenticated user's ID, then sort newest-first.
    #
    # .all() executes the query and returns a plain Python list.
    # If there are no matching rows, .all() returns [] — HTTP 200 with []
    # is the correct response when a valid user simply has no complaints yet.
    complaints = (
        db.query(Complaint)
        .filter(Complaint.user_id == current_user.id)   # only THIS user's complaints
        .order_by(Complaint.created_at.desc())           # newest complaint first
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

    Only the user who submitted the complaint can view it.
    """

    # Step 1 — Find the complaint
    complaint = (
        db.query(Complaint)
        .filter(Complaint.tracking_id == tracking_id)
        .first()
    )

    # Step 2 — Complaint doesn't exist
    if complaint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Complaint not found.",
        )

    # Step 3 — Make sure the logged-in user owns it
    if complaint.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not allowed to view this complaint.",
        )

    # Step 4 — Return complaint
    return complaint
