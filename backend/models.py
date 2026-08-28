# models.py
# This file defines the database tables for SmartTracker AI as Python classes.
# Each class = one table in the database.
# SQLAlchemy reads these classes and creates the actual tables when the app starts.

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,         # used to define a table column
    Integer,        # whole numbers  (1, 2, 3 …)
    String,         # text / varchar
    Text,           # longer text (complaint body)
    DateTime,       # date + time values
    ForeignKey,     # links one table to another
    Boolean,        # True / False  (reserved for future use)
)
from sqlalchemy.orm import relationship  # defines the Python-level link between models

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
    role = Column(String(50), nullable=False, default="citizen")
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

    # --- Timestamps ---
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    # --- Relationship ---
    owner = relationship("User", back_populates="complaints")

    @property
    def resolution(self):
        """Expose the latest approved response formatted for frontend resolution property."""
        if self.responses:
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
    complaint = relationship("Complaint", backref="responses")
    approver = relationship("User")

    def __repr__(self):
        return f"<Response id={self.id} complaint_id={self.complaint_id}>"
