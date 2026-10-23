# ai_client.py
# Subprocess-isolated adapter around the waste AI.
#
# The FastAPI process NEVER imports ai/ modules. The AI runs in a spawned
# child Python process that communicates ONLY via JSON over stdin/stdout
# (image bytes travel base64-encoded inside the JSON envelope — never argv,
# never raw bytes on a pipe).
#
# CONTRACT (source of truth: branch waste-image-classification, ai/src/waste_pipeline.py):
#   process_waste_image(
#       image_bytes: bytes,
#       mime_type: str = "image/jpeg",
#       additional_context: str | None = None,
#       location: dict | None = None,          # {"lat": float, "lng": float} or {"address": str}
#       prior_reports_at_location: int = 0,
#   ) -> dict
#
#   Output fields (preserved VERBATIM — no remapping here):
#     image_usable, unusable_reason,
#     waste_type (wet|dry|hazardous|sanitary|e_waste|mixed|none),
#     waste_type_confidence, severity (domestic|moderate|dump_scale|none),
#     severity_confidence, reasoning, follow_up_question,
#     recurring_flag, prior_reports_at_location, location,
#     escalate_to_authority, needs_human_review, review_reasons,
#     disposal_guidance, errors
#
# Failure modes are ALWAYS controlled dicts (fail-open); this module never
# raises into the API layer:
#   {"success": True,  "result": {...AI dict...}, "error": None, "latency_ms": int}
#   {"success": False, "result": None, "error": "AI_TIMEOUT|AI_INVALID_RESPONSE|"
#                                      "AI_EXIT_<code>|AI_SETUP_FAILED", "details": ..., "latency_ms": int}
#
# Not fabricated here (added later by the caller/service layer):
#   model_name, model_version — the AI exposes neither.

import base64
import json
import os
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Configuration (environment-driven; nothing machine-specific hardcoded)
# ---------------------------------------------------------------------------
WASTE_AI_MODE_ENV = "WASTE_AI_MODE"           # off | assist
WASTE_AI_SRC_ENV = "WASTE_AI_SRC"             # dir containing waste_pipeline.py, config.py, .env
WASTE_AI_TIMEOUT_ENV = "WASTE_AI_TIMEOUT_S"   # hard timeout, seconds

MODE_OFF = "off"
MODE_ASSIST = "assist"
VALID_MODES = (MODE_OFF, MODE_ASSIST)

DEFAULT_TIMEOUT_S = 120

# Error codes returned in controlled failure results
ERR_DISABLED = "AI_DISABLED"
ERR_NO_SRC = "AI_SOURCE_NOT_CONFIGURED"
ERR_SRC_MISSING = "AI_SOURCE_NOT_FOUND"
ERR_TIMEOUT = "AI_TIMEOUT"
ERR_INVALID_RESPONSE = "AI_INVALID_RESPONSE"
ERR_SETUP_FAILED = "AI_SETUP_FAILED"


def get_mode() -> str:
    """Configured AI mode ('off' | 'assist'). Unknown values fail safe to 'off'."""
    raw = (os.getenv(WASTE_AI_MODE_ENV) or MODE_ASSIST).strip().lower()
    return raw if raw in VALID_MODES else MODE_OFF


def get_timeout_s() -> int:
    """Hard timeout for the AI subprocess (seconds). Falls back to 120 on junk."""
    raw = os.getenv(WASTE_AI_TIMEOUT_ENV, str(DEFAULT_TIMEOUT_S)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_S
    return value if value > 0 else DEFAULT_TIMEOUT_S


def get_ai_src() -> str | None:
    """Configured AI source directory (WASTE_AI_SRC), or None when unset/empty."""
    raw = (os.getenv(WASTE_AI_SRC_ENV) or "").strip()
    return raw or None


# ---------------------------------------------------------------------------
# Controlled results (fail-open contract)
# ---------------------------------------------------------------------------
def _failure(error: str, details: str | None = None, started: float | None = None) -> dict:
    return {
        "success": False,
        "result": None,
        "error": error,
        "details": details,
        "latency_ms": int((time.monotonic() - started) * 1000) if started is not None else None,
    }


def analyze_waste_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    additional_context: str | None = None,
    location: dict | None = None,
    prior_reports_at_location: int = 0,
) -> dict:
    """Invoke the waste AI in a subprocess. NEVER raises; returns a controlled dict.

    success=True  -> result holds the AI's exact output dictionary (verbatim).
    success=False -> error is a stable machine-readable code; the API layer
                     proceeds without AI (fail-open).
    """
    started = time.monotonic()

    mode = get_mode()
    if mode == MODE_OFF:
        return _failure(ERR_DISABLED, "WASTE_AI_MODE=off — AI not invoked", started)

    ai_src = get_ai_src()
    if not ai_src:
        return _failure(ERR_NO_SRC, f"{WASTE_AI_SRC_ENV} is not configured", started)

    worker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_worker.py")
    if not os.path.isfile(worker_path):
        return _failure(ERR_SETUP_FAILED, f"worker script missing: {worker_path}", started)
    if not os.path.isdir(ai_src):
        return _failure(ERR_SRC_MISSING, f"{WASTE_AI_SRC_ENV} does not exist: {ai_src}", started)

    payload = {
        "image_b64": base64.b64encode(image_bytes).decode("ascii"),
        "mime_type": mime_type,
        "additional_context": additional_context,
        "location": location,
        "prior_reports_at_location": prior_reports_at_location,
    }

    # Hermetic-ish env: keep the API's environment (PATH etc.) but make the AI's
    # own .env the FIRST dotenv candidate so its config wins inside the child.
    # NOTE: GOOGLE_API_KEY is deliberately NOT set here — the AI's load_dotenv()
    # must be free to fill it from ai/.env (dotenv never overrides existing vars).
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONSAFEPATH"] = "1"  # never resolve imports from the CWD by accident
    child_env["WASTE_AI_SRC"] = ai_src

    try:
        completed = subprocess.run(
            [sys.executable, worker_path],
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            timeout=get_timeout_s(),
            env=child_env,
            cwd=ai_src,  # AI-side relative paths (e.g. dotenv defaults) resolve sanely
        )
    except subprocess.TimeoutExpired:
        return _failure(ERR_TIMEOUT, "Waste AI exceeded the configured timeout", started)
    except OSError as exc:
        return _failure(ERR_SETUP_FAILED, f"failed to spawn AI subprocess: {exc}", started)

    if completed.returncode != 0:
        stderr_tail = completed.stderr.decode("utf-8", errors="replace")[-500:] if completed.stderr else ""
        return _failure(
            f"AI_EXIT_{completed.returncode}",
            stderr_tail or "AI subprocess exited non-zero with no stderr",
            started,
        )

    try:
        envelope = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        stdout_head = completed.stdout.decode("utf-8", errors="replace")[:200]
        return _failure(ERR_INVALID_RESPONSE, f"stdout was not valid JSON: {stdout_head!r}", started)

    if not isinstance(envelope, dict) or envelope.get("ok") is not True or "result" not in envelope:
        return _failure(ERR_INVALID_RESPONSE, "stdout JSON did not match the worker envelope", started)

    result = envelope.get("result")
    if not isinstance(result, dict):
        return _failure(ERR_INVALID_RESPONSE, "AI result was not an object", started)

    return {
        "success": True,
        "result": result,   # AI dictionary, preserved verbatim
        "error": None,
        "details": None,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }


def verify_cleanup(
    before_image_bytes: bytes,
    after_image_bytes: bytes,
    before_mime: str = "image/jpeg",
    after_mime: str = "image/jpeg",
) -> dict:
    """Invoke verify_cleanup() via the same subprocess protocol.

    CleanupVerification fields (verbatim on success):
      after_image_usable, unusable_reason, cleanup_appears_complete,
      confidence, reasoning, admin_review_recommended
    """
    started = time.monotonic()

    mode = get_mode()
    if mode == MODE_OFF:
        return _failure(ERR_DISABLED, "WASTE_AI_MODE=off — AI not invoked", started)

    ai_src = get_ai_src()
    if not ai_src:
        return _failure(ERR_NO_SRC, f"{WASTE_AI_SRC_ENV} is not configured", started)

    worker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_worker.py")
    if not os.path.isfile(worker_path):
        return _failure(ERR_SETUP_FAILED, f"worker script missing: {worker_path}", started)
    if not os.path.isdir(ai_src):
        return _failure(ERR_SRC_MISSING, f"{WASTE_AI_SRC_ENV} does not exist: {ai_src}", started)

    payload = {
        "task": "verify_cleanup",
        "before_b64": base64.b64encode(before_image_bytes).decode("ascii"),
        "after_b64": base64.b64encode(after_image_bytes).decode("ascii"),
        "before_mime": before_mime,
        "after_mime": after_mime,
    }

    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONSAFEPATH"] = "1"
    child_env["WASTE_AI_SRC"] = ai_src

    try:
        completed = subprocess.run(
            [sys.executable, worker_path],
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            timeout=get_timeout_s(),
            env=child_env,
            cwd=ai_src,
        )
    except subprocess.TimeoutExpired:
        return _failure(ERR_TIMEOUT, "Waste AI exceeded the configured timeout", started)
    except OSError as exc:
        return _failure(ERR_SETUP_FAILED, f"failed to spawn AI subprocess: {exc}", started)

    if completed.returncode != 0:
        stderr_tail = completed.stderr.decode("utf-8", errors="replace")[-500:] if completed.stderr else ""
        return _failure(
            f"AI_EXIT_{completed.returncode}",
            stderr_tail or "AI subprocess exited non-zero with no stderr",
            started,
        )

    try:
        envelope = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        stdout_head = completed.stdout.decode("utf-8", errors="replace")[:200]
        return _failure(ERR_INVALID_RESPONSE, f"stdout was not valid JSON: {stdout_head!r}", started)

    if not isinstance(envelope, dict) or envelope.get("ok") is not True or "result" not in envelope:
        return _failure(ERR_INVALID_RESPONSE, "stdout JSON did not match the worker envelope", started)

    result = envelope.get("result")
    if not isinstance(result, dict):
        return _failure(ERR_INVALID_RESPONSE, "AI result was not an object", started)

    return {
        "success": True,
        "result": result,
        "error": None,
        "details": None,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
