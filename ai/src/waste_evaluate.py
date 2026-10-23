import os
import time
import json
import mimetypes
from waste_pipeline import process_waste_image
from waste_eval_data import WASTE_TEST_CASES
from config import PROJECT_ROOT

IMAGES_FOLDER = os.path.join(PROJECT_ROOT, "images")


def run_waste_evaluation():
    all_cases = len(WASTE_TEST_CASES)
    ambiguous = [c for c in WASTE_TEST_CASES if c.get("known_ambiguous")]
    total = all_cases - len(ambiguous)
    usable_correct = waste_type_correct = severity_correct = escalate_correct = 0
    failures = []

    for i, case in enumerate(WASTE_TEST_CASES, start=1):
        print(f"Running case {i}/{all_cases}: {case['image']}...", end=" ")
        image_path = os.path.join(IMAGES_FOLDER, case["image"])
        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            mime_type, _ = mimetypes.guess_type(image_path)
            result = process_waste_image(image_bytes, mime_type=mime_type or "image/jpeg")

            if case.get("known_ambiguous"):
                print(f"SKIPPED (known ambiguous): got waste_type={result['waste_type']}, severity={result['severity']}")
                time.sleep(4)
                continue

            usable_match = result["image_usable"] == case["expected_usable"]
            type_match = result["waste_type"] == case["expected_waste_type"]
            severity_match = result["severity"] == case["expected_severity"]
            escalate_match = result["escalate_to_authority"] == case["expected_escalate"]
            usable_correct += usable_match
            waste_type_correct += type_match
            severity_correct += severity_match
            escalate_correct += escalate_match

            ok = usable_match and type_match and severity_match and escalate_match
            print("PASS" if ok else "FAIL")
            if not ok:
                failures.append({
                    "image": case["image"],
                    "expected": {"usable": case["expected_usable"], "waste_type": case["expected_waste_type"],
                                 "severity": case["expected_severity"], "escalate": case["expected_escalate"]},
                    "actual": {"usable": result["image_usable"], "waste_type": result["waste_type"],
                               "severity": result["severity"], "escalate": result["escalate_to_authority"]},
                    "source": result.get("source"),
                })
        except Exception as e:
            print(f"CRASHED: {e}")
            failures.append({"image": case["image"], "error": str(e)})
        time.sleep(4)

    print("\n" + "=" * 60)
    print("WASTE EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Scored cases:           {total}  (+{len(ambiguous)} excluded as known-ambiguous)")
    print(f"Usability accuracy:     {usable_correct}/{total} ({usable_correct/total*100:.1f}%)")
    print(f"Waste-type accuracy:    {waste_type_correct}/{total} ({waste_type_correct/total*100:.1f}%)")
    print(f"Severity accuracy:      {severity_correct}/{total} ({severity_correct/total*100:.1f}%)")
    print(f"Escalation accuracy:    {escalate_correct}/{total} ({escalate_correct/total*100:.1f}%)")
    if failures:
        print(f"\n--- {len(failures)} FAILURE(S) ---")
        for f in failures:
            print(json.dumps(f, indent=2))
    else:
        print("\nNo failures.")


if __name__ == "__main__":
    run_waste_evaluation()