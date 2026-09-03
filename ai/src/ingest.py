from config import CHROMA_DB_PATH, POLICIES_FOLDER, CHUNK_MAX_WORDS, CHUNK_MIN_WORDS
import chromadb
from sentence_transformers import SentenceTransformer
import os

# This model turns text into a 384-number vector representing its meaning.
# It downloads automatically the first time you run this (about 80MB).
embedder = SentenceTransformer("all-MiniLM-L6-v2")

# PersistentClient means the database saves to disk in ./chroma_db,
# so it survives between runs (as opposed to living only in memory).
client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
# get_or_create so re-running this script doesn't error out if it already exists
collection = client.get_or_create_collection("policies")


def chunk_text(text, max_words=CHUNK_MAX_WORDS, min_words=CHUNK_MIN_WORDS):
    """
    Splits text into chunks by PARAGRAPH (blank-line-separated), not raw word count.
    This keeps each chunk as one complete, self-contained policy rule instead of
    cutting a sentence in half at an arbitrary word boundary.

    Safety nets:
    - If a paragraph is too long (> max_words), we further split it by sentence.
    - If a paragraph is very short (< min_words), we merge it with the next one,
      so we don't end up with tiny fragments lacking context (e.g. just a title line).
    """
    # Split on blank lines first — this is how paragraphs are separated in your .txt files
    raw_paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = []
    buffer = ""  # holds a short paragraph waiting to be merged with the next one

    for para in raw_paragraphs:
        word_count = len(para.split())

        # If this paragraph is too long on its own, split it further by sentence
        if word_count > max_words:
            sentences = para.replace("\n", " ").split(". ")
            sub_chunk = ""
            for sentence in sentences:
                if len((sub_chunk + sentence).split()) > max_words and sub_chunk:
                    chunks.append(sub_chunk.strip())
                    sub_chunk = sentence
                else:
                    sub_chunk += (". " if sub_chunk else "") + sentence
            if sub_chunk:
                chunks.append(sub_chunk.strip())
            continue

        # If this paragraph is short, hold onto it and merge with the next one
        combined = (buffer + " " + para).strip() if buffer else para
        if len(combined.split()) < min_words:
            buffer = combined
            continue

        chunks.append(combined)
        buffer = ""

    # If anything's left in the buffer at the end, add it as a final chunk
    if buffer:
        chunks.append(buffer)

    return chunks

DEPARTMENT_MAP = {
    "billing": "billing",
    "logistics": "logistics",
    "techsupport": "tech_support",
    "customerservice": "customer_service",
}

def ingest_policies(folder=POLICIES_FOLDER):
    for fname in os.listdir(folder):
        if not fname.endswith(".txt"):
            continue

        prefix = fname.split("_")[0]
        department = DEPARTMENT_MAP.get(prefix, prefix)  # fallback to prefix if not mapped

        with open(os.path.join(folder, fname), encoding="utf-8") as f:
            text = f.read()

        chunks = chunk_text(text)

        for i, chunk in enumerate(chunks):
            embedding = embedder.encode(chunk).tolist()
            collection.add(
                ids=[f"{fname}_{i}"],
                embeddings=[embedding],
                documents=[chunk],
                metadatas=[{"department": department, "source": fname}]
            )
        print(f"Ingested {len(chunks)} chunk(s) from {fname} (department: {department})")

    print(f"\nTotal chunks in collection: {collection.count()}")

if __name__ == "__main__":
    ingest_policies()