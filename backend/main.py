"""
SmartTracker AI - FastAPI skeleton
Run: uvicorn main:app --reload
"""
from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from db import get_conn
from ai_pipeline import classify_and_extract, generate_draft_response, entities_to_json

app = FastAPI(title="SmartTracker AI")


# ---------- request/response models ----------

class ComplaintCreate(BaseModel):
    user_id: int
    complaint_text: str


class ComplaintOut(BaseModel):
    id: int
    user_id: int
    complaint_text: str
    category: Optional[str]
    department: Optional[str]
    confidence_score: Optional[float]
    extracted_entities: Optional[str]
    status: str
    created_at: str
    updated_at: str


class ApprovalIn(BaseModel):
    admin_id: int
    final_response: str


# ---------- customer: submit a complaint ----------

@app.post("/complaints", response_model=ComplaintOut, status_code=201)
def submit_complaint(payload: ComplaintCreate, conn=Depends(get_conn)):
    user = conn.execute(
        "SELECT id FROM users WHERE id = ?", (payload.user_id,)
    ).fetchone()
    if not user:
        raise HTTPException(404, "user_id does not exist")

    cur = conn.execute(
        "INSERT INTO complaints (user_id, complaint_text) VALUES (?, ?)",
        (payload.user_id, payload.complaint_text),
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


# ---------- admin: review queue ----------

@app.get("/admin/queue")
def admin_queue(conn=Depends(get_conn)):
    rows = conn.execute(
        """SELECT c.id, c.complaint_text, c.category, c.department,
                  c.confidence_score, c.extracted_entities, r.ai_draft_response
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


# ---------- helper ----------

def _get_complaint_row(conn, complaint_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM complaints WHERE id = ?", (complaint_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "complaint not found")
    return dict(row)
