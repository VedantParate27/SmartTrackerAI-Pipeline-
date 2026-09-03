# schemas.py
# This file defines the "shape" of data that comes IN to (requests) and goes
# OUT of (responses) the SmartTracker AI API.
#
# Pydantic schemas serve two purposes:
#   1. Validation  — automatically reject bad input before it touches the database
#   2. Documentation — FastAPI reads these to generate the /docs page automatically
#
# This file uses Pydantic v2 syntax (installed: 2.5.x).

from typing import Optional, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


# ---------------------------------------------------------------------------
# SCHEMA 1 — RegisterRequest
# ---------------------------------------------------------------------------
# Shape of the JSON body a client must send to create a new account.
#
# Example valid request body:
# {
#   "name": "Ashish Kumar",
#   "email": "ashish@example.com",
#   "password": "secret123",
#   "role": "citizen",
#   "department": "Finance"
# }
class RegisterRequest(BaseModel):

    # Full name — must be between 2 and 100 characters, cannot be blank spaces
    name: str = Field(
        ...,                   # "..." means this field is required (no default)
        min_length=2,
        max_length=100,
        description="Full name of the user",
        examples=["Ashish Kumar"],
    )

    # Email — Pydantic's EmailStr validates the format automatically
    # (e.g. rejects "notanemail" or "missing@dot")
    email: EmailStr = Field(
        ...,
        description="A valid email address",
        examples=["ashish@example.com"],
    )

    # Password — at least 8 characters to prevent trivially weak passwords
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password (minimum 8 characters)",
        examples=["secret123"],
    )

    # Role — optional; defaults to "citizen" if the client doesn't send it
    # Only the values listed in the validator are accepted.
    role: Optional[str] = Field(
        default="citizen",
        description='User role: "citizen", "staff", or "admin"',
        examples=["citizen"],
    )

    # Department — optional; only relevant for staff/admin users
    department: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Department the user belongs to (optional)",
        examples=["Finance"],
    )

    # --- Field-level validators ---
    # These run automatically when Pydantic receives incoming data.

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        """Reject names that are only whitespace (e.g. '   ')."""
        if not value.strip():
            raise ValueError("Name cannot be blank or whitespace only.")
        return value.strip()   # also strip surrounding spaces before saving

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, value: Optional[str]) -> Optional[str]:
        """Only allow the three defined roles."""
        allowed = {"citizen", "staff", "admin"}
        if value is not None and value not in allowed:
            raise ValueError(f"Role must be one of {sorted(allowed)}.")
        return value

    @field_validator("password")
    @classmethod
    def password_must_not_be_common(cls, value: str) -> str:
        """Block a few obviously weak passwords."""
        blocked = {"password", "12345678", "password1", "qwerty123"}
        if value.lower() in blocked:
            raise ValueError("Password is too common. Please choose a stronger one.")
        return value


# ---------------------------------------------------------------------------
# SCHEMA 2 — LoginRequest
# ---------------------------------------------------------------------------
# Shape of the JSON body a client sends to log in.
#
# Example:
# {
#   "email": "ashish@example.com",
#   "password": "secret123"
# }
class LoginRequest(BaseModel):

    email: EmailStr = Field(
        ...,
        description="Registered email address",
        examples=["ashish@example.com"],
    )

    password: str = Field(
        ...,
        min_length=8,          # same floor as registration to give helpful errors
        max_length=128,
        description="Account password",
        examples=["secret123"],
    )


# ---------------------------------------------------------------------------
# SCHEMA 3 — TokenResponse
# ---------------------------------------------------------------------------
# Shape of the JSON body the server sends BACK after a successful login.
# This is what the client stores and includes in future requests.
#
# Example response:
# {
#   "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
#   "token_type": "bearer"
# }
class TokenResponse(BaseModel):

    access_token: str = Field(
        ...,
        description="JWT access token the client uses for authenticated requests",
    )

    token_type: str = Field(
        default="bearer",
        description='Always "bearer" — tells the client how to use the token',
    )


# ---------------------------------------------------------------------------
# SCHEMA 4 — RegisterResponse
# ---------------------------------------------------------------------------
# Shape of the JSON body the server sends back after a successful registration.
# We deliberately exclude the password hash — never expose it in a response.
#
# Example response:
# {
#   "id": 1,
#   "name": "Ashish Kumar",
#   "email": "ashish@example.com",
#   "role": "citizen"
# }
class RegisterResponse(BaseModel):

    id: int = Field(..., description="Auto-assigned database ID of the new user")
    name: str = Field(..., description="Name that was stored")
    email: EmailStr = Field(..., description="Email that was stored")
    role: str = Field(..., description="Role assigned to the user")

    # model_config tells Pydantic v2 to read data from SQLAlchemy ORM objects
    # (not just plain dictionaries).  Without this, response_model would fail.
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# SCHEMA 5 — CreateComplaintRequest
# ---------------------------------------------------------------------------
# Shape of the JSON body the client sends when submitting a new complaint.
# Notice what is NOT here: name, email, tracking_id, status, priority.
# Those are set automatically by the server — the client cannot influence them.
#
# Example valid request body:
# {
#   "complaint_text": "The streetlight on Main St has been broken for two weeks.",
#   "phone": "9876543210"
# }
class CreateComplaintRequest(BaseModel):

    # The full complaint message — must be at least 10 characters so we don't
    # accept accidental one-word submissions.
    complaint_text: str = Field(
        ...,                   # required field
        min_length=10,
        max_length=5000,
        description="The full text of the complaint (10–5000 characters)",
        examples=["The streetlight on Main St has been broken for two weeks."],
    )

    # Optional phone number — no format enforcement here; different countries
    # use different formats. We store whatever the user provides.
    phone: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Contact phone number (optional)",
        examples=["9876543210"],
    )

    # --- Field-level validator ---
    @field_validator("complaint_text")
    @classmethod
    def complaint_text_must_not_be_blank(cls, value: str) -> str:
        """Reject complaint text that is only whitespace."""
        if not value.strip():
            raise ValueError("Complaint text cannot be blank or whitespace only.")
        return value.strip()   # strip surrounding spaces before saving


# ---------------------------------------------------------------------------
# SCHEMA 6 — ComplaintResponse
# ---------------------------------------------------------------------------
# Shape of the JSON body the server sends BACK after a complaint is created.
# We only expose the fields the client needs — internal DB IDs are omitted.
#
# Example response:
# {
#   "tracking_id": "TRK-a3f8b2c1",
#   "complaint_text": "The streetlight on Main St has been broken for two weeks.",
#   "status": "pending",
#   "priority": "medium",
#   "department": null,
#   "created_at": "2025-01-15T10:30:00+00:00"
# }
class ComplaintResponse(BaseModel):

    tracking_id: str = Field(
        ...,
        description="Unique public reference for tracking this complaint",
    )

    complaint_text: str = Field(
        ...,
        description="The complaint message that was submitted",
    )

    status: str = Field(
        ...,
        description='Current status of the complaint (e.g. "pending")',
    )

    priority: str = Field(
        ...,
        description='Priority level assigned to the complaint (e.g. "medium")',
    )

    # department may be None until an admin classifies the complaint
    department: Optional[str] = Field(
        default=None,
        description="Department assigned to handle the complaint (may be null initially)",
    )

    created_at: str = Field(
        ...,
        description="ISO 8601 timestamp of when the complaint was created",
    )

    # model_config tells Pydantic v2 to read values directly from SQLAlchemy
    # ORM model attributes rather than from a plain dict.
    model_config = {"from_attributes": True}

    # We convert created_at (a datetime object from the DB) to an ISO 8601 string
    # so the response is always a consistent, human-readable format.
    @field_validator("created_at", mode="before")
    @classmethod
    def serialise_datetime(cls, value):
        """Convert datetime → ISO 8601 string if it isn't already a string."""
        if hasattr(value, "isoformat"):   # it's a datetime object
            return value.isoformat()
        return str(value)                 # already a string, pass through


# ---------------------------------------------------------------------------
# SCHEMA 7 — AdminComplaintUpdateRequest
# ---------------------------------------------------------------------------
# Shape of the JSON body an admin sends to update a complaint.
# All three fields are optional so the admin can update any subset.
# At least ONE field must be provided (enforced by the validator below).
#
# Example — update only the status:
# { "status": "in_progress" }
#
# Example — update all three:
# { "status": "resolved", "priority": "high", "department": "Public Works" }
class AdminComplaintUpdateRequest(BaseModel):

    # New status — e.g. "pending", "in_progress", "resolved", "closed"
    status: Optional[Literal["pending", "in_progress", "resolved", "closed"]] = Field(
        default=None,
        description='New status value ("pending", "in_progress", "resolved", "closed")',
        examples=["in_progress"],
    )

    # New priority — accepts only "low", "medium", "high", "urgent"
    priority: Optional[Literal["low", "medium", "high", "urgent"]] = Field(
        default=None,
        description='New priority level ("low", "medium", "high", "urgent")',
        examples=["high"],
    )

    # Department responsible for handling the complaint
    department: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Department assigned to handle the complaint",
        examples=["Public Works"],
    )

    @field_validator("department")
    @classmethod
    def department_must_not_be_blank(cls, value: Optional[str]) -> Optional[str]:
        """Strip surrounding whitespace; treat whitespace-only as None."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None

    # --- Model-level validator ---
    # Runs after all individual fields are validated.
    # Ensures the admin sends at least one field to change.
    from pydantic import model_validator

    @model_validator(mode="after")
    def at_least_one_field_required(self) -> "AdminComplaintUpdateRequest":
        """Reject a request body where every field is None (nothing to update)."""
        if self.status is None and self.priority is None and self.department is None:
            raise ValueError(
                "At least one field (status, priority, or department) must be provided."
            )
        return self


# ---------------------------------------------------------------------------
# SCHEMA 8 — AdminQueueItem
# ---------------------------------------------------------------------------
# Shape of each item returned by GET /admin/queue.
#
# This schema maps SQLAlchemy Complaint column names to the field names the
# frontend TypeScript Complaint type expects, so the admin queue table renders
# correctly without any frontend changes.
#
# Fields that do not yet exist in the database (AI classification, evidence,
# audit trail, etc.) are returned as null / [] placeholders.  This keeps the
# response forward-compatible: later tasks can replace placeholders with real
# data without changing the contract.
#
# Example response item:
# {
#   "id": "TRK-a3f8b2c1",
#   "requester_name": "Ashish Kumar",
#   "contact": "ashish@example.com",
#   "text": "My salary was deducted without notice...",
#   "status": "pending",
#   "priority": "Medium",
#   "assigned_department": null,
#   "language": "en",
#   "submitted_at": "2025-01-15T10:30:00+00:00",
#   "updated_at": "2025-01-15T10:30:00+00:00",
#   "channel": "Backend",
#   "classification": null,
#   "entities": [],
#   "evidence": [],
#   "ai_draft": null,
#   "edited_draft": null,
#   "resolution": null,
#   "closure_reason": null,
#   "duplicate_of": null,
#   "comments": [],
#   "audit": [],
#   "attachments": []
# }
from typing import List, Any

class AdminQueueItem(BaseModel):

    # --- Renamed fields (DB column → frontend field name) ---

    # tracking_id → id: the public human-readable reference (e.g. "TRK-a3f8b2c1")
    id: str = Field(..., alias="tracking_id", description="Public tracking reference")

    # name → requester_name: stored on the complaint at submission time
    requester_name: str = Field(..., alias="name", description="Name of the complainant")

    # email → contact: stored on the complaint at submission time
    contact: str = Field(..., alias="email", description="Contact email of the complainant")

    # complaint_text → text: the full complaint message
    text: str = Field(..., alias="complaint_text", description="Full complaint text")

    # --- Pass-through fields (same column name, same meaning) ---

    # status: passed through as-is for MVP.
    # Backend vocab ("pending", "in_progress") does not match frontend vocab
    # ("Pending Review", "In Progress") — status mapping is deferred to the
    # complaint status lifecycle task.
    status: str = Field(..., description="Current complaint status")

    # priority: title-cased by the validator below ("medium" → "Medium")
    priority: str = Field(..., description="Priority level, title-cased")

    # language: ISO 639-1 code, e.g. "en"
    language: str = Field(..., description="Language of the complaint")

    # --- Renamed timestamp fields ---

    # created_at → submitted_at
    submitted_at: str = Field(
        ...,
        alias="created_at",
        description="ISO 8601 timestamp of when the complaint was submitted",
    )

    # updated_at: same column name, just needs datetime → string conversion
    updated_at: str = Field(
        ...,
        description="ISO 8601 timestamp of the last update",
    )

    # --- Renamed nullable field ---

    # department → assigned_department: may be null until an admin assigns it
    assigned_department: Optional[str] = Field(
        default=None,
        alias="department",
        description="Department assigned to handle the complaint (may be null)",
    )

    # --- Hardcoded field (no DB column) ---

    # channel: not stored in the DB; complaints submitted via the API are
    # labelled "Backend" so the frontend has a non-null string to display.
    channel: str = Field(
        default="Backend",
        description="Submission channel (hardcoded for backend-submitted complaints)",
    )

    # --- Null / empty placeholders for AI fields not yet in the database ---
    # These will be replaced with real data in later tasks.

    classification: Optional[Any] = Field(
        default=None,
        description="AI classification result (not yet available from DB)",
    )
    entities: List[Any] = Field(
        default_factory=list,
        description="Extracted entities (not yet available from DB)",
    )
    evidence: List[Any] = Field(
        default_factory=list,
        description="Retrieved policy evidence (not yet available from DB)",
    )
    ai_draft: Optional[Any] = Field(
        default=None,
        description="AI-generated draft response (not yet available from DB)",
    )
    edited_draft: Optional[str] = Field(
        default=None,
        description="Human-edited draft (not yet available from DB)",
    )
    resolution: Optional[Any] = Field(
        default=None,
        description="Approved resolution (not yet available from DB)",
    )
    closure_reason: Optional[str] = Field(
        default=None,
        description="Reason for closing or rejecting the complaint",
    )
    duplicate_of: Optional[str] = Field(
        default=None,
        description="Reference of the original case if this is a duplicate",
    )
    comments: List[Any] = Field(
        default_factory=list,
        description="Admin comments (not yet available from DB)",
    )
    audit: List[Any] = Field(
        default_factory=list,
        description="Audit trail events (not yet available from DB)",
    )
    attachments: List[Any] = Field(
        default_factory=list,
        description="File attachments (not yet available from DB)",
    )

    # Allow Pydantic to read values directly from SQLAlchemy ORM objects
    # (not just plain dicts), and allow aliases to be used for population.
    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
    }

    # --- Field-level validators ---

    @field_validator("priority", mode="before")
    @classmethod
    def title_case_priority(cls, value: str) -> str:
        """Normalize priority to title-case so frontend receives 'Medium' not 'medium'."""
        return value.title() if isinstance(value, str) else value

    @field_validator("submitted_at", "updated_at", mode="before")
    @classmethod
    def serialise_timestamps(cls, value) -> str:
        """Convert datetime objects to ISO 8601 strings."""
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

# ---------------------------------------------------------------------------
# SCHEMA 9 — ApproveResponseRequest
# ---------------------------------------------------------------------------
class ApproveResponseRequest(BaseModel):
    text: str = Field(
        ..., 
        min_length=1, 
        max_length=5000, 
        description="Approved response text"
    )
    next_status: Literal["in_progress", "resolved"] = Field(
        ..., 
        description="Next backend status for the complaint"
    )

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        """Reject whitespace-only text."""
        if not value.strip():
            raise ValueError("Text must not be blank")
        return value

# ---------------------------------------------------------------------------
# SCHEMA 10 — ApproveResponseResult
# ---------------------------------------------------------------------------
class ApproveResponseResult(BaseModel):
    tracking_id: str = Field(..., description="Public tracking reference")
    response_text: str = Field(..., description="The approved text that was saved")
    approved_by: str = Field(..., description="Name of the admin who approved")
    approved_at: str = Field(..., description="ISO 8601 timestamp of approval")
    status: str = Field(..., description="New status of the complaint")
