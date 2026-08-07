from google import genai
import json
import os
import time
from dotenv import load_dotenv

load_dotenv(dotenv_path=r"C:\Users\SwakeetMali\smarttracker-ai\.env")
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

CLASSIFY_PROMPT = """You are a grievance classification system. Read the complaint and respond with ONLY valid JSON. No explanation, no markdown formatting, just the JSON object.

Required JSON format:
{{
  "category": "billing" or "technical" or "delivery" or "refund" or "account" or "other",
  "department": "billing" or "tech_support" or "logistics" or "customer_service",
  "urgency": "low" or "medium" or "high",
  "entities": {{"order_id": null or a string, "account_id": null or a string, "error_code": null or a string}},
  "summary": "one short sentence summarizing the issue"
}}

Example 1:
Complaint: "My order #ORD-9982 never arrived and it's been 3 weeks, I'm furious"
Output: {{"category": "delivery", "department": "logistics", "urgency": "high", "entities": {{"order_id": "ORD-9982", "account_id": null, "error_code": null}}, "summary": "Order not delivered after 3 weeks"}}

Example 2:
Complaint: "I keep getting error code E-402 when I try to log into my account"
Output: {{"category": "technical", "department": "tech_support", "urgency": "medium", "entities": {{"order_id": null, "account_id": null, "error_code": "E-402"}}, "summary": "User cannot log in due to error E-402"}}

Now classify this complaint:
Complaint: "{text}"
Output:"""


def classify_complaint(text: str) -> dict:
    prompt = CLASSIFY_PROMPT.format(text=text)
    models_to_try = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]

    for attempt in range(3):
        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                raw = response.text.strip()
                if raw.startswith("```"):
                    raw = raw.strip("`")
                    raw = raw.replace("json", "", 1).strip()
                return json.loads(raw)
            except Exception as e:
                print(f"  {model_name} failed: {e}")
                continue
        time.sleep(10)

    raise RuntimeError("All models failed after retries — check API status or your quota.")
if __name__ == "__main__":
    tests = [
        "I ordered a laptop 3 weeks ago (order ORD-1234) and it still hasn't shipped. This is ridiculous.",
        "nothing works, fix it now",
        "Your app charged me twice for the same subscription, and also I can't reset my password, error E-501",
        "hi, just wondering when my refund for order 7788 will process"
    ]
    for t in tests:
        print(f"\nInput: {t}")
        print(json.dumps(classify_complaint(t), indent=2))