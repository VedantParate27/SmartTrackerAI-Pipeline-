import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "smarttracker.db"


def get_conn() -> sqlite3.Connection:
    """One connection per request. FastAPI closes it via Depends + yield."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()
