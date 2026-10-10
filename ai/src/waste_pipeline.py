"""
Orchestrates the waste-image flow: classify the image, decide whether to
escalate to authorities or provide disposal guidance, and route accordingly.
This is the waste-domain equivalent of pipeline.py's process_complaint().
"""
from hybrid_classifier import classify_hybrid as classify_waste_image
from config import ESCALATE_SEVERITIES, RECURRING_REPORT_THRESHOLD, WASTE_CONFIDENCE_THRESHOLD
from waste_rag import retrieve_guidance_chunks, generate_disposal_guidance

def process_waste_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    additional_context: str = None,
    location: dict = None,
    prior_reports_at_location: int = 0,
) -> dict:
    """
    location: {"lat": float, "lng": float} or {"address": str}, or None
    prior_reports_at_location: count of previous reports at this exact
        location, supplied by the backend if available. 0 if unknown/none.
    """
    result = {
        "image_usable": None,
        "unusable_reason": None,
        "waste_type": None,
        "waste_type_confidence": None,
        "severity": None,
        "severity_confidence": None,
        "reasoning": None,
        "location": location,
        "prior_reports_at_location": prior_reports_at_location,
        "recurring_flag": False,
        "escalate_to_authority": False,
        "needs_human_review": False,
        "review_reasons": [],
        "disposal_guidance": None,
        "errors": [],
        "source": None, 
        "fallback_reason": None, 
        "environment": None,
    }

    # --- Step 1: Classify the image ---
    try:
        classification = classify_waste_image(
            image_bytes, mime_type=mime_type, additional_context=additional_context
        )
        result.update({
            "image_usable": classification["image_usable"],
            "unusable_reason": classification["unusable_reason"],
            "waste_type": classification["waste_type"],
            "waste_type_confidence": classification["waste_type_confidence"],
            "severity": classification["severity"],
            "severity_confidence": classification["severity_confidence"],
            "reasoning": classification["reasoning"],
            "follow_up_question": classification["follow_up_question"],
            "source": classification.get("source"), 
            "fallback_reason": classification.get("fallback_reason"), 
            "environment": classification.get("environment"),
        })
    except Exception as e:
        result["errors"].append(f"classification_failed: {e}")
        result["needs_human_review"] = True
        result["review_reasons"].append("classification_error")
        return result

    # --- Step 2: If the image isn't usable, stop here and escalate for a human to look ---
    if not result["image_usable"]:
        result["needs_human_review"] = True
        result["review_reasons"].append(f"unusable_image: {result['unusable_reason']}")
        return result

    # --- Step 3: Check confidence on both judgments ---
    low_waste_type_conf = result["waste_type_confidence"] < WASTE_CONFIDENCE_THRESHOLD
    low_severity_conf = result["severity_confidence"] < WASTE_CONFIDENCE_THRESHOLD
    if low_waste_type_conf or low_severity_conf:
        result["needs_human_review"] = True
        if low_waste_type_conf:
            result["review_reasons"].append(
                f"low_waste_type_confidence: {result['waste_type_confidence']:.2f}"
            )
        if low_severity_conf:
            result["review_reasons"].append(
                f"low_severity_confidence: {result['severity_confidence']:.2f}"
            )

    # --- Step 4: Recurring-location check ---
    result["recurring_flag"] = prior_reports_at_location >= RECURRING_REPORT_THRESHOLD

        # --- Step 5: The actual escalation decision ---
    if result["severity"] in ESCALATE_SEVERITIES or result["recurring_flag"]:
        result["escalate_to_authority"] = True
        if result["recurring_flag"] and result["severity"] not in ESCALATE_SEVERITIES:
            result["review_reasons"].append(
                f"recurring_location: {prior_reports_at_location} prior reports"
            )
    else:
        # Not escalating — generate grounded disposal guidance instead
        try:
            chunks = retrieve_guidance_chunks(result["waste_type"])
            result["disposal_guidance"] = generate_disposal_guidance(
                result["waste_type"], chunks, additional_context=additional_context
            )
        except Exception as e:
            result["errors"].append(f"disposal_guidance_failed: {e}")
            result["needs_human_review"] = True
            result["review_reasons"].append("disposal_guidance_generation_error")

    return result


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python waste_pipeline.py <image_path> [context] [prior_reports]")
        sys.exit(1)

    image_path = sys.argv[1]
    context = sys.argv[2] if len(sys.argv) > 2 else None
    prior_reports = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    import mimetypes
    mime_type, _ = mimetypes.guess_type(image_path)
    if mime_type is None:
        mime_type = "image/jpeg"

    result = process_waste_image(
        image_bytes,
        mime_type=mime_type,
        additional_context=context,
        location={"lat": 17.385, "lng": 78.4867},  # placeholder test coordinates
        prior_reports_at_location=prior_reports,
    )
    print(json.dumps(result, indent=2))