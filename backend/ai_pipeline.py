"""
Adapter between the existing FastAPI routes and the Phase 2 AI engine.

The backend routes keep their existing function interface:
classify_and_extract(), generate_draft_response(), entities_to_json()

The actual AI work is performed by ai/src/.
"""

import json
import importlib
import sys
from pathlib import Path

# The legacy AI modules use local imports such as "from config import ...".
# Keep their directory off sys.path until an AI operation is actually called so
# importing the FastAPI application does not eagerly load optional ML packages.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
AI_SRC = PROJECT_ROOT / "ai" / "src"

def _ai_module(name: str):
    if str(AI_SRC) not in sys.path:
        sys.path.insert(0, str(AI_SRC))
    return importlib.import_module(name)


def classify_and_extract(complaint_text: str) -> dict:
    """
    Run Phase 2 classification while preserving the backend's
    existing return format.
    """
    result = _ai_module("classifier").classify_complaint(complaint_text)

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
    retrieval = _ai_module("retrieval")
    candidates = retrieval.hybrid_search(
        complaint_text,
        department,
        top_k=10
    )

    ranked_chunks = retrieval.rerank(
        complaint_text,
        candidates,
        top_k=3
    )

    chunks = [
        (doc, meta)
        for doc, meta, _score in ranked_chunks
    ]

    return _ai_module("generator").generate_response(complaint_text, chunks)


def entities_to_json(entities: dict) -> str:
    return json.dumps(entities)


def process_waste_image(*args, **kwargs) -> dict:
    """Load the optional waste-image pipeline only when a complaint needs it."""
    return _ai_module("waste_pipeline").process_waste_image(*args, **kwargs)


def verify_cleanup(*args, **kwargs) -> dict:
    """Load the optional cleanup verifier only when a proof needs it."""
    return _ai_module("cleanup_verifier").verify_cleanup(*args, **kwargs)
