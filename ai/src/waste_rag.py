"""
RAG for waste disposal guidance: retrieves the relevant waste-guideline
document for a given waste type and generates grounded disposal advice,
reusing the same retrieval and generation patterns as the main complaint
pipeline, pointed at a separate ChromaDB collection and prompt.
"""
import chromadb
from sentence_transformers import SentenceTransformer, CrossEncoder
from google import genai
import os
import math
import time
from dotenv import load_dotenv
from config import CHROMA_DB_PATH, ENV_PATH, MODELS_TO_TRY, MAX_RETRY_CYCLES, RETRY_WAIT_SECONDS

load_dotenv(dotenv_path=ENV_PATH)
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

embedder = SentenceTransformer("all-MiniLM-L6-v2")
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
waste_collection = chroma_client.get_or_create_collection("waste_guidelines")


FILENAME_TO_WASTE_TYPE = {
    "wet_waste.txt": "wet",
    "dry_waste.txt": "dry",
    "hazardous_waste.txt": "hazardous",
    "sanitary_waste.txt": "sanitary",
    "ewaste_waste.txt": "e_waste",
    "mixed_waste.txt": "mixed",
}


def ingest_waste_guidelines(folder):
    import os as _os
    for fname in _os.listdir(folder):
        if not fname.endswith(".txt"):
            continue
        waste_type = FILENAME_TO_WASTE_TYPE.get(fname, fname.replace(".txt", ""))
        with open(_os.path.join(folder, fname), encoding="utf-8") as f:
            text = f.read()
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        for i, para in enumerate(paragraphs):
            embedding = embedder.encode(para).tolist()
            waste_collection.add(
                ids=[f"{fname}_{i}"],
                embeddings=[embedding],
                documents=[para],
                metadatas=[{"waste_type": waste_type, "source": fname}]
            )
        print(f"Ingested {len(paragraphs)} chunk(s) from {fname} (waste_type: {waste_type})")
    print(f"Total chunks: {waste_collection.count()}")


def retrieve_guidance_chunks(waste_type: str, top_k: int = 3):
    all_data = waste_collection.get(where={"waste_type": waste_type})
    docs = all_data["documents"]
    metas = all_data["metadatas"]
    if not docs:
        return []
    query = f"how to dispose of {waste_type} waste"
    pairs = [(query, doc) for doc in docs]
    scores = reranker.predict(pairs)

    def sigmoid(x):
        return 1 / (1 + math.exp(-x))

    ranked = sorted(zip(docs, metas, scores), key=lambda x: -x[2])[:top_k]
    return [(doc, meta, sigmoid(float(score))) for doc, meta, score in ranked]


DISPOSAL_PROMPT = """You are a waste management assistant giving a citizen clear, practical disposal advice.

STRICT RULES:
- Only use facts from the CONTEXT below. Do not invent disposal methods, regulations, or facilities not mentioned in the context.
- After each factual claim drawn from a guideline document, cite that source using [Source: filename.txt]. Only use this citation format for real documents actually provided in the CONTEXT below — never invent a source name, and never cite anything when explaining that information is missing. If the context does not cover the situation, say so plainly in your own words with no bracketed citation attached.
- Keep the tone friendly, practical, and brief — this is a citizen who wants clear next steps, not a formal letter.

CONTEXT:
{context}

WASTE TYPE DETECTED: {waste_type}
ADDITIONAL DETAILS: {additional_context}

DISPOSAL GUIDANCE:"""


def generate_disposal_guidance(waste_type: str, chunks: list, additional_context: str = None) -> str:
    context = "\n\n".join(f"[{meta['source']}]: {doc}" for doc, meta, score in chunks)
    prompt = DISPOSAL_PROMPT.format(
        context=context if context else "(no guidance found)",
        waste_type=waste_type,
        additional_context=additional_context if additional_context else "(none provided)",
    )

    for attempt in range(MAX_RETRY_CYCLES):
        for model_name in MODELS_TO_TRY:
            try:
                response = client.models.generate_content(model=model_name, contents=prompt)
                return response.text
            except Exception as e:
                print(f"  {model_name} failed: {e}")
                continue
        time.sleep(RETRY_WAIT_SECONDS)

    raise RuntimeError("All models failed after retries.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "ingest":
        ingest_waste_guidelines(r"C:\Users\SwakeetMali\smarttracker-ai\data\waste_guidelines")
    else:
        chunks = retrieve_guidance_chunks("wet")
        guidance = generate_disposal_guidance("wet", chunks)
        print(guidance)