"""
SmartTracker AI - FastAPI backend
Run: uvicorn main:app --reload
"""

from datetime import datetime
from pathlib import Path
from typing import Optional
import json
import uuid

from fastapi import Depends, FastAPI, HTTPException, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator, model_validator

from db import get_conn
from ai_pipeline import (
    classify_and_extract,
    generate_draft_response,
    entities_to_json,
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
)
from waste_pipeline import process_waste_image


app = FastAPI(title="SmartTracker AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- configuration ----------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = PROJECT_ROOT / "backend" / "uploads" / "complaints"

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


class ApprovalIn(BaseModel):
    final_response: str


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
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    location_type: Optional[str] = Form(None),
    manual_address: Optional[str] = Form(None),
    image: UploadFile = File(...),
    current_user=Depends(get_current_user),
    conn=Depends(get_conn),
):
    # Validate the form fields using the same Pydantic rules as before.
    payload = ComplaintCreate(
        complaint_text=complaint_text,
        latitude=latitude,
        longitude=longitude,
        location_type=location_type,
        manual_address=manual_address,
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
            "address": payload.manual_address.strip(),
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
            )),
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
    complaint_id: int,
    current_user=Depends(get_current_user),
    conn=Depends(get_conn),
):
    row = conn.execute(
        "SELECT user_id FROM complaints WHERE id = ?",
        (complaint_id,),
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

    return _get_complaint_row(conn, complaint_id)


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
