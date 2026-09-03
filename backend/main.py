import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# Database imports
# ---------------------------------------------------------------------------
from database import Base, engine
from models import AppStateSnapshot, Complaint, User, Response  # noqa: F401

# ---------------------------------------------------------------------------
# Router imports
# ---------------------------------------------------------------------------
# Each router file groups related endpoints together.
# We import the router object and register it with the main app below.
from routers import auth as auth_router
from routers import complaints as complaints_router
from routers import admin as admin_router
from routers import app_state as app_state_router


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown logic
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    print("Starting up SmartTracker AI …")
    Base.metadata.create_all(bind=engine)
    print("Database tables ready.")

    yield  # app is now running and serving requests

    # --- SHUTDOWN ---
    print("Shutting down SmartTracker AI …")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="SmartTracker AI Backend",
    lifespan=lifespan,
)

# The Vite app and FastAPI normally run on different ports in development.
# Keep the allow-list configurable for deployed environments while making the
# documented local setup work without opening CORS to every origin.
allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "SMARTTRACKER_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ---------------------------------------------------------------------------
# Register routers
# ---------------------------------------------------------------------------
# include_router attaches all routes defined inside auth_router.router
# to the main app, so POST /auth/register becomes available.
app.include_router(auth_router.router)
app.include_router(complaints_router.router)
app.include_router(admin_router.router)
app.include_router(app_state_router.router)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
def home():
    return {"message": "SmartTracker AI Backend is running"}


@app.get("/health", tags=["system"])
def health():
    """Small readiness endpoint used by local tooling and deployments."""
    return {"status": "ok"}

