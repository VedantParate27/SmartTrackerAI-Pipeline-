import chromadb
from sentence_transformers import SentenceTransformer
import os

# This model turns text into a 384-number vector representing its meaning.
# It downloads automatically the first time you run this (about 80MB).
embedder = SentenceTransformer("all-MiniLM-L6-v2")

# PersistentClient means the database saves to disk in ./chroma_db,
# so it survives between runs (as opposed to living only in memory).
client = chromadb.PersistentClient(path=r"C:\Users\SwakeetMali\smarttracker-ai\chroma_db")

# get_or_create so re-running this script doesn't error out if it already exists
collection = client.get_or_create_collection("policies")


def chunk_text(text, chunk_size=100):
    """
    Splits text into chunks of roughly `chunk_size` words.
    We chunk because embeddings work better on short, focused text
    than on one giant document.
    """
    words = text.split()
    return [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]


DEPARTMENT_MAP = {
    "billing": "billing",
    "logistics": "logistics",
    "techsupport": "tech_support",
    "customerservice": "customer_service",
}

def ingest_policies(folder=r"C:\Users\SwakeetMali\smarttracker-ai\data\policies"):
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