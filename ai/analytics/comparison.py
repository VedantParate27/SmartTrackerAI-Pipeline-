r"""
Location comparison: turns cleanup records into chart-ready data.

Usage:
    python ai\analytics\comparison.py                 # all locations
    python ai\analytics\comparison.py Dadar Wadala    # compare two

Currently runs on SYNTHETIC records. Nothing printed here is a real finding.
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

    out = {
        "meta": {"records": len(subset), "sources": sorted({r.source for r in subset})},
        "locations": locations,
        "waste_types": waste_types,
        "severities": severities,
        "weeks": weeks,
        "totals": {},
        "by_waste_type": {},
        "by_severity": {},
        "weekly": {},
        "median_cleaning_minutes": {},
        "median_response_minutes": {},
    }
    for loc in locations:
        rs = [r for r in subset if r.location == loc]
        wt = Counter(r.waste_type for r in rs)
        sev = Counter(r.severity for r in rs)
        wk = Counter(week_label(r.assigned_at) for r in rs)
        out["totals"][loc] = len(rs)
        out["by_waste_type"][loc] = {w: wt.get(w, 0) for w in waste_types}
        out["by_severity"][loc] = {s: sev.get(s, 0) for s in severities}
        out["weekly"][loc] = {w: wk.get(w, 0) for w in weeks}
        out["median_cleaning_minutes"][loc] = med([r.cleaning_minutes for r in rs])
        out["median_response_minutes"][loc] = med([r.response_minutes for r in rs])
    return out


if __name__ == "__main__":
    chosen = sys.argv[1:] or None
    result = compare_locations(generate_records(300), chosen)

    print(f"Records: {result['meta']['records']}  sources: {result['meta']['sources']}")
    print(f"{'Location':<18}{'Total':>6}{'Med clean (min)':>17}{'Med response (min)':>20}")
    for loc in result["locations"]:
        print(f"{loc:<18}{result['totals'][loc]:>6}"
              f"{str(result['median_cleaning_minutes'][loc]):>17}"
              f"{str(result['median_response_minutes'][loc]):>20}")

    print("\nCleanups by waste type:")
    for loc in result["locations"]:
        print(f"  {loc}: {result['by_waste_type'][loc]}")

    path = os.path.join(os.path.dirname(__file__), "comparison_sample.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved chart data to {path}")