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
        """Only allow the defined roles."""
        allowed = {"citizen", "cleaner", "staff", "admin"}
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
class CreateComplaintRequest(BaseModel):

    complaint_text: str = Field(
        ...,                   # required field
        min_length=10,
        max_length=5000,
        description="The full text of the complaint (10–5000 characters)",
        examples=["There is an accumulation of e-waste near the community center."],
    )

    phone: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Contact phone number (optional)",
        examples=["9876543210"],
    )

    # Waste Management Fields
    waste_type: Optional[str] = Field(default=None, description="Type of waste (e.g. E-waste, Medical waste, Dry waste, Wet waste)")
    waste_context: Optional[str] = Field(default=None, description="Waste context or environment description")
    quantity_severity: Optional[str] = Field(default=None, description="Quantity or severity level (small, medium, large, hazardous)")
    recommended_action: Optional[str] = Field(default=None, description="Disposal guidance or cleaner instructions")
    intervention_required: Optional[bool] = Field(default=False, description="Whether cleaner intervention is required")

    # Location Fields
    latitude: Optional[float] = Field(default=None, description="Latitude coordinate")
    longitude: Optional[float] = Field(default=None, description="Longitude coordinate")
    address_text: Optional[str] = Field(default=None, description="Human-readable location address/landmark")

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

    department: Optional[str] = Field(
        default=None,
        description="Department assigned to handle the complaint (may be null initially)",
    )

    waste_type: Optional[str] = Field(default=None, description="Type of waste")
    waste_context: Optional[str] = Field(default=None, description="Waste context")
    quantity_severity: Optional[str] = Field(default=None, description="Quantity/severity")
    recommended_action: Optional[str] = Field(default=None, description="Recommended action")
    intervention_required: Optional[bool] = Field(default=False, description="Intervention required flag")

    latitude: Optional[float] = Field(default=None, description="Latitude coordinate")
    longitude: Optional[float] = Field(default=None, description="Longitude coordinate")
    address_text: Optional[str] = Field(default=None, description="Location text")

    created_at: str = Field(
        ...,
        description="ISO 8601 timestamp of when the complaint was created",
    )

    model_config = {"from_attributes": True}

    @field_validator("created_at", mode="before")
    @classmethod
    def serialise_datetime(cls, value):
        """Convert datetime → ISO 8601 string if it isn't already a string."""
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)


# ---------------------------------------------------------------------------
# SCHEMA 7 — AdminComplaintUpdateRequest
# ---------------------------------------------------------------------------
class AdminComplaintUpdateRequest(BaseModel):

    status: Optional[Literal["pending", "in_progress", "resolved", "closed"]] = Field(
        default=None,
        description='New status value ("pending", "in_progress", "resolved", "closed")',
        examples=["in_progress"],
    )

    priority: Optional[Literal["low", "medium", "high", "urgent"]] = Field(
        default=None,
        description='New priority level ("low", "medium", "high", "urgent")',
        examples=["high"],
    )

    department: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Department assigned to handle the complaint",
        examples=["Public Works"],
    )

    @field_validator("department")
    @classmethod
    def department_must_not_be_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None

    from pydantic import model_validator

    @model_validator(mode="after")
    def at_least_one_field_required(self) -> "AdminComplaintUpdateRequest":
        if self.status is None and self.priority is None and self.department is None:
            raise ValueError(
                "At least one field (status, priority, or department) must be provided."
            )
        return self


# ---------------------------------------------------------------------------
# SCHEMA 8 — AdminQueueItem
# ---------------------------------------------------------------------------
from typing import List, Any

class AdminQueueItem(BaseModel):

    id: str = Field(..., alias="tracking_id", description="Public tracking reference")
    requester_name: str = Field(..., alias="name", description="Name of the complainant")
    contact: str = Field(..., alias="email", description="Contact email of the complainant")
    text: str = Field(..., alias="complaint_text", description="Full complaint text")

    status: str = Field(..., description="Current complaint status")
    priority: str = Field(..., description="Priority level, title-cased")
    language: str = Field(..., description="Language of the complaint")

    submitted_at: str = Field(
        ...,
        alias="created_at",
        description="ISO 8601 timestamp of when the complaint was submitted",
    )
    updated_at: str = Field(
        ...,
        description="ISO 8601 timestamp of the last update",
    )

    assigned_department: Optional[str] = Field(
        default=None,
        alias="department",
        description="Department assigned to handle the complaint (may be null)",
    )

    waste_type: Optional[str] = Field(default=None, description="Waste type")
    waste_context: Optional[str] = Field(default=None, description="Waste context")
    quantity_severity: Optional[str] = Field(default=None, description="Quantity/severity")
    recommended_action: Optional[str] = Field(default=None, description="Recommended action")
    intervention_required: Optional[bool] = Field(default=False, description="Intervention required flag")
    latitude: Optional[float] = Field(default=None, description="Latitude")
    longitude: Optional[float] = Field(default=None, description="Longitude")
    address_text: Optional[str] = Field(default=None, description="Address text")

    channel: str = Field(
        default="Backend",
        description="Submission channel",
    )

    classification: Optional[Any] = Field(default=None)
    entities: List[Any] = Field(default_factory=list)
    evidence: List[Any] = Field(default_factory=list)
    ai_draft: Optional[Any] = Field(default=None)
    edited_draft: Optional[str] = Field(default=None)
    resolution: Optional[Any] = Field(default=None)
    closure_reason: Optional[str] = Field(default=None)
    duplicate_of: Optional[str] = Field(default=None)
    comments: List[Any] = Field(default_factory=list)
    audit: List[Any] = Field(default_factory=list)
    attachments: List[Any] = Field(default_factory=list)

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
    }

    @field_validator("priority", mode="before")
    @classmethod
    def title_case_priority(cls, value: str) -> str:
        return value.title() if isinstance(value, str) else value

    @field_validator("submitted_at", "updated_at", mode="before")
    @classmethod
    def serialise_timestamps(cls, value) -> str:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

# ---------------------------------------------------------------------------
# SCHEMA 9 — ApproveResponseRequest & Result
# ---------------------------------------------------------------------------
class ApproveResponseRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    next_status: Literal["in_progress", "resolved"] = Field(...)

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Text must not be blank")
        return value

class ApproveResponseResult(BaseModel):
    tracking_id: str
    response_text: str
    approved_by: str
    approved_at: str
    status: str

# ---------------------------------------------------------------------------
# SCHEMA 10 — CLEANER & TASK SCHEMAS
# ---------------------------------------------------------------------------
class AssignCleanerRequest(BaseModel):
    cleaner_id: int = Field(..., description="ID of the cleaner user to assign")
    notes: Optional[str] = Field(default=None, description="Optional notes or instructions for cleaner")

class AssignCleanerResponse(BaseModel):
    task_id: str
    tracking_id: str
    assigned_cleaner_id: Optional[int]
    cleaner_name: Optional[str]
    status: str
    assigned_at: str

class CleanupProofResponse(BaseModel):
    id: int
    task_id: int
    image_url: str
    uploaded_by: int
    uploaded_at: str
    verification_status: str
    verified_by: Optional[int] = None
    verified_at: Optional[str] = None
    rejection_reason: Optional[str] = None

    model_config = {"from_attributes": True}

    @field_validator("uploaded_at", "verified_at", mode="before")
    @classmethod
    def serialise_proof_timestamps(cls, value):
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

class CleanerTaskResponse(BaseModel):
    task_id: str
    tracking_id: str
    status: str
    assigned_at: str
    completed_at: Optional[str] = None
    notes: Optional[str] = None
    complaint_text: str
    waste_type: Optional[str] = None
    quantity_severity: Optional[str] = None
    recommended_action: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address_text: Optional[str] = None
    proofs: List[CleanupProofResponse] = []

    model_config = {"from_attributes": True}

    @field_validator("assigned_at", "completed_at", mode="before")
    @classmethod
    def serialise_task_timestamps(cls, value):
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

class VerifyProofRequest(BaseModel):
    approved: bool = Field(..., description="True if verified, False if rejected")
    rejection_reason: Optional[str] = Field(default=None, description="Reason if proof is rejected")
    next_status: Optional[Literal["resolved", "closed"]] = Field(default="resolved", description="Next complaint status if approved")

class VerifyProofResult(BaseModel):
    proof_id: int
    task_id: str
    tracking_id: str
    verification_status: str
    task_status: str
    complaint_status: str
    verified_at: str

