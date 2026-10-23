
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from records import generate_records
from estimator import TimeEstimator


OUTPUT_DIR = Path(__file__).resolve().parent
RECORD_COUNT = 300


def get_field(record, *names, default="unknown"):
    for name in names:
        if isinstance(record, dict) and name in record:
            return record[name]

        if hasattr(record, name):
            return getattr(record, name)

    return default


def main():
    records = generate_records(RECORD_COUNT)

    if not records:
        raise RuntimeError("No records were generated.")

    estimator = TimeEstimator().fit(records)

    location_counts = Counter()
    severity_counts = Counter()
    waste_counts = Counter()
    location_severity = defaultdict(Counter)

    for record in records:
        location = str(
            get_field(record, "location", "location_name")
        )
        severity = str(
            get_field(record, "severity", "severity_level")
        )
        waste_type = str(
            get_field(record, "waste_type", "waste")
        )

        location_counts[location] += 1
        severity_counts[severity] += 1
        waste_counts[waste_type] += 1
        location_severity[location][severity] += 1

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_type": "synthetic demonstration data",
        "total_records": len(records),
        "location_summary": [],
        "severity_distribution": dict(severity_counts),
        "waste_type_distribution": dict(waste_counts),
        "cleanup_time_estimates": [],
    }

    for location, count in location_counts.most_common():
        report["location_summary"].append({
            "location": location,
            "record_count": count,
            "percentage": round(count / len(records) * 100, 2),
        })

        for severity, severity_count in (
            location_severity[location].items()
        ):
            matching = [
                record for record in records
                if str(get_field(
                    record, "location", "location_name"
                )) == location
                and str(get_field(
                    record, "severity", "severity_level"
                )) == severity
            ]

            if not matching:
                continue

            sample = matching[0]
            waste_type = str(
                get_field(sample, "waste_type", "waste")
            )

            estimate = estimator.predict(
                location, waste_type, severity
            )

            report["cleanup_time_estimates"].append({
                "location": location,
                "severity": severity,
                "records": severity_count,
                "estimated_minutes": estimate["minutes"],
                "based_on": estimate["based_on"],
                "training_samples": estimate["n"],
            })

    json_path = OUTPUT_DIR / "analytics_report.json"
    text_path = OUTPUT_DIR / "analytics_report.txt"

    json_path.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    lines = [
        "SMARTTRACKER ANALYTICS REPORT",
        "=" * 35,
        f"Generated: {report['generated_at']}",
        "Dataset: Synthetic demonstration data",
        f"Total records: {report['total_records']}",
        "",
        "LOCATION COMPARISON",
        "-" * 35,
    ]

    for item in report["location_summary"]:
        lines.append(
            f"{item['location']}: {item['record_count']} records "
            f"({item['percentage']}%)"
        )

    lines.extend([
        "",
        "SEVERITY DISTRIBUTION",
        "-" * 35,
    ])

    for severity, count in report["severity_distribution"].items():
        lines.append(f"{severity}: {count}")

    lines.extend([
        "",
        "WASTE TYPE DISTRIBUTION",
        "-" * 35,
    ])

    for waste_type, count in report["waste_type_distribution"].items():
        lines.append(f"{waste_type}: {count}")

    lines.extend([
        "",
        "ESTIMATED CLEANUP TIMES",
        "-" * 35,
    ])

    for item in report["cleanup_time_estimates"]:
        lines.append(
            f"{item['location']} | {item['severity']} | "
            f"{item['estimated_minutes']} minutes | "
            f"{item['records']} records"
        )

    lines.extend([
        "",
        "Note: All records are synthetic. Estimates are a baseline,",
        "not validated real-world cleanup-time measurements.",
    ])

    text_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\nJSON report saved: {json_path}")
    print(f"Text report saved: {text_path}")
    print("\nREPORT GENERATION PASSED")


if __name__ == "__main__":
    main()
