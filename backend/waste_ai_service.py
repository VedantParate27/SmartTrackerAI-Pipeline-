# waste_ai_service.py
# Background execution + persistence for the waste-AI flow.
#
# Responsibilities:
#   - schedule_ai_analysis(): register the background task (never blocks the request)
#   - run_ai_analysis(): load the pending WasteAIResult, read the stored image,
#     invoke ai_client.analyze_waste_image() (subprocess-isolated), and persist
#     the outcome VERBATIM onto the result row.
#
# Fail-open contract:
#   - The complaint is NEVER touched here (AI predictions live only in WasteAIResult).
#   - Any failure (missing image file, adapter error, unexpected exception)
#     marks the row ai_status="failed" with errors_json — no exception ever
#     escapes into the request lifecycle (the task runs after the response).
#   - AI vocabulary is stored verbatim: sanitary stays sanitary, mixed stays
#     mixed, dump_scale stays dump_scale; escalate_to_authority and
#     needs_human_review stay separate fields; NO intervention_required is
#     invented; model_name/model_version stay NULL (the AI exposes neither).

import json
from pathlib import Path

import ai_client
import image_utils
from database import SessionLocal
from models import CleanupProof, Complaint, WasteAIResult, utcnow

# NOTE: SessionLocal is imported at module level (not deep inside the function)
# so the test harness can substitute it cleanly; production always uses the
# real sessionmaker bound to the application database.


def schedule_ai_analysis(background_tasks, result_id: int) -> None:
    """Register the AI run as a background task (FastAPI BackgroundTasks)."""
    background_tasks.add_task(run_ai_analysis, result_id)


def _safe_image_path(image_url: str | None) -> Path | None:
    """Map a stored /uploads/complaints/... URL to its file path, safely.

    Rejects anything that is not a bare complaint-image filename (path
    traversal, other upload namespaces, nested paths).
    """
    if not image_url:
        return None
    prefix = "/uploads/complaints/"
    if not image_url.startswith(prefix):
        return None
    filename = image_url[len(prefix):]
    if "/" in filename or "\\" in filename or ".." in filename:
        return None
    if not filename.startswith("complaint_"):
        return None
    path = (image_utils.COMPLAINT_IMAGE_DIR / filename).resolve()
    try:
        path.relative_to(image_utils.COMPLAINT_IMAGE_DIR.resolve())
    except ValueError:
        return None
    return path


def run_ai_analysis(result_id: int) -> None:
    """Execute one AI analysis and persist it. Never raises."""
    db = SessionLocal()
    try:
        result = db.query(WasteAIResult).filter(WasteAIResult.id == result_id).first()
        if result is None:
            return  # nothing to do (row vanished — e.g. test teardown)

        image_path = _safe_image_path(result.image_url)
        if image_path is None or not image_path.is_file():
            _mark_failed(db, result, [{
                "error": "IMAGE_UNAVAILABLE",
                "details": f"stored complaint image not found: {result.image_url}",
            }])
            return

        try:
            image_bytes = image_path.read_bytes()
        except OSError as exc:
            _mark_failed(db, result, [{
                "error": "IMAGE_UNREADABLE",
                "details": str(exc),
            }])
            return

        complaint = db.query(Complaint).filter(Complaint.id == result.complaint_id).first()

        location = None
        if complaint is not None and complaint.latitude is not None and complaint.longitude is not None:
            location = {"lat": float(complaint.latitude), "lng": float(complaint.longitude)}

        outcome = ai_client.analyze_waste_image(
            image_bytes,
            mime_type=result.image_mime_type or "image/jpeg",
            additional_context=(complaint.waste_context if complaint is not None else None),
            location=location,
            prior_reports_at_location=int(result.prior_reports_count or 0),
        )

        if outcome.get("success"):
            ai = outcome["result"] or {}
            result.ai_status = "completed"
            result.image_usable = bool(ai.get("image_usable"))
            result.unusable_reason = ai.get("unusable_reason")
            result.waste_type = ai.get("waste_type")                       # verbatim
            result.waste_type_confidence = ai.get("waste_type_confidence")
            result.severity = ai.get("severity")                           # verbatim
            result.severity_confidence = ai.get("severity_confidence")
            result.reasoning = ai.get("reasoning")
            result.follow_up_question = ai.get("follow_up_question")
            result.recurring_flag = bool(ai.get("recurring_flag"))
            result.escalate_to_authority = bool(ai.get("escalate_to_authority"))
            result.needs_human_review = bool(ai.get("needs_human_review"))
            result.review_reasons_json = json.dumps(ai.get("review_reasons") or [], default=str)
            result.disposal_guidance = ai.get("disposal_guidance")
            # AI-level stage errors (e.g. guidance generation) — row still completes
            result.errors_json = json.dumps(ai.get("errors") or [], default=str)
        else:
            _mark_failed(db, result, [{
                "error": outcome.get("error") or "AI_UNKNOWN_ERROR",
                "details": outcome.get("details"),
            }])

        result.latency_ms = outcome.get("latency_ms")
        db.commit()
    except Exception as exc:  # absolute fail-open: the task must never blow up the app
        try:
            db.rollback()
            result = db.query(WasteAIResult).filter(WasteAIResult.id == result_id).first()
            if result is not None:
                _mark_failed(db, result, [{
                    "error": "AI_RUN_EXCEPTION",
                    "details": f"{type(exc).__name__}: {exc}",
                }])
        except Exception:
            pass
    finally:
        db.close()


def _mark_failed(db, result: WasteAIResult, errors: list) -> None:
    result.ai_status = "failed"
    result.errors_json = json.dumps(errors, default=str)
    db.commit()


# ---------------------------------------------------------------------------
# Cleanup-proof AI verification (verify_cleanup contract) — Step 6
# ---------------------------------------------------------------------------
# AFTER-proof assistance: runs in a background task after the CleanupProof row
# is committed, exactly like run_ai_analysis. Fail-open: only the ai_* advisory
# columns are ever touched — the proof and task survive any failure, the proof
# is never marked verified by AI, and the complaint is never resolved by AI.
# The human verification workflow (verification_status / verified_by /
# verified_at) remains the single source of truth.

def schedule_cleanup_verification(background_tasks, proof_id: int) -> None:
    """Register the cleanup verification as a background task (never blocks the request)."""
    background_tasks.add_task(run_cleanup_verification, proof_id)


def _safe_proof_path(image_url: str | None) -> Path | None:
    """Map a stored /uploads/proof_... URL to its file path, safely.

    Rejects anything that is not a bare proof filename (path traversal, other
    upload namespaces, nested paths).
    """
    if not image_url:
        return None
    prefix = "/uploads/"
    if not image_url.startswith(prefix):
        return None
    filename = image_url[len(prefix):]
    if "/" in filename or "\\" in filename or ".." in filename:
        return None
    if not filename.startswith("proof_"):
        return None
    path = (image_utils.UPLOADS_DIR / filename).resolve()
    try:
        path.relative_to(image_utils.UPLOADS_DIR.resolve())
    except ValueError:
        return None
    return path


def _mime_for_suffix(path: Path) -> str:
    """MIME for a stored image from its sniffed extension (safe fallback JPEG)."""
    return image_utils.EXT_TO_MIME.get(path.suffix.lstrip(".").lower(), "image/jpeg")


def run_cleanup_verification(proof_id: int) -> None:
    """Execute one verify_cleanup() run and persist it. Never raises."""
    db = SessionLocal()
    try:
        proof = db.query(CleanupProof).filter(CleanupProof.id == proof_id).first()
        if proof is None:
            return  # nothing to do (row vanished — e.g. test teardown)

        # The human decision outranks the AI: if verification already completed
        # before this run, keep the advisory columns empty and never resurrect.
        if proof.verification_status != "pending_verification":
            return

        after_path = _safe_proof_path(proof.image_url)
        # The BEFORE image is the complaint's original image, stored under the
        # complaints namespace — resolve it with the Step-3 complaint-image guard.
        before_path = _safe_image_path(proof.before_image_url)
        if after_path is None or not after_path.is_file():
            proof.ai_errors_json = json.dumps([{
                "error": "AFTER_IMAGE_UNAVAILABLE",
                "details": f"stored proof image not found: {proof.image_url}",
            }], default=str)
            proof.ai_processed_at = utcnow()
            db.commit()
            return
        if before_path is None or not before_path.is_file():
            # No BEFORE reference (e.g. complaint had no image): verification
            # simply cannot run; the proof stays fully human-reviewable.
            proof.ai_errors_json = json.dumps([{
                "error": "BEFORE_IMAGE_UNAVAILABLE",
                "details": f"stored complaint image not found: {proof.before_image_url}",
            }], default=str)
            proof.ai_processed_at = utcnow()
            db.commit()
            return

        try:
            before_bytes = before_path.read_bytes()
            after_bytes = after_path.read_bytes()
        except OSError as exc:
            proof.ai_errors_json = json.dumps([{
                "error": "IMAGE_UNREADABLE",
                "details": str(exc),
            }], default=str)
            proof.ai_processed_at = utcnow()
            db.commit()
            return

        outcome = ai_client.verify_cleanup(
            before_bytes,
            after_bytes,
            before_mime=_mime_for_suffix(before_path),
            after_mime=_mime_for_suffix(after_path),
        )

        if outcome.get("success"):
            ai = outcome["result"] or {}
            proof.ai_after_image_usable = ai.get("after_image_usable")
            proof.ai_unusable_reason = ai.get("unusable_reason")
            proof.ai_cleanup_appears_complete = ai.get("cleanup_appears_complete")
            proof.ai_confidence = ai.get("confidence")
            proof.ai_reasoning = ai.get("reasoning")
            # Preserve the AI's documented behavior: confidence < 0.7 (or a
            # missing confidence) => admin review recommended. The AI's own
            # flag wins when it supplies one.
            recommended = ai.get("admin_review_recommended")
            if recommended is None:
                confidence = ai.get("confidence")
                recommended = not (isinstance(confidence, (int, float)) and confidence >= 0.7)
            proof.ai_admin_review_recommended = bool(recommended)
            proof.ai_errors_json = None
        else:
            proof.ai_errors_json = json.dumps([{
                "error": outcome.get("error") or "AI_UNKNOWN_ERROR",
                "details": outcome.get("details"),
            }], default=str)

        proof.ai_processed_at = utcnow()
        db.commit()
    except Exception as exc:  # absolute fail-open: the task must never blow up the app
        try:
            db.rollback()
            proof = db.query(CleanupProof).filter(CleanupProof.id == proof_id).first()
            if proof is not None:
                proof.ai_errors_json = json.dumps([{
                    "error": "AI_RUN_EXCEPTION",
                    "details": f"{type(exc).__name__}: {exc}",
                }], default=str)
                proof.ai_processed_at = utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
