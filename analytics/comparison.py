
r"""
Location and cleaner comparison: chart-ready analytics data.

Usage:
    python analytics\comparison.py
    python analytics\comparison.py Dadar Wadala

NOTE: Uses synthetic records only. Results are not real findings.
"""

import json
import os
import sys
from collections import Counter
from statistics import median

sys.path.insert(0, os.path.dirname(__file__))
from records import generate_records


def week_label(dt):
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def med(values):
    return round(median(values), 1) if values else None


def compare_locations(records, locations=None):
    locations = locations or sorted({r.location for r in records})
    subset = [r for r in records if r.location in locations]

    waste_types = sorted({r.waste_type for r in subset})
    severities = sorted({r.severity for r in subset})
    weeks = sorted({week_label(r.assigned_at) for r in subset})
    cleaners = sorted({
        getattr(r, "cleaner_id", "UNKNOWN") for r in subset
    })

    out = {
        "meta": {
            "records": len(subset),
            "sources": sorted({r.source for r in subset}),
            "synthetic_data": all(
                r.source == "synthetic" for r in subset
            ),
        },
        "locations": locations,
        "waste_types": waste_types,
        "severities": severities,
        "weeks": weeks,
        "cleaners": cleaners,
        "totals": {},
        "by_waste_type": {},
        "by_severity": {},
        "weekly": {},
        "median_cleaning_minutes": {},
        "median_response_minutes": {},
        "cleaner_totals": {},
        "cleaner_median_cleaning_minutes": {},
        "cleaner_by_location": {},
    }

    for loc in locations:
        rs = [r for r in subset if r.location == loc]

        wt = Counter(r.waste_type for r in rs)
        sev = Counter(r.severity for r in rs)
        wk = Counter(week_label(r.assigned_at) for r in rs)

        out["totals"][loc] = len(rs)
        out["by_waste_type"][loc] = {
            w: wt.get(w, 0) for w in waste_types
        }
        out["by_severity"][loc] = {
            s: sev.get(s, 0) for s in severities
        }
        out["weekly"][loc] = {
            w: wk.get(w, 0) for w in weeks
        }
        out["median_cleaning_minutes"][loc] = med(
            [r.cleaning_minutes for r in rs]
        )
        out["median_response_minutes"][loc] = med(
            [r.response_minutes for r in rs]
        )

    for cleaner in cleaners:
        cleaner_records = [
            r for r in subset
            if getattr(r, "cleaner_id", "UNKNOWN") == cleaner
        ]

        out["cleaner_totals"][cleaner] = len(cleaner_records)
        out["cleaner_median_cleaning_minutes"][cleaner] = med(
            [r.cleaning_minutes for r in cleaner_records]
        )

        out["cleaner_by_location"][cleaner] = {}

        for loc in locations:
            matching = [
                r for r in cleaner_records if r.location == loc
            ]

            out["cleaner_by_location"][cleaner][loc] = {
                "count": len(matching),
                "median_cleaning_minutes": med(
                    [r.cleaning_minutes for r in matching]
                ),
            }

    return out


if __name__ == "__main__":
    chosen = sys.argv[1:] or None
    result = compare_locations(generate_records(300), chosen)

    print(
        f"Records: {result['meta']['records']}  "
        f"sources: {result['meta']['sources']}  "
        f"(SYNTHETIC data)"
    )

    print(
        f"{'Location':<20}{'Total':>7}"
        f"{'Med clean':>13}{'Med response':>16}"
    )

    for loc in result["locations"]:
        print(
            f"{loc:<20}"
            f"{result['totals'][loc]:>7}"
            f"{str(result['median_cleaning_minutes'][loc]):>13}"
            f"{str(result['median_response_minutes'][loc]):>16}"
        )

    print("\nCleanups by waste type:")
    for loc in result["locations"]:
        print(f"  {loc}: {result['by_waste_type'][loc]}")

    print("\nCleanups by severity:")
    for loc in result["locations"]:
        print(f"  {loc}: {result['by_severity'][loc]}")

    print("\nCleaner summary:")
    for cleaner in result["cleaners"]:
        print(
            f"  {cleaner}: "
            f"{result['cleaner_totals'][cleaner]} cleanups, "
            f"median cleaning time "
            f"{result['cleaner_median_cleaning_minutes'][cleaner]} min"
        )

    path = os.path.join(
        os.path.dirname(__file__), "comparison_sample.json"
    )

    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"\nSaved chart data to {path}")
