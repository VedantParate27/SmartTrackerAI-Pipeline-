"""
Adapter between the existing FastAPI routes and the Phase 2 AI engine.

The backend routes keep their existing function interface:
classify_and_extract(), generate_draft_response(), entities_to_json()

The actual AI work is performed by ai/src/.
"""

import json
import sys
from pathlib import Path

# Phase 2 AI files use local imports such as "from config import ...".
# Adding ai/src to sys.path lets those modules work when called by FastAPI.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
AI_SRC = PROJECT_ROOT / "ai" / "src"

if str(AI_SRC) not in sys.path:
    sys.path.insert(0, str(AI_SRC))

from classifier import classify_complaint
from retrieval import hybrid_search, rerank
from generator import generate_response


def classify_and_extract(complaint_text: str) -> dict:
    """
    Run Phase 2 classification while preserving the backend's
    existing return format.
    """
    result = classify_complaint(complaint_text)

    return {
        "category": result["category"],
        "department": result["department"],
        "confidence_score": result.get("confidence", 0.0),
        "extracted_entities": result.get("entities", {}),
    }


def generate_draft_response(
    complaint_text: str,
    entities: dict,
    department: str
) -> str:
    """
    Run Phase 2 retrieval, reranking and grounded response generation.

    The entities argument is retained for compatibility with the
    existing backend route.
    """
    candidates = hybrid_search(
        complaint_text,
        department,
        top_k=10
    )

    ranked_chunks = rerank(
        complaint_text,
        candidates,
        top_k=3
    )

    chunks = [
        (doc, meta)
        for doc, meta, _score in ranked_chunks
    ]

    return generate_response(complaint_text, chunks)


def entities_to_json(entities: dict) -> str:
    return json.dumps(entities)