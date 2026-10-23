"""
Dedicated test suite for low-confidence handling. Each case is deliberately
ambiguous, contradictory, or under-specified — designed to genuinely
challenge the classifier rather than have one clear right answer. Pass
criterion: the system should recognize its own uncertainty (confidence
below threshold) and flag for human review, rather than confidently
guessing.
"""
from pipeline import process_complaint
from config import CONFIDENCE_THRESHOLD
import json
import time

LOW_CONFIDENCE_TEST_CASES = [
    "not sure if this is a billing thing or a delivery thing but something's wrong with my last order",
    "My refund arrived but I never asked for one and also I love your service but I want to cancel everything",
    "refund??",
    "this is either a bug or I'm just confused, not sure which",
    "something happened with my account, don't know if it's serious or not",
    "half the time it works, half the time it doesn't, not sure if that's a big deal",
    "I have a question that's kind of about billing but also kind of not",
]


def run_low_confidence_tests():
    total = len(LOW_CONFIDENCE_TEST_CASES)
    correctly_flagged = 0
    results = []

    for i, text in enumerate(LOW_CONFIDENCE_TEST_CASES, start=1):
        print(f"\n{'='*70}")
        print(f"CASE {i}/{total}: {text}")
        print('='*70)

        try:
            result = process_complaint(text)
            confidence = result.get("confidence")
            flagged = result.get("needs_human_review")
            reasons = result.get("review_reasons", [])
            has_confidence_reason = any("low_classification_confidence" in r for r in reasons)

            print(f"confidence: {confidence}")
            print(f"needs_human_review: {flagged}")
            print(f"review_reasons: {reasons}")

            case_correct = confidence is not None and confidence < CONFIDENCE_THRESHOLD and has_confidence_reason
            if case_correct:
                correctly_flagged += 1

            results.append({
                "text": text,
                "confidence": confidence,
                "correctly_flagged": case_correct,
            })

        except Exception as e:
            print(f"CRASHED: {type(e).__name__}: {e}")
            results.append({"text": text, "correctly_flagged": False, "error": str(e)})

        time.sleep(4)

    print(f"\n\n{'='*70}")
    print("LOW-CONFIDENCE TEST SUMMARY")
    print('='*70)
    print(f"Correctly flagged as low-confidence: {correctly_flagged}/{total} ({correctly_flagged/total*100:.1f}%)")
    print("\nNote: a case NOT being flagged doesn't necessarily mean failure —")
    print("it may mean the model found a genuinely confident, correct reading")
    print("of a case we assumed was ambiguous. Review each case's actual")
    print("classification before concluding this is a false negative.")

    for r in results:
        if not r.get("correctly_flagged"):
            print(f"\nNOT flagged: \"{r['text']}\" (confidence: {r.get('confidence')})")


if __name__ == "__main__":
    run_low_confidence_tests()