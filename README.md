# SmartTracker AI Pipeline

FastAPI + SQLite backend, TanStack Start frontend. Two terminals.

## 1. Backend — http://localhost:8000

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
python create_admin.py
uvicorn main:app --reload --port 8000
```

## 2. Frontend — http://localhost:3000

```bash
cd frontend
npm install
copy .env.example .env          # macOS/Linux: cp .env.example .env
npm run dev
```

## 3. Use it

```
http://localhost:3000/submit    Create an account, submit -> returns TRK-xxxxxxxx
http://localhost:3000/track     Paste that TRK-xxxxxxxx
http://localhost:3000/admin     Sign in as admin, open a case, approve a reply
http://localhost:8000/docs      Swagger
```

Admin login created by `create_admin.py`:

```
admin@smar9cdttracker.com / admin12345
```
## AI module

The `ai/` folder contains the classification, retrieval, and response-generation pipeline. See `ai/README.md` for setup and integration details. It currently writes results to its own local database as a placeholder — needs to be reconciled with the backend's database before full integration.

## Reset the database

```bash
cd backend
del smarttracker.db             # macOS/Linux: rm smarttracker.db
python create_admin.py
```

## Checks

```bash
cd frontend
npx tsc --noEmit                # types
npm run lint                    # eslint
npm run build                   # production build
```

## Notes

- Frontend needs the backend running; every screen reads from the API and shows
  a loading, empty, or error state. Nothing is seeded or mocked.
- `VITE_API_URL` (frontend/.env) must match the backend origin, and that origin
  must appear in `SMARTTRACKER_CORS_ORIGINS` (backend/.env).
- JWTs expire after 60 minutes; the UI offers a re-login on 401.
