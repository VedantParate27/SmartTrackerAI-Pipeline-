"""
Persistent storage for AI pipeline results, so admins can review
classifications, draft responses, and any flagged issues after the
fact rather than only seeing them in console output.

Uses SQLite as a lightweight local placeholder — designed so the real
team database (once provided) can replace just this file without
requiring changes to pipeline.py or any other module.
"""
import sqlite3
import json
import os
from datetime import datetime, timezone
from config import PROJECT_ROOT

DB_PATH = os.path.join(PROJECT_ROOT, "admin_review.db")


def init_db():
    """Creates the results table if it doesn't already exist. Safe to call every run."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS complaint_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            complaint_text TEXT NOT NULL,
            category TEXT,
            department TEXT,
            urgency TEXT,
            confidence REAL,
            entities_json TEXT,
            summary TEXT,
            retrieved_sources_json TEXT,
            top_retrieval_score REAL,
            draft_response TEXT,
            citation_check_json TEXT,
            needs_human_review INTEGER,
            review_reasons_json TEXT,
            errors_json TEXT,
            admin_status TEXT DEFAULT 'pending'
        )
    """)
    conn.commit()
    conn.close()


def save_result(result: dict) -> int:
    """
    Saves a process_complaint() result dict to the database.
    Returns the new row's id.
    """
    init_db()  # ensures table exists even on first-ever call
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO complaint_results (
            created_at, complaint_text, category, department, urgency,
            confidence, entities_json, summary, retrieved_sources_json,
            top_retrieval_score, draft_response, citation_check_json,
            needs_human_review, review_reasons_json, errors_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
                datetime.now(timezone.utc).isoformat(),
        result.get("complaint_text"),
        result.get("category"),
        result.get("department"),
        result.get("urgency"),
        result.get("confidence"),
        json.dumps(result.get("entities")),
        result.get("summary"),
        json.dumps(result.get("retrieved_sources")),
        result.get("top_retrieval_score"),
        result.get("draft_response"),
        json.dumps(result.get("citation_check")),
        1 if result.get("needs_human_review") else 0,
        json.dumps(result.get("review_reasons")),
        json.dumps(result.get("errors")),
    ))
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def get_pending_review(limit: int = 20) -> list[dict]:
    """Returns complaints flagged for human review, most recent first."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # lets us access columns by name
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM complaint_results
        WHERE needs_human_review = 1 AND admin_status = 'pending'
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_all_results(limit: int = 50) -> list[dict]:
    """Returns all stored results, most recent first."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM complaint_results ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


if __name__ == "__main__":
    # Quick manual test: save a fake result and read it back
    init_db()
    fake_result = {
        "complaint_text": "test complaint for storage check",
        "category": "other",
        "department": "customer_service",
        "urgency": "low",
        "confidence": 0.9,
        "entities": {"order_ids": [], "account_id": None, "error_code": None},
        "summary": "Testing storage",
        "retrieved_sources": ["customerservice_general.txt"],
        "top_retrieval_score": 0.5,
        "draft_response": "This is a test draft.",
        "citation_check": {"fully_grounded": True},
        "needs_human_review": False,
        "review_reasons": [],
        "errors": [],
    }
    new_id = save_result(fake_result)
    print(f"Saved test result with id={new_id}")

    all_results = get_all_results(5)
    print(f"\nMost recent {len(all_results)} result(s) in DB:")
    for r in all_results:
        print(f"  id={r['id']}, department={r['department']}, needs_review={r['needs_human_review']}")
        pending = get_pending_review()
    print(f"\n--- {len(pending)} complaint(s) pending human review ---")
    for r in pending:
        print(f"  id={r['id']}, department={r['department']}, reasons={r['review_reasons_json']}")