# tests/test_seed_task_events.py
# Seeded cleanup-task lifecycle events (Step 6).
#
# Covers:
#   - seeded tasks that represent work under way / completed carry a
#     `started_at` timestamp and exactly one matching `task_started` event
#   - seeded tasks that are merely assigned keep neither
#   - the seeded event chain is chronologically consistent and agrees with the
#     task/proof rows it references
#   - replaying the chain never produces a second start event
#   - the real cleaner start event records the task's ACTUAL previous status
#
# Isolated temporary-SQLite setup: the seeder is re-pointed at a throwaway
# database, so neither the real smarttracker.db nor the shared in-memory test
# database is ever written to.

import random
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend import seed_data  # noqa: E402
from backend.database import _create_database_engine, get_db, run_migrations  # noqa: E402
from backend.models import CleanupProof, CleanupTask, Complaint, EventLog, User  # noqa: E402
from backend.main import app  # noqa: E402
from backend.routers.auth import create_access_token  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = _create_database_engine(
        f"sqlite:///{tmp_path / 'seed_task_events.db'}",
        connect_args={"check_same_thread": False},
    )
    run_migrations(target_engine=engine)
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    # --- the seeder writes to the temporary database only ---
    monkeypatch.setattr(seed_data, "_InjectedSession", None, raising=False)
    monkeypatch.setattr(seed_data, "_InjectedEngine", None, raising=False)
    monkeypatch.setattr(seed_data, "SessionLocal", session_factory, raising=True)
    monkeypatch.setattr(seed_data, "engine", engine, raising=True)

    # --- the API serves the same temporary database ---
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        yield session_factory, client
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        client.close()
        engine.dispose()


def _seed(session_factory, complaints=60, cleaners=3, seed=11):
    summary = seed_data.seed_database(
        number_of_complaints=complaints,
        number_of_cleaners=cleaners,
        seed=seed,
    )
    assert summary["complaints"] == complaints
    return summary


def _events_for(db, case_id):
    return (
        db.query(EventLog)
        .filter(EventLog.case_id == case_id)
        .order_by(EventLog.event_id.asc())
        .all()
    )


def _start_events(db, case_id):
    return (
        db.query(EventLog)
        .filter(EventLog.case_id == case_id, EventLog.activity == "task_started")
        .all()
    )


# ---------------------------------------------------------------------------
# Seeded task start timestamps and events
# ---------------------------------------------------------------------------
def test_seeded_started_tasks_have_started_at_and_one_task_started_event(env):
    session_factory, _ = env
    _seed(session_factory)

    with session_factory() as db:
        tasks = db.query(CleanupTask).all()
        started = [t for t in tasks if t.proofs]
        assert started, "expected seeded tasks whose work actually happened"

        for task in started:
            assert task.started_at is not None
            events = _start_events(db, task.complaint.tracking_id)
            assert len(events) == 1
            # The event carries exactly the task's start timestamp.
            assert events[0].timestamp == task.started_at
            assert events[0].old_value == "assigned"
            assert events[0].new_value == "in_progress"


def test_seeded_assigned_only_tasks_have_no_start_timestamp_or_event(env):
    session_factory, _ = env
    _seed(session_factory)

    with session_factory() as db:
        tasks = db.query(CleanupTask).all()
        not_started = [t for t in tasks if not t.proofs]
        assert not_started, "expected seeded tasks that were only assigned"

        for task in not_started:
            assert task.started_at is None
            assert task.status == "assigned"
            assert _start_events(db, task.complaint.tracking_id) == []


def test_seeded_event_timestamps_are_chronologically_consistent(env):
    session_factory, _ = env
    _seed(session_factory)

    with session_factory() as db:
        complaints = (
            db.query(Complaint).filter(Complaint.source == "seed").all()
        )
        assert complaints
        checked_started = 0

        for complaint in complaints:
            events = {e.activity: e for e in _events_for(db, complaint.tracking_id)}

            assert "complaint_created" in events
            created = events["complaint_created"].timestamp

            if "dispatch_decided" not in events:
                # Guidance-resolved case: no dispatch, no task, no start.
                assert "cleaner_assigned" not in events
                assert "task_started" not in events
                continue

            assert created <= events["dispatch_decided"].timestamp
            assert events["dispatch_decided"].timestamp <= events["cleaner_assigned"].timestamp

            if "task_started" not in events:
                continue
            checked_started += 1

            started = events["task_started"].timestamp
            task = (
                db.query(CleanupTask)
                .filter(CleanupTask.complaint_id == complaint.id)
                .one()
            )

            # Assignment never happens after the start.
            assert events["cleaner_assigned"].timestamp <= started
            # The event and the row agree on the assignment time.
            assert task.assigned_at == events["cleaner_assigned"].timestamp
            assert task.started_at == started

            if "proof_submitted" in events:
                submitted = events["proof_submitted"].timestamp
                # The start never happens after the first proof upload.
                assert started <= submitted
                first_proof = (
                    db.query(CleanupProof)
                    .filter(CleanupProof.task_id == task.id)
                    .order_by(CleanupProof.uploaded_at.asc())
                    .first()
                )
                assert first_proof.uploaded_at == submitted

            if "proof_verified" in events:
                verified = events["proof_verified"].timestamp
                assert events["proof_submitted"].timestamp <= verified
                # completed_at remains the admin-verification timestamp.
                assert task.completed_at == verified
                assert verified <= events["complaint_resolved"].timestamp

        assert checked_started > 0


def test_seeded_tasks_never_get_a_physical_finish_timestamp(env):
    """completed_at stays the verification time; nothing else is invented."""
    session_factory, _ = env
    _seed(session_factory)

    with session_factory() as db:
        for task in db.query(CleanupTask).all():
            if task.status == "verified":
                assert task.completed_at is not None
                assert task.started_at is not None
                assert task.started_at <= task.completed_at
            else:
                # 'assigned' (never started) and 'rejected' (not verified)
                # tasks have no completion timestamp at all.
                assert task.completed_at is None


def _relative_timeline(session_factory):
    """Per-case timeline expressed as offsets from the complaint creation time.

    Absolute timestamps are anchored to the wall clock at seed time (the
    project's existing convention, so seeded data stays recent). The offsets
    and the random choices behind them must be reproducible for a fixed seed.
    """
    rows = []
    with session_factory() as db:
        for complaint in (
            db.query(Complaint).order_by(Complaint.id.asc()).all()
        ):
            task = (
                db.query(CleanupTask)
                .filter(CleanupTask.complaint_id == complaint.id)
                .first()
            )
            proofs = (
                db.query(CleanupProof)
                .filter(CleanupProof.task_id == task.id)
                .order_by(CleanupProof.uploaded_at.asc())
                .all()
                if task
                else []
            )
            events = {e.activity: e for e in _events_for(db, complaint.tracking_id)}
            base = complaint.created_at

            def offset(value):
                return None if value is None else (value - base).total_seconds()

            rows.append((
                complaint.waste_type,
                complaint.quantity_severity,
                complaint.address_text,
                task.status if task else None,
                offset(task.assigned_at) if task else None,
                offset(task.started_at) if task else None,
                [offset(p.uploaded_at) for p in proofs],
                offset(task.completed_at) if task else None,
                offset(events["task_started"].timestamp) if "task_started" in events else None,
                offset(events["proof_submitted"].timestamp) if "proof_submitted" in events else None,
            ))
    return rows


def test_seeding_is_deterministic_for_a_fixed_seed(env):
    session_factory, _ = env
    _seed(session_factory, complaints=30, cleaners=2, seed=21)
    first = _relative_timeline(session_factory)

    _seed(session_factory, complaints=30, cleaners=2, seed=21)
    second = _relative_timeline(session_factory)

    assert len(second) == 2 * len(first)
    # The same seed reproduces the same timeline (the second run appends new
    # cases with the same relative shape).
    assert second[: len(first)] == first


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------
def test_repeated_seeding_does_not_duplicate_start_events(env):
    session_factory, _ = env
    _seed(session_factory, complaints=40, cleaners=2, seed=5)
    _seed(session_factory, complaints=40, cleaners=2, seed=5)

    with session_factory() as db:
        tasks = db.query(CleanupTask).all()
        assert tasks
        for task in tasks:
            if task.proofs:
                assert len(_start_events(db, task.complaint.tracking_id)) == 1

        # One start event per case that has one — never two.
        cases_with_start = db.query(EventLog.case_id).filter(
            EventLog.activity == "task_started"
        ).distinct().count()
        total_start_events = db.query(EventLog).filter(
            EventLog.activity == "task_started"
        ).count()
        assert total_start_events == cases_with_start


def test_replaying_the_event_chain_adds_no_second_start_event(env):
    """The idempotency guard: the same case never gets two start events."""
    session_factory, _ = env
    _seed(session_factory, complaints=30, cleaners=2, seed=3)

    with session_factory() as db:
        task = (
            db.query(CleanupTask)
            .filter(CleanupTask.started_at.isnot(None))
            .first()
        )
        assert task is not None
        complaint = task.complaint
        proof_times = [
            p.uploaded_at
            for p in db.query(CleanupProof)
            .filter(CleanupProof.task_id == task.id)
            .order_by(CleanupProof.uploaded_at.asc())
            .all()
        ]
        assert proof_times

        assert len(_start_events(db, complaint.tracking_id)) == 1

        seed_data._seed_events(
            db,
            complaint,
            complaint.user_id,
            random.Random(1),
            cleaner_id=task.assigned_cleaner_id,
            with_task=True,
            with_proofs=True,
            verified=False,
            assigned_at=task.assigned_at,
            started_at=task.started_at,
            proof_times=proof_times,
            verify_at=None,
        )
        db.commit()

        assert len(_start_events(db, complaint.tracking_id)) == 1


def test_clearing_seeded_data_removes_the_start_events(env):
    """The existing wipe convention also removes the new start events."""
    session_factory, _ = env
    _seed(session_factory, complaints=30, cleaners=2, seed=3)

    with session_factory() as db:
        assert db.query(EventLog).filter(
            EventLog.activity == "task_started"
        ).count() > 0

    removed = seed_data.clear_seeded_data()

    with session_factory() as db:
        assert removed == 30
        assert db.query(EventLog).filter(
            EventLog.activity == "task_started"
        ).count() == 0
        assert db.query(CleanupTask).count() == 0


# ---------------------------------------------------------------------------
# The real (non-seeded) start event
# ---------------------------------------------------------------------------
def test_real_start_event_records_the_actual_previous_status(env):
    session_factory, client = env
    with session_factory() as db:
        cleaner = User(
            name="Cleaner",
            email="real-start-cleaner@example.com",
            password_hash="hash",
            role="cleaner",
        )
        db.add(cleaner)
        db.flush()
        complaint = Complaint(
            user_id=None,
            name="Citizen",
            email="citizen@example.com",
            complaint_text="Waste left beside the gate.",
            status="in_progress",
        )
        db.add(complaint)
        db.flush()
        task = CleanupTask(
            complaint_id=complaint.id,
            assigned_cleaner_id=cleaner.id,
            status="assigned",
        )
        db.add(task)
        db.commit()
        cleaner_id = cleaner.id
        task_id = task.task_id
        tracking_id = complaint.tracking_id

    headers = {"Authorization": f"Bearer {create_access_token(cleaner_id, 'cleaner')}"}

    assert client.post(f"/cleaner/tasks/{task_id}/start", headers=headers).status_code == 200
    assert client.post(f"/cleaner/tasks/{task_id}/start", headers=headers).status_code == 200

    with session_factory() as db:
        events = _start_events(db, tracking_id)
        assert len(events) == 2
        # The first start really came from 'assigned'.
        assert events[0].old_value == "assigned"
        assert events[0].new_value == "in_progress"
        # The repeat start came from 'in_progress' — not from 'assigned'.
        assert events[1].old_value == "in_progress"
        assert events[1].new_value == "in_progress"

        task = db.query(CleanupTask).filter(CleanupTask.task_id == task_id).one()
        assert task.started_at is not None
