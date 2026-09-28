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
def _column_ddl(column) -> str:
    """Render a SQLAlchemy column as SQLite ADD COLUMN DDL (no server defaults —
    SQLite cannot add columns with non-constant defaults, so new columns are
    nullable and the ORM supplies defaults for new rows)."""
    from sqlalchemy import Boolean, DateTime, Float, String, Text

    col_type = str(column.type)
    if isinstance(column.type, Boolean):
        col_type = "BOOLEAN"
    elif isinstance(column.type, DateTime):
        col_type = "DATETIME"
    elif isinstance(column.type, Float):
        col_type = "FLOAT"
    elif isinstance(column.type, Text):
        col_type = "TEXT"
    elif isinstance(column.type, String) and column.type.length:
        col_type = f"VARCHAR({column.type.length})"
    return f"{column.name} {col_type}"


def run_migrations(target_engine=None):
    """
    Idempotent schema migration for SQLite databases.

    Ensures all declared tables exist and every declared column is present on
    existing tables (ALTER TABLE ... ADD COLUMN), without dropping or modifying
    existing data. Generalized in Phase 3 to cover ALL tables so the new
    research-layer columns (complaints) and tables (ai_outputs, ai_corrections,
    event_log) appear on databases created by earlier versions.
    """
    if target_engine is None:
        target_engine = engine

    # Ensure all declared tables exist (safe no-op for existing tables)
    Base.metadata.create_all(bind=target_engine)

    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(target_engine)

    for table in Base.metadata.sorted_tables:
        if table.name not in inspector.get_table_names():
            continue  # create_all already handled brand-new tables
        existing_columns = {col["name"] for col in inspector.get_columns(table.name)}

        for column in table.columns:
            if column.name in existing_columns:
                continue
            # Never ALTER primary keys or foreign keys on existing tables;
            # new tables created by create_all always carry them already.
            if column.primary_key or column.foreign_keys:
                continue
            ddl = _column_ddl(column)
            with target_engine.begin() as connection:
                connection.execute(
                    text(f"ALTER TABLE {table.name} ADD COLUMN {ddl}")
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

