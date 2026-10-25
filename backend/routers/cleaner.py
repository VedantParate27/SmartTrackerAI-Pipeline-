# routers/cleaner.py
# Handles cleaner-specific API endpoints for Waste Management AI.
#
# Phase-3 additions: task_started event (timestamps the field-execution stage
# for process mining) and event logging on proof upload. Everything else is
# the existing, tested workflow.

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.db import get_conn
from backend.models import CleanupProof, CleanupTask, User, WasteAIResult, cleaner_locations, utcnow
from backend.routers.complaints import get_current_cleaner_user
from backend.routers.eventlog import log_event
from backend.schemas import CleanerTaskResponse, CleanupProofResponse
from backend.task_timeline import first_proof_uploaded_at
from backend import image_utils
from backend.waste_ai_service import schedule_cleanup_verification

router = APIRouter(prefix="/cleaner", tags=["cleaner"])

def build_cleaner_task_response(task: CleanupTask) -> CleanerTaskResponse:
    complaint = task.complaint
    proof_responses = []
    for proof in task.proofs:
        proof_img = proof.image_url or getattr(proof, "image_path", None)
        if proof_img:
            proof_img = proof_img.replace("\\", "/")

        up_at = proof.uploaded_at
        up_at_str = (
            up_at.isoformat() if hasattr(up_at, "isoformat")
            else (str(up_at) if up_at and str(up_at) != "None" else None)
        )
        ver_at = proof.verified_at
        ver_at_str = (
            ver_at.isoformat() if hasattr(ver_at, "isoformat")
            else (str(ver_at) if ver_at and str(ver_at) != "None" else None)
        )

        proof_responses.append(
            CleanupProofResponse(
                id=proof.id,
                task_id=proof.task_id,
                image_url=proof_img,
                image_path=getattr(proof, "image_path", None),
                uploaded_by=proof.uploaded_by,
                uploaded_at=up_at_str,
                verification_status=proof.verification_status,
                verified_by=proof.verified_by,
                verified_at=ver_at_str,
                rejection_reason=proof.rejection_reason,
            )
        )

    # Resolve complaint original image
    complaint_img = None
    if complaint:
        if hasattr(complaint, "waste_ai_results") and complaint.waste_ai_results:
            for ai_res in reversed(complaint.waste_ai_results):
                if ai_res.image_url:
                    complaint_img = ai_res.image_url
                    break
        if not complaint_img and task.proofs:
            for proof in task.proofs:
                if getattr(proof, "before_image_url", None):
                    complaint_img = proof.before_image_url
                    break
        if not complaint_img and getattr(complaint, "image_path", None):
            complaint_img = complaint.image_path

    if complaint_img:
        complaint_img = complaint_img.replace("\\", "/")

    # Resolve location
    addr_text = None
    manual_addr = None
    loc_type = None
    lat = None
    lng = None
    loc_display = "Location not available"

    if complaint:
        addr_text = complaint.address_text
        manual_addr = getattr(complaint, "manual_address", None)
        loc_type = getattr(complaint, "location_type", None)
        lat = complaint.latitude
        lng = complaint.longitude

        readable_addr = addr_text or manual_addr or (complaint.location.name if complaint.location else None)
        if readable_addr:
            loc_display = readable_addr
        elif lat is not None and lng is not None:
            loc_display = f"GPS ({lat:.4f}, {lng:.4f})"
        else:
            loc_display = "Location not available"

    assigned_at_str = None
    if task.assigned_at and str(task.assigned_at) != "None":
        assigned_at_str = (
            task.assigned_at.isoformat()
            if hasattr(task.assigned_at, "isoformat")
            else str(task.assigned_at)
        )

    started_at_str = None
    if task.started_at and str(task.started_at) != "None":
        started_at_str = (
            task.started_at.isoformat()
            if hasattr(task.started_at, "isoformat")
            else str(task.started_at)
        )

    completed_at_str = None
    if task.completed_at and str(task.completed_at) != "None":
        completed_at_str = (
            task.completed_at.isoformat()
            if hasattr(task.completed_at, "isoformat")
            else str(task.completed_at)
        )

    first_proof_at = first_proof_uploaded_at(task.proofs)
    first_proof_at_str = None
    if first_proof_at and str(first_proof_at) != "None":
        first_proof_at_str = (
            first_proof_at.isoformat()
            if hasattr(first_proof_at, "isoformat")
            else str(first_proof_at)
        )

    return CleanerTaskResponse(
        id=task.id,
        complaint_id=complaint.id if complaint else None,
        cleaner_id=task.assigned_cleaner_id,
        complaint_status=complaint.status if complaint else None,
        task_id=task.task_id or f"TSK-{task.id}",
        tracking_id=complaint.tracking_id if complaint else "",
        status=task.status,
        assigned_at=assigned_at_str,
        started_at=started_at_str,
        completed_at=completed_at_str,
        first_proof_uploaded_at=first_proof_at_str,
        notes=task.notes,
        complaint_text=complaint.complaint_text if complaint else "",
        waste_type=complaint.waste_type if complaint else None,
        quantity_severity=complaint.quantity_severity if complaint else None,
        severity=getattr(complaint, "severity", None) or (complaint.quantity_severity if complaint else None),
        recommended_action=complaint.recommended_action if complaint else None,
        latitude=lat,
        longitude=lng,
        address_text=addr_text or manual_addr,
        manual_address=manual_addr or addr_text,
        location_type=loc_type or ("gps" if (lat and lng and not manual_addr) else "manual"),
        location_display=loc_display,
        image_url=complaint_img,
        image_path=complaint_img,
        proofs=proof_responses,
    )


def _active_granted_location_ids(db: Session, cleaner_id: int) -> set:
    """Location IDs the cleaner currently holds an ACTIVE grant for.

    A revoked grant (cleaner_locations.is_active=False) is deliberately
    excluded: a revoked permission can never authorize access to a
    location-specific task. The set is empty for a cleaner who never had a
    grant — and an empty set still permits location-less legacy tasks.
    """
    return {
        row.location_id
        for row in db.execute(
            cleaner_locations.select().where(
                cleaner_locations.c.cleaner_id == cleaner_id,
                cleaner_locations.c.is_active.is_(True),
            )
        ).all()
    }


def _get_task_checked(db: Session, task_id: str, current_user: User) -> CleanupTask:
    """Shared lookup + object-level authorization for cleaner task endpoints.

    Three checks, in order:
    1. the task must exist (404 otherwise);
    2. the caller must be the assigned cleaner, or an admin (403 otherwise);
    3. when the task's complaint carries a location, the caller must hold an
       ACTIVE grant for that location (403 otherwise). A revoked or inactive
       grant removes the access it once gave — it can never authorize the
       task. Complaints without a location keep working unchanged: they carry
       no location requirement at all.
    """
    task = db.query(CleanupTask).filter(CleanupTask.task_id == task_id).first()
    if not task and str(task_id).isdigit():
        task = db.query(CleanupTask).filter(CleanupTask.id == int(task_id)).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        )
    if current_user.role != "admin" and task.assigned_cleaner_id != current_user.id:
        if str(task_id).isdigit():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="cleanup task not found",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this task.",
        )
    if current_user.role != "admin":
        location_id = task.complaint.location_id
        if location_id is not None:
            granted = _active_granted_location_ids(db, current_user.id)
            if location_id not in granted:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Your location permission for this task has been revoked.",
                )
    return task


# ---------------------------------------------------------------------------
# GET /cleaner/tasks
# ---------------------------------------------------------------------------
@router.get(
    "/tasks",
    status_code=status.HTTP_200_OK,
    summary="[Cleaner] List assigned cleanup tasks",
)
def get_cleaner_tasks(
    db: Session = Depends(get_db),
    conn=Depends(get_conn),
    current_user: User = Depends(get_current_cleaner_user),
):
    """Return tasks assigned to the authenticated cleaner.

    A task whose complaint carries a location is only listed while the
    cleaner still holds an ACTIVE grant for that location — a revoked grant
    removes the task from the list. Location-less legacy tasks are always
    listed. Admins keep the unrestricted view.
    """
    try:
        col_rows = conn.execute("PRAGMA table_info(cleanup_tasks)").fetchall()
        task_cols = {col[1] for col in col_rows}
    except Exception:
        task_cols = set()

    if "task_id" not in task_cols:
        if current_user.role != "cleaner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cleaner access required.",
            )
        rows = conn.execute(
            """
            SELECT t.id,
                   t.complaint_id,
                   t.cleaner_id,
                   t.assigned_by,
                   t.status,
                   t.notes,
                   t.created_at,
                   t.updated_at,
                   t.completed_at,
                   c.tracking_id,
                   c.complaint_text,
                   c.waste_type,
                   c.severity,
                   c.image_path,
                   c.location_type,
                   c.latitude,
                   c.longitude,
                   c.manual_address,
                   c.status AS complaint_status
            FROM cleanup_tasks t
            JOIN complaints c ON c.id = t.complaint_id
            WHERE t.cleaner_id = ?
            ORDER BY t.created_at
            """,
            (current_user.id,),
        ).fetchall()
        return [dict(r) for r in rows]

    query = db.query(CleanupTask)
    if current_user.role != "admin":
        query = query.filter(CleanupTask.assigned_cleaner_id == current_user.id)
    tasks = query.order_by(CleanupTask.assigned_at.desc()).all()

    if current_user.role != "admin":
        granted = _active_granted_location_ids(db, current_user.id)
        tasks = [
            task
            for task in tasks
            if task.complaint.location_id is None
            or task.complaint.location_id in granted
        ]

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
    the first proof upload is the only field-stage signal.

    `started_at` is written ONCE, on the first genuine start of the task.
    A repeated start request never resets it, and a task that was already
    in_progress when the column was introduced receives the value on its next
    start call. It is never back-filled from other timestamps.
    """
    task = _get_task_checked(db, task_id, current_user)

    # The status the task was in BEFORE this request — a repeated start of an
    # already in_progress task must not claim it came from 'assigned'.
    previous_status = task.status

    if task.status == "assigned":
        task.status = "in_progress"
    elif task.status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task cannot be started from status '{task.status}'.",
        )

    # Field-execution start timestamp: recorded once, never reset.
    if task.started_at is None:
        task.started_at = utcnow()

    log_event(
        db,
        case_id=task.complaint.tracking_id,
        activity="task_started",
        actor_id=current_user.id,
        actor_role="cleaner",
        old_value=previous_status,
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
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_cleaner_user),
):
    """Upload the AFTER-cleanup proof photo for an assigned cleanup task.

    Step 6 hardening (waste-AI integration; authorization and task-state
    behavior unchanged):
      - image validated exactly like citizen images (MIME whitelist + magic
        bytes + content/MIME consistency + 8 MB cap) — client MIME is never
        trusted; rejected content returns HTTP 422 with an error code;
      - stored with a server-generated UUID name (uploads/proof_<uuid>.<ext>);
      - the complaint's original image is referenced as the BEFORE image
        (CleanupProof.before_image_url — URL reference, file never copied);
      - cleanup-AI verification runs as a BACKGROUND task — this request
        never waits for Gemini, and an AI failure never affects the proof,
        the task, or this response (fail-open; the admin still reviews).
    """
    task = _get_task_checked(db, task_id, current_user)

    # A completed (verified) task accepts no further proof submissions;
    # every active state (assigned / in_progress / proof_submitted / rejected)
    # may (re)submit evidence — the resubmission-after-rejection workflow.
    if task.status == "verified":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This task is already verified; no further proof can be submitted.",
        )

    # --- Read with a hard cap: never load arbitrarily large bodies ---
    cap = image_utils.MAX_IMAGE_BYTES + 1
    data = await file.read(cap)
    if len(data) > image_utils.MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=image_utils.ERR_IMAGE_TOO_LARGE,
        )

    ok, err_code = image_utils.validate_image_upload(data, file.content_type)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=err_code,
        )

    sniffed = image_utils.sniff_extension(data[:16])
    image_url, _mime = image_utils.store_proof_image(data, sniffed)

    # --- BEFORE image: the complaint's original (latest) waste image ---
    # URL reference only — the physical file is never copied or moved.
    before_url = None
    complaint = task.complaint
    if complaint is not None:
        latest = (
            db.query(WasteAIResult)
            .filter(WasteAIResult.complaint_id == complaint.id)
            .order_by(WasteAIResult.created_at.desc(), WasteAIResult.id.desc())
            .first()
        )
        if latest is not None:
            before_url = latest.image_url

    old_status = task.status
    proof = CleanupProof(
        task_id=task.task_id or f"TSK-{task.id}",
        image_url=image_url,
        before_image_url=before_url,
        uploaded_by=current_user.id,
        verification_status="pending_verification",
    )
    db.add(proof)
    task.status = "proof_submitted"

    try:
        # Flush assigns proof.id while keeping the transaction uncommitted.
        db.flush()

        log_event(
            db,
            case_id=task.complaint.tracking_id,
            activity="proof_submitted",
            actor_id=current_user.id,
            actor_role="cleaner",
            old_value=old_status,
            new_value="proof_submitted",
            meta={"proof_id": proof.id, "image_url": image_url},
        )

        db.commit()
        db.refresh(proof)
        db.refresh(task)

    except Exception:
        db.rollback()
        # Do not leave a stored image with no DB row behind.
        try:
            stored = image_utils.UPLOADS_DIR / image_url.rsplit("/", 1)[1]
            stored.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save cleanup proof.",
        )

    # --- Schedule the background cleanup-AI verification AFTER the commit ---
    schedule_cleanup_verification(background_tasks, proof.id)

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
