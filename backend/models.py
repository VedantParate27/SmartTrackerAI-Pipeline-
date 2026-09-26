# models.py
# This file defines the database tables for SmartTracker AI as Python classes.
# Each class = one table in the database.
# SQLAlchemy reads these classes and creates the actual tables when the app starts.

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
        default=lambda: f"TRK-{uuid.uuid4().hex[:8]}"  # e.g. "TRK-a3f8b2c1"
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
    quantity_severity = Column(String(50), nullable=True)     # small, medium, large, hazardous
    recommended_action = Column(Text, nullable=True)          # self disposal guidance or cleaner instructions
    intervention_required = Column(Boolean, nullable=True, default=False)

    # --- Location Fields (Member 4 Integration) ---
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    address_text = Column(String(255), nullable=True)

    # --- Timestamps ---
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    # --- Relationship ---
    owner = relationship("User", back_populates="complaints")
    cleanup_task = relationship("CleanupTask", back_populates="complaint", uselist=False)

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

    task = relationship("CleanupTask", back_populates="proofs")
    uploader = relationship("User", foreign_keys=[uploaded_by])
    verifier = relationship("User", foreign_keys=[verified_by])

    def __repr__(self):
        return f"<CleanupProof id={self.id} task_id={self.task_id} status={self.verification_status!r}>"

