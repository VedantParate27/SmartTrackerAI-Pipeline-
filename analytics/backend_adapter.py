
"""Read-only adapter for SmartTracker backend analytics data."""

import os
import sqlite3
from pathlib import Path


def get_backend_db_path():
    """Resolve the backend SQLite database path."""
    database_url = os.getenv("SMARTTRACKER_DATABASE_URL", "").strip()

    if database_url:
        if not database_url.startswith("sqlite:///"):
            raise ValueError(
                "This adapter currently supports SQLite backend databases only."
            )
        return Path(database_url.removeprefix("sqlite:///"))

    return (
        Path(__file__).resolve().parents[2]
        / "SmartTrackerAI-Pipeline-"
        / "backend"
        / "smarttracker.db"
    )


def load_backend_records():
    """Load cleanup tasks and lifecycle events without modifying the database."""
    db_path = get_backend_db_path()

    if not db_path.exists():
        raise FileNotFoundError(
            f"Backend database not found: {db_path}. "
            "Check SMARTTRACKER_DATABASE_URL."
        )

    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row

    try:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

        required = {"complaints", "cleanup_tasks", "event_log"}
        missing = required - tables
        if missing:
            raise RuntimeError(
                f"Backend database is missing tables: {', '.join(sorted(missing))}"
            )

        tasks = [
            dict(row)
            for row in connection.execute("SELECT * FROM cleanup_tasks")
        ]

        events = [
            dict(row)
            for row in connection.execute(
                """
                SELECT event_id, case_id, activity, actor_id, actor_role,
                       timestamp, old_value, new_value, meta_json
                FROM event_log
                WHERE activity IN (
                    'task_started', 'proof_submitted',
                    'proof_verified', 'proof_rejected'
                )
                ORDER BY timestamp
                """
            )
        ]

        return {
            "database": str(db_path),
            "tasks": tasks,
            "events": events,
            "task_count": len(tasks),
            "event_count": len(events),
            "source": "backend",
        }
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        result = load_backend_records()
        print(f"Source: {result['source']}")
        print(f"Database: {result['database']}")
        print(f"Cleanup tasks: {result['task_count']}")
        print(f"Lifecycle events: {result['event_count']}")
        print("Read-only connection: successful")
    except Exception as exc:
        print(f"Adapter test failed: {exc}")
        raise
