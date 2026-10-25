"""
End-to-end integration test for the SmartTracker AI waste-cleanup workflow.

Lifecycle covered (all through the real FastAPI routes in backend/main.py):

    citizen registers -> admin authenticates -> admin creates a cleaner ->
    citizen submits a complaint with a before-image -> (mock) waste AI asks
    for admin review -> admin approves + assigns the cleaner -> cleaner sees
    the task -> cleaner starts it -> cleaner uploads an after-image ->
    (mock) cleanup verifier -> task/complaint enter "verification" ->
    admin approves the proof -> persisted final states are checked.

Plus authorization checks and invalid status transitions.

Safety rules enforced by this file
----------------------------------
* The ONLY database touched is backend/smarttracker_test.db. The live
  backend/smarttracker.db is never opened: the FastAPI connection dependency
  is overridden, db.DB_PATH is also pointed at the test DB as a second guard,
  and the test refuses to run if both paths resolve to the same file.
* The test DB must already exist with the application's schema. This file
  never creates, migrates or drops tables.
* Every identity uses a unique per-run email and a random per-run password.
  The test admin is inserted only into the test DB, using the project's own
  auth.hash_password. No existing account or secret is used.
* Teardown deletes ONLY rows reachable from this run's test users.
* Uploaded images go to a pytest temp directory, not backend/uploads/.
* No real AI module is imported or executed (see _import_main_with_ai_stubbed).
"""

import base64
import json
import os
import secrets
import sqlite3
import sys
import types
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_DB = BACKEND_DIR / "smarttracker_test.db"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Two tiny, genuinely valid JPEGs (8x8 px) with different content so the
# before/after hand-off to the verifier can be asserted byte for byte.
BEFORE_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABsSFBcUERsXFhceHBsgKEIrKCUlKFE6"
    "PTBCYFVlZF9VXVtqeJmBanGQc1tdhbWGkJ6jq62rZ4C8ybqmx5moq6T/2wBDARwe"
    "HigjKE4rK06kbl1upKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSk"
    "pKSkpKSkpKSkpKSkpKT/wAARCAAIAAgDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAA"
    "AAAAAAAAAAT/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAA"
    "AAAABP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AJgBiH//2Q=="
)
AFTER_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABsSFBcUERsXFhceHBsgKEIrKCUlKFE6"
    "PTBCYFVlZF9VXVtqeJmBanGQc1tdhbWGkJ6jq62rZ4C8ybqmx5moq6T/2wBDARwe"
    "HigjKE4rK06kbl1upKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSk"
    "pKSkpKSkpKSkpKSkpKT/wAARCAAIAAgDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAA"
    "AAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAA"
    "AAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AL4AP//Z"
)

# Columns the active routes in main.py / auth.py actually read or write.
REQUIRED_SCHEMA = {
    "users": {"id", "name", "email", "password_hash", "role"},
    "complaints": {
        "id", "tracking_id", "user_id", "name", "email", "complaint_text",
        "category", "department", "confidence_score", "extracted_entities",
        "latitude", "longitude", "location_type", "manual_address",
        "image_path", "image_mime_type", "waste_type",
        "waste_type_confidence", "severity", "severity_confidence",
        "ai_reasoning", "follow_up_question", "recurring_flag",
        "prior_reports_at_location", "escalate_to_authority",
        "needs_human_review", "review_reasons", "disposal_guidance",
        "status", "created_at", "updated_at",
    },
    "responses": {"id", "complaint_id", "ai_draft_response"},
    "cleanup_tasks": {
        "id", "complaint_id", "cleaner_id", "assigned_by", "status",
        "notes", "created_at", "updated_at", "completed_at",
    },
    "cleanup_proofs": {
        "id", "task_id", "image_path", "image_mime_type",
        "verification_status", "verification_confidence",
        "verification_reason", "uploaded_at", "reviewed_at", "reviewed_by",
    },
}

ROLES = {
    "admin": "admin",
    "citizen": "citizen",
    "citizen2": "citizen",
    "cleaner": "cleaner",
    "cleaner2": "cleaner",
}


# ---------------------------------------------------------------------------
# Test-database helpers (every connection goes to TEST_DB, nothing else)
# ---------------------------------------------------------------------------
def _connect(readonly=False):
    if readonly:
        conn = sqlite3.connect(f"{TEST_DB.as_uri()}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(TEST_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _one(sql, params=()):
    conn = _connect(readonly=True)
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _all(sql, params=()):
    conn = _connect(readonly=True)
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _marks(items):
    return ",".join("?" * len(items))


def _assert_test_db_ready():
    """Fail loudly (never fall back to the live DB) if the test DB is unusable."""
    if not TEST_DB.exists():
        pytest.fail(
            f"{TEST_DB} does not exist. Create it with the application's "
            "schema first. This test never falls back to backend/smarttracker.db."
        )
    problems = []
    conn = _connect(readonly=True)
    try:
        for table, needed in REQUIRED_SCHEMA.items():
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if not cols:
                problems.append(f"table '{table}' is missing")
            elif needed - cols:
                problems.append(f"table '{table}' lacks columns {sorted(needed - cols)}")
    finally:
        conn.close()
    if problems:
        pytest.fail(
            f"{TEST_DB.name} does not have the schema the active routes use: "
            + "; ".join(problems)
        )


def _delete_records_for(emails):
    """Delete only rows reachable from this run's unique test users (FK order)."""
    conn = _connect()
    try:
        user_ids = [
            r["id"]
            for r in conn.execute(
                f"SELECT id FROM users WHERE email IN ({_marks(emails)})", emails
            )
        ]
        if not user_ids:
            return
        complaint_ids = [
            r["id"]
            for r in conn.execute(
                f"SELECT id FROM complaints WHERE user_id IN ({_marks(user_ids)})",
                user_ids,
            )
        ]
        task_ids = [
            r["id"]
            for r in conn.execute(
                f"SELECT id FROM cleanup_tasks WHERE complaint_id IN ({_marks(complaint_ids)})"
                f" OR cleaner_id IN ({_marks(user_ids)})"
                f" OR assigned_by IN ({_marks(user_ids)})",
                complaint_ids + user_ids + user_ids,
            )
        ]
        conn.execute(
            f"DELETE FROM cleanup_proofs WHERE task_id IN ({_marks(task_ids)})"
            f" OR reviewed_by IN ({_marks(user_ids)})",
            task_ids + user_ids,
        )
        conn.execute(
            f"DELETE FROM responses WHERE complaint_id IN ({_marks(complaint_ids)})",
            complaint_ids,
        )
        conn.execute(
            f"DELETE FROM cleanup_tasks WHERE id IN ({_marks(task_ids)})", task_ids
        )
        conn.execute(
            f"DELETE FROM complaints WHERE id IN ({_marks(complaint_ids)})",
            complaint_ids,
        )
        conn.execute(f"DELETE FROM users WHERE id IN ({_marks(user_ids)})", user_ids)
        conn.commit()
    finally:
        conn.close()


def get_test_conn():
    """Same shape as db.get_conn, but bound to the disposable test DB."""
    conn = sqlite3.connect(TEST_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# AI doubles (patched onto the references main.py actually calls)
# ---------------------------------------------------------------------------
class FakeAI:
    """Deterministic stand-ins; call signatures mirror the call sites in main.py."""

    def __init__(self):
        self.waste_calls = []
        self.verify_calls = []

    def reset(self):
        self.waste_calls.clear()
        self.verify_calls.clear()

    # main.submit_complaint calls this with keyword arguments only.
    def process_waste_image(
        self,
        *,
        image_bytes,
        mime_type,
        additional_context,
        location,
        prior_reports_at_location,
    ):
        self.waste_calls.append(
            {
                "image_bytes": image_bytes,
                "mime_type": mime_type,
                "additional_context": additional_context,
                "location": location,
                "prior_reports_at_location": prior_reports_at_location,
            }
        )
        return {
            "waste_type": "mixed_waste",
            "waste_type_confidence": 0.91,
            "severity": "medium",
            "severity_confidence": 0.82,
            "reasoning": "Mocked waste analysis for workflow testing.",
            "follow_up_question": None,
            "recurring_flag": False,
            "prior_reports_at_location": prior_reports_at_location,
            "escalate_to_authority": False,
            "needs_human_review": True,
            "review_reasons": ["mock_requires_admin_review"],
            "disposal_guidance": "Mocked disposal guidance.",
        }

    # main.upload_cleanup_proof: verify_cleanup(before, after, before_mime=, after_mime=)
    def verify_cleanup(self, before_bytes, after_bytes, *, before_mime, after_mime):
        self.verify_calls.append(
            {
                "before_bytes": before_bytes,
                "after_bytes": after_bytes,
                "before_mime": before_mime,
                "after_mime": after_mime,
            }
        )
        return {
            "reasoning": "Mocked cleanup verification.",
            "unusable_reason": None,
            "admin_review_recommended": False,
            "after_image_usable": True,
            "cleanup_appears_complete": True,
            "confidence": 0.95,
        }


def _import_main_with_ai_stubbed():
    """
    Import backend/main.py without importing ai_pipeline, waste_pipeline or
    cleanup_verifier (they may load models at import time). If main is already
    imported by another test module the AI modules are already loaded, so
    nothing is stubbed. Returns (main_module, undo_callable).
    """
    import importlib

    added = []
    imported_here = "backend.main" not in sys.modules
    if imported_here:

        def refuse(name):
            def _refuse(*args, **kwargs):
                raise AssertionError(f"{name} must not run in the workflow test")

            return _refuse

        stubs = {
            "backend.ai_pipeline": (
                "classify_and_extract",
                "generate_draft_response",
                "entities_to_json",
                "process_waste_image",
                "verify_cleanup",
            ),
        }
        for module_name, names in stubs.items():
            if module_name in sys.modules:
                continue
            stub = types.ModuleType(module_name)
            for name in names:
                setattr(stub, name, refuse(f"{module_name}.{name}"))
            sys.modules[module_name] = stub
            added.append(module_name)

    main = importlib.import_module("backend.main")
    assert Path(main.__file__).resolve().parent == BACKEND_DIR, (
        f"imported {main.__file__}, expected a module inside {BACKEND_DIR}"
    )

    def undo():
        for module_name in added:
            sys.modules.pop(module_name, None)
        if imported_here:
            sys.modules.pop("backend.main", None)

    return main, undo


# ---------------------------------------------------------------------------
# Shared environment (module scope: bcrypt hashing is the slow part, so the
# five identities are created once and reused by every test below)
# ---------------------------------------------------------------------------
def _expect(response, status_code):
    assert response.status_code == status_code, (
        f"{response.request.method} {response.request.url.path} -> "
        f"{response.status_code} (expected {status_code}): {response.text}"
    )
    return response


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    _assert_test_db_ready()

    from backend import auth, db

    assert TEST_DB.name == "smarttracker_test.db"
    assert TEST_DB.resolve() != Path(db.DB_PATH).resolve(), (
        "test DB and live DB resolve to the same file; refusing to run"
    )

    main, undo_import = _import_main_with_ai_stubbed()
    run_id = uuid.uuid4().hex[:10]
    emails = {role: f"wf-{role}-{run_id}@example.com" for role in ROLES}
    passwords = {role: secrets.token_urlsafe(12) for role in ROLES}
    upload_root = tmp_path_factory.mktemp("workflow_uploads")
    ai = FakeAI()

    previous_override = main.app.dependency_overrides.get(db.get_conn)
    from backend.database import _create_database_engine, get_db
    from sqlalchemy.orm import sessionmaker

    test_engine = _create_database_engine(
        f"sqlite:///{TEST_DB.resolve().as_posix()}",
        connect_args={"check_same_thread": False},
    )
    test_session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )

    def override_get_db():
        session = test_session_factory()
        try:
            yield session
        finally:
            session.close()

    previous_db_override = main.app.dependency_overrides.get(get_db)
    try:
        with pytest.MonkeyPatch.context() as mp:
            # Second guard: even code that bypassed the override would hit the test DB.
            mp.setattr(db, "DB_PATH", TEST_DB)
            main.app.dependency_overrides[db.get_conn] = get_test_conn
            main.app.dependency_overrides[get_db] = override_get_db

            # The patched connection must really be the test DB.
            gen = get_test_conn()
            probe = next(gen)
            try:
                attached = probe.execute("PRAGMA database_list").fetchone()["file"]
            finally:
                gen.close()
            assert os.path.samefile(attached, TEST_DB)

            # Keep uploaded images out of backend/uploads/.
            mp.setattr(main, "PROJECT_ROOT", upload_root)
            mp.setattr(
                main, "UPLOAD_DIR", upload_root / "backend" / "uploads" / "complaints"
            )
            mp.setattr(
                main,
                "CLEANUP_PROOF_UPLOAD_DIR",
                upload_root / "backend" / "uploads" / "cleanup_proofs",
            )

            # Patch the exact references the routes call.
            mp.setattr(main, "process_waste_image", ai.process_waste_image)
            mp.setattr(main, "verify_cleanup", ai.verify_cleanup)

            # Test admin: inserted only into the test DB with the project's hasher.
            conn = _connect()
            try:
                cur = conn.execute(
                    "INSERT INTO users (name, email, password_hash, role)"
                    " VALUES (?, ?, ?, 'admin')",
                    (
                        "Workflow Admin",
                        emails["admin"],
                        auth.hash_password(passwords["admin"]),
                    ),
                )
                conn.commit()
                ids = {"admin": cur.lastrowid}
            finally:
                conn.close()

            with TestClient(main.app) as client:

                def login(role):
                    resp = _expect(
                        client.post(
                            "/auth/login",
                            json={"email": emails[role], "password": passwords[role]},
                        ),
                        200,
                    )
                    return {"Authorization": f"Bearer {resp.json()['access_token']}"}

                headers = {"admin": login("admin")}
                registered = {}

                for role in ("citizen", "citizen2"):
                    resp = _expect(
                        client.post(
                            "/auth/register",
                            json={
                                "name": f"Workflow {role}",
                                "email": emails[role],
                                "password": passwords[role],
                            },
                        ),
                        201,
                    )
                    registered[role] = resp.json()
                    ids[role] = registered[role]["id"]

                for role in ("cleaner", "cleaner2"):
                    resp = _expect(
                        client.post(
                            "/admin/cleaners",
                            headers=headers["admin"],
                            json={
                                "name": f"Workflow {role}",
                                "email": emails[role],
                                "password": passwords[role],
                            },
                        ),
                        201,
                    )
                    registered[role] = resp.json()
                    ids[role] = registered[role]["id"]

                for role in ("citizen", "citizen2", "cleaner", "cleaner2"):
                    headers[role] = login(role)

                yield types.SimpleNamespace(
                    client=client,
                    main=main,
                    ai=ai,
                    run_id=run_id,
                    emails=emails,
                    passwords=passwords,
                    ids=ids,
                    headers=headers,
                    registered=registered,
                    upload_root=upload_root,
                )
    finally:
        try:
            _delete_records_for(list(emails.values()))
        finally:
            if previous_override is None:
                main.app.dependency_overrides.pop(db.get_conn, None)
            else:
                main.app.dependency_overrides[db.get_conn] = previous_override
            if previous_db_override is None:
                main.app.dependency_overrides.pop(get_db, None)
            else:
                main.app.dependency_overrides[get_db] = previous_db_override
            undo_import()


@pytest.fixture(autouse=True)
def _reset_ai_calls(env):
    env.ai.reset()
    yield


# ---------------------------------------------------------------------------
# Workflow helpers
# ---------------------------------------------------------------------------
def _submit(env, label, role="citizen"):
    """Submit a complaint at a unique manual address (so prior reports == 0)."""
    address = f"Workflow test address {env.run_id} {label}"
    response = env.client.post(
        "/complaints",
        headers=env.headers[role],
        data={
            "complaint_text": f"Workflow test waste complaint ({label})",
            "location_type": "manual",
            "manual_address": address,
        },
        files={"image": ("before.jpg", BEFORE_JPEG, "image/jpeg")},
    )
    return response, address


def _submit_ok(env, label, role="citizen"):
    return _expect(_submit(env, label, role)[0], 201).json()


def _assign(env, complaint_id, cleaner="cleaner", notes="Integration test assignment"):
    resp = _expect(
        env.client.post(
            f"/admin/complaints/{complaint_id}/review",
            headers=env.headers["admin"],
            json={
                "decision": "approve_cleanup",
                "cleaner_id": env.ids[cleaner],
                "notes": notes,
            },
        ),
        200,
    )
    return resp.json()["cleanup_task"]["id"]


def _start(env, task_id, role="cleaner"):
    return env.client.post(f"/cleaner/tasks/{task_id}/start", headers=env.headers[role])


def _proof(env, task_id, role="cleaner", content_type="image/jpeg", data=AFTER_JPEG):
    return env.client.post(
        f"/cleaner/tasks/{task_id}/proof",
        headers=env.headers[role],
        files={"image": ("after.jpg", data, content_type)},
    )


def _verify(env, task_id, decision="approve", notes=None):
    return env.client.post(
        f"/admin/cleanup-tasks/{task_id}/verify",
        headers=env.headers["admin"],
        json={"decision": decision, "notes": notes},
    )


def _statuses(complaint_id, task_id):
    complaint = _one("SELECT status FROM complaints WHERE id = ?", (complaint_id,))
    task = _one("SELECT status FROM cleanup_tasks WHERE id = ?", (task_id,))
    return complaint["status"], task["status"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_identities_are_created_and_authenticated(env):
    """Steps 1-3: citizen registered, admin authenticated, cleaner created + authenticated."""
    assert env.registered["citizen"]["role"] == "citizen"
    assert env.registered["citizen"]["email"] == env.emails["citizen"]
    assert env.registered["cleaner"]["role"] == "cleaner"

    for role, expected_role in ROLES.items():
        row = _one(
            "SELECT role, password_hash FROM users WHERE id = ?", (env.ids[role],)
        )
        assert row["role"] == expected_role
        assert row["password_hash"] != env.passwords[role]  # stored hashed

    _expect(
        env.client.post(
            "/auth/register",
            json={
                "name": "Duplicate Citizen",
                "email": env.emails["citizen"],
                "password": secrets.token_urlsafe(12),
            },
        ),
        400,
    )
    _expect(
        env.client.post(
            "/auth/login",
            json={"email": env.emails["citizen"], "password": secrets.token_urlsafe(12)},
        ),
        401,
    )


def test_complete_cleanup_workflow(env):
    """Steps 4-13: complaint -> review -> assignment -> cleanup -> verified & resolved."""
    ai = env.ai

    # 4-5. Citizen submits a complaint with a before-image; the mocked waste AI
    # asks for admin review.
    response, address = _submit(env, "lifecycle")
    complaint = _expect(response, 201).json()
    complaint_id = complaint["id"]

    assert complaint["tracking_id"].startswith("TRK-")
    assert complaint["user_id"] == env.ids["citizen"]
    assert complaint["status"] == "awaiting_review"
    # Values below come from the mock, so they also prove the mock actually ran
    # (main.py swallows pipeline exceptions and would otherwise fall back silently).
    assert complaint["waste_type"] == "mixed_waste"
    assert complaint["severity"] == "medium"
    assert complaint["needs_human_review"] is True
    assert complaint["escalate_to_authority"] is False
    assert complaint["review_reasons"] == json.dumps(["mock_requires_admin_review"])
    assert complaint["prior_reports_at_location"] == 0
    assert complaint["image_mime_type"] == "image/jpeg"
    assert (env.upload_root / complaint["image_path"]).read_bytes() == BEFORE_JPEG

    assert len(ai.waste_calls) == 1
    waste_call = ai.waste_calls[0]
    assert waste_call["image_bytes"] == BEFORE_JPEG
    assert waste_call["mime_type"] == "image/jpeg"
    assert waste_call["location"] == {"address": address}
    assert waste_call["prior_reports_at_location"] == 0

    queue = _expect(
        env.client.get("/admin/queue", headers=env.headers["admin"]), 200
    ).json()
    assert complaint_id in [item["id"] for item in queue]

    # 6. Admin approves the complaint and assigns the cleaner.
    review = _expect(
        env.client.post(
            f"/admin/complaints/{complaint_id}/review",
            headers=env.headers["admin"],
            json={
                "decision": "approve_cleanup",
                "cleaner_id": env.ids["cleaner"],
                "notes": "Integration test assignment",
            },
        ),
        200,
    ).json()
    task_id = review["cleanup_task"]["id"]
    assert review["status"] == "assigned"
    assert review["cleanup_task"]["status"] == "assigned"
    assert review["cleanup_task"]["cleaner_id"] == env.ids["cleaner"]
    assert review["cleanup_task"]["assigned_by"] == env.ids["admin"]
    assert _one(
        "SELECT status, needs_human_review FROM complaints WHERE id = ?",
        (complaint_id,),
    ) == {"status": "assigned", "needs_human_review": 0}

    # 7. The cleaner sees the assigned task; the other cleaner does not.
    tasks = _expect(
        env.client.get("/cleaner/tasks", headers=env.headers["cleaner"]), 200
    ).json()
    task = next(t for t in tasks if t["complaint_id"] == complaint_id)
    assert task["id"] == task_id
    assert task["status"] == "assigned"
    assert task["complaint_status"] == "assigned"
    assert task["tracking_id"] == complaint["tracking_id"]
    assert task["waste_type"] == "mixed_waste"
    other_tasks = _expect(
        env.client.get("/cleaner/tasks", headers=env.headers["cleaner2"]), 200
    ).json()
    assert task_id not in [t["id"] for t in other_tasks]

    # 8. The cleaner starts the task.
    started = _expect(_start(env, task_id), 200).json()
    assert started["status"] == "in_progress"
    assert _statuses(complaint_id, task_id) == ("in_progress", "in_progress")

    # 9-11. After-image upload; mocked verifier; task + complaint enter verification.
    proof_response = _expect(_proof(env, task_id), 200).json()
    assert proof_response["task_status"] == "verification"
    assert proof_response["complaint_status"] == "verification"
    assert proof_response["ai_verification"] == {
        "after_image_usable": True,
        "cleanup_appears_complete": True,
        "confidence": 0.95,
        "admin_review_recommended": False,
    }
    assert proof_response["proof"]["verification_status"] == "pending"
    assert proof_response["proof"]["verification_confidence"] == 0.95
    assert proof_response["proof"]["verification_reason"] == "Mocked cleanup verification."
    assert _statuses(complaint_id, task_id) == ("verification", "verification")

    assert len(ai.verify_calls) == 1
    verify_call = ai.verify_calls[0]
    assert verify_call["before_bytes"] == BEFORE_JPEG
    assert verify_call["after_bytes"] == AFTER_JPEG
    assert verify_call["before_mime"] == "image/jpeg"
    assert verify_call["after_mime"] == "image/jpeg"

    admin_view = _expect(
        env.client.get("/admin/cleanup-tasks", headers=env.headers["admin"]), 200
    ).json()
    listed = next(t for t in admin_view if t["id"] == task_id)
    assert listed["verification_status"] == "pending"
    assert listed["cleaner_email"] == env.emails["cleaner"]

    # 12. Admin approves the cleanup proof.
    verified = _expect(
        _verify(env, task_id, "approve", "Integration test approval"), 200
    ).json()
    assert verified["admin_decision"] == "approve"
    assert verified["task"]["status"] == "completed"
    assert verified["task"]["completed_at"] is not None
    assert verified["proof"]["verification_status"] == "approved"
    assert verified["proof"]["reviewed_by"] == env.ids["admin"]
    assert verified["complaint"] == {"id": complaint_id, "status": "resolved"}

    # 13. Persisted final states, read through an independent read-only connection.
    task_row = _one(
        "SELECT status, completed_at, cleaner_id, assigned_by FROM cleanup_tasks WHERE id = ?",
        (task_id,),
    )
    complaint_row = _one("SELECT status FROM complaints WHERE id = ?", (complaint_id,))
    proofs = _all("SELECT * FROM cleanup_proofs WHERE task_id = ? ORDER BY id", (task_id,))

    assert task_row["status"] == "completed"
    assert task_row["completed_at"] is not None
    assert task_row["cleaner_id"] == env.ids["cleaner"]
    assert task_row["assigned_by"] == env.ids["admin"]
    assert complaint_row["status"] == "resolved"
    assert len(proofs) == 1
    assert proofs[0]["verification_status"] == "approved"
    assert proofs[0]["reviewed_by"] == env.ids["admin"]
    assert proofs[0]["reviewed_at"] is not None
    assert proofs[0]["verification_reason"].endswith("Admin approval: Integration test approval")
    assert (env.upload_root / proofs[0]["image_path"]).read_bytes() == AFTER_JPEG

    # The citizen sees the resolved status; a second approval is rejected.
    seen = _expect(
        env.client.get(f"/complaints/{complaint_id}", headers=env.headers["citizen"]),
        200,
    ).json()
    assert seen["status"] == "resolved"
    _expect(_verify(env, task_id, "approve"), 409)
    assert _statuses(complaint_id, task_id) == ("resolved", "completed")


def test_authentication_and_role_boundaries(env):
    client, headers = env.client, env.headers

    # No / bad credentials.
    _expect(client.get("/admin/queue"), 401)
    _expect(client.get("/cleaner/tasks"), 401)
    _expect(client.get("/admin/queue", headers={"Authorization": "Bearer not-a-jwt"}), 401)

    # Citizen is not an admin or a cleaner.
    _expect(client.get("/admin/queue", headers=headers["citizen"]), 403)
    _expect(client.get("/cleaner/tasks", headers=headers["citizen"]), 403)
    _expect(
        client.post(
            "/admin/cleaners",
            headers=headers["citizen"],
            json={
                "name": "Nope Nope",
                "email": f"wf-nope-{env.run_id}@example.com",
                "password": secrets.token_urlsafe(12),
            },
        ),
        403,
    )
    assert _one(
        "SELECT id FROM users WHERE email = ?", (f"wf-nope-{env.run_id}@example.com",)
    ) is None

    # Cleaner may not use admin endpoints.
    _expect(client.get("/admin/cleanup-tasks", headers=headers["cleaner"]), 403)
    _expect(
        client.post(
            "/admin/complaints/1/review",
            headers=headers["cleaner"],
            json={"decision": "reject"},
        ),
        403,
    )
    _expect(
        client.post(
            "/admin/cleanup-tasks/1/verify",
            headers=headers["cleaner"],
            json={"decision": "approve"},
        ),
        403,
    )

    # Admin is not a cleaner.
    _expect(client.get("/cleaner/tasks", headers=headers["admin"]), 403)


def test_complaint_visibility_and_input_validation(env):
    complaint = _submit_ok(env, "visibility")
    complaint_id = complaint["id"]

    # Owner and admin can read it; another citizen cannot.
    _expect(env.client.get(f"/complaints/{complaint_id}", headers=env.headers["citizen"]), 200)
    _expect(env.client.get(f"/complaints/{complaint_id}", headers=env.headers["admin"]), 200)
    _expect(env.client.get(f"/complaints/{complaint_id}", headers=env.headers["citizen2"]), 403)
    _expect(env.client.get("/complaints/2147483647", headers=env.headers["admin"]), 404)

    # Rejected uploads never reach the AI and are not persisted.
    ai_calls_before = len(env.ai.waste_calls)
    before_count = _one(
        "SELECT COUNT(*) AS n FROM complaints WHERE user_id = ?", (env.ids["citizen"],)
    )["n"]
    form = {
        "complaint_text": "Should be rejected",
        "location_type": "manual",
        "manual_address": f"Workflow test address {env.run_id} rejected",
    }
    _expect(
        env.client.post(
            "/complaints",
            headers=env.headers["citizen"],
            data=form,
            files={"image": ("notes.txt", b"not an image", "text/plain")},
        ),
        400,
    )
    _expect(
        env.client.post(
            "/complaints",
            headers=env.headers["citizen"],
            data=form,
            files={"image": ("empty.jpg", b"", "image/jpeg")},
        ),
        400,
    )
    _expect(
        env.client.post("/complaints", headers=env.headers["citizen"], data=form), 422
    )
    assert len(env.ai.waste_calls) == ai_calls_before
    after_count = _one(
        "SELECT COUNT(*) AS n FROM complaints WHERE user_id = ?", (env.ids["citizen"],)
    )["n"]
    assert after_count == before_count


def test_admin_review_rules(env):
    complaint_id = _submit_ok(env, "review-rules")["id"]
    review_url = f"/admin/complaints/{complaint_id}/review"
    admin = env.headers["admin"]

    _expect(env.client.post(review_url, headers=admin, json={"decision": "bogus"}), 422)
    _expect(
        env.client.post(review_url, headers=admin, json={"decision": "approve_cleanup"}), 400
    )
    _expect(
        env.client.post(
            review_url,
            headers=admin,
            json={"decision": "approve_cleanup", "cleaner_id": env.ids["citizen"]},
        ),
        400,
    )
    _expect(
        env.client.post(
            "/admin/complaints/2147483647/review", headers=admin, json={"decision": "reject"}
        ),
        404,
    )
    assert _one("SELECT id FROM cleanup_tasks WHERE complaint_id = ?", (complaint_id,)) is None

    # Rejecting keeps the complaint in review and records the reason.
    rejected = _expect(
        env.client.post(
            review_url, headers=admin, json={"decision": "reject", "notes": "needs a closer look"}
        ),
        200,
    ).json()
    assert rejected == {
        "complaint_id": complaint_id,
        "status": "awaiting_review",
        "cleanup_task": None,
    }
    row = _one("SELECT status, review_reasons FROM complaints WHERE id = ?", (complaint_id,))
    assert row["status"] == "awaiting_review"
    assert "admin_rejected_waste_review: needs a closer look" in row["review_reasons"]

    # Approving afterwards works once; a second approval conflicts.
    task_id = _assign(env, complaint_id)
    _expect(
        env.client.post(
            review_url,
            headers=admin,
            json={"decision": "approve_cleanup", "cleaner_id": env.ids["cleaner2"]},
        ),
        409,
    )
    tasks = _all("SELECT id, cleaner_id FROM cleanup_tasks WHERE complaint_id = ?", (complaint_id,))
    assert tasks == [{"id": task_id, "cleaner_id": env.ids["cleaner"]}]


def test_cleanup_task_transition_rules(env):
    complaint_id = _submit_ok(env, "transition-rules")["id"]
    task_id = _assign(env, complaint_id)
    ai = env.ai

    # Another cleaner cannot see or act on the task.
    _expect(_start(env, task_id, role="cleaner2"), 404)
    _expect(_proof(env, task_id, role="cleaner2"), 404)

    # Not started yet: no proof upload, nothing for the admin to verify.
    _expect(_proof(env, task_id), 409)
    _expect(_verify(env, task_id), 409)
    assert ai.verify_calls == []
    assert _statuses(complaint_id, task_id) == ("assigned", "assigned")

    # Start once; starting again conflicts.
    _expect(_start(env, task_id), 200)
    _expect(_start(env, task_id), 409)

    # In progress with no proof: still nothing to verify; bad proof types are rejected.
    _expect(_verify(env, task_id), 409)
    _expect(_proof(env, task_id, content_type="text/plain", data=b"nope"), 400)
    _expect(_proof(env, task_id, data=b""), 400)
    assert ai.verify_calls == []
    assert _all("SELECT id FROM cleanup_proofs WHERE task_id = ?", (task_id,)) == []

    # A proof moves both records to verification; a second upload conflicts.
    _expect(_proof(env, task_id), 200)
    assert _statuses(complaint_id, task_id) == ("verification", "verification")
    _expect(_proof(env, task_id), 409)
    assert len(ai.verify_calls) == 1

    # Rejecting the proof sends the work back to the cleaner and cannot be repeated.
    rejected = _expect(_verify(env, task_id, "reject", "still messy"), 200).json()
    assert rejected["admin_decision"] == "reject"
    assert rejected["task"]["status"] == "assigned"
    assert rejected["proof"]["verification_status"] == "rejected"
    assert rejected["proof"]["verification_reason"].endswith("Admin rejection: still messy")
    assert rejected["complaint"]["status"] == "in_progress"
    assert _statuses(complaint_id, task_id) == ("in_progress", "assigned")
    _expect(_verify(env, task_id, "reject"), 409)
    _expect(_verify(env, task_id, "bogus"), 422)
