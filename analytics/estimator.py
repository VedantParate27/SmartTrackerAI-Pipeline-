
"""
Cleaning-time estimator for location and cleaner analytics.

Uses the median cleaning time from the most specific group with enough
past cleanups, falling back to broader groups when necessary.

NOTE: Tested on SYNTHETIC data only. Estimates are demonstrations,
not evidence of real cleanup performance.
"""

import os
import sys
import random
from collections import defaultdict, Counter
from statistics import mean, median

sys.path.insert(0, os.path.dirname(__file__))
from records import generate_records

MIN_SAMPLES = 5

LEVELS = [
    ("location+waste_type+severity", ("location", "waste_type", "severity")),
    ("location+severity", ("location", "severity")),
    ("severity", ("severity",)),
    ("overall", ()),
]

CLEANER_LEVELS = [
    ("cleaner+location+waste_type+severity",
     ("cleaner_id", "location", "waste_type", "severity")),
    ("cleaner+location+severity",
     ("cleaner_id", "location", "severity")),
    ("cleaner+severity", ("cleaner_id", "severity")),
    ("cleaner overall", ("cleaner_id",)),
]


class TimeEstimator:
    def fit(self, records):
        self.tables = []
        self.cleaner_tables = []

        for name, keys in LEVELS:
            groups = defaultdict(list)

            for r in records:
                group_key = tuple(getattr(r, k) for k in keys)
                groups[group_key].append(r.cleaning_minutes)

            self.tables.append((name, keys, groups))

        for name, keys in CLEANER_LEVELS:
            groups = defaultdict(list)

            for r in records:
                cleaner_id = getattr(r, "cleaner_id", None)

                if not cleaner_id:
                    continue

                group_key = tuple(getattr(r, k) for k in keys)
                groups[group_key].append(r.cleaning_minutes)

            self.cleaner_tables.append((name, keys, groups))

        return self

    def predict(self, location, waste_type, severity):
        values = {
            "location": location,
            "waste_type": waste_type,
            "severity": severity,
        }

        for name, keys, groups in self.tables:
            samples = groups.get(tuple(values[k] for k in keys), [])

            if len(samples) >= MIN_SAMPLES:
                return {
                    "minutes": round(median(samples), 1),
                    "based_on": name,
                    "n": len(samples),
                }

        return {
            "minutes": None,
            "based_on": "not enough data",
            "n": 0,
        }

    def predict_for_cleaner(
        self, cleaner_id, location, waste_type, severity
    ):
        values = {
            "cleaner_id": cleaner_id,
            "location": location,
            "waste_type": waste_type,
            "severity": severity,
        }

        for name, keys, groups in self.cleaner_tables:
            samples = groups.get(tuple(values[k] for k in keys), [])

            if len(samples) >= MIN_SAMPLES:
                return {
                    "minutes": round(median(samples), 1),
                    "based_on": name,
                    "n": len(samples),
                }

        result = self.predict(location, waste_type, severity)
        result = result.copy()
        result["based_on"] = "general fallback: " + result["based_on"]
        return result

    def predict_cleaner(self, cleaner_id, location, waste_type, severity):
        return self.predict_for_cleaner(
            cleaner_id, location, waste_type, severity
        )


if __name__ == "__main__":
    records = generate_records(300)
    rng = random.Random(1)
    rng.shuffle(records)

    cut = int(len(records) * 0.8)
    train, test = records[:cut], records[cut:]

    est = TimeEstimator().fit(train)
    baseline = median(r.cleaning_minutes for r in train)

    errors_model = []
    errors_base = []
    levels_used = Counter()

    for r in test:
        prediction = est.predict(
            r.location, r.waste_type, r.severity
        )
        levels_used[prediction["based_on"]] += 1

        if prediction["minutes"] is None:
            continue

        errors_model.append(
            abs(prediction["minutes"] - r.cleaning_minutes)
        )
        errors_base.append(
            abs(baseline - r.cleaning_minutes)
        )

    print(f"Train: {len(train)}  Test: {len(test)} (SYNTHETIC data)")

    if errors_model:
        print(
            "Mean absolute error, grouped estimator:",
            f"{mean(errors_model):.1f} min",
        )
        print(
            "Mean absolute error, overall median:",
            f"{mean(errors_base):.1f} min",
        )
    else:
        print("Not enough data to evaluate the grouped estimator.")

    print("\nGroups used for general predictions:")
    for name, count in levels_used.most_common():
        print(f"  {name}: {count}")

    print("\nExample general prediction:")
    print(est.predict("Dadar", "wet", "moderate"))

    print("\nExample cleaner-specific prediction:")
    print(
        est.predict_for_cleaner(
            "C001", "Dadar", "wet", "moderate"
        )
    )
