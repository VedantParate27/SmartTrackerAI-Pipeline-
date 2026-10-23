"""
Shared record format + SYNTHETIC test data for the location analytics work.

Everything generated here is invented for testing. The durations come from the
assumptions below, not from real cleanups, so results computed from this data
must never be reported as findings.
"""
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

LOCATIONS = ["Dadar", "Wadala", "Kalyan-Dombivali"]
WASTE_TYPES = ["wet", "dry", "hazardous", "sanitary", "e_waste", "mixed"]
SEVERITIES = ["domestic", "moderate", "dump_scale"]

# ASSUMPTIONS (invented for testing): typical cleaning minutes per severity,
# and a per-location multiplier.
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
        assigned = start_day + timedelta(minutes=rng.randint(0, 30 * 24 * 60))
        started = assigned + timedelta(minutes=rng.randint(5, 90))
        minutes = BASE_MINUTES[severity] * LOCATION_FACTOR[location] * rng.uniform(0.6, 1.5)
        finished = started + timedelta(minutes=minutes)
        records.append(CleanupRecord(i, location, waste_type, severity,
                                     assigned, started, finished))
    return records


if __name__ == "__main__":
    recs = generate_records()
    print(f"Generated {len(recs)} synthetic records")
    for r in recs[:3]:
        print(r.to_dict())
    for loc in LOCATIONS:
        count = sum(1 for r in recs if r.location == loc)
        print(f"{loc}: {count}")