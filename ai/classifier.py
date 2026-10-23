import json

from .common import call_gemini_with_retry, strip_json_fences

CLASSIFY_PROMPT = """You are a grievance classification system. Read the complaint and respond with ONLY valid JSON. No explanation, no markdown formatting, just the JSON object.

Required JSON format:
{{
  "category": "billing" or "technical" or "delivery" or "refund" or "account" or "other",
  "department": "billing" or "tech_support" or "logistics" or "customer_service",
  "urgency": "low" or "medium" or "high",
  "confidence": a number between 0 and 1 representing how confident you are in this classification,
  "entities": {{"order_id": null or a string, "account_id": null or a string, "error_code": null or a string}},
  "summary": "one short sentence summarizing the issue"
}}

Example 1:
Complaint: "My order #ORD-9982 never arrived and it's been 3 weeks, I'm furious"
Output: {{"category": "delivery", "department": "logistics", "urgency": "high", "confidence": 0.93, "entities": {{"order_id": "ORD-9982", "account_id": null, "error_code": null}}, "summary": "Order not delivered after 3 weeks"}}

Example 2:
Complaint: "I keep getting error code E-402 when I try to log into my account"
Output: {{"category": "technical", "department": "tech_support", "urgency": "medium", "confidence": 0.88, "entities": {{"order_id": null, "account_id": null, "error_code": "E-402"}}, "summary": "User cannot log in due to error E-402"}}

Now classify this complaint:
Complaint: "{text}"
Output:"""


def classify_complaint(text: str) -> dict:
    prompt = CLASSIFY_PROMPT.format(text=text)

    for model_name in MODELS_TO_TRY:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Classification,
                    temperature=0,
                ),
            )

            if response.parsed is None:
                raise RuntimeError(
                    f"{model_name} returned no structured response"
                )

            return response.parsed.model_dump()

        except Exception as e:
            error_text = str(e)

            print(f"  {model_name} failed: {error_text}")

            # Do not repeatedly hammer Gemini when the API says
            # the quota/rate limit has been exhausted.
            if (
                "429" in error_text
                or "RESOURCE_EXHAUSTED" in error_text
                or "quota" in error_text.lower()
                or "rate limit" in error_text.lower()
            ):
                raise RuntimeError(
                    f"Gemini quota/rate limit exceeded for {model_name}. "
                    "Please wait for the quota window to reset."
                ) from e

            # For other errors, try the next configured model.
            continue

    raise RuntimeError(
        "All configured Gemini models failed. Check API status or configuration."
    )


if __name__ == "__main__":
    tests = [
        "I ordered a laptop 3 weeks ago (order ORD-1234) and it still hasn't shipped. This is ridiculous.",
        "nothing works, fix it now",
        "Your app charged me twice for the same subscription, and also I can't reset my password, error E-501",
        "hi, just wondering when my refund for order 7788 will process",
    ]
    for t in tests:
        print(f"\nInput: {t}")
        print(json.dumps(classify_complaint(t), indent=2))
