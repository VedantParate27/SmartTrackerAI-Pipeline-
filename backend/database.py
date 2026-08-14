# database.py
# This file sets up the database connection for SmartTracker AI.
# It uses SQLite (a lightweight file-based database) with SQLAlchemy (an ORM toolkit).

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# ---------------------------------------------------------------------------
# 1. DATABASE URL
# ---------------------------------------------------------------------------
# SQLite stores the entire database in a single file called "smarttracker.db".
# This file will be created automatically in the same folder as this script
# when the app runs for the first time.
#
# The URL format for SQLite is:  sqlite:///./filename.db
#   - "sqlite:///"  → tells SQLAlchemy to use the SQLite driver
#   - "./"          → means "current directory" (relative path)
#   - "smarttracker.db" → the name of the database file
DATABASE_URL = "sqlite:///./smarttracker.db"

# ---------------------------------------------------------------------------
# 2. ENGINE
# ---------------------------------------------------------------------------
# The engine is the core interface between SQLAlchemy and the database.
# It manages the actual connection to the database file.
#
# connect_args={"check_same_thread": False}
#   → This is required ONLY for SQLite.
#   → By default, SQLite only allows one thread to use a connection at a time.
#   → FastAPI can use multiple threads, so we disable that restriction here.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

# ---------------------------------------------------------------------------
# 3. SESSION FACTORY
# ---------------------------------------------------------------------------
# A "session" is like a temporary workspace where you build up a set of
# database operations (inserts, updates, queries) and then commit them all
# at once, or roll them back if something goes wrong.
#
# SessionLocal is a factory (a blueprint) for creating new session objects.
#   - autocommit=False → we manually control when changes are saved
#   - autoflush=False  → changes aren't automatically written before queries
#   - bind=engine      → connects sessions to our SQLite database
SessionLocal = sessionmaker(
    autocommit=False,   # manually control when changes are saved (safer)
    autoflush=False,
    bind=engine
)

# ---------------------------------------------------------------------------
# 4. DECLARATIVE BASE
# ---------------------------------------------------------------------------
# Base is the parent class that all database models will inherit from.
# When you create a model like "class User(Base)", SQLAlchemy knows it
# represents a table in the database.
Base = declarative_base()

# ---------------------------------------------------------------------------
# 5. DEPENDENCY — get_db()
# ---------------------------------------------------------------------------
# This is a FastAPI "dependency" function used in API route functions.
# It opens a database session, provides it to the route, and ensures the
# session is properly closed afterward — even if an error occurs.
#
# Usage in a route:
#   from database import get_db
#   from sqlalchemy.orm import Session
#   from fastapi import Depends
#
#   @app.get("/example")
#   def example(db: Session = Depends(get_db)):
#       ...
def get_db():
    db = SessionLocal()   # open a new session
    try:
        yield db          # hand the session to the route function
    finally:
        db.close()        # always close the session when done
