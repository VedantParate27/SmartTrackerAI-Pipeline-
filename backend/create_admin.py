# create_admin.py
# One-time development script for SmartTracker AI.
#
# Run from the backend/venv folder (the same folder as main.py):
#   cd "d:\Smart Tracker AI\backend\venv"
#   python create_admin.py
#
# What it does:
#   - Connects to the existing smarttracker.db (created by the FastAPI app)
#   - Creates a single admin user if the email does not already exist
#   - Hashes the password using the same bcrypt function used at registration
#   - Prints the outcome and exits
#
# Do NOT run this in production without changing the credentials.

import sys

# ---------------------------------------------------------------------------
# Imports from the existing backend modules
# ---------------------------------------------------------------------------
# database.py provides the engine (connection to smarttracker.db) and
# SessionLocal (the factory for creating DB sessions).
from database import Base, SessionLocal, engine

# models.py provides the User class (maps to the "users" table).
from models import User

# hash_password lives in routers/auth.py — we reuse it so the hash format
# is identical to what the registration endpoint produces.
from routers.auth import hash_password


# ---------------------------------------------------------------------------
# Admin credentials  (development only — change before any real deployment)
# ---------------------------------------------------------------------------
ADMIN_NAME       = "Admin User"
ADMIN_EMAIL      = "admin@smar9cdttracker.com"
ADMIN_PASSWORD   = "admin12345"     # will be hashed — never stored as plain text
ADMIN_ROLE       = "admin"
ADMIN_DEPARTMENT = "Administration"


def create_admin() -> None:
    # Step 1 — Make sure the "users" table exists.
    # If the FastAPI app has already been started at least once, the table
    # already exists and this call is a safe no-op.
    Base.metadata.create_all(bind=engine)

    # Step 2 — Open a database session.
    db = SessionLocal()

    try:
        # Step 3 — Check whether this admin account already exists.
        existing = db.query(User).filter(User.email == ADMIN_EMAIL).first()

        if existing:
            print(f"[INFO] Admin already exists: '{ADMIN_EMAIL}' (id={existing.id}). Nothing was changed.")
            return

        # Step 4 — Hash the password (bcrypt, same algorithm as registration).
        hashed = hash_password(ADMIN_PASSWORD)

        # Step 5 — Build the User row.
        admin_user = User(
            name=ADMIN_NAME,
            email=ADMIN_EMAIL,
            password_hash=hashed,   # hashed — plain password is never stored
            role=ADMIN_ROLE,
            department=ADMIN_DEPARTMENT,
        )

        # Step 6 — Save to the database.
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)   # loads the auto-assigned id back into the object

        print("[OK] Admin user created successfully.")
        print(f"     id         : {admin_user.id}")
        print(f"     name       : {admin_user.name}")
        print(f"     email      : {admin_user.email}")
        print(f"     role       : {admin_user.role}")
        print(f"     department : {admin_user.department}")
        print(f"     created_at : {admin_user.created_at}")

    except Exception as exc:
        db.rollback()   # undo any partial changes if something went wrong
        print(f"[ERROR] Could not create admin user: {exc}", file=sys.stderr)
        sys.exit(1)

    finally:
        db.close()   # always close the session, even if an error occurred


if __name__ == "__main__":
    create_admin()
