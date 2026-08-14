from contextlib import asynccontextmanager

from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Database imports
# ---------------------------------------------------------------------------
from database import Base, engine
from models import User, Complaint   # noqa: F401  (imported for side-effects)

# ---------------------------------------------------------------------------
# Router imports
# ---------------------------------------------------------------------------
# Each router file groups related endpoints together.
# We import the router object and register it with the main app below.
from routers import auth as auth_router
from routers import complaints as complaints_router
from routers import admin as admin_router


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

# ---------------------------------------------------------------------------
# Register routers
# ---------------------------------------------------------------------------
# include_router attaches all routes defined inside auth_router.router
# to the main app, so POST /auth/register becomes available.
app.include_router(auth_router.router)
app.include_router(complaints_router.router)
app.include_router(admin_router.router)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
def home():
    return {
        "message": "SmartTracker AI Backend is running"
    }
