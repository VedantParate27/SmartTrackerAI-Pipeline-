import sys
from pathlib import Path

import pytest
from sqlalchemy import Column, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.database import _create_database_engine, run_migrations, Base as RealBase
from backend.models import (
    Complaint,
    CleanupTask,
    Location,
    User,
    cleaner_locations,
)


def test_sqlite_migration_on_legacy_database(tmp_path):
    db_file = tmp_path / "legacy_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    # Create old/legacy complaints table without new waste/location columns
    LegacyBase = declarative_base()

    class LegacyComplaint(LegacyBase):
        __tablename__ = "complaints"
        id = Column(Integer, primary_key=True, index=True)
        tracking_id = Column(String(50), unique=True)
        user_id = Column(Integer, nullable=True)
        name = Column(String(100))
        email = Column(String(150))
        phone = Column(String(20), nullable=True)
        complaint_text = Column(Text)
        language = Column(String(10), default="en")
        priority = Column(String(20), default="medium")
        status = Column(String(30), default="pending")
        department = Column(String(100), nullable=True)


    LegacyBase.metadata.create_all(bind=engine)

    # Insert a pre-existing row into legacy database
    Session = sessionmaker(bind=engine)
    with Session() as db:
        old_comp = LegacyComplaint(
            tracking_id="TRK-OLD001",
            name="Old User",
            email="old@example.com",
            complaint_text="Old streetlight complaint from before migration",
            status="pending",
        )
        db.add(old_comp)
        db.commit()

    # Verify new columns do not exist yet
    inspector = inspect(engine)
    cols_before = {c["name"] for c in inspector.get_columns("complaints")}
    assert "waste_type" not in cols_before
    assert "latitude" not in cols_before

    # Run idempotent migration
    run_migrations(target_engine=engine)

    # Run migration a second time to verify idempotency
    run_migrations(target_engine=engine)

    # Verify all columns exist now
    inspector_after = inspect(engine)
    cols_after = {c["name"] for c in inspector_after.get_columns("complaints")}
    assert "waste_type" in cols_after
    assert "latitude" in cols_after
    assert "intervention_required" in cols_after
    assert "location_id" in cols_after
    assert "cleanup_tasks" in inspector_after.get_table_names()
    assert "cleanup_proofs" in inspector_after.get_table_names()
    assert "locations" in inspector_after.get_table_names()
    assert "cleaner_locations" in inspector_after.get_table_names()

    # Verify old row is completely intact and accessible through Real ORM Complaint model
    with Session() as db:
        migrated_comp = db.query(Complaint).filter(Complaint.tracking_id == "TRK-OLD001").first()
        assert migrated_comp is not None
        assert migrated_comp.name == "Old User"
        assert migrated_comp.waste_type is None
        assert migrated_comp.location_id is None
        assert migrated_comp.status == "pending"

    with Session() as db:
        assert {
            location.slug for location in db.query(Location).all()
        } == {"dadar", "wadala", "kalyan-dombivli"}


def test_location_migration_preserves_existing_rows_and_is_idempotent(tmp_path):
    db_file = tmp_path / "legacy_workflow.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(150) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(50) NOT NULL,
                created_at DATETIME NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE complaints (
                id INTEGER PRIMARY KEY,
                tracking_id VARCHAR(50) NOT NULL UNIQUE,
                user_id INTEGER,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(150) NOT NULL,
                complaint_text TEXT NOT NULL,
                language VARCHAR(10) NOT NULL,
                priority VARCHAR(20) NOT NULL,
                status VARCHAR(30) NOT NULL,
                latitude FLOAT,
                longitude FLOAT,
                address_text VARCHAR(255)
            )
        """))
        connection.execute(text("""
            CREATE TABLE cleanup_tasks (
                id INTEGER PRIMARY KEY,
                task_id VARCHAR(50) NOT NULL UNIQUE,
                complaint_id INTEGER NOT NULL UNIQUE,
                assigned_cleaner_id INTEGER,
                status VARCHAR(30) NOT NULL,
                assigned_at DATETIME NOT NULL,
                completed_at DATETIME
            )
        """))
        connection.execute(text("""
            INSERT INTO users
                (id, name, email, password_hash, role, created_at)
            VALUES (1, 'Existing Cleaner', 'cleaner@example.com', 'hash',
                    'cleaner', CURRENT_TIMESTAMP)
        """))
        connection.execute(text("""
            INSERT INTO complaints
                (id, tracking_id, user_id, name, email, complaint_text,
                 language, priority, status)
            VALUES (1, 'TRK-LEGACY', 1, 'Existing Citizen', 'citizen@example.com',
                    'Legacy complaint', 'en', 'medium', 'pending')
        """))
        connection.execute(text("""
            INSERT INTO cleanup_tasks
                (id, task_id, complaint_id, assigned_cleaner_id, status, assigned_at)
            VALUES (1, 'TSK-LEGACY', 1, 1, 'assigned', CURRENT_TIMESTAMP)
        """))

    run_migrations(target_engine=engine)
    run_migrations(target_engine=engine)

    Session = sessionmaker(bind=engine)
    with Session() as db:
        user = db.query(User).filter(User.id == 1).one()
        complaint = db.query(Complaint).filter(Complaint.id == 1).one()
        task = db.query(CleanupTask).filter(CleanupTask.id == 1).one()

        assert user.email == "cleaner@example.com"
        assert complaint.tracking_id == "TRK-LEGACY"
        assert complaint.location_id is None
        assert task.task_id == "TSK-LEGACY"
        assert task.started_at is None
        assert task.completed_at is None


def test_multiple_cleaner_locations_and_duplicate_constraints(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'location_constraints.db'}",
        connect_args={"check_same_thread": False},
    )
    run_migrations(target_engine=engine)

    Session = sessionmaker(bind=engine)
    with Session() as db:
        cleaner = User(
            name="Cleaner",
            email="cleaner@example.com",
            password_hash="hash",
            role="cleaner",
        )
        db.add(cleaner)
        db.flush()
        locations = db.query(Location).order_by(Location.id).limit(2).all()
        db.execute(
            cleaner_locations.insert(),
            [
                {"cleaner_id": cleaner.id, "location_id": locations[0].id},
                {"cleaner_id": cleaner.id, "location_id": locations[1].id},
            ],
        )
        db.commit()

        assert {location.slug for location in cleaner.permitted_locations} == {
            locations[0].slug,
            locations[1].slug,
        }

        with pytest.raises(IntegrityError):
            db.add(Location(name="Duplicate Dadar", slug="dadar"))
            db.commit()
        db.rollback()

        with pytest.raises(IntegrityError):
            db.execute(
                cleaner_locations.insert().values(
                    cleaner_id=cleaner.id,
                    location_id=locations[0].id,
                )
            )
            db.commit()


def test_sqlite_foreign_keys_reject_invalid_cleaner_locations(tmp_path):
    engine = _create_database_engine(
        f"sqlite:///{tmp_path / 'foreign_keys.db'}",
        connect_args={"check_same_thread": False},
    )
    try:
        run_migrations(target_engine=engine)

        Session = sessionmaker(bind=engine)
        with Session() as db:
            cleaner = User(
                name="Cleaner",
                email="foreign-key-cleaner@example.com",
                password_hash="hash",
                role="cleaner",
            )
            db.add(cleaner)
            db.flush()
            location = db.query(Location).filter_by(slug="dadar").one()

            db.execute(
                cleaner_locations.insert().values(
                    cleaner_id=cleaner.id,
                    location_id=location.id,
                )
            )
            db.commit()

            with pytest.raises(IntegrityError):
                db.execute(
                    cleaner_locations.insert().values(
                        cleaner_id=999999,
                        location_id=location.id,
                    )
                )
                db.commit()
            db.rollback()

            with pytest.raises(IntegrityError):
                db.execute(
                    cleaner_locations.insert().values(
                        cleaner_id=cleaner.id,
                        location_id=999999,
                    )
                )
                db.commit()
            db.rollback()
    finally:
        engine.dispose()
