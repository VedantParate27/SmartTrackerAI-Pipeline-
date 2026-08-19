# SmartTracker AI

Grievance handling system: complaints submitted → classified & matched
against policy docs via RAG → draft response generated → admin approves →
resolved.

## Structure

```
smarttracker-ai/
├── backend/            FastAPI app (routes, db, schema)
│   ├── main.py          5 routes: submit, process, get, admin queue, approve
│   ├── db.py             sqlite3 connection dependency
│   ├── ai_pipeline.py    adapter: routes call this, this calls ai/
│   ├── schema.sql
│   ├── seed.sql
│   └── test_smoke.py
├── ai/                  RAG engine (classification, retrieval, generation)
│   ├── common.py         shared config + Gemini retry helper
│   ├── classifier.py     Gemini: category/department/urgency/entities
│   ├── retrieval.py      hybrid vector + BM25 search over ChromaDB
│   ├── generator.py      Gemini: grounded, cited draft response
│   └── pipeline.py       orchestrates the three above
├── data/policies/       policy .txt files, ingested into ChromaDB
├── chroma_setup.py      run once to populate ChromaDB from data/policies/
└── requirements.txt
```

## Setup (Windows/PowerShell)

```powershell
py -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env
# edit .env and set GOOGLE_API_KEY

cd backend
python ..\Database\init_db.py   # if you keep a separate init script, else:
# sqlite3 smarttracker.db < schema.sql
# sqlite3 smarttracker.db < seed.sql
cd ..

python chroma_setup.py          # ingest policy docs into ChromaDB (one-time)

cd backend
uvicorn main:app --reload
```

## Notes / things worth double-checking

- **Gemini model IDs**: `classifier.py` and `generator.py` try
  `gemini-3.6-flash` then `gemini-3.5-flash-lite`. These were carried over
  from the original code and were not verified against Google's current
  model list — check before relying on them.
- **`confidence_score`**: the original AI module never emitted this field
  even though `schema.sql` has a column for it. I added a `confidence`
  field to the classifier's prompt/output so it flows through end-to-end.
- Deleted as duplicates/dead weight: `smarttracker-backend/` (86MB, mostly
  a checked-in `venv/`, no AI integration), `backend/` (SQLAlchemy + JWT
  auth, but never called the AI pipeline at all), and the loose top-level
  `Database/` folder and stray `.db` files (schema was duplicated 3x).
