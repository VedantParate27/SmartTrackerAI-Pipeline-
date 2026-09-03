from classifier import classify_complaint
from retrieval import hybrid_search, rerank
from generator import generate_response
from config import CONFIDENCE_THRESHOLD
from config import RETRIEVAL_RELEVANCE_THRESHOLD
from verification import verify_citations
from storage import save_result

def process_complaint(text: str) -> dict:
    """
    The single entry point for the AI module.

    Input: raw complaint text (a string)
    Output: a dictionary containing everything downstream systems need.
    If a step fails, the result still includes whatever succeeded, plus
    an "errors" list describing what went wrong and where — instead of
    crashing the whole request.
    """
    result = {
        "complaint_text": text,
        "category": None,
        "department": None,
        "urgency": None,
        "entities": None,
        "summary": None,
        "confidence": None,
        "retrieved_sources": [],
        "draft_response": None,
        "needs_human_review": False,
        "review_reasons": [],
        "errors": [],
    }

    # --- Step 1: Classification ---
    try:
        classification = classify_complaint(text)
        result["category"] = classification["category"]
        result["department"] = classification["department"]
        result["urgency"] = classification["urgency"]
        result["entities"] = classification["entities"]
        result["summary"] = classification["summary"]
        result["confidence"] = classification["confidence"]

        if classification["confidence"] < CONFIDENCE_THRESHOLD:
            result["needs_human_review"] = True
            result["review_reasons"].append(
                f"low_classification_confidence: {classification['confidence']:.2f} (threshold: {CONFIDENCE_THRESHOLD})"
            )
    except Exception as e:
        result["errors"].append(f"classification_failed: {e}")
        result["draft_response"] = (
            "Unable to automatically classify this complaint. "
            "Escalating for manual review."
        )
        return result

        # --- Step 2: Retrieval ---
    chunks = []
    try:
        candidates = hybrid_search(text, result["department"], top_k=5)
        ranked_chunks = rerank(text, candidates, top_k=3)
        result["retrieved_sources"] = [meta["source"] for _, meta, _ in ranked_chunks]
        result["top_retrieval_score"] = ranked_chunks[0][2] if ranked_chunks else None

        if not ranked_chunks:
            result["errors"].append(
                f"retrieval_empty: no matching policy chunks found for department '{result['department']}'"
            )
            result["needs_human_review"] = True
            result["review_reasons"].append("no_policy_found")
        elif ranked_chunks[0][2] < RETRIEVAL_RELEVANCE_THRESHOLD:
            result["needs_human_review"] = True
            result["review_reasons"].append(
                f"low_retrieval_relevance: top match score {ranked_chunks[0][2]:.6f} (threshold: {RETRIEVAL_RELEVANCE_THRESHOLD})"
            )

        chunks = [(doc, meta) for doc, meta, _ in ranked_chunks]

    except Exception as e:
        result["errors"].append(f"retrieval_failed: {e}")
        # --- Step 3: Generation ---
    try:
        result["draft_response"] = generate_response(text, chunks)

        # Verify every citation in the draft actually traces back to a
        # real retrieved source — a rule-based safety net on top of the
        # prompt-level grounding instructions.
        verification = verify_citations(result["draft_response"], result["retrieved_sources"])
        result["citation_check"] = verification

        if not verification["fully_grounded"]:
            result["needs_human_review"] = True
            result["review_reasons"].append(
                f"unverified_citation: draft cites source(s) not in retrieved context: {verification['invalid']}"
            )
    except Exception as e:
        result["errors"].append(f"generation_failed: {e}")
        result["draft_response"] = (
            "Classification and retrieval succeeded, but an automated draft "
            "response could not be generated. Please write a manual response "
            "using the retrieved sources above."
        )
        result["citation_check"] = None

        # Persist the result so admins can review it later, including
    # anything flagged for human attention.
    try:
        result["db_id"] = save_result(result)
    except Exception as e:
        result["errors"].append(f"storage_failed: {e}")
        result["db_id"] = None

    return result


if __name__ == "__main__":
    import json

    test_complaints = [
        "my order hasn't arrived in 3 weeks, order ORD-1234",
        "I was charged twice for my subscription this month",
        "I can't log into my account, getting error E-402"
        "My refund arrived but I never asked for one and also I love your service but I want to cancel everything",
        "मेरा ऑर्डर अभी तक नहीं आया, बहुत बुरी सर्विस है"
    ]

    for complaint in test_complaints:
        print(f"\n{'='*60}")
        print(f"COMPLAINT: {complaint}")
        print('='*60)
        result = process_complaint(complaint)
        print(json.dumps(result, indent=2))