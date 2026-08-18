# SmartTracker AI Pipeline

The TanStack frontend is connected to the FastAPI backend. Cases, policy
metadata, audit history, draft reviews, and administrative updates are stored
in SQLite through `GET /app/state` and `PUT /app/state`. Browser local storage
is an offline fallback, not the primary data source.

## Run locally

Open two terminals from the repository root.

Backend:

```powershell
cd backend
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn main:app --reload --port 8000 --env-file .env
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. The home page reports whether it is connected to
FastAPI. API documentation is available at `http://localhost:8000/docs`.

To use a different API host, copy `frontend/.env.example` to `frontend/.env`
and change `VITE_API_URL`. For a deployed frontend, set the backend environment
variable `SMARTTRACKER_CORS_ORIGINS` to the allowed comma-separated origins.
Copy `backend/.env.example` to `backend/.env` and set a strong
`SMARTTRACKER_SECRET_KEY` before any non-local deployment.

## Checks

```powershell
python -m pytest backend/tests
cd frontend
npm run lint
npm run build
```

The AI classification/retrieval module is still optional. Without model and
vector-store configuration, the UI uses its deterministic prototype pipeline;
the backend persistence and all visible workflow updates remain live.
