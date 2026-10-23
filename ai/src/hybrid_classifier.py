import io
from PIL import Image
from dwm_classifier import classify_with_dwm
from waste_classifier import classify_waste_image
from config import DWM_CONFIDENCE_THRESHOLD


def classify_hybrid(image_bytes, mime_type="image/jpeg", additional_context=None):
    fallback_reason = None
    dwm_result = None

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        result = classify_with_dwm(image)
        dwm_result = result

        if (
            result["waste_type_confidence"] >= DWM_CONFIDENCE_THRESHOLD
            and result["severity_confidence"] >= DWM_CONFIDENCE_THRESHOLD
        ):
            result["source"] = "dwm"
            result["fallback_reason"] = None
            return result

        fallback_reason = "low_dwm_confidence"

    except Exception as exc:
        fallback_reason = str(exc)

    try:
        result = classify_waste_image(
            image_bytes,
            mime_type=mime_type,
            additional_context=additional_context,
        )
        result["source"] = "llm_fallback"
        result["fallback_reason"] = fallback_reason
        return result
    except Exception as llm_exc:
        # If LLM is unavailable (e.g. 503) and DWM had a usable result,
        # fall back to the DWM prediction (flagged for review via threshold)
        if dwm_result and dwm_result.get("image_usable"):
            dwm_result["source"] = "dwm"
            dwm_result["fallback_reason"] = f"llm_error: {llm_exc}"
            return dwm_result
        raise
