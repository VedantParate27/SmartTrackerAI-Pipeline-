# database.py
# This file sets up the database connection for SmartTracker AI.
# It uses SQLite (a lightweight file-based database) with SQLAlchemy (an ORM toolkit).

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

# ---------------------------------------------------------------------------
# 1. DATABASE URL
# ---------------------------------------------------------------------------
DEFAULT_DATABASE_PATH = Path(__file__).resolve().with_name("smarttracker.db")
DATABASE_URL = os.getenv(
    "SMARTTRACKER_DATABASE_URL",
    f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}",
)

# ---------------------------------------------------------------------------
# 2. ENGINE
# ---------------------------------------------------------------------------
engine_options = {}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_options)

# ---------------------------------------------------------------------------
# 3. SESSION FACTORY
# ---------------------------------------------------------------------------
SessionLocal = sessionmaker(
    autocommit=False,   # manually control when changes are saved (safer)
    autoflush=False,
    bind=engine
)

# ---------------------------------------------------------------------------
# 4. DECLARATIVE BASE
# ---------------------------------------------------------------------------
Base = declarative_base()


# ---------------------------------------------------------------------------
# 5. IDEMPOTENT MIGRATION HELPER
# ---------------------------------------------------------------------------
def run_migrations(target_engine=None):
    """
    Idempotent schema migration for SQLite databases.
    Ensures missing columns and new tables are safely added to existing database files
    without dropping or modifying existing data.
    """
    if target_engine is None:
        target_engine = engine

    # Ensure all declared tables exist
    Base.metadata.create_all(bind=target_engine)

    from models import Complaint
    from sqlalchemy import Boolean, DateTime, String

    inspector = inspect(target_engine)
    if "complaints" in inspector.get_table_names():
        existing_columns = {col["name"] for col in inspector.get_columns("complaints")}

        for column in Complaint.__table__.columns:
            if column.name not in existing_columns:
                col_type = str(column.type)
                if isinstance(column.type, Boolean):
                    col_type = "BOOLEAN DEFAULT 0"
                elif isinstance(column.type, DateTime):
                    col_type = "DATETIME"
                elif isinstance(column.type, String) and column.type.length:
                    col_type = f"VARCHAR({column.type.length})"

                with target_engine.begin() as connection:
                    connection.execute(
                        text(f"ALTER TABLE complaints ADD COLUMN {column.name} {col_type}")
                    )



# ---------------------------------------------------------------------------
# 6. DEPENDENCY — get_db()
# ---------------------------------------------------------------------------
def get_db():
    db = SessionLocal()   # open a new session
    try:
        yield db          # hand the session to the route function
    finally:
        db.close()        # always close the session when done

