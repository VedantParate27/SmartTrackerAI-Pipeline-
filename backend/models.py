# models.py
# This file defines the database tables for SmartTracker AI as Python classes.
# Each class = one table in the database.
# SQLAlchemy reads these classes and creates the actual tables when the app starts.
#
# Phase-3 (research layer) additions:
#   * AIOutput      — advisory AI triage results pushed by the AI team (never fabricated here)
#   * AICorrection  — admin corrections of AI predictions (human-in-the-loop evidence)
#   * EventLog      — actor-attributed lifecycle event log (process-mining input)
#   * Complaint     — new research/DWM columns (triage_mode, review flags, resolved_at, source)
#
# Waste-AI integration (contract: branch waste-image-classification):
#   * WasteAIResult — ONE advisory waste-image AI analysis attempt per row (append-only)
#   * CleanupProof  — extended with ai_* advisory verification fields (verify_cleanup())

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,         # used to define a table column
    Integer,        # whole numbers  (1, 2, 3 …)
    Float,          # floating point numbers (lat/long)
    String,         # text / varchar
    Text,           # longer text (complaint body)
    DateTime,       # date + time values
    ForeignKey,     # links one table to another
    Boolean,        # True / False
)
from sqlalchemy.orm import relationship, backref  # defines the Python-level link between models

from database import Base  # import the shared Base class from database.py


# ---------------------------------------------------------------------------
# HELPER
# ---------------------------------------------------------------------------
def utcnow():
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# MODEL 1 — User
# ---------------------------------------------------------------------------
# Maps to a table called "users" in smarttracker.db.
# Stores everyone who can log in or submit complaints.
class User(Base):
    __tablename__ = "users"   # exact name of the table in the database

    # --- Primary Key ---
    id = Column(Integer, primary_key=True, index=True)

    # --- Personal Info ---
    name = Column(String(100), nullable=False)          # full name, required
    email = Column(String(150), unique=True, nullable=False, index=True)  # must be unique
    password_hash = Column(String(255), nullable=False)  # we never store plain passwords!

    # --- Role & Department ---
    role = Column(String(50), nullable=False, default="citizen") # citizen, cleaner, staff, admin
    department = Column(String(100), nullable=True)  # optional; staff belong to a dept

    # --- Timestamp ---
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    # --- Relationship ---
    complaints = relationship("Complaint", back_populates="owner")

    def __repr__(self):
        return f"<User id={self.id} email={self.email!r} role={self.role!r}>"


# ---------------------------------------------------------------------------
# MODEL 2 — Complaint
# ---------------------------------------------------------------------------
class Complaint(Base):
    __tablename__ = "complaints"

    # --- Primary Key ---
    id = Column(Integer, primary_key=True, index=True)

    # --- Public Tracking ID ---
    tracking_id = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: f"TRK-{uuid.uuid4().hex[:8]}"
    )

    # --- Foreign Key (link to users table) ---
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # --- Submitter Details ---
    name = Column(String(100), nullable=False)           # name of the complainant
    email = Column(String(150), nullable=False)          # contact email
    phone = Column(String(20), nullable=True)            # optional phone number

    # --- Complaint Content ---
    complaint_text = Column(Text, nullable=False)        # the full complaint message
    language = Column(String(10), nullable=False, default="en")  # ISO 639-1 code

    # --- Classification ---
    priority = Column(String(20), nullable=False, default="medium")
    status = Column(String(30), nullable=False, default="pending")
    department = Column(String(100), nullable=True)

    # --- Waste Management Fields ---
    waste_type = Column(String(50), nullable=True)            # E-waste, Medical waste, Dry waste, Wet waste
    waste_context = Column(Text, nullable=True)               # e.g. indoor vs outdoor, public accumulation
    quantity_severity = Column(String(50), nullable=True)     # small, medium, large
    recommended_action = Column(Text, nullable=True)          # self disposal guidance or cleaner instructions
    intervention_required = Column(Boolean, nullable=True, default=False)

    # --- Location Fields (Member 4 Integration) ---
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    address_text = Column(String(255), nullable=True)

    # --- Research / DWM fields (Phase 3) -----------------------------------
    # triage_mode: NULL = not yet triaged; "manual" = human-only cohort;
    # "ai_assisted" = AI suggestion available to the admin (research cohorts).
    triage_mode = Column(String(20), nullable=True)
    # Mandatory human-review flag set by the escalation gate (triage.py).
    review_required = Column(Boolean, nullable=True, default=False)
    review_reason = Column(String(100), nullable=True)   # low_confidence | hazardous_waste | missing_prediction
    # Where this row came from: "citizen" (real submission) or "seed" (synthetic).
    source = Column(String(20), nullable=False, default="citizen")
    # Explicit resolution timestamp for resolution-time metrics (NULL until resolved).
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # --- Timestamps ---
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    # --- Relationships ---
    owner = relationship("User", back_populates="complaints")
    cleanup_task = relationship("CleanupTask", back_populates="complaint", uselist=False)
    # Waste-AI analysis history: append-only, one row per analysis attempt
    # (re-uploads / re-runs add rows; nothing is ever overwritten).
    waste_ai_results = relationship(
        "WasteAIResult",
        back_populates="complaint",
        order_by="WasteAIResult.created_at",
        cascade="all, delete-orphan",
    )
    ai_outputs = relationship(
        "AIOutput",
        back_populates="complaint",
        order_by="AIOutput.predicted_at",
        cascade="all, delete-orphan",
    )
    corrections = relationship(
        "AICorrection",
        back_populates="complaint",
        order_by="AICorrection.created_at",
        cascade="all, delete-orphan",
    )

    @property
    def resolution(self):
        """Expose the latest approved response formatted for frontend resolution property."""
        if hasattr(self, "responses") and self.responses:
            latest = self.responses[-1]
            approver_name = latest.approver.name if latest.approver else "Admin"
            approved_at_str = (
                latest.approved_at.isoformat()
                if hasattr(latest.approved_at, "isoformat")
                else str(latest.approved_at)
            )
            return {
                "text": latest.response_text,
                "approver": approver_name,
                "sentAt": approved_at_str,
            }
        return None

    def __repr__(self):
        return (
            f"<Complaint id={self.id} tracking_id={self.tracking_id!r} "
            f"status={self.status!r} priority={self.priority!r}>"
        )


# ---------------------------------------------------------------------------
# MODEL 3 — AppStateSnapshot
# ---------------------------------------------------------------------------
class AppStateSnapshot(Base):
    __tablename__ = "app_state_snapshots"
    id = Column(Integer, primary_key=True, default=1)
    payload = Column(Text, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    def __repr__(self):
        return f"<AppStateSnapshot revision={self.revision}>"


# ---------------------------------------------------------------------------
# MODEL 4 — Response
# ---------------------------------------------------------------------------
class Response(Base):
    __tablename__ = "responses"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id"), nullable=False, index=True)
    response_text = Column(Text, nullable=False)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    approved_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    # Relationships
    complaint = relationship("Complaint", backref=backref("responses", order_by="Response.approved_at"))
    approver = relationship("User")

    def __repr__(self):
        return f"<Response id={self.id} complaint_id={self.complaint_id}>"


# ---------------------------------------------------------------------------
# MODEL 5 — CleanupTask
# ---------------------------------------------------------------------------
class CleanupTask(Base):
    __tablename__ = "cleanup_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: f"TSK-{uuid.uuid4().hex[:8]}"
    )
    complaint_id = Column(Integer, ForeignKey("complaints.id"), unique=True, nullable=False, index=True)
    assigned_cleaner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    status = Column(String(30), nullable=False, default="assigned")  # assigned, in_progress, proof_submitted, verified, rejected
    assigned_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)

    complaint = relationship("Complaint", back_populates="cleanup_task")
    cleaner = relationship("User")
    proofs = relationship("CleanupProof", back_populates="task", order_by="CleanupProof.uploaded_at")

    def __repr__(self):
        return f"<CleanupTask id={self.id} task_id={self.task_id!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# MODEL 6 — CleanupProof
# ---------------------------------------------------------------------------
class CleanupProof(Base):
    __tablename__ = "cleanup_proofs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("cleanup_tasks.id"), nullable=False, index=True)
    image_url = Column(String(500), nullable=False)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    uploaded_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    verification_status = Column(String(30), nullable=False, default="pending_verification") # pending_verification, verified, rejected
    verified_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # -----------------------------------------------------------------------
    # Waste-AI advisory verification fields (verify_cleanup() contract).
    # ADVISORY ONLY: the AI never approves or rejects a proof. The human
    # verification workflow (verification_status / verified_by / verified_at /
    # rejection_reason above) remains the single source of truth.
    # -----------------------------------------------------------------------
    before_image_url = Column(String(500), nullable=True)   # complaint image used as "before"
    ai_after_image_usable = Column(Boolean, nullable=True)
    ai_unusable_reason = Column(Text, nullable=True)
    ai_cleanup_appears_complete = Column(Boolean, nullable=True)
    ai_confidence = Column(Float, nullable=True)
    ai_reasoning = Column(Text, nullable=True)
    ai_admin_review_recommended = Column(Boolean, nullable=True)
    ai_processed_at = Column(DateTime(timezone=True), nullable=True)
    ai_errors_json = Column(Text, nullable=True)

    task = relationship("CleanupTask", back_populates="proofs")
    uploader = relationship("User", foreign_keys=[uploaded_by])
    verifier = relationship("User", foreign_keys=[verified_by])

    def __repr__(self):
        return f"<CleanupProof id={self.id} task_id={self.task_id} status={self.verification_status!r}>"


# ---------------------------------------------------------------------------
# MODEL 6b — WasteAIResult  (NEW — waste-AI analysis results)
# ---------------------------------------------------------------------------
# One row per waste-image AI analysis attempt (append-only). Re-uploading an
# image or re-running the AI creates a NEW row; history is never overwritten.
#
# Contract source: branch waste-image-classification, process_waste_image()
# (ai/src/waste_pipeline.py). AI vocabulary is stored VERBATIM:
#   waste_type: wet | dry | hazardous | sanitary | e_waste | mixed | none
#   severity:   domestic | moderate | dump_scale | none
# The backend does NOT remap these to the legacy complaint taxonomy.
# All prediction fields are nullable so a row can exist in "pending" or
# "failed" state before/without AI output.
class WasteAIResult(Base):
    __tablename__ = "waste_ai_results"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id"), nullable=False, index=True)

    # --- Processing state (backend-managed) ---
    # pending | completed | failed
    ai_status = Column(String(20), nullable=False, default="pending")

    # --- Analyzed image ---
    image_url = Column(String(500), nullable=True)
    image_mime_type = Column(String(50), nullable=True)

    # --- Image usability gate ---
    image_usable = Column(Boolean, nullable=True)
    unusable_reason = Column(Text, nullable=True)

    # --- Predictions (AI vocabulary stored verbatim) ---
    waste_type = Column(String(20), nullable=True)
    waste_type_confidence = Column(Float, nullable=True)
    severity = Column(String(20), nullable=True)
    severity_confidence = Column(Float, nullable=True)
    reasoning = Column(Text, nullable=True)
    follow_up_question = Column(Text, nullable=True)

    # --- Location recurrence inputs/outputs (backend computed the count) ---
    recurring_flag = Column(Boolean, nullable=True, default=False)
    prior_reports_count = Column(Integer, nullable=True)
    radius_m = Column(Integer, nullable=True)

    # --- Workflow decision (advisory) ---
    escalate_to_authority = Column(Boolean, nullable=True, default=False)

    # --- Human-review flagging (orthogonal to escalation) ---
    needs_human_review = Column(Boolean, nullable=True, default=False)
    review_reasons_json = Column(Text, nullable=True)

    # --- Grounded disposal guidance (non-escalated cases only) ---
    disposal_guidance = Column(Text, nullable=True)

    # --- Diagnostics ---
    errors_json = Column(Text, nullable=True)

    # --- Provenance (the AI supplies neither name nor version; the adapter stamps these) ---
    model_name = Column(String(100), nullable=True)
    model_version = Column(String(50), nullable=True)
    latency_ms = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    complaint = relationship("Complaint", back_populates="waste_ai_results")

    def __repr__(self):
        return (
            f"<WasteAIResult id={self.id} complaint_id={self.complaint_id} "
            f"status={self.ai_status!r} waste_type={self.waste_type!r} severity={self.severity!r}>"
        )


# ---------------------------------------------------------------------------
# MODEL 7 — AIOutput  (NEW — advisory AI triage results)
# ---------------------------------------------------------------------------
# One row per AI inference pushed by the AI team. Append-only so re-predictions
# form a history. The backend NEVER generates these rows itself.
class AIOutput(Base):
    __tablename__ = "ai_outputs"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id"), nullable=False, index=True)

    # --- Predictions (advisory; humans decide) ---
    waste_type_pred = Column(String(50), nullable=True)
    severity_pred = Column(String(50), nullable=True)
    intervention_required_pred = Column(Boolean, nullable=True)

    # --- Confidence & escalation (the G2 mechanism) ---
    confidence = Column(Float, nullable=True)                # 0.0–1.0; NULL if model gave none
    threshold_used = Column(Float, nullable=False, default=0.7)
    escalated = Column(Boolean, nullable=False, default=False)
    escalation_reason = Column(String(100), nullable=True)   # low_confidence | hazardous_waste | missing_prediction

    # --- Provenance ---
    model_name = Column(String(100), nullable=False)
    model_version = Column(String(50), nullable=False)
    latency_ms = Column(Integer, nullable=True)
    predicted_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    complaint = relationship("Complaint", back_populates="ai_outputs")

    def __repr__(self):
        return (
            f"<AIOutput id={self.id} complaint_id={self.complaint_id} "
            f"waste_type={self.waste_type_pred!r} confidence={self.confidence}>"
        )


# ---------------------------------------------------------------------------
# MODEL 8 — AICorrection  (NEW — admin corrections of AI predictions)
# ---------------------------------------------------------------------------
# Stores only fields where the human CHANGED the AI value, plus which fields
# were accepted (ai_value == admin_value rows are acceptance evidence).
class AICorrection(Base):
    __tablename__ = "ai_corrections"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id"), nullable=False, index=True)
    field_name = Column(String(50), nullable=False)   # waste_type | quantity_severity | intervention_required
    ai_value = Column(String(100), nullable=True)     # what the model predicted (as string)
    admin_value = Column(String(100), nullable=True)  # what the human decided
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    complaint = relationship("Complaint", back_populates="corrections")
    admin = relationship("User")

    def __repr__(self):
        return f"<AICorrection id={self.id} complaint_id={self.complaint_id} field={self.field_name!r}>"


# ---------------------------------------------------------------------------
# MODEL 9 — EventLog  (NEW — lifecycle event log for process mining)
# ---------------------------------------------------------------------------
# One row per state change. Activity vocabulary is controlled by
# taxonomy.EVENT_ACTIVITIES (see eventlog.log_event). The export endpoint
# emits pm4py-ready CSV (case:concept:name / concept:name / time:timestamp).
class EventLog(Base):
    __tablename__ = "event_log"

    event_id = Column(Integer, primary_key=True, index=True)
    case_id = Column(String(50), nullable=False, index=True)   # complaint tracking id
    activity = Column(String(50), nullable=False, index=True)  # controlled vocabulary
    actor_id = Column(Integer, nullable=True)
    actor_role = Column(String(50), nullable=True)             # citizen|ai_system|admin|cleaner|system
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    old_value = Column(String(255), nullable=True)
    new_value = Column(String(255), nullable=True)
    meta_json = Column(Text, nullable=True)                    # JSON: confidence, proof_id, reasons...

    def __repr__(self):
        return f"<EventLog id={self.event_id} case={self.case_id!r} activity={self.activity!r}>"
