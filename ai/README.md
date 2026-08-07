# SmartTracker AI — AI Module

## What this does
Takes a raw customer complaint (plain text) and returns:
- A category and department classification
- Extracted entities (order ID, account ID, error code)
- Relevant policy citations, retrieved via hybrid search (semantic + keyword)
- A grounded draft response — generated using ONLY the retrieved policy text, to prevent hallucinated promises

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
    "order_id": "string or null",
    "account_id": "string or null",
    "error_code": "string or null"
  },
  "summary": "one-sentence summary of the complaint",
  "retrieved_sources": ["list of policy document filenames used"],
  "draft_response": "the full grounded draft reply as a string"
}
```

## Setup (for anyone running this locally)
1. Python 3.11+
2. `pip install -r requirements.txt`
3. Create a `.env` file in the project root with: `GOOGLE_API_KEY=your_key_here`
4. Run `python src/ingest.py` once to populate the vector database from `data/policies/`
5. Test with `python src/pipeline.py`

## Important notes for integration
- **This currently uses placeholder policy documents** in `data/policies/`. Once the real project database/policy documents are provided, they'll replace these files, and `ingest.py` will be re-run — no other code changes needed on this end.
- **Gemini free-tier quota is 20 requests/day per model.** The pipeline automatically falls back between `gemini-3.5-flash-lite` and `gemini-3.6-flash` if one is rate-limited or unavailable, but be aware of this when testing in bulk.
- `process_complaint()` currently makes 2 API calls per complaint (1 classification + 1 generation), so budget quota accordingly during integration testing.