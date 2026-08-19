from .classifier import classify_complaint
from .retrieval import hybrid_search
from .generator import generate_response


def process_complaint(text: str) -> dict:
    """
    The single entry point for the AI module.

    Input: raw complaint text (a string)
    Output: a dictionary containing everything downstream systems need —
            classification, routing info, sources used, and the draft reply.
    """
    classification = classify_complaint(text)
    chunks = hybrid_search(text, classification["department"])
    draft = generate_response(text, chunks)

    return {
        "complaint_text": text,
        "category": classification["category"],
        "department": classification["department"],
        "urgency": classification["urgency"],
        "confidence": classification.get("confidence", 0.0),
        "entities": classification["entities"],
        "summary": classification["summary"],
        "retrieved_sources": [meta["source"] for _, meta in chunks],
        "draft_response": draft,
    }


if __name__ == "__main__":
    import json

    test_complaints = [
        "my order hasn't arrived in 3 weeks, order ORD-1234",
        "I was charged twice for my subscription this month",
        "I can't log into my account, getting error E-402",
    ]

    for complaint in test_complaints:
        print(f"\n{'='*60}")
        print(f"COMPLAINT: {complaint}")
        print("=" * 60)
        result = process_complaint(complaint)
        print(json.dumps(result, indent=2))
