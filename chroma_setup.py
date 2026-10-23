"""
One-time (idempotent) setup: ingest all policy documents in data/policies/
into ChromaDB so the RAG pipeline has something to retrieve against.

Run: python chroma_setup.py
Re-run any time you add new policy docs (add force=True to re-ingest all).
"""
from ai.ingest import ingest_policies

if __name__ == "__main__":
    ingest_policies()
