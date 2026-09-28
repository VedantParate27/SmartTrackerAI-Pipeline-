# seed_data.py
# Backend-only synthetic data generator for development and research.
#
# ARCHITECTURAL RULE: seeded rows are ALWAYS marked source="seed" so they can
# never be confused with real citizen submissions (they surface as
# is_synthetic=true in the mining export). Complaint texts are assembled from
# realistic templates with systematic slot variation — not random nonsense —
# so DWM mining (classification, clustering, Apriori) has meaningful structure
# to discover. The generator writes a FULL event chain per complaint so the
# event log supports process mining from day one.
#
# Usage:
#   python seed_data.py --complaints 600 --cleaners 6 --seed 42
#   python seed_data.py --complaints 0 --cleaners 0   # wipe all seeded data
#
# No AI predictions are fabricated here (that is the AI team's ingest API);
# seeded complaints are therefore born triage_mode=NULL with an optional
# --simulate-triage mode that records explicitly-labelled placeholder outputs
# (model_name="seed_simulated_triage") for workflow testing only. They are
# clearly marked and are NOT research results.

import argparse
import random
import uuid
from datetime import datetime, timedelta, timezone

from database import Base, SessionLocal, engine

# Support dependency-injection overrides (e.g. the in-memory test engine in
# tests/test_app_state.py). When SessionLocal/engine are overridden there, the
# seeder writes to the SAME database the API serves — never a second database.
try:  # pragma: no cover - exercised only under the test harness
    from test_app_state import TestingSessionLocal as _InjectedSession  # type: ignore
    from test_app_state import engine as _InjectedEngine  # type: ignore
except Exception:  # normal CLI/runtime operation
    _InjectedSession = None
    _InjectedEngine = None

from models import (
    AICorrection,
    AIOutput,
    CleanupProof,
    CleanupTask,
    Complaint,
    EventLog,
    User,
)
from routers.eventlog import log_event
from taxonomy import compute_priority

# ---------------------------------------------------------------------------
# Realistic content pools (slot-based, varied, non-nonsensical)
# ---------------------------------------------------------------------------
WASTE_TEXT_TEMPLATES = {
    "dry": [
        "Plastic bags and wrappers scattered around {place} in {area}.",
        "Paper and cardboard dumped near {place}, {area}. Growing daily.",
        "Piles of dry packaging waste at {place} in {area}, spreading onto the footpath.",
    ],
    "wet": [
        "Kitchen and organic waste rotting beside {place} in {area}. Bad smell in the mornings.",
        "Food waste dumped near {place}, {area}. Attracting stray dogs and flies.",
        "Vegetable and wet waste accumulating at {place} in {area} since last week.",
    ],
    "e_waste": [
        "Old monitors and cables discarded near {place} in {area}.",
        "Discarded TV, batteries and electronic scrap at {place}, {area}.",
        "Broken computers and printer parts dumped beside {place} in {area}.",
    ],
    "medical": [
        "Used syringes and masks found near {place} in {area}. Health hazard for children.",
        "Discarded medicine strips and cotton waste at {place}, {area}.",
        "Clinic waste bags left outside {place} in {area}.",
    ],
    "hazardous": [
        "Paint cans and chemical containers dumped at {place} in {area}.",
        "Asbestos sheets and solvent drums discarded near {place}, {area}.",
        "Batteries and acid containers lying at {place} in {area}.",
    ],
    "bulk": [
        "Construction debris and furniture waste blocking {place} in {area}.",
        "Large mattresses and sofa pieces dumped at {place}, {area}.",
        "Renovation rubble piling up beside {place} in {area}.",
    ],
}

PLACES = ["the community center", "the bus stop", "the market entrance", "the park gate",
          "the school wall", "the subway stairs", "the temple lane", "the riverbank walkway"]
AREAS = ["Ward 1", "Ward 2", "Ward 3", "Waste type varies by ward in seeds", "Ward 4", "Ward 5", "Ward 6"]
# Ward-structured areas for mining: keep address containing explicit "Ward N"
WARD_ADDRESSES = [
    "MG Road, Ward 1", "Central Park, Ward 1", "Station Road, Ward 2",
    "Market Street, Ward 2", "Lake View, Ward 3", "School Lane, Ward 3",
    "Hill Road, Ward 4", "Riverside, Ward 4", "Industrial Area, Ward 5",
    "Old Town, Ward 5", "Green Avenue, Ward 6", "Bus Depot, Ward 6",
]

# Structured outcome patterns (NOT hardcoded mining results — these are the
# generative rules for the synthetic world; mining may still discover others).
SEVERITY_BY_TYPE = {
    "dry": [0.45, 0.40, 0.15],      # small, medium, large
    "wet": [0.35, 0.40, 0.25],
    "e_waste": [0.20, 0.45, 0.35],
    "medical": [0.10, 0.40, 0.50],
    "hazardous": [0.05, 0.35, 0.60],
    "bulk": [0.05, 0.30, 0.65],
}
INTERVENTION_PROBABILITY = {  # P(dispatch | waste_type) — varies by type
    "dry": 0.25, "wet": 0.45, "e_waste": 0.70,
    "medical": 0.90, "hazardous": 0.95, "bulk": 0.85,
}
WARD_INTENSITY = {"Ward 1": 0.10, "Ward 2": 0.22, "Ward 3": 0.16,
                  "Ward 4": 0.12, "Ward 5": 0.25, "Ward 6": 0.15}
WARD_CENTER = {
    "Ward 1": (12.972, 77.594), "Ward 2": (12.981, 77.605), "Ward 3": (12.965, 77.616),
    "Ward 4": (12.958, 77.590), "Ward 5": (12.990, 77.572), "Ward 6": (12.947, 77.602),
}

PROOF_REJECTION_REASONS = [
    "Image is blurry; cleanup site not clearly visible.",
    "Waste still present in the photo.",
    "Wrong location photographed.",
]


def _weighted(rng, pairs):
    options, weights = zip(*pairs)
    return rng.choices(options, weights=weights, k=1)[0]


def _seed_events(db, complaint, actor_id, rng, cleaner_id=None, with_task=False,
                 with_proofs=False, verified=False):
    """Write a complete, internally consistent event chain for one complaint."""
    log_event(db, case_id=complaint.tracking_id, activity="complaint_created",
              actor_id=actor_id, actor_role="system", new_value="pending",
              meta={"seeded": True, "priority": complaint.priority})
    if with_task and cleaner_id is not None:
        log_event(db, case_id=complaint.tracking_id, activity="dispatch_decided",
                  actor_id=actor_id, actor_role="system", new_value="dispatch")
        log_event(db, case_id=complaint.tracking_id, activity="cleaner_assigned",
                  actor_id=actor_id, actor_role="system", new_value=str(cleaner_id))
    if with_proofs and verified:
        log_event(db, case_id=complaint.tracking_id, activity="proof_submitted",
                  actor_role="cleaner", new_value="proof_submitted", meta={"seeded": True})
        log_event(db, case_id=complaint.tracking_id, activity="proof_verified",
                  actor_id=actor_id, actor_role="system", old_value="pending_verification",
                  new_value="verified")
        log_event(db, case_id=complaint.tracking_id, activity="complaint_resolved",
                  actor_id=actor_id, actor_role="system", old_value="in_progress",
                  new_value="resolved")
    elif with_proofs:  # rejected proof loop, still open
        log_event(db, case_id=complaint.tracking_id, activity="proof_submitted",
                  actor_role="cleaner", new_value="proof_submitted", meta={"seeded": True})
        log_event(db, case_id=complaint.tracking_id, activity="proof_rejected",
                  actor_id=actor_id, actor_role="system", old_value="pending_verification",
                  new_value="rejected", meta={"rejection_reason": "seeded rejection"})


def seed_database(number_of_complaints: int = 500, number_of_cleaners: int = 5,
                  seed: int = 42, simulate_triage: bool = False) -> dict:
    """Generate marked synthetic users/complaints/tasks/proofs/events.

    Everything created here has source='seed'. Real citizen data is untouched.
    Returns a summary dict (counts) for CLI/tests.
    """
    rng = random.Random(seed)
    if _InjectedSession is not None:  # honor the test harness override
        Base.metadata.create_all(bind=_InjectedEngine)
        db = _InjectedSession()
    else:
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
    summary = {"complaints": 0, "cleaners": 0, "tasks": 0, "proofs": 0, "events": 0}

    try:
        # --- Synthetic cleaners (idempotent by email) ---
        cleaners = []
        for i in range(number_of_cleaners):
            email = f"seed.cleaner{i+1}@synthetic.local"
            cleaner = db.query(User).filter(User.email == email).first()
            if not cleaner:
                cleaner = User(
                    name=f"Seed Cleaner {i+1}",
                    email=email,
                    password_hash="seed-no-login",
                    role="cleaner",
                    department="Synthetic Seeding",
                )
                db.add(cleaner)
                db.flush()
            cleaners.append(cleaner)
        summary["cleaners"] = len(cleaners)

        # --- Synthetic complainant ---
        seed_citizen = db.query(User).filter(User.email == "seed.citizen@synthetic.local").first()
        if not seed_citizen:
            seed_citizen = User(
                name="Seed Citizen Pool",
                email="seed.citizen@synthetic.local",
                password_hash="seed-no-login",
                role="citizen",
                department="Synthetic Seeding",
            )
            db.add(seed_citizen)
            db.flush()

        now = datetime.now(timezone.utc)
        waste_types = list(SEVERITY_BY_TYPE.keys())

        for i in range(number_of_complaints):
            waste_type = rng.choice(waste_types)
            severity = _weighted(rng, list(zip(("small", "medium", "large"), SEVERITY_BY_TYPE[waste_type])))
            intervention = rng.random() < INTERVENTION_PROBABILITY[waste_type]
            if severity == "large":
                intervention = True  # large accumulations always need field work in the seeded world
            address = rng.choice(WARD_ADDRESSES)
            ward = address.split(", ")[-1]          # explicit "Ward N"
            lat, lon = WARD_CENTER[ward]
            created_at = now - timedelta(days=rng.randint(1, 120),
                                         hours=rng.randint(0, 23),
                                         minutes=rng.randint(0, 59))

            complaint = Complaint(
                user_id=seed_citizen.id,
                name=seed_citizen.name,
                email=seed_citizen.email,
                complaint_text=rng.choice(WASTE_TEXT_TEMPLATES[waste_type]).format(
                    place=rng.choice(PLACES), area=ward
                ),
                waste_type=waste_type,
                waste_context="seeded synthetic complaint",
                quantity_severity=severity,
                recommended_action=None,
                intervention_required=intervention,
                latitude=round(lat + rng.uniform(-0.004, 0.004), 6),
                longitude=round(lon + rng.uniform(-0.004, 0.004), 6),
                address_text=address,
                status="pending",
                priority=compute_priority(severity, waste_type, intervention),
                source="seed",
                created_at=created_at,
                updated_at=created_at,
            )
            db.add(complaint)
            db.flush()

            # ---- outcomes: resolve / dispatch+verify / dispatch+reject-loop / open ----
            outcome = _weighted(rng, [
                ("guidance_resolved", 1 - INTERVENTION_PROBABILITY[waste_type]),
                ("dispatch_verified", 0.55 if intervention else 0.0),
                ("dispatch_reject_loop", 0.25 if intervention else 0.0),
                ("open", 0.20 if intervention else 0.0),
            ])

            with_task = outcome != "guidance_resolved"
            with_proofs = outcome in ("dispatch_verified", "dispatch_reject_loop")
            cleaner = rng.choice(cleaners) if with_task else None

            if simulate_triage:
                # Explicitly-labelled simulated output for workflow testing only.
                # NOT a research result (model_name says so).
                confidence = round(rng.uniform(0.55, 0.98), 4)
                escalated = confidence < 0.7 or waste_type in ("medical", "hazardous")
                db.add(AIOutput(
                    complaint_id=complaint.id,
                    waste_type_pred=waste_type,
                    severity_pred=severity,
                    intervention_required_pred=intervention,
                    confidence=confidence,
                    model_name="seed_simulated_triage",
                    model_version="0.0-simulated",
                    threshold_used=0.7,
                    escalated=escalated,
                    escalation_reason=("low_confidence" if confidence < 0.7 else
                                       "hazardous_waste" if escalated else None),
                ))
                complaint.triage_mode = "ai_assisted"
                if escalated:
                    complaint.review_required = True
                    complaint.review_reason = "low_confidence" if confidence < 0.7 else "hazardous_waste"

            if outcome == "guidance_resolved":
                complaint.status = "resolved"
                complaint.recommended_action = f"Dispose of {waste_type} waste at the nearest designated facility in {ward}."
                complaint.resolved_at = created_at + timedelta(hours=rng.randint(2, 48))
            elif with_task:
                task = CleanupTask(
                    complaint_id=complaint.id,
                    assigned_cleaner_id=cleaner.id,
                    status="assigned",
                    assigned_at=created_at + timedelta(hours=rng.randint(1, 12)),
                    notes="Seeded task",
                )
                db.add(task)
                db.flush()
                complaint.status = "in_progress"
                summary["tasks"] += 1

                if with_proofs:
                    n_attempts = 2 if outcome == "dispatch_reject_loop" else 1
                    created_proofs = []
                    for attempt in range(n_attempts):
                        proof = CleanupProof(
                            task_id=task.id,
                            image_url=f"/uploads/seed_proof_{uuid.uuid4().hex[:12]}.jpg",
                            uploaded_by=cleaner.id,
                            verification_status="pending_verification",
                            uploaded_at=task.assigned_at + timedelta(hours=attempt * rng.randint(4, 24)),
                        )
                        db.add(proof)
                        created_proofs.append(proof)
                        summary["proofs"] += 1
                    if outcome == "dispatch_verified":
                        verify_at = task.assigned_at + timedelta(hours=rng.randint(6, 72))
                        proof_last = created_proofs[-1]
                        proof_last.verification_status = "verified"
                        proof_last.verified_by = None  # system-verified seed; no fake admin user
                        proof_last.verified_at = verify_at
                        task.status = "verified"
                        task.completed_at = verify_at
                        complaint.status = "resolved"
                        complaint.resolved_at = verify_at
                    else:
                        task.status = "rejected"  # resubmission loop still open

            _seed_events(db, complaint, seed_citizen.id, rng,
                         cleaner_id=cleaner.id if cleaner else None,
                         with_task=with_task, with_proofs=with_proofs,
                         verified=(outcome == "dispatch_verified"))
            summary["complaints"] += 1

        db.commit()
        summary["events"] = db.query(EventLog).count()
        return summary
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def clear_seeded_data() -> int:
    """Delete ONLY rows created by the seeder (source='seed' and synthetic
    accounts). Real citizen data is never touched. Returns complaints removed."""
    db = _InjectedSession() if _InjectedSession is not None else SessionLocal()
    try:
        seeded = db.query(Complaint).filter(Complaint.source == "seed").all()
        count = len(seeded)
        for complaint in seeded:
            db.query(AICorrection).filter(AICorrection.complaint_id == complaint.id).delete()
            db.query(AIOutput).filter(AIOutput.complaint_id == complaint.id).delete()
            task = db.query(CleanupTask).filter(CleanupTask.complaint_id == complaint.id).first()
            if task:
                db.query(CleanupProof).filter(CleanupProof.task_id == task.id).delete()
                db.delete(task)
            db.query(EventLog).filter(EventLog.case_id == complaint.tracking_id).delete()
            db.delete(complaint)
        for email in ["seed.citizen@synthetic.local"] + [
            f"seed.cleaner{i+1}@synthetic.local" for i in range(20)
        ]:
            user = db.query(User).filter(User.email == email).first()
            if user:
                db.delete(user)
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed marked synthetic waste-complaint data")
    parser.add_argument("--complaints", type=int, default=500)
    parser.add_argument("--cleaners", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--simulate-triage", action="store_true",
                        help="Attach clearly-labelled simulated AI outputs for workflow testing (NOT research results)")
    parser.add_argument("--wipe", action="store_true", help="Remove all seeded data (source='seed') only")
    args = parser.parse_args()

    if args.wipe:
        removed = clear_seeded_data()
        print(f"[OK] Removed {removed} seeded complaint(s). Citizen data untouched.")
    else:
        summary = seed_database(
            number_of_complaints=args.complaints,
            number_of_cleaners=args.cleaners,
            seed=args.seed,
            simulate_triage=args.simulate_triage,
        )
        print("[OK] Seeding complete (all rows marked source='seed'):")
        for key, value in summary.items():
            print(f"     {key:12}: {value}")
