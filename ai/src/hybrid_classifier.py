import io
from PIL import Image
from dwm_classifier import classify_with_dwm
from waste_classifier import classify_waste_image
from config import DWM_CONFIDENCE_THRESHOLD


def classify_hybrid(image_bytes, mime_type="image/jpeg", additional_context=None):
    fallback_reason = None
    if additional_context:
        fallback_reason = "context_provided"  # the models only see the image
    else:
        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            result = classify_with_dwm(image)
            if (result["waste_type_confidence"] >= DWM_CONFIDENCE_THRESHOLD
                    and result["severity_confidence"] >= DWM_CONFIDENCE_THRESHOLD):
                result["source"], result["fallback_reason"] = "dwm", None
                return result
            fallback_reason = "low_dwm_confidence"
        except Exception as e:
            fallback_reason = str(e)

    result = classify_waste_image(image_bytes, mime_type=mime_type, additional_context=additional_context)
    result["source"], result["fallback_reason"] = "llm_fallback", fallback_reason
    return result