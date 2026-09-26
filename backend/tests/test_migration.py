import sys
from pathlib import Path

from sqlalchemy import Column, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import run_migrations, Base as RealBase
from models import Complaint, User


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
    assert "cleanup_tasks" in inspector_after.get_table_names()
    assert "cleanup_proofs" in inspector_after.get_table_names()

    # Verify old row is completely intact and accessible through Real ORM Complaint model
    with Session() as db:
        migrated_comp = db.query(Complaint).filter(Complaint.tracking_id == "TRK-OLD001").first()
        assert migrated_comp is not None
        assert migrated_comp.name == "Old User"
        assert migrated_comp.waste_type is None
        assert migrated_comp.status == "pending"
