# SmartTracker AI Module (Member 3)

## What this does
Takes a raw customer complaint (plain text) and returns a full triage result: classification, routing, extracted entities, retrieved policy citations, a grounded draft response, and automatic flags for anything that needs human review.

## How to call it
```python
from src.pipeline import process_complaint

result = process_complaint("my order hasn't arrived in 3 weeks, order ORD-1234")
```

## Output shape
```json
{
  "complaint_text": "string",
  "category": "billing | technical | delivery | refund | account | other",
  "department": "billing | tech_support | logistics | customer_service",
  "urgency": "low | medium | high",
  "entities": {
    "order_ids": ["string", "..."],
    "account_id": "string or null",
    "error_code": "string or null"
  },
  "summary": "one-sentence summary",
  "confidence": 0.0,
  "retrieved_sources": ["policy filenames used"],
  "top_retrieval_score": 0.0,
  "draft_response": "the grounded draft reply",
  "citation_check": {
    "cited": ["..."], "valid": ["..."], "invalid": ["..."], "fully_grounded": true
  },
  "needs_human_review": false,
  "review_reasons": ["..."],
  "errors": ["..."],
  "db_id": 1
}
```

## Setup
1. Python 3.11+
2. `pip install -r requirements.txt`
3. Create a `.env` in `ai/` with: `GOOGLE_API_KEY=your_key_here`
4. Update paths in `src/config.py` (`PROJECT_ROOT`) to match wherever this repo lives locally
5. Run `python src/ingest.py` once to populate the vector database from `data/policies/`
6. Test with `python src/pipeline.py`

## Key files
- `src/pipeline.py` — main entry point, `process_complaint()`
- `src/classifier.py` — Gemini-based classification (structured output, confidence scoring)
- `src/retrieval.py` — hybrid search (vector + BM25 + RRF) with cross-encoder reranking
- `src/generator.py` — grounded draft response generation
- `src/verification.py` — post-generation citation verification
- `src/storage.py` — persists every result to `admin_review.db` (SQLite) for admin review
- `src/config.py` — all tunable constants (models, thresholds, paths)
- `src/evaluate.py` / `src/evaluate_retrieval.py` — accuracy evaluation scripts
- `data/policies/` — placeholder policy documents (to be replaced with real company policies)

## Integration notes
- **This currently writes to its own local SQLite database** (`admin_review.db`) as a placeholder for admin review — this is separate from the backend's `smarttracker.db`. These likely need to be reconciled with Member 2 so results end up in one shared database instead of two.
- **Policy documents are placeholders.** Once real policies are provided, replace files in `data/policies/` and re-run `ingest.py` — no other code changes needed.
- **Gemini free-tier quota is 20 requests/day per model**, with automatic fallback between models. Budget accordingly during integration testing.
- Every result includes a `needs_human_review` flag and `review_reasons` — the admin dashboard (frontend `/admin` routes) should surface these prominently.