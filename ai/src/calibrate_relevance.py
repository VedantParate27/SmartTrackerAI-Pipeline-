"""
One-time calibration script: checks whether the cross-encoder's relevance
scores meaningfully separate "correct department match" from "wrong
department match," so we can pick a real, evidence-based threshold
rather than guessing one.
"""
from retrieval import hybrid_search, rerank
import statistics

# Each case: a complaint, its CORRECT department, and one INCORRECT department
# deliberately mismatched, to see how much the score drops for irrelevant results.
CALIBRATION_CASES = [
    {"text": "my order hasn't arrived in 3 weeks, order ORD-1234", "correct_dept": "logistics", "wrong_dept": "billing"},
    {"text": "I was charged twice for my subscription this month", "correct_dept": "billing", "wrong_dept": "tech_support"},
    {"text": "I can't log into my account, getting error E-402", "correct_dept": "tech_support", "wrong_dept": "logistics"},
    {"text": "I need my account deleted, this is a GDPR request", "correct_dept": "customer_service", "wrong_dept": "billing"},
    {"text": "why is my invoice showing $49.99 instead of $29.99", "correct_dept": "billing", "wrong_dept": "customer_service"},
]


def get_top_score(text, department):
    candidates = hybrid_search(text, department, top_k=5)
    ranked = rerank(text, candidates, top_k=3)
    if not ranked:
        return None
    return ranked[0][2]  # top (doc, meta, score) tuple's score


def run_calibration():
    correct_scores = []
    wrong_scores = []

    for case in CALIBRATION_CASES:
        correct_score = get_top_score(case["text"], case["correct_dept"])
        wrong_score = get_top_score(case["text"], case["wrong_dept"])

        print(f"\nComplaint: {case['text'][:60]}...")
        print(f"  Correct dept ({case['correct_dept']}): {correct_score}")
        print(f"  Wrong dept   ({case['wrong_dept']}): {wrong_score}")

        if correct_score is not None:
            correct_scores.append(correct_score)
        if wrong_score is not None:
            wrong_scores.append(wrong_score)

    print("\n" + "=" * 60)
    print("CALIBRATION SUMMARY")
    print("=" * 60)
    if correct_scores:
        print(f"Correct-match scores: min={min(correct_scores):.4f}, max={max(correct_scores):.4f}, avg={statistics.mean(correct_scores):.4f}")
    if wrong_scores:
        print(f"Wrong-match scores:   min={min(wrong_scores):.4f}, max={max(wrong_scores):.4f}, avg={statistics.mean(wrong_scores):.4f}")

    if correct_scores and wrong_scores:
        gap = min(correct_scores) - max(wrong_scores)
        print(f"\nGap between worst-correct and best-wrong: {gap:.4f}")
        if gap > 0:
            suggested_threshold = (min(correct_scores) + max(wrong_scores)) / 2
            print(f"Clean separation found. Suggested threshold: {suggested_threshold:.4f}")
        else:
            print("No clean separation — correct and wrong-department scores overlap.")
            print("A fixed relevance threshold is not reliable for this model/domain.")


if __name__ == "__main__":
    run_calibration()