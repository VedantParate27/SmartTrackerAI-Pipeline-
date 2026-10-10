"""
migrate_add_location.py
One-time, idempotent migration for Phase 3 GPS/location support.

schema.sql's CREATE TABLE IF NOT EXISTS only applies to brand-new databases.
Anyone with an existing smarttracker.db from Phase 2 needs this instead —
run it once against your local DB and it's safe to run again (it checks
before adding each column).

Usage (from the backend/ folder, same place as main.py):
    python migrate_add_location.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "smarttracker.db"

NEW_COLUMNS = [
    ("latitude", "REAL"),
    ("longitude", "REAL"),
    ("location_type", "TEXT"),  # SQLite can't add a CHECK via ALTER; enforced in the API layer instead
    ("manual_address", "TEXT"),
]


def migrate() -> None:
    if not DB_PATH.exists():
        print(f"[INFO] {DB_PATH} does not exist yet — nothing to migrate. "
              f"It will be created with the new columns already included "
              f"the first time the app runs against schema.sql.")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(complaints)")}

        added = []
        for name, col_type in NEW_COLUMNS:
            if name not in existing_cols:
                conn.execute(f"ALTER TABLE complaints ADD COLUMN {name} {col_type}")
                added.append(name)

        conn.commit()

        if added:
            print(f"[OK] Added columns to complaints: {', '.join(added)}")
        else:
            print("[INFO] All location columns already present. Nothing to do.")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
