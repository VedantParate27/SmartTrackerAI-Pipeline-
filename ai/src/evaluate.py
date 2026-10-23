"""
Runs the classifier against a labeled test set and reports accuracy metrics.
Re-run this anytime you change the classifier prompt or logic to check
whether you improved or regressed accuracy.
"""
from numpy import rint

from classifier import classify_complaint
from eval_data import TEST_CASES
import json
import time


def run_evaluation():
    # Split out cases we've identified as genuinely ambiguous — we still run
    # them (useful to observe behavior), but we don't count them in the
    # pass/fail score, since there's no single objectively correct answer.
    scored_cases = [c for c in TEST_CASES if not c.get("known_ambiguous")]
    ambiguous_cases = [c for c in TEST_CASES if c.get("known_ambiguous")]
    total = len(scored_cases)

    category_correct = 0
    department_correct = 0
    urgency_correct = 0
    urgency_scored = 0
    failures = []
    urgency_mismatches = []

    case_number = 0
    total_all = len(TEST_CASES)

    for case in TEST_CASES:
        case_number += 1
        print(f"Running case {case_number}/{total_all}...", end=" ")
        try:
            result = classify_complaint(case["text"])
        except Exception as e:
            print(f"CRASHED: {e}")
            failures.append({"text": case["text"], "error": str(e)})
            time.sleep(4)
            continue

        if case.get("known_ambiguous"):
            print(f"SKIPPED (known ambiguous) — got category={result['category']}, department={result['department']}")
            time.sleep(4)
            continue

        cat_match = result["category"] == case["expected_category"]
        dept_match = result["department"] == case["expected_department"]

        category_correct += cat_match
        department_correct += dept_match

        if case["expected_urgency"] is not None:
            urgency_scored += 1
            urgency_match = result["urgency"] == case["expected_urgency"]
            urgency_correct += urgency_match

        status = "PASS" if (cat_match and dept_match) else "FAIL"
        urgency_note = ""
        if case["expected_urgency"] is not None and not urgency_match:
            urgency_note = f" (urgency mismatch: expected={case['expected_urgency']}, got={result['urgency']})"
            urgency_mismatches.append({
                "text": case["text"],
                "expected_urgency": case["expected_urgency"],
                "actual_urgency": result["urgency"],
            })
        print(status + urgency_note)

        if not cat_match or not dept_match:
            failures.append({
                "text": case["text"],
                "expected": {
                    "category": case["expected_category"],
                    "department": case["expected_department"],
                    "urgency": case["expected_urgency"],
                },
                "actual": {
                    "category": result["category"],
                    "department": result["department"],
                    "urgency": result["urgency"],
                },
            })

        time.sleep(4)  # stay comfortably under the 15-requests/minute limit

    # --- Print summary report ---
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Total scored cases:      {total}  (+{len(ambiguous_cases)} excluded as known-ambiguous)")
    print(f"Category accuracy:       {category_correct}/{total} ({category_correct/total*100:.1f}%)")
    print(f"Department accuracy:     {department_correct}/{total} ({department_correct/total*100:.1f}%)")
    if urgency_scored > 0:
        print(f"Urgency accuracy:        {urgency_correct}/{urgency_scored} ({urgency_correct/urgency_scored*100:.1f}%) [scored cases only]")
        if urgency_mismatches:
            print(f"\n--- {len(urgency_mismatches)} URGENCY MISMATCH(ES) (category/dept still correct) ---")
            for u in urgency_mismatches:
                print(json.dumps(u, indent=2))
    if failures:
        print(f"\n--- {len(failures)} FAILURE(S) / CRASH(ES) ---")
        for f in failures:
            print(json.dumps(f, indent=2))
    else:
        print("\nNo failures — all scored cases passed category + department checks.")


if __name__ == "__main__":
    run_evaluation()