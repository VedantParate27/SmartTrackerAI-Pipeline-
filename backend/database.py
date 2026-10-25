# database.py
# This file sets up the database connection for SmartTracker AI.
# It uses SQLite (a lightweight file-based database) with SQLAlchemy (an ORM toolkit).

import os
import re
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
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


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


def _create_database_engine(database_url, **options):
    database_engine = create_engine(database_url, **options)
    if database_engine.dialect.name == "sqlite":
        event.listen(
            database_engine,
            "connect",
            _enable_sqlite_foreign_keys,
        )
    return database_engine


engine = _create_database_engine(DATABASE_URL, **engine_options)

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


def _ensure_location_schema(target_engine):
    """Add location-specific legacy columns, indexes, and seed locations."""
    inspector = inspect(target_engine)
    complaint_columns = {
        column["name"] for column in inspector.get_columns("complaints")
    } if "complaints" in inspector.get_table_names() else set()

    if "location_id" not in complaint_columns:
        with target_engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE complaints ADD COLUMN location_id INTEGER "
                "REFERENCES locations(id)"
            ))

    with target_engine.begin() as connection:
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_complaints_location_id "
            "ON complaints (location_id)"
        ))
        connection.execute(text(
            "INSERT INTO locations "
            "(name, slug, is_active, created_at, updated_at) "
            "SELECT :name, :slug, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "WHERE NOT EXISTS (SELECT 1 FROM locations WHERE slug = :slug)"
        ), {"name": "Dadar", "slug": "dadar"})
        connection.execute(text(
            "INSERT INTO locations "
            "(name, slug, is_active, created_at, updated_at) "
            "SELECT :name, :slug, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "WHERE NOT EXISTS (SELECT 1 FROM locations WHERE slug = :slug)"
        ), {"name": "Wadala", "slug": "wadala"})
        connection.execute(text(
            "INSERT INTO locations "
            "(name, slug, is_active, created_at, updated_at) "
            "SELECT :name, :slug, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "WHERE NOT EXISTS (SELECT 1 FROM locations WHERE slug = :slug)"
        ), {"name": "Kalyan-Dombivli", "slug": "kalyan-dombivli"})


def _upgrade_complaint_status_constraint(target_engine):
    """Remove the legacy status CHECK when it rejects the current ``pending`` state.

    SQLite cannot alter a CHECK constraint in place.  The rebuild keeps the
    existing table definition and data, changing only the status constraint;
    explicit indexes and triggers are recreated afterwards.
    """
    with target_engine.connect() as connection:
        table_sql = connection.execute(text(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'complaints'"
        )).scalar_one_or_none()

        if not table_sql or "pending" in table_sql.lower():
            return

        status_check = re.compile(
            r"(\bstatus\b\s+\w+(?:\([^)]*\))?\s+NOT\s+NULL\s+"
            r"DEFAULT\s+'[^']+')\s+CHECK\s*\(\s*status\s+IN\s*"
            r"\([^)]*\)\s*\)",
            re.IGNORECASE | re.DOTALL,
        )
        upgraded_sql, replacements = status_check.subn(r"\1", table_sql, count=1)
        if replacements != 1:
            return

        upgraded_sql = re.sub(
            r'CREATE\s+TABLE\s+(?:"complaints"|`complaints`|\[complaints\]|complaints)',
            "CREATE TABLE complaints_status_upgrade",
            upgraded_sql,
            count=1,
            flags=re.IGNORECASE,
        )
        indexes = connection.execute(text(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = 'complaints' AND sql IS NOT NULL"
        )).scalars().all()
        triggers = connection.execute(text(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'trigger' AND tbl_name = 'complaints' AND sql IS NOT NULL"
        )).scalars().all()
        columns = connection.execute(text("PRAGMA table_info(complaints)")).mappings().all()
        quoted_columns = ", ".join(
            f'"{column["name"].replace(chr(34), chr(34) * 2)}"'
            for column in columns
        )

        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
        connection.commit()
        try:
            with connection.begin():
                connection.execute(text(upgraded_sql))
                connection.execute(text(
                    f"INSERT INTO complaints_status_upgrade ({quoted_columns}) "
                    f"SELECT {quoted_columns} FROM complaints"
                ))
                connection.execute(text("DROP TABLE complaints"))
                connection.execute(text(
                    "ALTER TABLE complaints_status_upgrade RENAME TO complaints"
                ))
                for index_sql in indexes:
                    connection.execute(text(index_sql))
                for trigger_sql in triggers:
                    connection.execute(text(trigger_sql))
        finally:
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys = ON")


def run_migrations(target_engine=None):
    """
    Idempotent schema migration for SQLite databases.

    Ensures all declared tables exist and every declared column is present on
    existing tables (ALTER TABLE ... ADD COLUMN), without dropping or modifying
    existing data. Generalized in Phase 3 to cover ALL tables so the new
    research-layer columns (complaints) and tables (ai_outputs, ai_corrections,
    event_log) appear on databases created by earlier versions.
    """
    import backend.models  # noqa: F401
    if target_engine is None:
        target_engine = engine

    # Ensure all declared tables exist (safe no-op for existing tables)
    Base.metadata.create_all(bind=target_engine)
    _ensure_location_schema(target_engine)

    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(target_engine)

    for table in Base.metadata.sorted_tables:
        if table.name not in inspector.get_table_names():
            continue  # create_all already handled brand-new tables
        existing_columns = {col["name"] for col in inspector.get_columns(table.name)}

        for column in table.columns:
            if column.name in existing_columns:
                continue
            # SQLite cannot safely add primary keys or required foreign keys to
            # an existing table.  Nullable relationship columns are safe to
            # add, and are needed for older workflow tables to match the ORM.
            if column.primary_key or (column.foreign_keys and not column.nullable):
                continue
            ddl = _column_ddl(column)
            with target_engine.begin() as connection:
                connection.execute(
                    text(f"ALTER TABLE {table.name} ADD COLUMN {ddl}")
                )

    _upgrade_complaint_status_constraint(target_engine)



# ---------------------------------------------------------------------------
# 6. DEPENDENCY — get_db()
# ---------------------------------------------------------------------------
def get_db():
    db = SessionLocal()   # open a new session
    try:
        yield db          # hand the session to the route function
    finally:
        db.close()        # always close the session when done
