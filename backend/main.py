"""
SmartTracker AI - FastAPI backend
Run: uvicorn main:app --reload
"""

from datetime import datetime
from pathlib import Path
from typing import Optional, Union
import json
import uuid

from fastapi import Depends, FastAPI, HTTPException, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

try:
    from backend.db import get_conn
    from backend.ai_pipeline import (
        classify_and_extract,
        generate_draft_response,
        entities_to_json,
        process_waste_image,
        verify_cleanup,
    )
    from backend.auth import (
        RegisterRequest,
        RegisterResponse,
        LoginRequest,
        TokenResponse,
        register_user,
        login_user,
        get_current_user,
        require_role,
        hash_password,
    )
    from backend.waste_ai_service import schedule_cleanup_verification
except ImportError:
    from db import get_conn
    from ai_pipeline import (
        classify_and_extract,
        generate_draft_response,
        entities_to_json,
        process_waste_image,
        verify_cleanup,
    )
    from auth import (
        RegisterRequest,
        RegisterResponse,
        LoginRequest,
        TokenResponse,
        register_user,
        login_user,
        get_current_user,
        require_role,
        hash_password,
    )
    from waste_ai_service import schedule_cleanup_verification

app = FastAPI(title="SmartTracker AI")


@app.get("/")
def root_status():
    return {"status": "ok", "service": "SmartTracker AI API"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://10.108.147.119:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://10.108.147.119:3001",
        "https://localhost:3000",
        "https://127.0.0.1:3000",
        "https://10.108.147.119:3000",
        "https://localhost:3001",
        "https://127.0.0.1:3001",
        "https://10.108.147.119:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- configuration ----------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPLAINTS_UPLOAD_DIR = PROJECT_ROOT / "backend" / "uploads" / "complaints"
CLEANUP_PROOFS_UPLOAD_DIR = PROJECT_ROOT / "backend" / "uploads" / "cleanup_proofs"

COMPLAINTS_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CLEANUP_PROOFS_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

UPLOAD_DIR = COMPLAINTS_UPLOAD_DIR

app.mount(
    "/uploads/complaints",
    StaticFiles(directory=COMPLAINTS_UPLOAD_DIR),
    name="uploads_complaints",
)
app.mount(
    "/uploads/cleanup_proofs",
    StaticFiles(directory=CLEANUP_PROOFS_UPLOAD_DIR),
    name="uploads_cleanup_proofs",
)

ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


# ---------- request/response models ----------

class ComplaintCreate(BaseModel):
    complaint_text: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_type: Optional[str] = None
    manual_address: Optional[str] = None

    @field_validator("location_type")
    @classmethod
    def location_type_must_be_valid(cls, value):
        if value is not None and value not in ("gps", "manual"):
            raise ValueError("location_type must be 'gps' or 'manual'")
        return value

    @model_validator(mode="after")
    def location_fields_must_be_consistent(self):
        if self.location_type == "gps":
            if self.latitude is None or self.longitude is None:
                raise ValueError(
                    "latitude and longitude are required when location_type is 'gps'"
                )

        if self.location_type == "manual":
            if not self.manual_address or not self.manual_address.strip():
                raise ValueError(
                    "manual_address is required when location_type is 'manual'"
                )

        return self


class ComplaintOut(BaseModel):
    id: int
    tracking_id: str
    user_id: int
    complaint_text: str

    category: Optional[str]
    department: Optional[str]
    confidence_score: Optional[float]
    ai_draft_response: Optional[str]
    extracted_entities: Optional[str]

    latitude: Optional[float]
    longitude: Optional[float]
    location_type: Optional[str]
    manual_address: Optional[str]

    image_path: Optional[str]
    image_mime_type: Optional[str]

    waste_type: Optional[str]
    waste_type_confidence: Optional[float]
    severity: Optional[str]
    severity_confidence: Optional[float]
    ai_reasoning: Optional[str]
    follow_up_question: Optional[str]

    recurring_flag: bool
    prior_reports_at_location: int
    escalate_to_authority: bool
    needs_human_review: bool
    review_reasons: Optional[str]
    disposal_guidance: Optional[str]

    status: str
    created_at: str
    updated_at: str


class CleanerCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class WasteReviewIn(BaseModel):
    decision: str
    cleaner_id: Optional[int] = None
    notes: Optional[str] = None

    @field_validator("decision")
    @classmethod
    def decision_must_be_valid(cls, value):
        if value not in ("approve_cleanup", "reject"):
            raise ValueError(
                "decision must be 'approve_cleanup' or 'reject'"
            )
        return value


class CleanupVerificationIn(BaseModel):
    decision: str
    notes: Optional[str] = None

    @field_validator("decision")
    @classmethod
    def decision_must_be_valid(cls, value):
        if value not in ("approve", "reject"):
            raise ValueError(
                "decision must be 'approve' or 'reject'"
            )
        return value


class ApprovalIn(BaseModel):
    final_response: str


@app.post("/admin/cleaners", status_code=201)
def create_cleaner(
    payload: CleanerCreate,
    current_user=Depends(get_current_user),
    conn=Depends(get_conn),
):
    require_role(current_user, "admin")

    normalized_email = str(payload.email).strip().lower()
    existing = conn.execute(
        "SELECT id FROM users WHERE LOWER(TRIM(email)) = ?",
        (normalized_email,),
    ).fetchone()

    if existing:
        raise HTTPException(
            status_code=400,
            detail="An account with this email address already exists.",
        )

    password_hash = hash_password(payload.password)

    cur = conn.execute(
        """
        INSERT INTO users (
            name,
            email,
            password_hash,
            role
        )
        VALUES (?, ?, ?, 'cleaner')
        """,
        (
            payload.name.strip(),
            normalized_email,
            password_hash,
        ),
    )

    conn.commit()

    return {
        "id": cur.lastrowid,
        "name": payload.name,
        "email": payload.email,
        "role": "cleaner",
    }


@app.get("/admin/cleaners")
def list_cleaners(
    current_user=Depends(get_current_user),
    conn=Depends(get_conn),
):
    require_role(current_user, "admin")

    rows = conn.execute(
        """
        SELECT id,
               name,
               email,
               role,
               department,
               created_at
        FROM users
        WHERE role = 'cleaner'
        ORDER BY name
        """
    ).fetchall()

    return [dict(r) for r in rows]


# ---------- auth: register / login ----------

@app.post("/auth/register", response_model=RegisterResponse, status_code=201)
def register(payload: RegisterRequest, conn=Depends(get_conn)):
    return register_user(conn, payload)


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, conn=Depends(get_conn)):
    return login_user(conn, payload)


# ---------- helpers ----------

def _count_prior_reports(
    conn,
    location_type: Optional[str],
    latitude: Optional[float],
    longitude: Optional[float],
    manual_address: Optional[str],
) -> int:
    """
    Count complaints previously reported at the same exact location.

    GPS locations use exact latitude/longitude matching.
    Manual locations use exact manual-address matching.
    """

    if location_type == "gps":
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM complaints
            WHERE location_type = 'gps'
              AND latitude = ?
              AND longitude = ?
            """,
            (latitude, longitude),
        ).fetchone()

        return int(row["count"]) if row else 0

    if location_type == "manual":
        if not manual_address or not manual_address.strip():
            return 0
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM complaints
            WHERE location_type = 'manual'
              AND manual_address = ?
            """,
            (manual_address.strip(),),
        ).fetchone()

        return int(row["count"]) if row else 0

    return 0


def _save_complaint_image(
    image_bytes: bytes,
    mime_type: str,
) -> str:
    """
    Save image bytes to disk and return the database path.
    """

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    extension = ALLOWED_IMAGE_MIME_TYPES[mime_type]
    filename = f"{uuid.uuid4().hex}{extension}"

    file_path = UPLOAD_DIR / filename
    file_path.write_bytes(image_bytes)

    return str(Path("backend") / "uploads" / "complaints" / filename)


# ---------- customer: submit complaint ----------

@app.post("/complaints", response_model=ComplaintOut, status_code=201)
def submit_complaint(
    complaint_text: str = Form(...),
    latitude: Optional[Union[float, str]] = Form(None),
    longitude: Optional[Union[float, str]] = Form(None),
    location_type: Optional[str] = Form(None),
    manual_address: Optional[str] = Form(None),
    image: UploadFile = File(...),
    current_user=Depends(get_current_user),
    conn=Depends(get_conn),
):
    # Normalize empty form strings to None
    norm_location_type = (
        location_type.strip()
        if location_type and location_type.strip()
        else None
    )
    norm_manual_address = (
        manual_address.strip()
        if manual_address and manual_address.strip()
        else None
    )

    norm_latitude: Optional[float] = None
    if latitude is not None and str(latitude).strip():
        try:
            norm_latitude = float(latitude)
        except (ValueError, TypeError):
            raise HTTPException(400, "latitude must be a valid number")

    norm_longitude: Optional[float] = None
    if longitude is not None and str(longitude).strip():
        try:
            norm_longitude = float(longitude)
        except (ValueError, TypeError):
            raise HTTPException(400, "longitude must be a valid number")

    # Validate the form fields using the same Pydantic rules as before.
    try:
        payload = ComplaintCreate(
            complaint_text=complaint_text,
            latitude=norm_latitude,
            longitude=norm_longitude,
            location_type=norm_location_type,
            manual_address=norm_manual_address,
        )
    except Exception as exc:
        raise HTTPException(
            400,
            f"Invalid complaint submission: {exc}",
        )

    if not payload.complaint_text.strip():
        raise HTTPException(400, "complaint_text cannot be empty")

    # Validate image MIME type.
    if image.content_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(
            400,
            "unsupported image type; allowed types are JPEG, PNG, and WEBP",
        )

    # Read the uploaded image.
    image_bytes = image.file.read()

    if not image_bytes:
        raise HTTPException(400, "uploaded image is empty")

    if len(image_bytes) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            413,
            "image is too large; maximum allowed size is 10 MB",
        )

    # Save image before running the AI pipeline.
    image_path = _save_complaint_image(
        image_bytes,
        image.content_type,
    )

    user_id = current_user["id"]
    tracking_id = f"TRK-{uuid.uuid4().hex[:8]}"

    prior_reports = _count_prior_reports(
        conn,
        payload.location_type,
        payload.latitude,
        payload.longitude,
        payload.manual_address,
    )

    # Build the location object expected by the waste pipeline.
    location = None

    if payload.location_type == "gps":
        location = {
            "lat": payload.latitude,
            "lng": payload.longitude,
        }

    elif payload.location_type == "manual":
        location = {
            "address": (
                payload.manual_address.strip()
                if payload.manual_address
                else ""
            ),
        }

    # Insert the complaint first so the report exists even if the AI
    # pipeline needs human review.
    cur = conn.execute(
        """
        INSERT INTO complaints (
            tracking_id,
            user_id,
            name,
            email,
            complaint_text,
            latitude,
            longitude,
            location_type,
            manual_address,
            image_path,
            image_mime_type,
            prior_reports_at_location,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tracking_id,
            user_id,
            current_user["name"],
            current_user["email"],
            payload.complaint_text.strip(),
            payload.latitude,
            payload.longitude,
            payload.location_type,
            (
                payload.manual_address.strip()
                if payload.manual_address
                else None
            ),
            image_path,
            image.content_type,
            prior_reports,
            "processing",
        ),
    )

    conn.commit()

    complaint_id = cur.lastrowid

    # Run the waste-image AI pipeline.
    try:
        waste_result = process_waste_image(
            image_bytes=image_bytes,
            mime_type=image.content_type,
            additional_context=payload.complaint_text.strip(),
            location=location,
            prior_reports_at_location=prior_reports,
        )

    except Exception as exc:
        # The pipeline normally catches its own model failures, but this
        # protects the API if an unexpected exception escapes.
        waste_result = {
            "waste_type": None,
            "waste_type_confidence": None,
            "severity": None,
            "severity_confidence": None,
            "reasoning": None,
            "follow_up_question": None,
            "recurring_flag": False,
            "prior_reports_at_location": prior_reports,
            "escalate_to_authority": False,
            "needs_human_review": True,
            "review_reasons": [f"pipeline_exception: {exc}"],
            "disposal_guidance": None,
        }

    # Convert pipeline review reasons into the JSON string stored in SQLite.
    review_reasons = waste_result.get("review_reasons") or []

    if isinstance(review_reasons, str):
        review_reasons_json = review_reasons
    else:
        review_reasons_json = json.dumps(review_reasons)

    needs_human_review = bool(
        waste_result.get("needs_human_review", False)
    )

    escalate_to_authority = bool(
        waste_result.get("escalate_to_authority", False)
    )

    # Waste complaints that need escalation/review enter the existing
    # admin-review state. Normal AI-processed complaints remain submitted.
    if needs_human_review or escalate_to_authority:
        final_status = "awaiting_review"
    else:
        final_status = "submitted"

    conn.execute(
        """
        UPDATE complaints
        SET image_path = ?,
            image_mime_type = ?,
            waste_type = ?,
            waste_type_confidence = ?,
            severity = ?,
            severity_confidence = ?,
            ai_reasoning = ?,
            follow_up_question = ?,
            recurring_flag = ?,
            prior_reports_at_location = ?,
            escalate_to_authority = ?,
            needs_human_review = ?,
            review_reasons = ?,
            disposal_guidance = ?,
            status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            image_path,
            image.content_type,
            waste_result.get("waste_type"),
            waste_result.get("waste_type_confidence"),
            waste_result.get("severity"),
            waste_result.get("severity_confidence"),
            waste_result.get("reasoning"),
            waste_result.get("follow_up_question"),
            int(bool(waste_result.get("recurring_flag", False))),
            int(waste_result.get(
                "prior_reports_at_location",
                prior_reports,
            ) or 0),
            int(escalate_to_authority),
            int(needs_human_review),
            review_reasons_json,
            waste_result.get("disposal_guidance"),
            final_status,
            complaint_id,
        ),
    )

    conn.commit()

    return _get_complaint_row(conn, complaint_id)


# ---------- pipeline: legacy Phase 2 text processing ----------

@app.post("/complaints/{complaint_id}/process", response_model=ComplaintOut)
def process_complaint(
    complaint_id: int,
    current_user=Depends(get_current_user),
    conn=Depends(get_conn),
):
    row = conn.execute(
        "SELECT * FROM complaints WHERE id = ?", (complaint_id,)
    ).fetchone()

    if not row:
        raise HTTPException(404, "complaint not found")

    if (
        current_user["role"] != "admin"
        and row["user_id"] != current_user["id"]
    ):
        raise HTTPException(
            403,
            "not authorized to process this complaint",
        )

    conn.execute(
        "UPDATE complaints SET status = 'processing' WHERE id = ?",
        (complaint_id,),
    )
    conn.commit()

    ai_result = classify_and_extract(row["complaint_text"])

    draft = generate_draft_response(
        row["complaint_text"],
        ai_result["extracted_entities"],
        ai_result["department"],
    )

    conn.execute(
        """
        UPDATE complaints
        SET category = ?,
            department = ?,
            confidence_score = ?,
            extracted_entities = ?,
            status = 'awaiting_review'
        WHERE id = ?
        """,
        (
            ai_result["category"],
            ai_result["department"],
            ai_result["confidence_score"],
            entities_to_json(ai_result["extracted_entities"]),
            complaint_id,
        ),
    )

    conn.execute(
        """
        INSERT INTO responses (
            complaint_id,
            ai_draft_response
        )
        VALUES (?, ?)
        """,
        (complaint_id, draft),
    )

    conn.commit()

    return _get_complaint_row(conn, complaint_id)


# ---------- customer: view status ----------

@app.get("/complaints/{complaint_id}", response_model=ComplaintOut)
def get_complaint(
    complaint_id: Union[int, str],
    current_user=Depends(get_current_user),
    conn=Depends(get_conn),
):
    if str(complaint_id).isdigit():
        row = conn.execute(
            "SELECT id, user_id FROM complaints WHERE id = ?",
            (int(complaint_id),),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id, user_id FROM complaints WHERE tracking_id = ?",
            (str(complaint_id),),
        ).fetchone()

    if not row:
        raise HTTPException(404, "complaint not found")

    if (
        current_user["role"] != "admin"
        and row["user_id"] != current_user["id"]
    ):
        raise HTTPException(
            403,
            "not authorized to view this complaint",
        )

    return _get_complaint_row(conn, row["id"])


def _get_complaint_row(conn, complaint_id: int) -> dict:
    row = conn.execute(
        """
        SELECT c.*, r.ai_draft_response
        FROM complaints c
        LEFT JOIN responses r
            ON r.complaint_id = c.id
        WHERE c.id = ?
        """,
        (complaint_id,),
    ).fetchone()

    if not row:
        raise HTTPException(404, "complaint not found")

    return dict(row)


# ---------- admin: review queue ----------

@app.get("/admin/queue")
def admin_queue(
    current_user=Depends(get_current_user),
    conn=Depends(get_conn),
):
    require_role(current_user, "admin")

    rows = conn.execute(
    """
    SELECT c.id,
           c.user_id,
           c.complaint_text,
           c.category,
           c.department,
           c.confidence_score,
           c.extracted_entities,
           c.latitude,
           c.longitude,
           c.location_type,
           c.manual_address,
           c.image_path,
           c.image_mime_type,
           c.waste_type,
           c.waste_type_confidence,
           c.severity,
           c.severity_confidence,
           c.ai_reasoning,
           c.follow_up_question,
           c.recurring_flag,
           c.prior_reports_at_location,
           c.escalate_to_authority,
           c.needs_human_review,
           c.review_reasons,
           c.disposal_guidance,
           c.status,
           c.created_at,
           c.updated_at,
           r.ai_draft_response
    FROM complaints c
    LEFT JOIN responses r
        ON r.complaint_id = c.id
    WHERE c.status = 'awaiting_review'
    ORDER BY c.created_at
    """
).fetchall()

    return [dict(r) for r in rows]



@app.get("/admin/complaints")
def admin_complaints(
    current_user=Depends(get_current_user),
    conn=Depends(get_conn),
):
    require_role(current_user, "admin")

    rows = conn.execute(
        """
        SELECT c.id,
               c.user_id,
               c.complaint_text,
               c.category,
               c.department,
               c.confidence_score,
               c.extracted_entities,
               c.latitude,
               c.longitude,
               c.location_type,
               c.manual_address,
               c.image_path,
               c.image_mime_type,
               c.waste_type,
               c.waste_type_confidence,
               c.severity,
               c.severity_confidence,
               c.ai_reasoning,
               c.follow_up_question,
               c.recurring_flag,
               c.prior_reports_at_location,
               c.escalate_to_authority,
               c.needs_human_review,
               c.review_reasons,
               c.disposal_guidance,
               c.status,
               c.created_at,
               c.updated_at,
               r.ai_draft_response
        FROM complaints c
        LEFT JOIN responses r
            ON r.complaint_id = c.id
        ORDER BY c.created_at DESC
        """
    ).fetchall()

    return [dict(r) for r in rows]


# ---------- admin: waste complaint review ----------

@app.post("/admin/complaints/{complaint_id}/review")
def review_waste_complaint(
    complaint_id: Union[int, str],
    payload: WasteReviewIn,
    current_user=Depends(get_current_user),
    conn=Depends(get_conn),
):
    require_role(current_user, "admin")

    if str(complaint_id).isdigit():
        clause = "WHERE id = ?"
        param = int(complaint_id)
    else:
        clause = "WHERE tracking_id = ?"
        param = str(complaint_id)

    complaint = conn.execute(
        f"""
        SELECT id,
               status,
               image_path,
               waste_type,
               severity,
               needs_human_review,
               escalate_to_authority
        FROM complaints
        {clause}
        """,
        (param,),
    ).fetchone()

    if not complaint:
        raise HTTPException(
            status_code=404,
            detail="complaint not found",
        )

    if complaint["status"] not in ("awaiting_review", "submitted"):
        if complaint["status"] == "assigned":
            raise HTTPException(
                status_code=409,
                detail="complaint has already been reviewed and assigned to a cleaner",
            )
        raise HTTPException(
            status_code=409,
            detail="complaint is not awaiting review",
        )

    if not complaint["image_path"] or not complaint["waste_type"]:
        raise HTTPException(
            status_code=400,
            detail="complaint is not a waste-management case",
        )

    if payload.decision == "approve_cleanup":
        if payload.cleaner_id is None:
            raise HTTPException(
                status_code=400,
                detail="cleaner_id is required when approving cleanup",
            )

        cleaner = conn.execute(
            """
            SELECT id
            FROM users
            WHERE id = ?
              AND role = 'cleaner'
            """,
            (payload.cleaner_id,),
        ).fetchone()

        if not cleaner:
            raise HTTPException(
                status_code=400,
                detail="selected user is not a valid cleaner",
            )

        existing_task = conn.execute(
            """
            SELECT id
            FROM cleanup_tasks
            WHERE complaint_id = ?
            """,
            (complaint_id,),
        ).fetchone()

        if existing_task:
            raise HTTPException(
                status_code=409,
                detail="cleanup task already exists for this complaint",
            )

        conn.execute(
            """
            INSERT INTO cleanup_tasks (
                complaint_id,
                cleaner_id,
                assigned_by,
                status,
                notes
            )
            VALUES (?, ?, ?, 'assigned', ?)
            """,
            (
                complaint_id,
                payload.cleaner_id,
                current_user["id"],
                payload.notes,
            ),
        )

        conn.execute(
            """
            UPDATE complaints
            SET status = 'assigned',
                needs_human_review = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (complaint_id,),
        )

        conn.commit()

        task = conn.execute(
            """
            SELECT id,
                   complaint_id,
                   cleaner_id,
                   assigned_by,
                   status,
                   notes,
                   created_at,
                   updated_at
            FROM cleanup_tasks
            WHERE complaint_id = ?
            """,
            (complaint_id,),
        ).fetchone()

        return {
            "complaint_id": complaint_id,
            "status": "assigned",
            "cleanup_task": dict(task),
        }

    conn.execute(
        """
        UPDATE complaints
        SET needs_human_review = 1,
            review_reasons = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            json.dumps(
                [
                    "admin_rejected_waste_review"
                    + (f": {payload.notes}" if payload.notes else "")
                ]
            ),
            complaint_id,
        ),
    )

    conn.commit()

    return {
        "complaint_id": complaint_id,
        "status": "awaiting_review",
        "cleanup_task": None,
    }




CLEANUP_PROOF_UPLOAD_DIR = (
    PROJECT_ROOT / "backend" / "uploads" / "cleanup_proofs"
)


def _save_cleanup_proof_image(image_bytes: bytes, mime_type: str) -> str:
    CLEANUP_PROOF_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    extension = ALLOWED_IMAGE_MIME_TYPES[mime_type]
    filename = f"{uuid.uuid4().hex}{extension}"
    file_path = CLEANUP_PROOF_UPLOAD_DIR / filename

    file_path.write_bytes(image_bytes)

    return str(
        Path("backend") / "uploads" / "cleanup_proofs" / filename
    )


# ---------- cleaner: task lifecycle ----------
# (GET /cleaner/tasks and POST /cleaner/tasks/{task_id}/start are handled by cleaner_router)



@app.post("/cleaner/tasks/{task_id}/proof")
async def upload_cleanup_proof(
    task_id: Union[int, str],
    image: UploadFile = File(...),
    current_user=Depends(get_current_user),
    conn=Depends(get_conn),
):
    require_role(current_user, "cleaner")

    task = conn.execute(
        """
        SELECT id,
               complaint_id,
               cleaner_id,
               status
        FROM cleanup_tasks
        WHERE (id = ? OR task_id = ?)
          AND (cleaner_id = ? OR assigned_cleaner_id = ?)
        """,
        (task_id, str(task_id), current_user["id"], current_user["id"]),
    ).fetchone()
    if task:
        task_id = task["id"]

    if not task:
        raise HTTPException(
            status_code=404,
            detail="cleanup task not found",
        )

    if task["status"] != "in_progress":
        raise HTTPException(
            status_code=409,
            detail="cleanup task must be in_progress before proof upload",
        )

    if image.content_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                "unsupported image type. "
                "Allowed types: image/jpeg, image/png, image/webp"
            ),
        )

    image_bytes = await image.read()

    if not image_bytes:
        raise HTTPException(
            status_code=400,
            detail="uploaded image is empty",
        )

    if len(image_bytes) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="uploaded image exceeds 10 MB limit",
        )

    existing_proof = conn.execute(
        """
        SELECT id
        FROM cleanup_proofs
        WHERE task_id = ?
          AND verification_status IN ('pending', 'needs_review')
        """,
        (task_id,),
    ).fetchone()

    if existing_proof:
        raise HTTPException(
            status_code=409,
            detail="cleanup proof has already been submitted",
        )

    complaint = conn.execute(
        """
        SELECT id,
               image_path,
               image_mime_type
        FROM complaints
        WHERE id = ?
        """,
        (task["complaint_id"],),
    ).fetchone()

    if not complaint:
        raise HTTPException(
            status_code=404,
            detail="associated complaint not found",
        )

    if not complaint["image_path"]:
        raise HTTPException(
            status_code=400,
            detail="complaint does not have a before image",
        )

    raw_path = Path(complaint["image_path"])
    if raw_path.is_absolute() and raw_path.exists():
        before_path = raw_path
    elif (PROJECT_ROOT / raw_path).exists():
        before_path = PROJECT_ROOT / raw_path
    elif (PROJECT_ROOT / "backend" / raw_path).exists():
        before_path = PROJECT_ROOT / "backend" / raw_path
    elif (PROJECT_ROOT / str(raw_path).lstrip("/\\")).exists():
        before_path = PROJECT_ROOT / str(raw_path).lstrip("/\\")
    else:
        before_path = PROJECT_ROOT / raw_path

    if not before_path.exists():
        raise HTTPException(
            status_code=500,
            detail="original complaint image could not be found",
        )

    proof_path = _save_cleanup_proof_image(
        image_bytes,
        image.content_type,
    )

    proof_file = PROJECT_ROOT / Path(proof_path)

    try:
        before_bytes = before_path.read_bytes()

        verification = verify_cleanup(
            before_bytes,
            image_bytes,
            before_mime=complaint["image_mime_type"] or "image/jpeg",
            after_mime=image.content_type,
        )

    except Exception as exc:
        verification = {
            "after_image_usable": True,
            "unusable_reason": None,
            "cleanup_appears_complete": True,
            "confidence": 0.5,
            "reasoning": f"Advisory fallback: AI verification unavailable ({exc}). Flagged for admin manual review.",
            "admin_review_recommended": True,
        }

    verification_reason = verification["reasoning"]

    if verification.get("unusable_reason"):
        verification_reason += (
            f" Unusable reason: "
            f"{verification['unusable_reason']}"
        )

    if verification.get("admin_review_recommended"):
        verification_reason += " Admin review recommended by AI."

    conn.execute(
        """
        INSERT INTO cleanup_proofs (
            task_id,
            image_path,
            image_mime_type,
            verification_status,
            verification_confidence,
            verification_reason
        )
        VALUES (?, ?, ?, 'pending', ?, ?)
        """,
        (
            task_id,
            proof_path,
            image.content_type,
            float(verification["confidence"]),
            verification_reason,
        ),
    )

    conn.execute(
        """
        UPDATE cleanup_tasks
        SET status = 'verification',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (task_id,),
    )

    conn.execute(
        """
        UPDATE complaints
        SET status = 'verification',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (task["complaint_id"],),
    )

    conn.commit()

    proof = conn.execute(
        """
        SELECT id,
               task_id,
               image_path,
               image_mime_type,
               verification_status,
               verification_confidence,
               verification_reason,
               uploaded_at,
               reviewed_at,
               reviewed_by
        FROM cleanup_proofs
        WHERE task_id = ?
        ORDER BY uploaded_at DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()

    return {
        "task_id": task_id,
        "complaint_id": task["complaint_id"],
        "task_status": "verification",
        "complaint_status": "verification",
        "ai_verification": {
            "after_image_usable": verification["after_image_usable"],
            "cleanup_appears_complete": verification[
                "cleanup_appears_complete"
            ],
            "confidence": verification["confidence"],
            "admin_review_recommended": verification[
                "admin_review_recommended"
            ],
        },
        "proof": dict(proof),
    }



# ---------- admin: cleanup task queue ----------

@app.get("/admin/cleanup-tasks")
def list_cleanup_tasks(
    current_user=Depends(get_current_user),
    conn=Depends(get_conn),
):
    require_role(current_user, "admin")

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
               c.status          AS complaint_status,
               u.name            AS cleaner_name,
               u.email           AS cleaner_email,
               p.id              AS proof_id,
               p.image_path      AS proof_image_path,
               p.image_mime_type AS proof_image_mime_type,
               p.verification_status,
               p.verification_confidence,
               p.verification_reason,
               p.uploaded_at,
               p.reviewed_at,
               p.reviewed_by
        FROM cleanup_tasks t
        JOIN complaints c ON c.id = t.complaint_id
        JOIN users u      ON u.id = t.cleaner_id
        LEFT JOIN cleanup_proofs p
            ON p.id = (
                SELECT id
                FROM cleanup_proofs
                WHERE task_id = t.id
                ORDER BY uploaded_at DESC
                LIMIT 1
            )
        ORDER BY t.created_at
        """
    ).fetchall()

    return [dict(r) for r in rows]


# ---------- admin: verify cleanup proof ----------

@app.post("/admin/cleanup-tasks/{task_id}/verify")
def verify_cleanup_task(
    task_id: int,
    payload: CleanupVerificationIn,
    current_user=Depends(get_current_user),
    conn=Depends(get_conn),
):
    require_role(current_user, "admin")

    task = conn.execute(
        """
        SELECT id,
               complaint_id,
               cleaner_id,
               assigned_by,
               status
        FROM cleanup_tasks
        WHERE id = ?
        """,
        (task_id,),
    ).fetchone()

    if not task:
        raise HTTPException(
            status_code=404,
            detail="cleanup task not found",
        )

    if task["status"] != "verification":
        raise HTTPException(
            status_code=409,
            detail="cleanup task is not awaiting verification",
        )

    proof = conn.execute(
        """
        SELECT id,
               task_id,
               image_path,
               image_mime_type,
               verification_status,
               verification_confidence,
               verification_reason,
               uploaded_at,
               reviewed_at,
               reviewed_by
        FROM cleanup_proofs
        WHERE task_id = ?
        ORDER BY uploaded_at DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()

    if not proof:
        raise HTTPException(
            status_code=404,
            detail="cleanup proof not found",
        )

    if proof["verification_status"] not in ("pending", "needs_review"):
        raise HTTPException(
            status_code=409,
            detail="cleanup proof has already been reviewed",
        )

    now_status = payload.decision

    if now_status == "approve":
        conn.execute(
            """
            UPDATE cleanup_proofs
            SET verification_status = 'approved',
                verification_reason = CASE
                    WHEN ? IS NULL OR ? = ''
                    THEN verification_reason
                    ELSE verification_reason || ' Admin approval: ' || ?
                END,
                reviewed_at = CURRENT_TIMESTAMP,
                reviewed_by = ?
            WHERE id = ?
            """,
            (
                payload.notes,
                payload.notes,
                payload.notes,
                current_user["id"],
                proof["id"],
            ),
        )

        conn.execute(
            """
            UPDATE cleanup_tasks
            SET status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (task_id,),
        )

        conn.execute(
            """
            UPDATE complaints
            SET status = 'resolved',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (task["complaint_id"],),
        )

    else:
        conn.execute(
            """
            UPDATE cleanup_proofs
            SET verification_status = 'rejected',
                verification_reason = CASE
                    WHEN ? IS NULL OR ? = ''
                    THEN verification_reason
                    ELSE verification_reason || ' Admin rejection: ' || ?
                END,
                reviewed_at = CURRENT_TIMESTAMP,
                reviewed_by = ?
            WHERE id = ?
            """,
            (
                payload.notes,
                payload.notes,
                payload.notes,
                current_user["id"],
                proof["id"],
            ),
        )

        conn.execute(
            """
            UPDATE cleanup_tasks
            SET status = 'assigned',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (task_id,),
        )

        conn.execute(
            """
            UPDATE complaints
            SET status = 'in_progress',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (task["complaint_id"],),
        )

    conn.commit()

    updated_task = conn.execute(
        """
        SELECT id,
               complaint_id,
               cleaner_id,
               assigned_by,
               status,
               notes,
               created_at,
               updated_at,
               completed_at
        FROM cleanup_tasks
        WHERE id = ?
        """,
        (task_id,),
    ).fetchone()

    updated_proof = conn.execute(
        """
        SELECT id,
               task_id,
               image_path,
               image_mime_type,
               verification_status,
               verification_confidence,
               verification_reason,
               uploaded_at,
               reviewed_at,
               reviewed_by
        FROM cleanup_proofs
        WHERE id = ?
        """,
        (proof["id"],),
    ).fetchone()

    complaint = conn.execute(
        """
        SELECT id,
               status
        FROM complaints
        WHERE id = ?
        """,
        (task["complaint_id"],),
    ).fetchone()

    return {
        "task": dict(updated_task),
        "proof": dict(updated_proof),
        "complaint": dict(complaint),
        "admin_decision": payload.decision,
    }


# ---------- admin: approve / edit response ----------

@app.post("/admin/responses/{complaint_id}/approve")
def approve_response(
    complaint_id: int,
    payload: ApprovalIn,
    current_user=Depends(get_current_user),
    conn=Depends(get_conn),
):
    require_role(current_user, "admin")

    response = conn.execute(
        "SELECT id FROM responses WHERE complaint_id = ?",
        (complaint_id,),
    ).fetchone()

    if not response:
        raise HTTPException(
            404,
            "no draft response for this complaint",
        )

    conn.execute(
        """
        UPDATE responses
        SET final_response = ?,
            approved_by = ?,
            approved_at = ?
        WHERE complaint_id = ?
        """,
        (
            payload.final_response,
            current_user["id"],
            datetime.utcnow().isoformat(),
            complaint_id,
        ),
    )

    conn.execute(
        "UPDATE complaints SET status = 'resolved' WHERE id = ?",
        (complaint_id,),
    )

    conn.commit()

    return {
        "complaint_id": complaint_id,
        "status": "resolved",
    }



# ---------- admin: location & time analytics ----------

@app.get("/admin/analytics/locations")
def admin_analytics_locations(
    current_user=Depends(get_current_user),
):
    require_role(current_user, "admin")
    report_path = PROJECT_ROOT / "analytics" / "comparison_sample.json"
    if report_path.exists():
        return json.loads(report_path.read_text(encoding="utf-8"))
    try:
        from analytics.comparison import compare_locations
        from analytics.records import generate_records
        return compare_locations(generate_records(300))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate analytics: {exc}")


@app.get("/admin/analytics/time-estimates")
def admin_analytics_time_estimates(
    current_user=Depends(get_current_user),
):
    require_role(current_user, "admin")
    report_path = PROJECT_ROOT / "analytics" / "analytics_report.json"
    if report_path.exists():
        return json.loads(report_path.read_text(encoding="utf-8"))
    return {
        "generated_at": datetime.now().isoformat(),
        "data_type": "synthetic demonstration data",
        "total_records": 0,
        "cleanup_time_estimates": [],
    }


# ---------------------------------------------------------------------------
# Modular router inclusions
# ---------------------------------------------------------------------------
try:
    from backend.routers import admin as admin_router
    from backend.routers import cleaner as cleaner_router
    from backend.routers import app_state as app_state_router
    from backend.routers import complaints as complaints_router
    from backend.routers import eventlog as eventlog_router
    from backend.routers import mining as mining_router
except ImportError:
    from routers import admin as admin_router
    from routers import cleaner as cleaner_router
    from routers import app_state as app_state_router
    from routers import complaints as complaints_router
    from routers import eventlog as eventlog_router
    from routers import mining as mining_router

app.include_router(admin_router.router)
app.include_router(cleaner_router.router)
app.include_router(app_state_router.router)
app.include_router(complaints_router.router)
app.include_router(eventlog_router.router)
app.include_router(mining_router.router)






