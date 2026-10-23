# routers/complaints.py
# Handles complaint-related API endpoints for SmartTracker AI.
# Currently implements:
#   POST /complaints                          — submit a new complaint (JSON body; unchanged contract)
#   POST /complaints/{tracking_id}/image      — upload/replace the citizen waste image (multipart)
#   GET  /complaints/my                      — list all complaints for the logged-in user
#   GET  /complaints/{tracking_id}           — get one complaint by tracking ID
#   GET  /complaints/{tracking_id}/ai-analysis — latest waste-AI analysis for the complaint
#
# Waste-AI integration (fail-open): the HTTP request NEVER waits for the AI.
# A pending WasteAIResult row is created immediately after the image is stored;
# the AI runs in a background task via the subprocess adapter (ai_client.py).
# AI failure never fails the complaint — it only marks the result row failed.

from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

# python-jose lets us decode and verify the JWT the client sends
from jose import JWTError, jwt

# FastAPI's security utility for reading the "Authorization: Bearer <token>" header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Our own modules
from database import get_db
from models import Complaint, User, WasteAIResult
from routers.auth import ALGORITHM, SECRET_KEY
from schemas import ComplaintResponse, CreateComplaintRequest
from taxonomy import compute_priority
import image_utils
from waste_ai_service import schedule_ai_analysis

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
# WASTE-AI: complaint image upload + AI-analysis access helpers
# ---------------------------------------------------------------------------
def _latest_ai_result(db: Session, complaint: Complaint) -> Optional[WasteAIResult]:
    """Latest WasteAIResult for a complaint (created_at DESC, id DESC tiebreak), or None."""
    return (
        db.query(WasteAIResult)
        .filter(WasteAIResult.complaint_id == complaint.id)
        .order_by(WasteAIResult.created_at.desc(), WasteAIResult.id.desc())
        .first()
    )


def _latest_ai_summary(result: Optional[WasteAIResult]) -> dict:
    """Small embedded AI summary for complaint responses (not the full 25 fields)."""
    if result is None:
        return {"ai_status": None}
    return {
        "ai_status": result.ai_status,
        "waste_type": result.waste_type,
        "severity": result.severity,
        "escalate_to_authority": result.escalate_to_authority,
        "needs_human_review": result.needs_human_review,
        "follow_up_question": result.follow_up_question,
    }


def _ai_analysis_response(result: WasteAIResult) -> dict:
    """Full single-analysis response: verbatim AI data + HTTP-reachable image URL."""
    from schemas import WasteAIResultResponse

    payload = WasteAIResultResponse.model_validate(result).model_dump(mode="json")
    if payload.get("image_url"):
        # image_url is stored as an application path (/uploads/...); expose the
        # same URL here — frontend prefixes it with the API origin.
        payload["image_url"] = payload["image_url"]
    return payload


def _can_view_ai_analysis(complaint: Complaint, user: User) -> bool:
    """Owner, assigned cleaner, or admin may view the AI analysis (task 13 authz)."""
    if user.role == "admin":
        return True
    if complaint.user_id == user.id:
        return True
    task = complaint.cleanup_task
    if task is not None and task.assigned_cleaner_id == user.id:
        return True
    return False


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

    # Derive priority from structured triage inputs when provided; the fixed
    # rule lives in taxonomy.compute_priority (auditable, comparable across
    # historical rows for DWM experiments). Falls back to "medium".
    derived_priority = compute_priority(
        body.quantity_severity, body.waste_type, body.intervention_required
    )

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
        priority=derived_priority,
        source="citizen",
    )

    # Lifecycle event log (lazy import avoids a module-level import cycle:
    # routers.eventlog imports get_current_admin_user from this module).
    # NOTE: db.flush() first so SQLAlchemy assigns tracking_id/id — column
    # defaults are applied at flush time, not at object construction.
    from routers.eventlog import log_event

    db.add(new_complaint)
    db.flush()
    log_event(
        db,
        case_id=new_complaint.tracking_id,
        activity="complaint_created",
        actor_id=current_user.id,
        actor_role="citizen",
        new_value="pending",
        meta={
            "priority": derived_priority,
            "waste_type": body.waste_type,
            "quantity_severity": body.quantity_severity,
            "intervention_required": body.intervention_required,
        },
    )

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
# POST /complaints/{tracking_id}/image   (waste-AI: citizen image upload)
# ---------------------------------------------------------------------------
@router.post(
    "/{tracking_id}/image",
    response_model=ComplaintResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload or replace the citizen waste image for a complaint",
)
def upload_complaint_image(
    tracking_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Attach/replace the waste image on a complaint and (re-)run the AI.

    Least-disruptive design: the existing JSON POST /complaints contract is
    untouched; images ride on this separate multipart endpoint. A NEW pending
    WasteAIResult is created per upload (append-only history preserved).
    Fail-open: AI failure never affects the complaint row or this response.
    """
    complaint = (
        db.query(Complaint)
        .filter(Complaint.tracking_id == tracking_id)
        .first()
    )
    if complaint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found.")

    # Ownership: only the owner (or an admin) may attach an image.
    if complaint.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not allowed to modify this complaint.")

    # --- Read with a hard cap: never load arbitrarily large bodies ---
    cap = image_utils.MAX_IMAGE_BYTES + 1
    data = file.file.read(cap)
    if len(data) > image_utils.MAX_IMAGE_BYTES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=image_utils.ERR_IMAGE_TOO_LARGE)

    ok, err_code = image_utils.validate_image_upload(data, file.content_type)
    if not ok:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=err_code)

    ext = image_utils.sniff_extension(data[:16])
    image_url, mime = image_utils.store_complaint_image(data, ext)

    # --- Recurrence (AI input), computed BEFORE scheduling; safe on junk ---
    from geo import count_prior_reports_nearby_or_zero
    prior_count = count_prior_reports_nearby_or_zero(
        db, complaint.latitude, complaint.longitude, current_complaint_id=complaint.id
    )
    from geo import get_default_radius_m
    radius_m = get_default_radius_m()

    # --- Append-only pending result row (Step 1 model) ---
    result = WasteAIResult(
        complaint_id=complaint.id,
        ai_status="pending",
        image_url=image_url,
        image_mime_type=mime,
        prior_reports_count=prior_count,
        radius_m=radius_m,
    )
    db.add(result)

    # NOTE: no lifecycle event is emitted at scheduling time. The event-log
    # vocabulary is research data (pm4py) — an event will be recorded when the
    # AI analysis actually completes/fails or when a human decides (later step,
    # coordinated with M4), never as a misleading pre-completion marker.

    try:
        db.commit()
    except Exception:
        db.rollback()
        # Do not leave a stored image with no DB row behind it.
        try:
            stored = image_utils.COMPLAINT_IMAGE_DIR / image_url.rsplit("/", 1)[1]
            stored.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to attach image.")
    db.refresh(result)

    # --- Schedule the background AI run AFTER the row is safely committed ---
    schedule_ai_analysis(background_tasks, result.id)

    db.refresh(complaint)
    latest = _latest_ai_result(db, complaint)
    return {**ComplaintResponse.model_validate(complaint).model_dump(mode="json"),
            **_latest_ai_summary(latest)}


# ---------------------------------------------------------------------------
# GET /complaints/{tracking_id}/ai-analysis
# ---------------------------------------------------------------------------
@router.get(
    "/{tracking_id}/ai-analysis",
    status_code=status.HTTP_200_OK,
    summary="Latest waste-AI analysis for a complaint",
)
def get_ai_analysis(
    tracking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the latest WasteAIResult (verbatim AI fields) for one complaint.

    404 when the complaint does not exist OR no AI analysis exists yet —
    nothing is fabricated. Authorization: owner, assigned cleaner, or admin.
    """
    complaint = (
        db.query(Complaint)
        .filter(Complaint.tracking_id == tracking_id)
        .first()
    )
    if complaint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found.")

    if not _can_view_ai_analysis(complaint, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not allowed to view this complaint's AI analysis.")

    latest = _latest_ai_result(db, complaint)
    if latest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No AI analysis exists for this complaint.")

    return _ai_analysis_response(latest)


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

    # Minimal waste-AI enrichment: embed the latest-analysis summary
    # (ai_status + headline fields) without changing the response model shape.
    return [
        {
            **ComplaintResponse.model_validate(c).model_dump(mode="json"),
            **_latest_ai_summary(_latest_ai_result(db, c)),
        }
        for c in complaints
    ]


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

    return {
        **ComplaintResponse.model_validate(complaint).model_dump(mode="json"),
        **_latest_ai_summary(_latest_ai_result(db, complaint)),
    }

