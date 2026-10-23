# task_timeline.py
# Single source of truth for the CLEANUP-TASK lifecycle timestamps.
#
# TIMESTAMP SEMANTICS (fixed, auditable, and never reinterpreted):
#   assigned_at             — when the task was assigned to a cleaner.
#   started_at              — when the cleaner GENUINELY started the work.
#                              Written once by POST /cleaner/tasks/{id}/start
#                              and never reset afterwards.
#   first_proof_uploaded_at — when the FIRST proof was uploaded for the task.
#                              This is a PROXY for the end of the cleaning work,
#                              not a verified physical finish time.
#   completed_at            — when an ADMIN verified the proof. It is the
#                              verification timestamp, NOT the physical end of
#                              the cleanup. It must never be used as a
#                              cleaning-duration endpoint.
#
# WHY THE FIRST-PROOF TIMESTAMP IS DERIVED AND NOT STORED
# ------------------------------------------------------
# CleanupProof.uploaded_at is NOT NULL and is written at insert time, and the
# live workflow only ever APPENDS proofs to a task (the single deletion path —
# the seeder's clear_seeded_data() — removes the whole task together with its
# proofs). The earliest upload of a task is therefore exactly its first proof
# upload, so the value is derived from the proof history instead of being
# duplicated into a second column. Deriving keeps one source of truth, needs no
# migration, and can never drift out of sync with the proofs it summarises.
#
# MIN(uploaded_at) is deliberately taken over ALL proofs of a task, including a
# proof that was later rejected: "first proof upload" is a historical fact and
# does not change when an admin rejects that attempt.

from datetime import datetime
from typing import Iterable, Optional

from models import CleanupProof


def first_proof_uploaded_at(proofs: Iterable[CleanupProof]) -> Optional[datetime]:
    """Return the earliest proof-upload timestamp among the given proofs.

    Returns None when the task has no proof yet (no upload has happened).
    The comparison is over timestamps read from the same column of the same
    table, so they are always mutually comparable.
    """
    earliest: Optional[datetime] = None
    for proof in proofs:
        uploaded_at = proof.uploaded_at
        if uploaded_at is None:
            continue
        if earliest is None or uploaded_at < earliest:
            earliest = uploaded_at
    return earliest
