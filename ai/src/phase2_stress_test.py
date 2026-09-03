"""
End-to-end Phase 2 stress test: verifies confidence flagging, retrieval-
relevance flagging, citation verification, and storage all work correctly
together under harder real-world-style inputs.
"""
from pipeline import process_complaint
from storage import get_pending_review
import json
import time

PHASE2_STRESS_CASES = [
    # Genuinely ambiguous — should trigger low classification confidence
    "not sure if this is a billing thing or a delivery thing but something's wrong with my last order",

    # Complaint about something with zero policy coverage at all
    "do you guys support integrations with Slack for order notifications?",

    # Clear complaint but phrased in a way that might retrieve weakly
    "yo my stuff never came lol whats up with that",

    # Straightforward, should sail through with no flags
    "I need a refund for order ORD-7000, it was damaged when it arrived",

    # A complaint entirely about something never covered in any policy
    "can I pay in installments using Klarna?",
]


def run_phase2_stress_test():
    for i, text in enumerate(PHASE2_STRESS_CASES, start=1):
        print(f"\n{'='*70}")
        print(f"CASE {i}/{len(PHASE2_STRESS_CASES)}: {text}")
        print('='*70)
        try:
            result = process_complaint(text)
            print(f"needs_human_review: {result['needs_human_review']}")
            print(f"review_reasons: {result['review_reasons']}")
            print(f"confidence: {result['confidence']}")
            print(f"top_retrieval_score: {result.get('top_retrieval_score')}")
            print(f"citation_check.fully_grounded: {result.get('citation_check', {}).get('fully_grounded')}")
            print(f"db_id: {result.get('db_id')}")
            print(f"errors: {result['errors']}")
        except Exception as e:
            print(f"CRASHED: {type(e).__name__}: {e}")
        time.sleep(4)

    print(f"\n\n{'='*70}")
    print("ADMIN REVIEW QUEUE AFTER THIS RUN")
    print('='*70)
    pending = get_pending_review()
    for r in pending:
        print(f"id={r['id']}, dept={r['department']}, reasons={r['review_reasons_json']}")


if __name__ == "__main__":
    run_phase2_stress_test()