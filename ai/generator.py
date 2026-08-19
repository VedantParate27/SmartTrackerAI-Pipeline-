from .common import call_gemini_with_retry

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


def generate_response(complaint: str, retrieved_chunks: list) -> str:
    context = "\n\n".join(
        f"[{meta['source']}]: {doc}" for doc, meta in retrieved_chunks
    )
    prompt = GEN_PROMPT.format(context=context, complaint=complaint)
    return call_gemini_with_retry(prompt)


if __name__ == "__main__":
    from .retrieval import hybrid_search

    complaint = "my order hasn't arrived in 3 weeks, order ORD-1234"
    department = "logistics"

    chunks = hybrid_search(complaint, department)
    draft = generate_response(complaint, chunks)

    print("=== DRAFT RESPONSE ===\n")
    print(draft)
