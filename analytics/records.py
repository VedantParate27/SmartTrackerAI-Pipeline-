
"""
Shared record format + SYNTHETIC test data for location analytics.
All generated records are invented and must not be treated as real findings.
"""

import random
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

LOCATIONS = ["Dadar", "Wadala", "Kalyan-Dombivali"]
WASTE_TYPES = ["wet", "dry", "hazardous", "sanitary", "e_waste", "mixed"]
SEVERITIES = ["domestic", "moderate", "dump_scale"]
CLEANER_IDS = ["C001", "C002", "C003", "C004", "C005"]

BASE_MINUTES = {"domestic": 15, "moderate": 40, "dump_scale": 120}
LOCATION_FACTOR = {"Dadar": 1.0, "Wadala": 1.2, "Kalyan-Dombivali": 0.9}


@dataclass
class CleanupRecord:
    cleanup_id: int
    location: str
    waste_type: str
    severity: str
    assigned_at: datetime
    started_at: datetime
    finished_at: datetime
    source: str = "synthetic"
    cleaner_id: str = "C001"

    @property
    def cleaning_minutes(self) -> float:
        return (self.finished_at - self.started_at).total_seconds() / 60

    @property
    def response_minutes(self) -> float:
        return (self.started_at - self.assigned_at).total_seconds() / 60

    def to_dict(self) -> dict:
        d = asdict(self)
        d["cleaning_minutes"] = round(self.cleaning_minutes, 1)
        d["response_minutes"] = round(self.response_minutes, 1)
        return d


def generate_records(n: int = 300, seed: int = 42) -> list:
    rng = random.Random(seed)
    start_day = datetime(2026, 10, 1)
    records = []

    for i in range(1, n + 1):
        location = rng.choice(LOCATIONS)
        severity = rng.choices(SEVERITIES, weights=[5, 3, 1])[0]
        waste_type = rng.choice(WASTE_TYPES)
        cleaner_id = rng.choice(CLEANER_IDS)

        assigned = start_day + timedelta(minutes=rng.randint(0, 30 * 24 * 60))
        started = assigned + timedelta(minutes=rng.randint(5, 90))
        minutes = (
            BASE_MINUTES[severity]
            * LOCATION_FACTOR[location]
            * rng.uniform(0.6, 1.5)
        )
        finished = started + timedelta(minutes=minutes)

        records.append(
            CleanupRecord(
                cleanup_id=i,
                location=location,
                waste_type=waste_type,
                severity=severity,
                assigned_at=assigned,
                started_at=started,
                finished_at=finished,
                source="synthetic",
                cleaner_id=cleaner_id,
            )
        )

    return records


if __name__ == "__main__":
    recs = generate_records()
    print(f"Generated {len(recs)} synthetic records")

    for r in recs[:3]:
        print(r.to_dict())

    for loc in LOCATIONS:
        count = sum(1 for r in recs if r.location == loc)
        print(f"{loc}: {count}")

    print("\nSynthetic cleanup counts by cleaner:")
    for cleaner in CLEANER_IDS:
        count = sum(1 for r in recs if r.cleaner_id == cleaner)
        print(f"{cleaner}: {count}")
