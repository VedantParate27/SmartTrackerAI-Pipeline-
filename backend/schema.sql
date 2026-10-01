-- ============================================================
-- SmartTracker AI — Application Database Schema (SQLite)
-- 4 tables: users, complaints, responses, policies
-- ============================================================

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'customer' CHECK (role IN ('customer','admin')),
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS complaints (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL,
    complaint_text      TEXT NOT NULL,
    category            TEXT,
    department          TEXT,
    confidence_score    REAL,
    extracted_entities  TEXT,           -- JSON string, e.g. {"order_id":"ORD123"}
    latitude            REAL,
    longitude           REAL,
    location_type       TEXT CHECK (location_type IN ('gps','manual')),
    manual_address      TEXT,
    status              TEXT NOT NULL DEFAULT 'submitted'
                         CHECK (status IN ('submitted','processing','awaiting_review','resolved')),
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS responses (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id       INTEGER NOT NULL UNIQUE,
    ai_draft_response  TEXT NOT NULL,
    final_response     TEXT,
    approved_by        INTEGER,
    approved_at        TIMESTAMP,
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (complaint_id) REFERENCES complaints(id),
    FOREIGN KEY (approved_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS policies (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    department   TEXT,
    filename     TEXT NOT NULL,
    version      TEXT,
    uploaded_by  INTEGER NOT NULL,
    upload_date  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (uploaded_by) REFERENCES users(id)
);

-- Indexes that your FastAPI queries will actually hit
CREATE INDEX IF NOT EXISTS idx_complaints_user_id ON complaints(user_id);
CREATE INDEX IF NOT EXISTS idx_complaints_status   ON complaints(status);
CREATE INDEX IF NOT EXISTS idx_responses_complaint ON responses(complaint_id);
CREATE INDEX IF NOT EXISTS idx_policies_department ON policies(department);

-- Auto-update complaints.updated_at whenever a row changes
CREATE TRIGGER IF NOT EXISTS trg_complaints_updated_at
AFTER UPDATE ON complaints
FOR EACH ROW
BEGIN
    UPDATE complaints SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
END;
