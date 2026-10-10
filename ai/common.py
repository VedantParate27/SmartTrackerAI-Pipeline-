"""
Shared config and Gemini helper for the AI/RAG module.

Fixes two things that existed as duplicates/hardcoded values across
classifier.py and generator.py in the original ai/ folder:
  1. Hardcoded absolute Windows paths (C:\\Users\\SwakeetMali\\...)
     -> now relative to the project root, overridable via .env
  2. The retry-across-models loop was copy-pasted in both files
     -> now lives here once, as call_gemini_with_retry()
"""
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

# Project root = one level up from this file (ai/common.py -> smarttracker-ai/)
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(dotenv_path=BASE_DIR / ".env")

CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", str(BASE_DIR / "chroma_db"))
POLICIES_DIR = os.getenv("POLICIES_DIR", str(BASE_DIR / "data" / "policies"))

_client = None


def get_client() -> genai.Client:
    """Lazy singleton so importing this module doesn't require an API key
    to already be set (useful for tests that don't touch Gemini)."""
    global _client
    if _client is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY not set. Copy .env.example to .env and fill it in."
            )
        _client = genai.Client(api_key=api_key)
    return _client


# NOTE: verify these model IDs against Google's current Gemini model list
# before relying on them - "gemini-3.6-flash" / "gemini-3.5-flash-lite" were
# carried over from the original code and were not verified here.
DEFAULT_MODELS = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]


def call_gemini_with_retry(
    prompt: str,
    models_to_try: list[str] = None,
    max_attempts: int = 3,
    backoff_seconds: int = 10,
) -> str:
    """Try each model in order; on total failure, sleep and retry the whole
    sweep. Raises RuntimeError if every model fails on every attempt.
    Returns the raw response text (unparsed)."""
    models_to_try = models_to_try or DEFAULT_MODELS
    client = get_client()

    for attempt in range(max_attempts):
        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name, contents=prompt
                )
                return response.text
            except Exception as e:
                print(f"  {model_name} failed: {e}")
                continue
        if attempt < max_attempts - 1:
            time.sleep(backoff_seconds)

    raise RuntimeError("All models failed after retries — check API status or your quota.")


def strip_json_fences(raw: str) -> str:
    """Gemini sometimes wraps JSON in ```json ... ``` - strip that off."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.replace("json", "", 1).strip()
    return raw
