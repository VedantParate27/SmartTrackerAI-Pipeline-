# schemas.py
# This file defines the "shape" of data that comes IN to (requests) and goes
# OUT of (responses) the SmartTracker AI API.
#
# Pydantic schemas serve two purposes:
#   1. Validation  — automatically reject bad input before it touches the database
#   2. Documentation — FastAPI reads these to generate the /docs page automatically
#
# This file uses Pydantic v2 syntax (installed: 2.5.x).

from typing import Optional

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
    status: Optional[str] = Field(
        default=None,
        max_length=30,
        description='New status value (e.g. "in_progress", "resolved", "closed")',
        examples=["in_progress"],
    )

    # New priority — e.g. "low", "medium", "high", "urgent"
    priority: Optional[str] = Field(
        default=None,
        max_length=20,
        description='New priority level (e.g. "low", "medium", "high", "urgent")',
        examples=["high"],
    )

    # Department responsible for handling the complaint
    department: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Department assigned to handle the complaint",
        examples=["Public Works"],
    )

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
