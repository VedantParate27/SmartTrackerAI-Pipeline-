# triage.py
# AI-triage ingest, escalation gate, and human-in-the-loop decision support.
#
# ARCHITECTURAL RULE: the backend never generates AI predictions. The AI team
# pushes real model output through record_ai_output(); the backend then applies
# the documented escalation rule and stores the decision context. A missing or
# failed AI call must never block complaint creation (fail-open design).

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from database import get_db
from models import AIOutput, Complaint
from routers.complaints import get_current_admin_user
from routers.eventlog import log_event
from taxonomy import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    EVENT_ACTIVITIES,
    HAZARDOUS_WASTE_TYPES,
    SEVERITIES,
    WASTE_TYPES,
    compute_priority,
)


# ---------------------------------------------------------------------------
# Escalation rule (the G2 mechanism — single implementation, unit-testable)
# ---------------------------------------------------------------------------
def decide_escalation(
    confidence: Optional[float],
    waste_type: Optional[str],
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
):
    """Return (escalated: bool, reason: Optional[str]).

    Rule (documented; evaluated in Experiment 2):
      1. missing confidence or missing prediction  -> escalate (data incomplete)
      2. confidence < threshold                    -> escalate (low confidence)
      3. waste type in {medical, hazardous}        -> escalate (safety policy)
      4. otherwise                                 -> no escalation
    """
    if confidence is None or waste_type is None:
        return True, "missing_prediction"
    if confidence < threshold:
        return True, "low_confidence"
    if waste_type in HAZARDOUS_WASTE_TYPES:
        return True, "hazardous_waste"
    return False, None


def record_ai_output(
    db: Session,
    complaint: Complaint,
    waste_type_pred: Optional[str],
    severity_pred: Optional[str],
    intervention_required_pred: Optional[bool],
    confidence: Optional[float],
    model_name: str,
    model_version: str,
    threshold_used: float,
    latency_ms: Optional[int] = None,
    actor_id: Optional[int] = None,
) -> AIOutput:
    """Persist one AI triage result, apply the escalation gate, and log events.

    Called by the AI-team ingest endpoint. Also derives the priority rule
    applied at creation time when new structured predictions arrive.
    """
    escalated, reason = decide_escalation(confidence, waste_type_pred, threshold_used)

    output = AIOutput(
        complaint_id=complaint.id,
        waste_type_pred=waste_type_pred,
        severity_pred=severity_pred,
        intervention_required_pred=intervention_required_pred,
        confidence=confidence,
        model_name=model_name,
        model_version=model_version,
        threshold_used=threshold_used,
        escalated=escalated,
        escalation_reason=reason,
        latency_ms=latency_ms,
    )
    db.add(output)

    # First structured triage result for this complaint updates the cohort and
    # priority (idempotent-ish: later outputs append rows but do not flip mode).
    if complaint.triage_mode is None:
        complaint.triage_mode = "ai_assisted"
    if complaint.priority in (None, "medium"):
        complaint.priority = compute_priority(
            severity_pred, waste_type_pred, intervention_required_pred
        )
    if escalated:
        complaint.review_required = True
        complaint.review_reason = reason

    log_event(
        db,
        case_id=complaint.tracking_id,
        activity="ai_prediction_generated",
        actor_id=actor_id,
        actor_role="ai_system",
        new_value=waste_type_pred,
        meta={
            "confidence": confidence,
            "model_name": model_name,
            "model_version": model_version,
            "threshold_used": threshold_used,
            "escalated": escalated,
            "escalation_reason": reason,
            "latency_ms": latency_ms,
        },
    )
    if escalated:
        log_event(
            db,
            case_id=complaint.tracking_id,
            activity="human_review_required",
            actor_role="system",
            new_value=reason,
            meta={"confidence": confidence, "threshold_used": threshold_used},
        )
    return output


# ---------------------------------------------------------------------------
# Ingest + read API (admin protected)
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/admin/complaints", tags=["ai-triage"])


class AIOutputRequest(BaseModel):
    """Contract for the AI team (see INTEGRATION_CONTRACTS.md)."""

    waste_type_pred: Optional[str] = Field(default=None)
    severity_pred: Optional[str] = Field(default=None)
    intervention_required_pred: Optional[bool] = Field(default=None)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    model_name: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    threshold_used: float = Field(default=DEFAULT_CONFIDENCE_THRESHOLD, ge=0.0, le=1.0)
    latency_ms: Optional[int] = Field(default=None, ge=0)

    model_config = {"protected_namespaces": ()}

    model_config = {"json_schema_extra": {
        "example": {
            "waste_type_pred": "e_waste",
            "severity_pred": "large",
            "intervention_required_pred": True,
            "confidence": 0.91,
            "model_name": "distilbert-waste-triage",
            "model_version": "1.0.0",
            "threshold_used": 0.7,
            "latency_ms": 240,
        }
    }}


class AIOutputResponse(BaseModel):
    id: int
    complaint_id: int
    waste_type_pred: Optional[str]
    severity_pred: Optional[str]
    intervention_required_pred: Optional[bool]
    confidence: Optional[float]
    model_name: str
    model_version: str
    threshold_used: float
    escalated: bool
    escalation_reason: Optional[str]
    latency_ms: Optional[int]
    predicted_at: str

    model_config = {
        "from_attributes": True,
        "protected_namespaces": (),
    }

    @field_validator("predicted_at", mode="before")
    @classmethod
    def serialise_predicted_at(cls, value):
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)


@router.post(
    "/{complaint_id}/ai-output",
    response_model=AIOutputResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[AI team] Ingest one AI triage result for a complaint",
)
def ingest_ai_output(
    complaint_id: int,
    body: AIOutputRequest,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_user),
):
    """Store an AI prediction and apply the escalation gate.

    Protected as admin because the AI service authenticates with a service
    account; this is the documented integration point — the backend itself
    never fabricates predictions."""
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if complaint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found.")

    if body.waste_type_pred is not None and body.waste_type_pred not in WASTE_TYPES:
        raise HTTPException(status_code=422, detail=f"waste_type_pred must be one of {WASTE_TYPES}")
    if body.severity_pred is not None and body.severity_pred not in SEVERITIES:
        raise HTTPException(status_code=422, detail=f"severity_pred must be one of {SEVERITIES}")

    output = record_ai_output(
        db,
        complaint,
        body.waste_type_pred,
        body.severity_pred,
        body.intervention_required_pred,
        body.confidence,
        body.model_name,
        body.model_version,
        body.threshold_used,
        body.latency_ms,
        actor_id=_admin.id,
    )
    db.commit()
    db.refresh(output)
    return output


@router.get(
    "/{complaint_id}/ai-output",
    response_model=list[AIOutputResponse],
    summary="[Admin] List AI triage outputs for a complaint",
)
def list_ai_outputs(
    complaint_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_user),
):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if complaint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found.")
    outputs = (
        db.query(AIOutput)
        .filter(AIOutput.complaint_id == complaint_id)
        .order_by(AIOutput.predicted_at.asc())
        .all()
    )
    return outputs
