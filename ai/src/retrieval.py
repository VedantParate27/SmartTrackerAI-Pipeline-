import chromadb
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi

embedder = SentenceTransformer("all-MiniLM-L6-v2")
client = chromadb.PersistentClient(path=r"C:\Users\SwakeetMali\smarttracker-ai\chroma_db")
collection = client.get_collection("policies")


def vector_search(query, department, top_k=3):
    """
    Semantic search: finds chunks whose MEANING is closest to the query,
    restricted to the given department using ChromaDB's metadata filter.
    """
    embedding = embedder.encode(query).tolist()
    results = collection.query(
        query_embeddings=[embedding],
        n_results=top_k,
        where={"department": department}
    )
    # results["documents"][0] is a list of matching chunk texts
    # results["metadatas"][0] is a list of matching metadata dicts (source filename, etc.)
    return list(zip(results["documents"][0], results["metadatas"][0]))


def bm25_search(query, department, top_k=3):
    """
    Keyword search: finds chunks with exact word/code overlap with the query.
    We first pull ALL chunks for this department, then rank them with BM25.
    """
    all_data = collection.get(where={"department": department})
    docs = all_data["documents"]
    metas = all_data["metadatas"]

    if not docs:
        return []

    tokenized_docs = [doc.lower().split() for doc in docs]
    bm25 = BM25Okapi(tokenized_docs)
    scores = bm25.get_scores(query.lower().split())

    ranked = sorted(zip(docs, metas, scores), key=lambda x: -x[2])
    return [(doc, meta) for doc, meta, score in ranked[:top_k]]


def hybrid_search(query, department, top_k=3):
    """
    Combines both searches and removes duplicate chunks that showed up in both.
    """
    vec_results = vector_search(query, department, top_k)
    bm25_results = bm25_search(query, department, top_k)

    seen = set()
    merged = []
    for doc, meta in vec_results + bm25_results:
        if doc not in seen:
            seen.add(doc)
            merged.append((doc, meta))

    return merged[:top_k]


if __name__ == "__main__":
    query = "my order hasn't arrived in 3 weeks, order ORD-1234"
    department = "logistics"

    print(f"Query: {query}")
    print(f"Department filter: {department}\n")

    results = hybrid_search(query, department)
    for i, (doc, meta) in enumerate(results, 1):
        print(f"--- Result {i} (source: {meta['source']}) ---")
        print(doc[:200] + "...\n")