from google import genai
import os
import time
from dotenv import load_dotenv
from config import MODELS_TO_TRY, MAX_RETRY_CYCLES, RETRY_WAIT_SECONDS, ENV_PATH

load_dotenv(dotenv_path=ENV_PATH)
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

GEN_PROMPT = """You are a customer support assistant drafting a reply to a customer complaint.

STRICT RULES:
- Only use facts that appear in the CONTEXT below. Do not invent policies, refund amounts, timelines, or promises not explicitly stated in the context.
- After each factual claim drawn from a policy document, cite that source using the format [Source: filename.txt]. Only use this citation format for real policy documents provided in the CONTEXT below — never invent a source name, and never use the citation format to describe your own reasoning, limitations, or lack of information. State those plainly in your own words instead, with no bracketed citation attached.
- If the CONTEXT does not contain enough information to resolve the complaint, say so honestly in plain language and state that the case will be escalated for manual review — do not guess, and do not cite a source for this statement since it is not a policy fact.
- Always respond in English, regardless of the language the complaint was written in, unless explicitly instructed otherwise.
- Keep the tone professional and empathetic.

CONTEXT:
{context}

CUSTOMER COMPLAINT:
{complaint}

DRAFT RESPONSE:"""


def generate_response(complaint: str, retrieved_chunks: list) -> str:
    context = "\n\n".join(
        f"[{meta['source']}]: {doc}" for doc, meta in retrieved_chunks
    )
    prompt = GEN_PROMPT.format(context=context, complaint=complaint)

    for attempt in range(MAX_RETRY_CYCLES):
        for model_name in MODELS_TO_TRY:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                return response.text
            except Exception as e:
                print(f"  {model_name} failed: {e}")
                continue
        time.sleep(RETRY_WAIT_SECONDS)

    raise RuntimeError("All models failed after retries — check API status or your quota.")


if __name__ == "__main__":
    from retrieval import hybrid_search, rerank

    complaint = "my order hasn't arrived in 3 weeks, order ORD-1234"
    department = "logistics"

    candidates = hybrid_search(complaint, department)
    chunks_with_scores = rerank(complaint, candidates)
    chunks = [(doc, meta) for doc, meta, score in chunks_with_scores]
    draft = generate_response(complaint, chunks)

    print("=== DRAFT RESPONSE ===\n")
    print(draft)