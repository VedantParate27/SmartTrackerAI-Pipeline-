from google import genai
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=r"C:\Users\SwakeetMali\smarttracker-ai\.env")
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

GEN_PROMPT = """You are a customer support assistant drafting a reply to a customer complaint.

STRICT RULES:
- Only use facts that appear in the CONTEXT below. Do not invent policies, refund amounts, timelines, or promises not explicitly stated in the context.
- After each factual claim, cite the source document in square brackets, like [Source: filename.txt].
- If the CONTEXT does not contain enough information to resolve the complaint, say so honestly and state that the case will be escalated for manual review — do not guess.
- Keep the tone professional and empathetic.

CONTEXT:
{context}

CUSTOMER COMPLAINT:
{complaint}

DRAFT RESPONSE:"""


import time

def generate_response(complaint: str, retrieved_chunks: list) -> str:
    context = "\n\n".join(
        f"[{meta['source']}]: {doc}" for doc, meta in retrieved_chunks
    )
    prompt = GEN_PROMPT.format(context=context, complaint=complaint)

    models_to_try = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]

    for attempt in range(3):
        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                return response.text
            except Exception as e:
                print(f"  {model_name} failed: {e}")
                continue
        time.sleep(10)

    raise RuntimeError("All models failed after retries — check API status or your quota.")

if __name__ == "__main__":
    from retrieval import hybrid_search

    complaint = "my order hasn't arrived in 3 weeks, order ORD-1234"
    department = "logistics"

    chunks = hybrid_search(complaint, department)
    draft = generate_response(complaint, chunks)

    print("=== DRAFT RESPONSE ===\n")
    print(draft)