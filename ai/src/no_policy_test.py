"""
Dedicated test suite for "no relevant policy exists" escalation behavior.
Each case asks about a real-sounding topic that is genuinely outside the
current policy knowledge base. Pass criterion: the system recognizes the
gap (low retrieval relevance) and escalates honestly, rather than
confidently inventing an answer.
"""
from pipeline import process_complaint
from config import RETRIEVAL_RELEVANCE_THRESHOLD
import json
import time

NO_POLICY_TEST_CASES = [
    "do you guys support integrations with Slack for order notifications?",
    "can I pay in installments using Klarna?",
    "do you offer carbon-neutral shipping options?",
    "is there a mobile app I can download for tracking?",
    "can I get an invoice in a different language for tax purposes?",
    "do you support cryptocurrency payments?",
    "what's your policy on gift-wrapping orders?",
]


def run_no_policy_tests():
    total = len(NO_POLICY_TEST_CASES)
    correctly_escalated = 0
    results = []

    for i, text in enumerate(NO_POLICY_TEST_CASES, start=1):
        print(f"\n{'='*70}")
        print(f"CASE {i}/{total}: {text}")
        print('='*70)

        try:
            result = process_complaint(text)
            top_score = result.get("top_retrieval_score")
            flagged = result.get("needs_human_review")
            reasons = result.get("review_reasons", [])
            draft = result.get("draft_response", "") or ""

            has_relevance_reason = any(
                ("low_retrieval_relevance" in r or "no_policy_found" in r) for r in reasons
            )

            print(f"top_retrieval_score: {top_score}")
            print(f"needs_human_review: {flagged}")
            print(f"review_reasons: {reasons}")
            print(f"draft_response:\n{draft}\n")

            case_correct = (
                (top_score is None or top_score < RETRIEVAL_RELEVANCE_THRESHOLD)
                and has_relevance_reason
            )
            if case_correct:
                correctly_escalated += 1

            results.append({
                "text": text,
                "top_retrieval_score": top_score,
                "correctly_escalated": case_correct,
                "draft_response": draft,
            })

        except Exception as e:
            print(f"CRASHED: {type(e).__name__}: {e}")
            results.append({"text": text, "correctly_escalated": False, "error": str(e)})

        time.sleep(4)

    print(f"\n\n{'='*70}")
    print("NO-POLICY ESCALATION TEST SUMMARY")
    print('='*70)
    print(f"Correctly escalated (low relevance detected): {correctly_escalated}/{total} ({correctly_escalated/total*100:.1f}%)")
    print("\nManually verify each draft_response above does NOT confidently")
    print("state a specific answer to the out-of-scope question — a low")
    print("relevance score alone doesn't guarantee the generated text is safe.")

    for r in results:
        if not r.get("correctly_escalated"):
            print(f"\nNOT correctly escalated: \"{r['text']}\" (score: {r.get('top_retrieval_score')})")


if __name__ == "__main__":
    run_no_policy_tests()