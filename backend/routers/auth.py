# routers/auth.py
# Handles all authentication-related API endpoints for SmartTracker AI.
# Implements:
#   POST /auth/register  — create a new user account
#   POST /auth/login     — verify credentials and return a signed JWT

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

# python-jose handles JWT creation and decoding
from jose import jwt

# passlib handles password hashing and verification
from passlib.context import CryptContext

# Our own modules
from database import get_db
from models import User
from schemas import LoginRequest, RegisterRequest, RegisterResponse, TokenResponse


# ===========================================================================
# SECTION 1 — JWT CONFIGURATION
# ===========================================================================
# The secret key is used to SIGN the token. Anyone who knows this key can
# forge tokens, so in production this must come from an environment variable
# or a secrets manager — never hard-code it in real deployments.
#
# To generate a strong key yourself:
#   python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY = os.getenv(
    "SMARTTRACKER_SECRET_KEY",
    "development-only-change-me-before-production",
)

# The algorithm that signs the token. HS256 (HMAC + SHA-256) is the standard
# choice for single-server apps — it's fast, well-supported, and secure.
ALGORITHM = "HS256"

# How long a token stays valid. After this time the token is rejected and
# the user must log in again. 60 minutes is a sensible default.
ACCESS_TOKEN_EXPIRE_MINUTES = 60


# ===========================================================================
# SECTION 2 — PASSWORD HASHING SETUP
# ===========================================================================
# CryptContext manages hashing and verification.
# schemes=["bcrypt"]  → use the bcrypt algorithm (deliberately slow = secure)
# deprecated="auto"   → if we ever add a newer scheme, old hashes auto-upgrade
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """
    Convert a plain-text password into an irreversible bcrypt hash.

    Example:
        hash_password("secret123")
        → "$2b$12$eImiTXuWVxfM37uY4JANjQ...."
    """
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Check whether a plain-text password matches a stored bcrypt hash.

    passlib hashes the attempt and compares — the plain password is never
    compared directly and cannot be recovered from the hash.

    Returns True if the passwords match, False otherwise.
    """
    return pwd_context.verify(plain_password, hashed_password)


# ===========================================================================
# SECTION 3 — JWT HELPER
# ===========================================================================
def create_access_token(user_id: int, role: str) -> str:
    """
    Build and sign a JWT access token for an authenticated user.

    The token payload ("claims") contains:
      sub  — subject: the user's database ID (stored as a string, JWT convention)
      role — the user's role ("citizen", "staff", "admin")
      exp  — expiration timestamp: when the token stops being valid

    Anyone who receives this token can read the payload (it is base64-encoded,
    not encrypted), but they CANNOT forge or tamper with it because it is signed
    with SECRET_KEY.  If they change even one character, verification will fail.

    Example decoded payload:
        {"sub": "1", "role": "citizen", "exp": 1723500000}
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    payload = {
        "sub": str(user_id),   # "sub" = subject; always a string by JWT convention
        "role": role,
        "exp": expire,         # python-jose converts datetime → Unix timestamp
    }

    # jwt.encode signs the payload and returns the compact token string
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token


# ===========================================================================
# SECTION 4 — ROUTER
# ===========================================================================
# APIRouter groups related endpoints together.
# prefix="/auth"  → every route below starts with /auth
# tags=["auth"]   → shown as a group named "auth" on the /docs page
router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------
@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
def register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
):
    """
    Create a new user account.

    - **name**: Full name (2–100 characters)
    - **email**: Must be a valid, unique email address
    - **password**: Minimum 8 characters (stored as a bcrypt hash, never plain text)
    - **department**: Optional — useful for staff members
    - **role**: Ignored — all public registrations are always assigned **citizen**
    """

    # Step 1 — Reject duplicate email
    existing_user = db.query(User).filter(User.email == body.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists.",
        )

    # Step 2 — Hash the password (never store plain text)
    hashed = hash_password(body.password)

    # Step 3 — Build the User row
    # role is hardcoded to "citizen" — ignoring body.role prevents self-promotion
    new_user = User(
        name=body.name,
        email=body.email,
        password_hash=hashed,
        role="citizen",
        department=body.department,
    )

    # Step 4 — Persist to the database
    db.add(new_user)
    db.commit()
    db.refresh(new_user)   # populates new_user.id from the DB

    # Step 5 — Return the response (password hash excluded by RegisterResponse)
    return new_user


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------
@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Log in and receive a JWT access token",
)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
):
    """
    Authenticate a user and return a signed JWT access token.

    - **email**: The registered email address
    - **password**: The account password

    On success, returns an **access_token** (JWT) and **token_type** ("bearer").

    The token expires after **60 minutes**. Include it in future requests as:
    ```
    Authorization: Bearer <access_token>
    ```

    Returns **401 Unauthorized** for any invalid email or password.
    Note: the error message is intentionally vague — we never reveal whether
    the email exists or whether it's the password that's wrong. This prevents
    attackers from using the login endpoint to enumerate valid email addresses.
    """

    # ------------------------------------------------------------------
    # Step 1 — Look up the user by email
    # ------------------------------------------------------------------
    user = db.query(User).filter(User.email == body.email).first()

    # ------------------------------------------------------------------
    # Step 2 — Verify the password
    # ------------------------------------------------------------------
    # We check both conditions together and return the SAME error message
    # whether the email doesn't exist OR the password is wrong.
    # This is called "constant-time failure" and prevents email enumeration.
    #
    # verify_password returns False if:
    #   - user is None (email not found), OR
    #   - the password doesn't match the stored hash
    password_ok = user is not None and verify_password(body.password, user.password_hash)

    if not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            # WWW-Authenticate header is part of the HTTP standard for 401 responses.
            # It tells the client which authentication scheme is expected.
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ------------------------------------------------------------------
    # Step 3 — Generate a JWT token
    # ------------------------------------------------------------------
    # At this point we know the credentials are valid.
    # We embed the user's ID and role into the token so that protected
    # endpoints can read those claims without hitting the database again.
    access_token = create_access_token(user_id=user.id, role=user.role)

    # ------------------------------------------------------------------
    # Step 4 — Return the token
    # ------------------------------------------------------------------
    return TokenResponse(access_token=access_token, token_type="bearer")
