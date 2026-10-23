from google import genai
from google.genai import types
from pydantic import BaseModel
from typing import Literal, Optional
from config import MODELS_TO_TRY, MAX_RETRY_CYCLES, RETRY_WAIT_SECONDS, ENV_PATH, CONFIDENCE_THRESHOLD
import json
import os
import time
from dotenv import load_dotenv

load_dotenv(dotenv_path=ENV_PATH)
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))


# --- STEP A: Define the exact shape of a classification result ---
# This replaces "hoping the JSON looks right" with "the API enforces this shape."
# Literal[...] means "must be exactly one of these strings" — nothing else is allowed.

class Entities(BaseModel):
    order_ids: list[str] = []
    account_id: Optional[str] = None
    error_code: Optional[str] = None


class Classification(BaseModel):
    category: Literal["billing", "technical", "delivery", "refund", "account", "other"]
    department: Literal["billing", "tech_support", "logistics", "customer_service"]
    urgency: Literal["low", "medium", "high"]
    entities: Entities
    summary: str
    confidence: float  # self-assessed confidence, 0.0 (pure guess) to 1.0 (certain)


# --- STEP B: The prompt, now WITHOUT needing to describe the JSON shape ourselves ---
# (Because response_schema enforces it, we don't need to explain the format in text —
#  that would actually be redundant and can hurt output quality.)

CLASSIFY_PROMPT = """You are a grievance classification system for a customer support platform. Read the complaint carefully, including vague or emotional language, and classify it accurately.

Guidelines:
- Extract entities (order_ids, account_id, error_code) only if explicitly present in the text — do not guess or invent them. If multiple order IDs are mentioned, include all of them in the order_ids list.
- If a complaint mentions multiple issues, classify by the PRIMARY/most urgent issue.
- If the complaint is vague with no clear category, use "other" and department "customer_service".
- Urgency reflects the OBJECTIVE SEVERITY of the situation, not the customer's tone. A calmly-worded complaint about a serious issue (e.g., an order missing for a month, a package marked delivered but never received, a time-sensitive request like cancelling before shipment) is just as "high" urgency as an angrily-worded one — do not lower urgency just because the customer sounds calm or polite.
- Urgency "high" = financial harm, repeated failures, unauthorized/unexpected charges (possible fraud), long-standing unresolved issues (weeks, not days), delivery marked complete but not received (possible fraud/loss), or time-sensitive requests (e.g., must happen before an irreversible action like shipping) — regardless of tone.
- Urgency "medium" = a clear, real issue without the above severity markers.
- Urgency "low" = a general question, minor inconvenience, or request with no time pressure or serious consequence.
- A calm, patient STATUS-CHECK question with no complaint or problem stated ("just wondering when X will happen", "checking on the status of Y") stays "low" urgency by default, even if it touches a topic like refunds or delivery — unless the underlying issue itself is independently severe.
- Tie-breaker: if a complaint EXPLICITLY mentions being charged, billed, or a payment for an order that never arrived, classify as "billing" — this is a financial dispute at its core.
- If a complaint is about non-delivery WITHOUT mentioning a charge or payment issue — even if the customer demands a refund as the resolution — classify as "delivery"/"logistics". Wanting a refund is a normal resolution for a delivery problem and does not by itself make it a billing issue.
- Tie-breaker: if a complaint involves BOTH technical and billing (e.g. "payment error while checking out"), classify by which system caused the failure — a broken checkout/login is "technical", a charge-related dispute after a successful transaction is "billing".
- If a payment or transaction FAILS to go through DURING AN ACTUAL ATTEMPTED PURCHASE (declined, rejected, error during checkout) — classify as "billing", since this is fundamentally a billing/payment issue, not a system malfunction. Reserve "technical" for failures unrelated to the transaction itself (e.g., page crashes, login errors, server errors).
- Account security issues (unauthorized login, account takeover, password changed without the user's action, suspicious activity) should be routed to "tech_support", NOT "customer_service" — these require technical/security handling procedures, even though the category may be "account". Urgency for these is always "high".
- Routine account profile updates (changing email, name, or contact details on file, with no security concern) remain "customer_service", NOT "tech_support" — only genuine security incidents (unauthorized access, suspicious login, compromised password) go to tech_support.
- Data privacy requests (GDPR/CCPA, account deletion requests explicitly citing privacy law) should be routed to "customer_service" and are always "high" urgency, since they carry legal/compliance deadlines.
- General questions about company-wide policy topics with no reference to the customer's own specific order, account, or transaction (e.g., "do you offer discounts", "what's your return policy") — classify as "other"/"customer_service".
- Questions about a specific action tied to the customer's OWN order or account (e.g., "can I change my delivery address", "can you cancel my order", "how do I update my email") — classify by the relevant department for that action (logistics for delivery/shipping actions, billing for payment actions, tech_support for account/security actions), even though it's phrased as a question rather than a complaint.
- Set "confidence" based on how clear-cut this classification is: 1.0 = the complaint unambiguously matches one category/department with no other reasonable interpretation. 0.7-0.9 = clear primary issue, minor ambiguity. 0.4-0.6 = genuinely could reasonably fall into more than one category. Below 0.4 = you are essentially guessing due to a vague or contradictory complaint.

Examples:

Complaint: "My order #ORD-9982 never arrived and it's been 3 weeks, I'm furious"
Classification: category=delivery, department=logistics, urgency=high, entities={{order_ids: ["ORD-9982"]}}, summary="Order not delivered after 3 weeks", confidence=0.95

Complaint: "URGENT — someone else logged into my account and changed my password, I can't get back in"
Classification: category=account, department=tech_support, urgency=high, entities={{}}, summary="Suspected account takeover; unauthorized login and password change", confidence=0.95

Complaint: "I keep getting error code E-402 when I try to log into my account"
Classification: category=technical, department=tech_support, urgency=medium, entities={{error_code: "E-402"}}, summary="User cannot log in due to error E-402", confidence=0.95

Complaint: "nothing works, fix it now"
Classification: category=other, department=customer_service, urgency=medium, entities={{}}, summary="Vague complaint with no specific issue identified", confidence=0.5

Complaint: "Your app charged me twice for the same subscription, and also I can't reset my password, error E-501"
Classification: category=billing, department=billing, urgency=high, entities={{error_code: "E-501"}}, summary="Duplicate subscription charge; also reports password reset error E-501", confidence=0.85

Complaint: "I was charged for an order that never arrived"
Classification: category=billing, department=billing, urgency=high, entities={{}}, summary="Customer charged for an order that was never delivered", confidence=0.9

Complaint: "order not come yet very bad service want money back"
Classification: category=delivery, department=logistics, urgency=high, entities={{}}, summary="Customer reports non-delivery and is requesting a refund due to poor service", confidence=0.8

Complaint: "order id is order_no_88213, still hasn't shipped after a month"
Classification: category=delivery, department=logistics, urgency=high, entities={{order_ids: ["order_no_88213"]}}, summary="Order has not shipped after a month", confidence=0.9

Complaint: "My payment method was declined even though I have sufficient balance"
Classification: category=billing, department=billing, urgency=medium, entities={{}}, summary="Payment declined despite sufficient balance", confidence=0.75

Now classify this complaint:
Complaint: "{text}"
Output:"""


# --- STEP C: The function, simplified since we no longer parse messy text ---

def classify_complaint(text: str) -> dict:
    prompt = CLASSIFY_PROMPT.format(text=text)
    for attempt in range(MAX_RETRY_CYCLES):
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
                # response.parsed is a Classification object (Pydantic),
                # .model_dump() converts it into a plain Python dictionary
                return response.parsed.model_dump()
            except Exception as e:
                print(f"  {model_name} failed: {e}")
                continue
        time.sleep(RETRY_WAIT_SECONDS)

    raise RuntimeError("All models failed after retries — check API status or your quota.")


if __name__ == "__main__":
    tests = [
        # Sarcasm / indirect tone
        "Oh great, ANOTHER month where you charge me for a subscription I cancelled. Love it.",

        # No entities at all, extremely vague
        "things are broken please help",

        # Entity in an unusual format
        "order id is order_no_88213, still hasn't shipped after a month",

        # Genuinely ambiguous between two departments
        "I was billed for a product that never got delivered",

        # Positive/neutral tone, not really a complaint
        "just checking, is there a way to change my delivery address after ordering?",

        # Extremely short
        "refund??",

        # Long, rambling, multiple weak signals
        "so basically last week I tried logging in and it didn't work, then I got an email saying my card was charged, but I never even placed an order this month, I'm so confused what is going on",

        # Technical jargon a real user might paste in
        "Getting a 500 Internal Server Error on checkout page, tried 3 times",

        # Non-English mixed / broken grammar (realistic for real-world input)
        "order not come yet very bad service want money back",

        # Empty-ish / junk input
        "test test 123"
    ]
    for t in tests:
        print(f"\nInput: {t}")
        try:
            print(json.dumps(classify_complaint(t), indent=2))
        except Exception as e:
            print(f"  FAILED: {e}")