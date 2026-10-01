"""
Image-based waste classification for the Municipal Solid Waste (MSW) domain.
Takes an uploaded image (plus optional location and free-text context) and
returns waste type, severity/scale, and an escalation decision — following
the same schema-enforcement and confidence-handling pattern as classifier.py.
"""
from google import genai
from google.genai import types
from pydantic import BaseModel
from typing import Literal, Optional
import os
import time
from dotenv import load_dotenv
from config import MODELS_TO_TRY, MAX_RETRY_CYCLES, RETRY_WAIT_SECONDS, ENV_PATH

load_dotenv(dotenv_path=ENV_PATH)
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))


# --- Schema: enforced output shape, same philosophy as Classification in classifier.py ---

class WasteClassification(BaseModel):
    image_usable: bool
    unusable_reason: Optional[str] = None
    waste_type: Literal["wet", "dry", "hazardous", "sanitary", "e_waste", "mixed", "none"]
    waste_type_confidence: float
    severity: Literal["domestic", "moderate", "dump_scale", "none"]
    severity_confidence: float
    reasoning: str
    follow_up_question: Optional[str] = None  # a single, specific question to ask the user, if useful


WASTE_CLASSIFY_PROMPT = """You are an image-based waste classification system for a municipal solid waste management platform. Analyze the uploaded image carefully.

FIRST, decide whether the image is usable. Set image_usable to false if ANY of these apply:
- No waste or garbage is visible in the image (e.g., a clean street, a person, an animal, an unrelated object)
- The image is too blurry, dark, or low-resolution to identify what is shown
- The image is a screenshot, drawing, or other non-photographic content rather than a real scene
If image_usable is false: set waste_type to "none", severity to "none", give a short unusable_reason, and set both confidence values to how sure you are that the image is unusable. Do not guess a waste type or severity for an unusable image.
If image_usable is true, continue with the analysis below and leave unusable_reason empty.

Determine two things:

1. WASTE TYPE — the dominant type of waste visible:
   - "wet": food scraps, vegetable/fruit waste, garden/organic waste
   - "dry": paper, cardboard, plastic, glass, metal, rubber
   - "hazardous": chemicals, paints, batteries, pesticides
   - "sanitary": diapers, sanitary napkins, masks, medical waste
   - "e_waste": electronics, wires, circuit boards, appliances
   - "mixed": clearly multiple types mixed together with no single dominant type

2. SEVERITY — the scale of the situation:
   - "domestic": small quantity, consistent with normal household waste, contained (bag/bin), no visible spread
   - "moderate": larger quantity, some spread beyond a container, or a noticeably messier/uncontained situation
   - "dump_scale": large accumulation, spread across an area, signs of long-term dumping (weathering, layering, decomposition, visible pests), or clearly not something a household would produce

Set confidence (0.0-1.0) for each judgment based on how clear the visual evidence is. Low confidence (below 0.5) means the image is ambiguous, poor quality, unclear, or borderline between categories.

Additional context that may be provided by the user (use it to inform your judgment, but the image is the primary evidence):
{additional_context}

Provide brief reasoning citing specific visual cues you observed (e.g., "large pile spanning several meters, visible decomposition" or "single bag of food waste in a kitchen bin").

Context can independently raise the severity level even if the image alone looks domestic-scale. Specifically:
- If the additional context indicates this is a RECURRING problem (e.g., "this happens every week", "been here for weeks", "keeps coming back"), treat this as equivalent to at least "moderate" severity, since a persistent problem at the same location indicates a systemic issue regardless of how small any single photo looks.
- If the context describes a genuinely one-time, recent event with no mention of recurrence, rely primarily on the visual evidence.
- Always mention in your reasoning whether context influenced your severity call, and how.
- Write the reasoning as a natural explanation for a human reviewer. Do not refer to "instructions," "the platform," or "the prompt" in it.
Decide whether a follow-up question would genuinely help resolve uncertainty:
- If image_usable is false, set follow_up_question to a short, specific instruction for retaking the photo, tailored to the actual problem (e.g., "Please retake the photo in better lighting, making sure the waste is clearly visible" for a blurry/dark image, or "Please upload a photo that clearly shows the waste or garbage you're reporting" if no waste is visible).
- If image_usable is true but severity_confidence is below 0.6, set follow_up_question to a short, specific question that would help clarify severity (e.g., "Has this been accumulating over time, or is this a one-time occurrence?").
- If image_usable is true, confidence is reasonably high, and no additional_context was provided, you may still ask a brief, optional clarifying question if it would meaningfully change the outcome (e.g., asking about recurrence at this exact spot) — but do not ask a question just to ask one.
- If nothing genuinely needs clarifying, set follow_up_question to null. Do not force a question when the situation is already clear."""

def classify_waste_image(image_bytes: bytes, mime_type: str = "image/jpeg", additional_context: str = None) -> dict:
    """
    Takes raw image bytes and returns a waste classification dict.
    additional_context is optional free text the user provided (e.g.,
    "this has been here for 2 weeks") — pass None if not provided.
    """
    context_text = additional_context if additional_context else "(none provided)"
    prompt_text = WASTE_CLASSIFY_PROMPT.format(additional_context=context_text)

    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    for attempt in range(MAX_RETRY_CYCLES):
        for model_name in MODELS_TO_TRY:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[image_part, prompt_text],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=WasteClassification,
                        temperature=0,
                    ),
                )
                return response.parsed.model_dump()
            except Exception as e:
                print(f"  {model_name} failed: {e}")
                continue
        time.sleep(RETRY_WAIT_SECONDS)

    raise RuntimeError("All models failed after retries — check API status or your quota.")


if __name__ == "__main__":
    import json
    import sys

    # Usage: python waste_classifier.py path/to/image.jpg
    if len(sys.argv) < 2:
        print("Usage: python waste_classifier.py <image_path> [optional context text]")
        sys.exit(1)

    image_path = sys.argv[1]
    context = sys.argv[2] if len(sys.argv) > 2 else None

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    # crude mime type guess from extension
    ext = image_path.lower().split(".")[-1]
    mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
    mime_type = mime_map.get(ext, "image/jpeg")

    result = classify_waste_image(image_bytes, mime_type=mime_type, additional_context=context)
    print(json.dumps(result, indent=2))