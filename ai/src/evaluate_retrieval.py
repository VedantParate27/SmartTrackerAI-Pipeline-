"""
Evaluates RETRIEVAL quality: given a complaint and its correct department,
does hybrid_search + rerank actually surface the policy chunk containing
the expected fact? This is separate from classifier accuracy — it isolates
retrieval performance specifically.
"""
from retrieval import hybrid_search, rerank
from rag_eval_data import RAG_TEST_CASES
import json


def run_retrieval_evaluation():
    total = len(RAG_TEST_CASES)
    correct = 0
    failures = []

    for i, case in enumerate(RAG_TEST_CASES, start=1):
        candidates = hybrid_search(case["text"], case["department"], top_k=5)
        ranked = rerank(case["text"], candidates, top_k=3)

        # Check if the expected keyword appears in ANY of the top retrieved chunks
        combined_text = " ".join(doc.lower() for doc, meta, score in ranked)
        found = case["expected_keyword"].lower() in combined_text

        status = "PASS" if found else "FAIL"
        print(f"Case {i}/{total}: {status} — expected '{case['expected_keyword']}'")

        if found:
            correct += 1
        else:
            failures.append({
                "text": case["text"],
                "department": case["department"],
                "expected_keyword": case["expected_keyword"],
                "retrieved_sources": [meta["source"] for _, meta, _ in ranked],
                "top_score": ranked[0][2] if ranked else None,
            })

    print("\n" + "=" * 60)
    print("RETRIEVAL EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Retrieval accuracy: {correct}/{total} ({correct/total*100:.1f}%)")

    if failures:
        print(f"\n--- {len(failures)} FAILURE(S) ---")
        for f in failures:
            print(json.dumps(f, indent=2))
    else:
        print("\nNo failures — retrieval found the expected fact in every case.")


if __name__ == "__main__":
    run_retrieval_evaluation()