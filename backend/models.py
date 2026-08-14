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
    # Every row gets a unique integer ID assigned automatically by the database.
    id = Column(Integer, primary_key=True, index=True)

    # --- Personal Info ---
    name = Column(String(100), nullable=False)          # full name, required
    email = Column(String(150), unique=True, nullable=False, index=True)  # must be unique
    password_hash = Column(String(255), nullable=False)  # we never store plain passwords!

    # --- Role & Department ---
    # role examples: "admin", "staff", "citizen"
    # nullable=False with a default means every new user gets "citizen" unless specified
    role = Column(String(50), nullable=False, default="citizen")
    department = Column(String(100), nullable=True)  # optional; staff belong to a dept

    # --- Timestamp ---
    # server_default is used so SQLite itself sets this if we forget to pass a value.
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    # --- Relationship ---
    # This tells SQLAlchemy: "A User can have many Complaints."
    # "back_populates" creates a two-way link so you can also go from
    # a Complaint back to its User via complaint.owner
    complaints = relationship("Complaint", back_populates="owner")

    def __repr__(self):
        return f"<User id={self.id} email={self.email!r} role={self.role!r}>"


# ---------------------------------------------------------------------------
# MODEL 2 — Complaint
# ---------------------------------------------------------------------------
# Maps to a table called "complaints" in smarttracker.db.
# Each row is one complaint submitted by a user or a citizen.
class Complaint(Base):
    __tablename__ = "complaints"

    # --- Primary Key ---
    id = Column(Integer, primary_key=True, index=True)

    # --- Public Tracking ID ---
    # A human-readable, shareable reference (e.g. "TRK-a3f8b2c1").
    # Generated automatically when a new complaint is created.
    # unique=True ensures no two complaints share the same tracking ID.
    tracking_id = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: f"TRK-{uuid.uuid4().hex[:8]}"  # e.g. "TRK-a3f8b2c1"
    )

    # --- Foreign Key (link to users table) ---
    # This column stores the id of the User who submitted this complaint.
    # nullable=True → a guest / citizen can submit without being logged in.
    # ForeignKey("users.id") tells the database: "this must match a real users.id"
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # --- Submitter Details ---
    # Stored directly on the complaint so it remains accurate even if the
    # user later changes their profile.
    name = Column(String(100), nullable=False)           # name of the complainant
    email = Column(String(150), nullable=False)          # contact email
    phone = Column(String(20), nullable=True)            # optional phone number

    # --- Complaint Content ---
    complaint_text = Column(Text, nullable=False)        # the full complaint message
    language = Column(String(10), nullable=False, default="en")  # ISO 639-1 code

    # --- Classification ---
    # priority examples : "low", "medium", "high", "urgent"
    # status examples   : "pending", "in_progress", "resolved", "closed"
    # department        : which department should handle this complaint
    priority = Column(String(20), nullable=False, default="medium")
    status = Column(String(30), nullable=False, default="pending")
    department = Column(String(100), nullable=True)

    # --- Timestamps ---
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    # onupdate=utcnow → automatically refreshed every time this row is saved again
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    # --- Relationship (reverse side) ---
    # "back_populates" must match the name used in User.complaints above.
    # This lets you do: complaint.owner  →  the User who submitted it
    owner = relationship("User", back_populates="complaints")

    def __repr__(self):
        return (
            f"<Complaint id={self.id} tracking_id={self.tracking_id!r} "
            f"status={self.status!r} priority={self.priority!r}>"
        )
