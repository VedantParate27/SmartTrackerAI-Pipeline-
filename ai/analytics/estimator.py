"""
Cleaning-time estimator (baseline) for the location analytics work.

Looks up the median cleaning time for the most specific group that has at
least MIN_SAMPLES past cleanups, and falls back to broader groups otherwise.

NOTE: tested on SYNTHETIC data only. It can recover the assumptions used to
generate that data, which says nothing about real cleanups. Do not report
results from synthetic data as findings.
"""
import os
import sys
import random
from collections import defaultdict, Counter
from statistics import mean, median

sys.path.insert(0, os.path.dirname(__file__))
from records import generate_records

MIN_SAMPLES = 5

# Most specific first.
LEVELS = [
    ("location+waste_type+severity", ("location", "waste_type", "severity")),
    ("location+severity", ("location", "severity")),
    ("severity", ("severity",)),
    ("overall", ()),
]


class TimeEstimator:
    def fit(self, records):
        self.tables = []
        for name, keys in LEVELS:
            groups = defaultdict(list)
            for r in records:
                groups[tuple(getattr(r, k) for k in keys)].append(r.cleaning_minutes)
            self.tables.append((name, keys, groups))
        return self

    def predict(self, location, waste_type, severity):
        values = {"location": location, "waste_type": waste_type, "severity": severity}
        for name, keys, groups in self.tables:
            samples = groups.get(tuple(values[k] for k in keys), [])
            if len(samples) >= MIN_SAMPLES:
                return {"minutes": round(median(samples), 1), "based_on": name, "n": len(samples)}
        return {"minutes": None, "based_on": "not enough data", "n": 0}


if __name__ == "__main__":
    records = generate_records(300)
    rng = random.Random(1)
    rng.shuffle(records)
    cut = int(len(records) * 0.8)
    train, test = records[:cut], records[cut:]

    est = TimeEstimator().fit(train)
    baseline = median(r.cleaning_minutes for r in train)

    errors_model, errors_base, levels_used = [], [], Counter()
    for r in test:
        p = est.predict(r.location, r.waste_type, r.severity)
        levels_used[p["based_on"]] += 1
        if p["minutes"] is None:
            continue
        errors_model.append(abs(p["minutes"] - r.cleaning_minutes))
        errors_base.append(abs(baseline - r.cleaning_minutes))

    print(f"Train: {len(train)}  Test: {len(test)}  (SYNTHETIC data)")
    print(f"Mean abs error, grouped estimator : {mean(errors_model):.1f} min")
    print(f"Mean abs error, one overall median: {mean(errors_base):.1f} min")
    print("Groups used for the test predictions:")
    for name, count in levels_used.most_common():
        print(f"  {name}: {count}")
    print("Example:", est.predict("Dadar", "wet", "moderate"))