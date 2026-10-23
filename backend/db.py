import os
import sqlite3
from pathlib import Path
from typing import Generator, Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db

DEFAULT_DB_PATH = Path(__file__).parent / "smarttracker.db"
DB_PATH = Path(
    os.getenv(
        "SMARTTRACKER_DATABASE_PATH",
        os.getenv("SMARTTRACKER_DB_PATH", str(DEFAULT_DB_PATH)),
    )
)


def get_conn(
    db: Optional[Session] = Depends(get_db),
) -> Generator[sqlite3.Connection, None, None]:
    """
    One connection per request. FastAPI closes it via Depends + yield.
    If database.get_db is available (or overridden in test suites), get_conn extracts
    the underlying sqlite3 driver connection from the active session so all raw
    queries and ORM queries share the same transactional database.
    Otherwise, it opens a direct connection to DB_PATH.
    """
    if db is not None:
        raw_connection = db.connection().connection.dbapi_connection
        raw_connection.row_factory = sqlite3.Row
        raw_connection.execute("PRAGMA foreign_keys = ON")
        yield raw_connection
    else:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()
