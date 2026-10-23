# mining.py
# Mining-ready dataset export service for the DWM team.
#
# ARCHITECTURAL RULE: no mining algorithms run here. This module only extracts
# and prepares a clean, denormalized, tabular dataset from historical complaints
# so the DWM member can run Decision Tree / Naive Bayes / K-Means /
# Hierarchical clustering / Apriori externally.
#
# Data-quality rules (requirement I):
#   - categorical values come from taxonomy (validated at write time)
#   - resolution_time_seconds is NULL unless both timestamps exist
#   - proof_attempts / verified only count what actually happened
#   - ai_confidence NULL means no AI output exists — never imputed
#   - ward is parsed ONLY from an explicit "Ward N" mention in the address
#   - is_synthetic marks seeded rows so research data stays separable

import csv
import io
from datetime import datetime, timezone

from models import AIOutput, CleanupProof, CleanupTask, Complaint

MINING_FIELDNAMES = [
    "complaint_id",
    "tracking_id",
    "waste_type",
    "severity",
    "intervention_required",
    "latitude",
    "longitude",
    "ward",
    "date",
    "hour",
    "day_of_week",
    "priority",
    "triage_mode",
    "ai_confidence",
    "ai_model_name",
    "human_review_required",
    "correction_count",
    "cleaner_assigned",
    "proof_attempts",
    "proof_verified",
    "final_status",
    "resolution_time_seconds",
    "source",
    "is_synthetic",
]


def derive_ward(address_text):
    """Extract a ward label only from an explicit 'Ward N' mention.
    Never invents a ward from coordinates or anything else."""
    if not address_text:
        return None
    tokens = address_text.lower().replace(",", " ").split()
    for index, token in enumerate(tokens):
        stem = "ward"
        remainder = token[len(stem):] if token.startswith(stem) else None
        if remainder is None:
            continue
        if not remainder:  # "ward" followed by the number as the next token
            remainder = tokens[index + 1] if index + 1 < len(tokens) else ""
        remainder = remainder.strip(".:-#")
        if remainder.isdigit():
            return f"ward_{int(remainder)}"
    return None


def _latest_ai_output(outputs):
    """Most recent AI output row (they are append-only)."""
    if not outputs:
        return None
    return sorted(outputs, key=lambda o: (o.predicted_at or datetime.min.replace(tzinfo=timezone.utc)))[-1]


def build_mining_rows(db) -> list[dict]:
    """Build the full mining dataset as a list of plain dicts (one per complaint)."""
    complaints = db.query(Complaint).order_by(Complaint.id.asc()).all()
    rows: list[dict] = []

    for complaint in complaints:
        ai_output = _latest_ai_output(complaint.ai_outputs)

        task: CleanupTask | None = complaint.cleanup_task
        proof_count = 0
        verified_any = False
        if task is not None and task.proofs:
            proof_count = len(task.proofs)
            verified_any = any(p.verification_status == "verified" for p in task.proofs)

        resolution_time_seconds = None
        if complaint.resolved_at and complaint.created_at:
            delta = complaint.resolved_at - complaint.created_at
            if delta.total_seconds() >= 0:
                resolution_time_seconds = int(delta.total_seconds())

        created = complaint.created_at
        rows.append(
            {
                "complaint_id": complaint.id,
                "tracking_id": complaint.tracking_id,
                "waste_type": complaint.waste_type,           # final (human-decided) value
                "severity": complaint.quantity_severity,
                "intervention_required": (
                    None if complaint.intervention_required is None
                    else bool(complaint.intervention_required)
                ),
                "latitude": complaint.latitude,
                "longitude": complaint.longitude,
                "ward": derive_ward(complaint.address_text),
                "date": created.date().isoformat() if created else None,
                "hour": created.hour if created else None,
                "day_of_week": created.strftime("%A") if created else None,
                "priority": complaint.priority,
                "triage_mode": complaint.triage_mode,
                "ai_confidence": ai_output.confidence if ai_output else None,
                "ai_model_name": ai_output.model_name if ai_output else None,
                "human_review_required": bool(complaint.review_required),
                "correction_count": len(complaint.corrections),
                "cleaner_assigned": task.assigned_cleaner_id if task else None,
                "proof_attempts": proof_count,
                "proof_verified": verified_any if task is not None else None,
                "final_status": complaint.status,
                "resolution_time_seconds": resolution_time_seconds,
                "source": complaint.source,
                "is_synthetic": complaint.source == "seed",
            }
        )
    return rows


def export_mining_csv(rows: list[dict]) -> str:
    """Serialize mining rows to CSV text with the canonical field order."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=MINING_FIELDNAMES, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
