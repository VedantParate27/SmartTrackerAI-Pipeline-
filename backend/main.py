"""
SmartTracker AI - FastAPI skeleton
Run: uvicorn main:app --reload
"""
from datetime import datetime
from typing import Optional
import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator, model_validator
from db import get_conn
from ai_pipeline import classify_and_extract, generate_draft_response, entities_to_json
from auth import (
    RegisterRequest,
    RegisterResponse,
    LoginRequest,
    TokenResponse,
    register_user,
    login_user,
)

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

# ---------- request/response models ----------

class ComplaintCreate(BaseModel):
    user_id: int
    complaint_text: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_type: Optional[str] = None  # 'gps' | 'manual'
    manual_address: Optional[str] = None

    @field_validator("location_type")
    @classmethod
    def location_type_must_be_valid(cls, value):
        if value is not None and value not in ("gps", "manual"):
            raise ValueError("location_type must be 'gps' or 'manual'")
        return value

    @model_validator(mode="after")
    def location_fields_must_be_consistent(self):
        if self.location_type == "gps" and (self.latitude is None or self.longitude is None):
            raise ValueError("latitude and longitude are required when location_type is 'gps'")
        if self.location_type == "manual" and not (self.manual_address and self.manual_address.strip()):
            raise ValueError("manual_address is required when location_type is 'manual'")
        return self


class ComplaintOut(BaseModel):
    id: int
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
    status: str
    created_at: str
    updated_at: str


class ApprovalIn(BaseModel):
    admin_id: int
    final_response: str


# ---------- auth: register / login ----------
# Issues JWTs but does not yet gate any existing endpoint — that is a
# separate, later increment so this stays a small, independently testable
# step.

@app.post("/auth/register", response_model=RegisterResponse, status_code=201)
def register(payload: RegisterRequest, conn=Depends(get_conn)):
    return register_user(conn, payload)


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, conn=Depends(get_conn)):
    return login_user(conn, payload)


# ---------- customer: submit a complaint ----------

@app.post("/complaints", response_model=ComplaintOut, status_code=201)
def submit_complaint(payload: ComplaintCreate, conn=Depends(get_conn)):
    user = conn.execute(
        "SELECT id, name, email FROM users WHERE id = ?",
        (payload.user_id,),
    ).fetchone()

    if not user:
        raise HTTPException(404, "user_id does not exist")

    tracking_id = f"TRK-{uuid.uuid4().hex[:8]}"

    cur = conn.execute(
        """INSERT INTO complaints (
               tracking_id,
               user_id,
               name,
               email,
               complaint_text,
               latitude,
               longitude,
               location_type,
               manual_address
           )
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tracking_id,
            payload.user_id,
            user["name"],
            user["email"],
            payload.complaint_text,
            payload.latitude,
            payload.longitude,
            payload.location_type,
            payload.manual_address,
        ),
    )

    conn.commit()

    complaint_id = cur.lastrowid
    return _get_complaint_row(conn, complaint_id)


# ---------- pipeline: classify + extract + generate draft ----------
# One endpoint, not two - in practice classification, extraction, and
# draft generation happen as a single backend job right after submission.
# Split it later only if you need to show progress between steps in the UI.

@app.post("/complaints/{complaint_id}/process", response_model=ComplaintOut)
def process_complaint(complaint_id: int, conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT * FROM complaints WHERE id = ?", (complaint_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "complaint not found")

    conn.execute(
        "UPDATE complaints SET status = 'processing' WHERE id = ?", (complaint_id,)
    )
    conn.commit()

    ai_result = classify_and_extract(row["complaint_text"])
    draft = generate_draft_response(
        row["complaint_text"], ai_result["extracted_entities"], ai_result["department"]
    )

    conn.execute(
        """UPDATE complaints
           SET category = ?, department = ?, confidence_score = ?,
               extracted_entities = ?, status = 'awaiting_review'
           WHERE id = ?""",
        (
            ai_result["category"],
            ai_result["department"],
            ai_result["confidence_score"],
            entities_to_json(ai_result["extracted_entities"]),
            complaint_id,
        ),
    )
    conn.execute(
        "INSERT INTO responses (complaint_id, ai_draft_response) VALUES (?, ?)",
        (complaint_id, draft),
    )
    conn.commit()
    return _get_complaint_row(conn, complaint_id)


# ---------- customer: view status ----------

@app.get("/complaints/{complaint_id}", response_model=ComplaintOut)
def get_complaint(complaint_id: int, conn=Depends(get_conn)):
    return _get_complaint_row(conn, complaint_id)


def _get_complaint_row(conn, complaint_id: int) -> dict:
    row = conn.execute(
        """SELECT c.*, r.ai_draft_response
           FROM complaints c
           LEFT JOIN responses r ON r.complaint_id = c.id
           WHERE c.id = ?""",
        (complaint_id,),
    ).fetchone()

    if not row:
        raise HTTPException(404, "complaint not found")

    return dict(row)


# ---------- admin: review queue ----------

@app.get("/admin/queue")
def admin_queue(conn=Depends(get_conn)):
    rows = conn.execute(
    """SELECT c.id, c.user_id, c.complaint_text, c.category, c.department,
              c.confidence_score, c.extracted_entities,
              c.latitude, c.longitude, c.location_type, c.manual_address,
              c.status, c.created_at, c.updated_at, r.ai_draft_response
       FROM complaints c
       JOIN responses r ON r.complaint_id = c.id
       WHERE c.status = 'awaiting_review'
       ORDER BY c.created_at"""
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- admin: approve / edit response ----------

@app.post("/admin/responses/{complaint_id}/approve")
def approve_response(complaint_id: int, payload: ApprovalIn, conn=Depends(get_conn)):
    admin = conn.execute(
        "SELECT id FROM users WHERE id = ? AND role = 'admin'", (payload.admin_id,)
    ).fetchone()
    if not admin:
        raise HTTPException(403, "not an admin")

    response = conn.execute(
        "SELECT id FROM responses WHERE complaint_id = ?", (complaint_id,)
    ).fetchone()
    if not response:
        raise HTTPException(404, "no draft response for this complaint")

    conn.execute(
        """UPDATE responses
           SET final_response = ?, approved_by = ?, approved_at = ?
           WHERE complaint_id = ?""",
        (payload.final_response, payload.admin_id, datetime.utcnow().isoformat(), complaint_id),
    )
    conn.execute(
        "UPDATE complaints SET status = 'resolved' WHERE id = ?", (complaint_id,)
    )
    conn.commit()
    return {"complaint_id": complaint_id, "status": "resolved"}
