"""
auth.py
Authentication for the LIVE SmartTracker AI backend (main.py + db.py).

This intentionally mirrors routers/auth.py's approach (bcrypt hashing,
JWT via python-jose) but is rewritten against the live raw-sqlite3 stack
(db.get_conn) instead of the unused SQLAlchemy models in database.py /
models.py. Those files are left untouched.
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field

from db import get_conn

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv(
    "SMARTTRACKER_SECRET_KEY",
    "development-only-change-me-before-production",
)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: int, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    # role is intentionally NOT accepted here — every public registration
    # is a 'customer'. Admin accounts are provisioned separately (see the
    # existing create_admin.py pattern), never self-assigned.


class RegisterResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------------------------------------------------------------------------
# Dependency: decode the bearer token into the current user's row.
# Not wired onto any existing endpoint yet — available for the next
# increment (protecting /complaints, /admin/* with real auth).
# ---------------------------------------------------------------------------
def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    conn: sqlite3.Connection = Depends(get_conn),
) -> sqlite3.Row:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# ---------------------------------------------------------------------------
# Core operations, called from the endpoints in main.py
# ---------------------------------------------------------------------------
def register_user(conn: sqlite3.Connection, body: RegisterRequest) -> RegisterResponse:
    existing = conn.execute(
        "SELECT id FROM users WHERE email = ?", (body.email,)
    ).fetchone()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists.",
        )

    hashed = hash_password(body.password)
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'customer')",
        (body.name, body.email, hashed),
    )
    conn.commit()
    user_id = cur.lastrowid
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return RegisterResponse(id=row["id"], name=row["name"], email=row["email"], role=row["role"])


def login_user(conn: sqlite3.Connection, body: LoginRequest) -> TokenResponse:
    user = conn.execute(
        "SELECT * FROM users WHERE email = ?", (body.email,)
    ).fetchone()

    # Same failure path whether the email doesn't exist or the password is
    # wrong, to avoid leaking which emails are registered.
    password_ok = user is not None and verify_password(body.password, user["password_hash"])
    if not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user_id=user["id"], role=user["role"])
    return TokenResponse(access_token=token)
