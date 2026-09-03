from config import CHROMA_DB_PATH, RETRIEVAL_CANDIDATE_POOL, RRF_K_CONSTANT
import chromadb
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder
import math

embedder = SentenceTransformer("all-MiniLM-L6-v2")
# Cross-encoder: scores query+chunk pairs directly for true relevance,
# more precise than rank-based fusion but slower, so we only use it on
# a small shortlist rather than the whole database.
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
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


def hybrid_search(query, department, top_k=3, k_constant=RRF_K_CONSTANT, candidate_pool=RETRIEVAL_CANDIDATE_POOL):
    """
    Combines vector + BM25 search using Reciprocal Rank Fusion (RRF).
    Instead of just concatenating results, each chunk gets a score based on
    WHERE it ranked in each search method — chunks that rank well in BOTH
    methods score highest overall.
    """
    # Pull a larger pool from each method than we ultimately need,
    # so RRF has enough candidates to properly compare and re-rank.
    vec_results = vector_search(query, department, candidate_pool)
    bm25_results = bm25_search(query, department, candidate_pool)

    # rrf_scores maps: chunk_text -> {"score": float, "meta": dict}
    rrf_scores = {}

    for rank, (doc, meta) in enumerate(vec_results, start=1):
        if doc not in rrf_scores:
            rrf_scores[doc] = {"score": 0.0, "meta": meta}
        rrf_scores[doc]["score"] += 1 / (k_constant + rank)

    for rank, (doc, meta) in enumerate(bm25_results, start=1):
        if doc not in rrf_scores:
            rrf_scores[doc] = {"score": 0.0, "meta": meta}
        rrf_scores[doc]["score"] += 1 / (k_constant + rank)

    # Sort all candidates by their combined RRF score, highest first
    ranked = sorted(rrf_scores.items(), key=lambda x: -x[1]["score"])

    return [(doc, data["meta"]) for doc, data in ranked[:top_k]]

def rerank(query, candidates, top_k=3):
    """
    Takes the RRF-fused candidates and re-scores them using a cross-encoder,
    which directly judges query-chunk relevance rather than relying on
    separate embeddings or rank position.

    Returns a list of (doc, meta, score) tuples instead of just (doc, meta),
    so callers can check whether the top result is genuinely relevant,
    not just "the best of a bad bunch."
    """
    if not candidates:
        return []

    pairs = [(query, doc) for doc, meta in candidates]
    scores = reranker.predict(pairs)

    def sigmoid(x):
        return 1 / (1 + math.exp(-x))

    scored = [(doc, meta, sigmoid(float(score))) for (doc, meta), score in zip(candidates, scores)]
    scored.sort(key=lambda x: -x[2])

    return scored[:top_k]

if __name__ == "__main__":
    query = "my order hasn't arrived in 3 weeks, order ORD-1234"
    department = "logistics"

    print(f"Query: {query}")
    print(f"Department filter: {department}\n")

    # Get a wider candidate pool from hybrid search first
    candidates = hybrid_search(query, department, top_k=5)

    # Then rerank that shortlist down to the final top 3
    results = rerank(query, candidates, top_k=3)

    for i, (doc, meta, score) in enumerate(results, 1):
        print(f"--- Result {i} (source: {meta['source']}, relevance: {score:.3f}) ---")
        print(doc[:200] + "...\n")