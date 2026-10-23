"""
Verifies cleanup proof by comparing a 'before' image (original complaint)
against an 'after' image (uploaded by a cleaner claiming the job is done).
Returns a verification result and flags uncertain cases for admin review.
"""
from google import genai
from google.genai import types
from pydantic import BaseModel
from typing import Optional
import os
import time
from dotenv import load_dotenv
from config import MODELS_TO_TRY, MAX_RETRY_CYCLES, RETRY_WAIT_SECONDS, ENV_PATH, WASTE_CONFIDENCE_THRESHOLD

load_dotenv(dotenv_path=ENV_PATH)
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))


class CleanupVerification(BaseModel):
    after_image_usable: bool
    unusable_reason: Optional[str] = None
    cleanup_appears_complete: bool
    confidence: float
    reasoning: str
    admin_review_recommended: bool


VERIFY_PROMPT = """You are verifying whether a reported waste/garbage issue has been properly cleaned up. You are shown two images: a BEFORE image (the original reported problem) and an AFTER image (submitted by a cleaner claiming the job is done).

First, check if the AFTER image is usable:
- Set after_image_usable to false if it's blurry, too dark, unrelated to the location/situation, or clearly not a genuine photo of the same site (e.g., a completely different scene, a screenshot, or an image with no relevant view of the area).

If the AFTER image is usable, compare it against the BEFORE image and determine:
- Does the AFTER image show the waste/garbage from the BEFORE image has been removed or substantially cleared?
- Consider that some visual differences (lighting, angle, time of day) are normal and do not indicate cleanup was not done — focus on whether the WASTE ITSELF is gone or remains.

Set confidence based on how clearly the comparison supports your conclusion. Set admin_review_recommended to true if: the after image is unusable, confidence is below 0.7, the comparison is ambiguous (e.g., partial cleanup, different area shown, angle makes comparison hard), or there is any reasonable doubt.

Provide reasoning citing specific visual differences or similarities you observed between the two images."""


def verify_cleanup(before_image_bytes: bytes, after_image_bytes: bytes,
                    before_mime: str = "image/jpeg", after_mime: str = "image/jpeg") -> dict:
    before_part = types.Part.from_bytes(data=before_image_bytes, mime_type=before_mime)
    after_part = types.Part.from_bytes(data=after_image_bytes, mime_type=after_mime)

    contents = [
        "BEFORE image:", before_part,
        "AFTER image:", after_part,
        VERIFY_PROMPT,
    ]

    for attempt in range(MAX_RETRY_CYCLES):
        for model_name in MODELS_TO_TRY:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=CleanupVerification,
                        temperature=0,
                    ),
                )
                result = response.parsed.model_dump()
                # Safety net: low confidence always forces review, regardless of the model's own flag
                if result["confidence"] < WASTE_CONFIDENCE_THRESHOLD:
                    result["admin_review_recommended"] = True
                return result
            except Exception as e:
                print(f"  {model_name} failed: {e}")
                continue
        time.sleep(RETRY_WAIT_SECONDS)

    raise RuntimeError("All models failed after retries.")


if __name__ == "__main__":
    import json
    import sys
    import mimetypes

    if len(sys.argv) < 3:
        print("Usage: python cleanup_verifier.py <before_image> <after_image>")
        sys.exit(1)

    before_path, after_path = sys.argv[1], sys.argv[2]

    with open(before_path, "rb") as f:
        before_bytes = f.read()
    with open(after_path, "rb") as f:
        after_bytes = f.read()

    before_mime, _ = mimetypes.guess_type(before_path)
    after_mime, _ = mimetypes.guess_type(after_path)

    result = verify_cleanup(
        before_bytes, after_bytes,
        before_mime=before_mime or "image/jpeg",
        after_mime=after_mime or "image/jpeg",
    )
    print(json.dumps(result, indent=2))