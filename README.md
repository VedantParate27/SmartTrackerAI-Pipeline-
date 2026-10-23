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
http://localhost:3000/submit         Citizen: create an account, report waste + photo -> TRK-xxxxxxxx
http://localhost:3000/track          Citizen: status of that complaint + all your reports
http://localhost:3000/admin          Admin: queue -> open a case -> read the photo check, decide, verify proof
http://localhost:3000/cleaner        Cleaner: assigned tasks -> start -> upload photo proof
http://localhost:3000/admin/events   Admin: event log, CSV exports for pm4py / DWM
http://localhost:8000/docs           Swagger
```

Admin login created by `create_admin.py`:

```
admin@smar9cdttracker.com / admin12345
```

## Demo data (optional)

```bash
cd backend
python seed_data.py --complaints 600 --cleaners 6 --seed 42 --simulate-triage
python seed_data.py --wipe          # removes only seeded rows
```

## Cleaner login (dev workaround)

Sign-up always creates a citizen and seeded cleaners cannot log in, so promote
an account you registered through the UI:

```bash
cd backend
python -c "from database import SessionLocal; from models import User; db=SessionLocal(); u=db.query(User).filter_by(email='you@example.com').one(); u.role='cleaner'; db.commit(); print('cleaner id', u.id)"
```

Sign in again at `/cleaner`. Assign tasks to that printed id from an admin case.

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
  a loading, empty, or error state. The frontend itself seeds or mocks nothing.
- `VITE_API_URL` (frontend/.env) must match the backend origin, and that origin
  must appear in `SMARTTRACKER_CORS_ORIGINS` (backend/.env).
- JWTs expire after 60 minutes; the UI offers a re-login on 401.
- Photo checks need the AI source: set `WASTE_AI_SRC` in `backend/.env` to the
  folder containing `waste_pipeline.py` and `cleanup_verifier.py` (`ai/src` on
  the `waste-image-classification` branch, not merged yet). Without it every
  photo check ends as "failed" and admins decide manually.
