"""
Real AI pipeline, replacing the old placeholder. Routes in main.py are
unchanged - they still call classify_and_extract(), generate_draft_response(),
and entities_to_json() exactly as before. This file just adapts those calls
onto the real RAG engine in ../ai/.
"""
import json
import sys
from pathlib import Path

# Make the sibling ai/ package importable (backend/ and ai/ are sibling
# folders under the project root).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.classifier import classify_complaint
from ai.retrieval import hybrid_search
from ai.generator import generate_response


def classify_and_extract(complaint_text: str) -> dict:
    """
    Returns: category (str), department (str), confidence_score (float 0-1),
    extracted_entities (dict). Matches the columns in schema.sql.
    """
    result = classify_complaint(complaint_text)
    return {
        "category": result["category"],
        "department": result["department"],
        "confidence_score": result.get("confidence", 0.0),
        "extracted_entities": result.get("entities", {}),
    }


def generate_draft_response(complaint_text: str, entities: dict, department: str) -> str:
    """
    Runs hybrid retrieval against the department's policy chunks in ChromaDB,
    then generates a grounded, cited draft response with Gemini.

    department comes from the classify_and_extract() call the route already
    made - passing it in avoids re-classifying the same text twice.
    """
    chunks = hybrid_search(complaint_text, department)
    return generate_response(complaint_text, chunks)


def entities_to_json(entities: dict) -> str:
    return json.dumps(entities)
