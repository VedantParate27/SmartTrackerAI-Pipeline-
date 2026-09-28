# taxonomy.py
# Central, single-source-of-truth constants for the research-oriented backend.
#
# Every router, schema, and service imports from here so that categorical
# values are consistent across the whole system. The DWM mining export and
# the event-log activity vocabulary both depend on these values, so they
# must not drift.

# ---------------------------------------------------------------------------
# Complaint categorical values
# ---------------------------------------------------------------------------
# Final waste-type taxonomy (6 classes). Matches the AI team's label set.
WASTE_TYPES = ("dry", "wet", "e_waste", "medical", "hazardous", "bulk")

# Quantity / severity levels (3 classes).
SEVERITIES = ("small", "medium", "large")

# Waste categories that always require human review regardless of confidence.
HAZARDOUS_WASTE_TYPES = ("medical", "hazardous")

COMPLAINT_STATUSES = ("pending", "in_progress", "resolved", "closed")
PRIORITIES = ("low", "medium", "high", "urgent")
TASK_STATUSES = ("assigned", "in_progress", "proof_submitted", "verified", "rejected")
ROLES = ("citizen", "cleaner", "staff", "admin")

# Where a complaint row came from. "seed" marks synthetic research data so it
# can always be separated from real citizen submissions.
COMPLAINT_SOURCES = ("citizen", "seed")

# Triage handling modes (research comparison cohorts).
TRIAGE_MODES = ("manual", "ai_assisted")

# Escalation / triage configuration -----------------------------------------
# Default confidence threshold below which AI output is escalated for
# mandatory human review. The AI team may override per request via
# threshold_used; the escalation rule itself lives in triage.py.
DEFAULT_CONFIDENCE_THRESHOLD = 0.7

# ---------------------------------------------------------------------------
# Event-log vocabulary (controlled — required for process mining)
# ---------------------------------------------------------------------------
# Core workflow activities. Process mining (pm4py) treats these as the
# activity labels, so they are deliberately a small, controlled set.
EVENT_ACTIVITIES = (
    "complaint_created",
    "ai_prediction_generated",
    "human_review_required",
    "human_review_completed",
    "admin_decision_made",
    "dispatch_decided",
    "guidance_decided",
    "cleaner_assigned",
    "cleaner_reassigned",
    "task_started",
    "proof_submitted",
    "proof_verified",
    "proof_rejected",
    "complaint_resolved",
    "complaint_closed",
    # Extension events (documented in INTEGRATION_CONTRACTS.md):
    "complaint_updated",   # admin PUT field changes that are not status moves
    "ai_correction_recorded",  # one event per corrected field
)

# Actor roles recorded on events. "ai_system" is the AI service itself,
# "system" is background/seed machinery.
EVENT_ACTOR_ROLES = ("citizen", "ai_system", "admin", "cleaner", "system")

# ---------------------------------------------------------------------------
# Priority derivation rule (documented workflow rule, NOT a mining result)
# ---------------------------------------------------------------------------
def compute_priority(quantity_severity, waste_type, intervention_required):
    """Derive complaint priority from structured triage inputs.

    Rule (fixed and documented so it is auditable, and so historical rows are
    comparable across the study):
      - hazardous waste type                     -> urgent
      - medical waste type                       -> high
      - severity "large" and intervention        -> high
      - severity "large" without intervention    -> medium
      - severity "small"                         -> low
      - anything else                            -> medium
    Unknown/None inputs fall through to the next applicable rule.
    """
    if waste_type == "hazardous":
        return "urgent"
    if waste_type == "medical":
        return "high"
    if quantity_severity == "large":
        return "high" if intervention_required else "medium"
    if quantity_severity == "small":
        return "low"
    return "medium"
