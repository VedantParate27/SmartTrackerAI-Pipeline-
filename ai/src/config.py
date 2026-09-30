"""
Central configuration for the AI module.
Change values here rather than hunting through individual files.
"""

# --- Gemini models, in fallback order ---
MODELS_TO_TRY = ["gemini-3.5-flash-lite", "gemini-3.6-flash"]

# --- Retry behavior for API calls ---
MAX_RETRY_CYCLES = 3        # how many times to loop through MODELS_TO_TRY before giving up
RETRY_WAIT_SECONDS = 10     # pause between full retry cycles

# --- Chunking (used in ingest.py) ---
CHUNK_MAX_WORDS = 150        # split a paragraph further if it exceeds this
CHUNK_MIN_WORDS = 20         # merge a paragraph with the next if it's shorter than this

# --- Retrieval (used in retrieval.py) ---
RETRIEVAL_CANDIDATE_POOL = 10   # how many candidates to pull per method before RRF fusion
RETRIEVAL_TOP_K = 5             # how many results hybrid_search returns after fusion
RERANK_TOP_K = 3                # how many results survive the final reranking step
RRF_K_CONSTANT = 60              # standard RRF damping constant

# --- Paths ---
import os
PROJECT_ROOT = r"C:\Users\SwakeetMali\smarttracker-ai"
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
CHROMA_DB_PATH = os.path.join(PROJECT_ROOT, "chroma_db")
POLICIES_FOLDER = os.path.join(PROJECT_ROOT, "data", "policies")
# --- Confidence & escalation thresholds ---
CONFIDENCE_THRESHOLD = 0.6      # below this, flag classification for human review
RETRIEVAL_RELEVANCE_THRESHOLD = 0.0005   # below this rerank score, treat as "no good policy match"

# --- Waste Management domain ---
WASTE_TYPES = ["wet", "dry", "hazardous", "sanitary", "e_waste", "mixed", "none"]
SEVERITY_LEVELS = ["domestic", "moderate", "dump_scale", "none"]
WASTE_CONFIDENCE_THRESHOLD = 0.6  # same philosophy as CONFIDENCE_THRESHOLD

# --- Waste escalation decision ---
ESCALATE_SEVERITIES = ["dump_scale"]  # severities that always escalate regardless of history
RECURRING_REPORT_THRESHOLD = 3  # 3+ prior reports at same location = treat as recurring