# ai_worker.py
# Child-process bridge for backend/ai_client.py.
#
# Runs in a SEPARATE Python process (spawned by ai_client.analyze_waste_image /
# ai_client.verify_cleanup). Protocol:
#   stdin : one JSON object
#           {"image_b64": str, "mime_type": str, "additional_context": str|null,
#            "location": dict|null, "prior_reports_at_location": int}
#           or {"task": "verify_cleanup", "before_b64": str, "after_b64": str,
#               "before_mime": str, "after_mime": str}
#   stdout: EXACTLY one JSON envelope, nothing else:
#           {"ok": true, "task": ..., "result": {<exact AI output dict>}}
#           (AI/transformer progress logs go to stderr by default and are
#            captured separately by the parent — they never touch stdout.)
#
# The AI source location comes from the WASTE_AI_SRC environment variable
# (set by the parent). The AI modules are imported LAZILY inside main(), so a
# bad WASTE_AI_SRC or broken AI environment produces a clean non-zero exit
# (captured as AI_EXIT_* with stderr detail by the parent) instead of a hang.
#
# This bridge contains NO AI logic and does not modify any ai/ file; it only
# calls the documented entry points:
#   waste_pipeline.process_waste_image(...)      (branch: waste-image-classification)
#   cleanup_verifier.verify_cleanup(...)

import base64
import json
import os
import sys
import traceback

WASTE_AI_SRC = (os.environ.get("WASTE_AI_SRC") or "").strip()


def _emit(envelope: dict) -> None:
    sys.stdout.write(json.dumps(envelope))
    sys.stdout.flush()


def _load_ai_entry():
    """Import the AI entry points lazily, after stdin has been read."""
    if not WASTE_AI_SRC:
        raise RuntimeError("WASTE_AI_SRC is not set")
    if not os.path.isdir(WASTE_AI_SRC):
        raise RuntimeError(f"WASTE_AI_SRC is not a directory: {WASTE_AI_SRC!r}")
    if WASTE_AI_SRC not in sys.path:
        sys.path.insert(0, WASTE_AI_SRC)
    from waste_pipeline import process_waste_image          # noqa: E402  (AI module)
    from cleanup_verifier import verify_cleanup as _verify  # noqa: E402  (AI module)
    return process_waste_image, _verify


def main() -> None:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("stdin JSON must be an object")
    except Exception as exc:
        sys.stderr.write(f"invalid stdin JSON: {exc}\n")
        sys.exit(2)

    try:
        process_waste_image, verify_cleanup = _load_ai_entry()
    except Exception:
        sys.stderr.write("AI import failed:\n" + traceback.format_exc())
        sys.exit(3)

    task = payload.get("task", "analyze")
    try:
        if task == "verify_cleanup":
            result = verify_cleanup(
                base64.b64decode(payload["before_b64"]),
                base64.b64decode(payload["after_b64"]),
                before_mime=payload.get("before_mime", "image/jpeg"),
                after_mime=payload.get("after_mime", "image/jpeg"),
            )
        else:
            result = process_waste_image(
                base64.b64decode(payload["image_b64"]),
                mime_type=payload.get("mime_type", "image/jpeg"),
                additional_context=payload.get("additional_context"),
                location=payload.get("location"),
                prior_reports_at_location=int(payload.get("prior_reports_at_location") or 0),
            )
    except SystemExit:
        raise
    except Exception:
        sys.stderr.write("AI execution failed:\n" + traceback.format_exc())
        sys.exit(4)

    _emit({"ok": True, "task": task, "result": result})


if __name__ == "__main__":
    main()
