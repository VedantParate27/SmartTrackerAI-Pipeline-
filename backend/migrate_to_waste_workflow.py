import argparse
import sqlite3
import uuid
from pathlib import Path


MIGRATION_ID = "001_waste_management_workflow"


def utc_timestamp():
    return "CURRENT_TIMESTAMP"


def generate_tracking_id():
    return f"TRK-{uuid.uuid4().hex[:8]}"


def migrate(db_path: str):
    path = Path(db_path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    try:
        conn.execute("PRAGMA foreign_keys = OFF")

        # Migration tracking table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id TEXT PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        already_applied = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE id = ?",
            (MIGRATION_ID,),
        ).fetchone()

        if already_applied:
            print(f"[INFO] Migration already applied: {MIGRATION_ID}")
            return

        print(f"[INFO] Migrating: {path}")

        conn.execute("BEGIN")

        # ------------------------------------------------------------
        # 1. Rebuild users table
        # ------------------------------------------------------------
        print("[1/5] Rebuilding users table...")

        conn.execute("DROP TABLE IF EXISTS users_new")

        conn.execute("""
            CREATE TABLE users_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                email         TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'citizen'
                              CHECK (role IN ('citizen', 'admin', 'cleaner')),
                department    TEXT,
                created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        users = conn.execute("""
            SELECT id, name, email, password_hash, role, created_at
            FROM users
            ORDER BY id
        """).fetchall()

        for user in users:
            role = "citizen" if user["role"] == "customer" else user["role"]

            if role not in ("citizen", "admin", "cleaner"):
                raise ValueError(
                    f"Unsupported existing user role: {user['role']!r}"
                )

            conn.execute("""
                INSERT INTO users_new
                    (id, name, email, password_hash, role, department, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                user["id"],
                user["name"],
                user["email"],
                user["password_hash"],
                role,
                None,
                user["created_at"],
            ))

        conn.execute("DROP TABLE users")
        conn.execute("ALTER TABLE users_new RENAME TO users")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)"
        )

        # ------------------------------------------------------------
        # 2. Rebuild complaints table
        # ------------------------------------------------------------
        print("[2/5] Rebuilding complaints table...")

        conn.execute("DROP TABLE IF EXISTS complaints_new")

        conn.execute("""
            CREATE TABLE complaints_new (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                tracking_id              TEXT NOT NULL UNIQUE,
                user_id                  INTEGER NOT NULL,

                name                     TEXT NOT NULL,
                email                    TEXT NOT NULL,
                phone                    TEXT,

                complaint_text           TEXT NOT NULL,
                language                 TEXT NOT NULL DEFAULT 'en',

                category                 TEXT,
                department              TEXT,
                priority                 TEXT NOT NULL DEFAULT 'medium',

                confidence_score         REAL,
                extracted_entities       TEXT,

                latitude                 REAL,
                longitude                REAL,
                location_type            TEXT
                                         CHECK (location_type IN ('gps', 'manual')),
                manual_address           TEXT,

                image_path               TEXT,
                image_mime_type          TEXT,

                waste_type               TEXT,
                waste_type_confidence   REAL,
                severity                 TEXT,
                severity_confidence     REAL,
                ai_reasoning             TEXT,
                follow_up_question       TEXT,

                recurring_flag           INTEGER NOT NULL DEFAULT 0,
                prior_reports_at_location INTEGER NOT NULL DEFAULT 0,
                escalate_to_authority   INTEGER NOT NULL DEFAULT 0,
                needs_human_review       INTEGER NOT NULL DEFAULT 0,
                review_reasons           TEXT,

                disposal_guidance        TEXT,

                status                   TEXT NOT NULL DEFAULT 'submitted'
                                         CHECK (
                                             status IN (
                                                 'submitted',
                                                 'processing',
                                                 'awaiting_review',
                                                 'assigned',
                                                 'in_progress',
                                                 'proof_submitted',
                                                 'verification',
                                                 'resolved',
                                                 'closed'
                                             )
                                         ),

                created_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        complaints = conn.execute("""
            SELECT
                c.id,
                c.user_id,
                c.complaint_text,
                c.category,
                c.department,
                c.confidence_score,
                c.extracted_entities,
                c.latitude,
                c.longitude,
                c.location_type,
                c.manual_address,
                c.status,
                c.created_at,
                c.updated_at,
                u.name,
                u.email
            FROM complaints c
            JOIN users u ON u.id = c.user_id
            ORDER BY c.id
        """).fetchall()

        used_tracking_ids = set()

        for complaint in complaints:
            tracking_id = generate_tracking_id()

            while tracking_id in used_tracking_ids:
                tracking_id = generate_tracking_id()

            used_tracking_ids.add(tracking_id)

            conn.execute("""
                INSERT INTO complaints_new (
                    id,
                    tracking_id,
                    user_id,
                    name,
                    email,
                    phone,
                    complaint_text,
                    language,
                    category,
                    department,
                    priority,
                    confidence_score,
                    extracted_entities,
                    latitude,
                    longitude,
                    location_type,
                    manual_address,
                    image_path,
                    image_mime_type,
                    waste_type,
                    waste_type_confidence,
                    severity,
                    severity_confidence,
                    ai_reasoning,
                    follow_up_question,
                    recurring_flag,
                    prior_reports_at_location,
                    escalate_to_authority,
                    needs_human_review,
                    review_reasons,
                    disposal_guidance,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, NULL, ?, 'en', ?, ?, 'medium',
                    ?, ?, ?, ?, ?, ?,
                    NULL, NULL,
                    NULL, NULL, NULL, NULL, NULL, NULL,
                    0, 0, 0, 0, NULL, NULL,
                    ?, ?, ?
                )
            """, (
                complaint["id"],
                tracking_id,
                complaint["user_id"],
                complaint["name"],
                complaint["email"],
                complaint["complaint_text"],
                complaint["category"],
                complaint["department"],
                complaint["confidence_score"],
                complaint["extracted_entities"],
                complaint["latitude"],
                complaint["longitude"],
                complaint["location_type"],
                complaint["manual_address"],
                complaint["status"],
                complaint["created_at"],
                complaint["updated_at"],
            ))

        conn.execute("DROP TABLE complaints")
        conn.execute("ALTER TABLE complaints_new RENAME TO complaints")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_complaints_user_id "
            "ON complaints(user_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_complaints_status "
            "ON complaints(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_complaints_tracking_id "
            "ON complaints(tracking_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_complaints_location "
            "ON complaints(latitude, longitude)"
        )

        # ------------------------------------------------------------
        # 3. Preserve existing responses and policies
        # ------------------------------------------------------------
        print("[3/5] Verifying existing responses and policies...")

        response_count = conn.execute(
            "SELECT COUNT(*) FROM responses"
        ).fetchone()[0]

        policy_count = conn.execute(
            "SELECT COUNT(*) FROM policies"
        ).fetchone()[0]

        print(f"      responses preserved: {response_count}")
        print(f"      policies preserved:  {policy_count}")

        # ------------------------------------------------------------
        # 4. Create cleanup workflow tables
        # ------------------------------------------------------------
        print("[4/5] Creating cleanup workflow tables...")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS cleanup_tasks (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id      INTEGER NOT NULL UNIQUE,
                cleaner_id        INTEGER NOT NULL,
                assigned_by       INTEGER NOT NULL,

                status            TEXT NOT NULL DEFAULT 'assigned'
                                  CHECK (
                                      status IN (
                                          'assigned',
                                          'in_progress',
                                          'proof_submitted',
                                          'verification',
                                          'completed',
                                          'rejected'
                                      )
                                  ),

                notes             TEXT,
                created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at      TIMESTAMP,

                FOREIGN KEY (complaint_id) REFERENCES complaints(id),
                FOREIGN KEY (cleaner_id) REFERENCES users(id),
                FOREIGN KEY (assigned_by) REFERENCES users(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS cleanup_proofs (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id               INTEGER NOT NULL,

                image_path            TEXT NOT NULL,
                image_mime_type       TEXT,

                verification_status   TEXT NOT NULL DEFAULT 'pending'
                                      CHECK (
                                          verification_status IN (
                                              'pending',
                                              'approved',
                                              'rejected',
                                              'needs_review'
                                          )
                                      ),

                verification_confidence REAL,
                verification_reason     TEXT,

                uploaded_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at           TIMESTAMP,
                reviewed_by           INTEGER,

                FOREIGN KEY (task_id) REFERENCES cleanup_tasks(id),
                FOREIGN KEY (reviewed_by) REFERENCES users(id)
            )
        """)

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cleanup_tasks_cleaner "
            "ON cleanup_tasks(cleaner_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cleanup_tasks_status "
            "ON cleanup_tasks(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cleanup_proofs_task "
            "ON cleanup_proofs(task_id)"
        )

        # ------------------------------------------------------------
        # 5. Migration validation
        # ------------------------------------------------------------
        print("[5/5] Validating migration...")

        users_after = conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        complaints_after = conn.execute(
            "SELECT COUNT(*) FROM complaints"
        ).fetchone()[0]

        responses_after = conn.execute(
            "SELECT COUNT(*) FROM responses"
        ).fetchone()[0]

        policies_after = conn.execute(
            "SELECT COUNT(*) FROM policies"
        ).fetchone()[0]

        if users_after != len(users):
            raise RuntimeError(
                f"User count changed: before={len(users)}, after={users_after}"
            )

        if complaints_after != len(complaints):
            raise RuntimeError(
                f"Complaint count changed: before={len(complaints)}, "
                f"after={complaints_after}"
            )

        if responses_after != response_count:
            raise RuntimeError(
                f"Response count changed: before={response_count}, "
                f"after={responses_after}"
            )

        if policies_after != policy_count:
            raise RuntimeError(
                f"Policy count changed: before={policy_count}, "
                f"after={policies_after}"
            )

        conn.execute("""
            INSERT INTO schema_migrations (id)
            VALUES (?)
        """, (MIGRATION_ID,))

        conn.commit()

        print()
        print("[OK] Migration completed successfully.")
        print(f"     Database : {path}")
        print(f"     Users    : {users_after}")
        print(f"     Complaints: {complaints_after}")
        print(f"     Responses: {responses_after}")
        print(f"     Policies : {policies_after}")

    except Exception:
        conn.rollback()
        print("[ERROR] Migration failed. Transaction rolled back.")
        raise

    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        required=True,
        help="Path to the SQLite database to migrate",
    )
    args = parser.parse_args()

    migrate(args.db)
