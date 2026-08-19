import os

import chromadb
from sentence_transformers import SentenceTransformer

from .common import CHROMA_DB_PATH, POLICIES_DIR

# This model turns text into a 384-number vector representing its meaning.
# It downloads automatically the first time you run this (about 80MB).
embedder = SentenceTransformer("all-MiniLM-L6-v2")

# PersistentClient means the database saves to disk, so it survives between runs.
_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
_collection = _client.get_or_create_collection("policies")

DEPARTMENT_MAP = {
    "billing": "billing",
    "logistics": "logistics",
    "techsupport": "tech_support",
    "customerservice": "customer_service",
}


def chunk_text(text, chunk_size=100):
    """
    Splits text into chunks of roughly `chunk_size` words.
    We chunk because embeddings work better on short, focused text
    than on one giant document.
    """
    words = text.split()
    return [" ".join(words[i : i + chunk_size]) for i in range(0, len(words), chunk_size)]


def ingest_policies(folder: str = None, force: bool = False):
    """Ingest every .txt policy file in `folder` into ChromaDB.

    By default this is idempotent: if the collection already has chunks,
    it skips re-ingesting unless force=True (avoids duplicate chunks from
    re-running the script).
    """
    folder = folder or POLICIES_DIR

    if not force and _collection.count() > 0:
        print(
            f"Collection already has {_collection.count()} chunks. "
            "Pass force=True to re-ingest."
        )
        return

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
            _collection.add(
                ids=[f"{fname}_{i}"],
                embeddings=[embedding],
                documents=[chunk],
                metadatas=[{"department": department, "source": fname}],
            )
        print(f"Ingested {len(chunks)} chunk(s) from {fname} (department: {department})")

    print(f"\nTotal chunks in collection: {_collection.count()}")


if __name__ == "__main__":
    ingest_policies()
