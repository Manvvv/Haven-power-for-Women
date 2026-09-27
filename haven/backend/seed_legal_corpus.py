"""
seed_legal_corpus.py — Idempotent ingestion of the VERIFIED Indian legal corpus.

Fixes the root cause of the Legal Assistant returning "no verified source": the
`legal_docs` collection was empty. This loads the curated corpus in
`services/legal_corpus.py` through the normal RAG ingestion pipeline (chunk ->
embed -> store), so retrieval has grounded, citable material.

Idempotent: `legal_rag.ingest_document` dedupes by chunk_hash, so re-running only
adds new/changed entries. Safe to run repeatedly.

Run on Windows (PowerShell), from the backend folder:
    cd haven\backend
    python seed_legal_corpus.py

Requires the same environment as the backend (MongoDB reachable via MONGODB_URI;
GEMINI_API_KEY optional — without it, embeddings degrade and retrieval falls back
to keyword mode, which still works with this corpus).
"""
import sys

from services import legal_corpus, legal_rag
from services.db import legal_docs
from services.embeddings import embedding_info


def main() -> int:
    coll = legal_docs()
    if coll is None:
        print("ERROR: MongoDB is not available. Check MONGODB_URI / network and retry.")
        return 2

    info = embedding_info()
    print(f"Embedding backend: {info['backend']} | status: {info['status']} | "
          f"semantic_search_available: {info.get('semantic_search_available')}")
    if info["status"] in ("DEMO", "FALLBACK"):
        print("NOTE: embeddings are in DEMO/FALLBACK mode (no GEMINI_API_KEY?). "
              "Corpus will still seed; retrieval will use keyword fallback until "
              "embeddings are configured, then re-run to backfill vectors.")

    entries = legal_corpus.all_entries()
    print(f"Corpus version {legal_corpus.CORPUS_VERSION}: {len(entries)} verified entries")
    print("-" * 72)

    total_ing = total_skip = 0
    failures = []
    for e in entries:
        res = legal_rag.ingest_document(
            title=e["title"],
            text=e["text"],
            source_name=e.get("authority", ""),
            source_url=e.get("source_url", ""),
            jurisdiction=e.get("jurisdiction", "India"),
            section=e.get("section", ""),
            verification_status=e.get("verification_status", "verified"),
            document_version=str(e.get("version", "1")),
            uploaded_by="seed_script",
            document_id=e["document_id"],
            metadata=e,
        )
        if res.get("error"):
            failures.append((e["document_id"], res["error"]))
            print(f"  ! {e['document_id']:32} ERROR: {res['error']}")
            continue
        ing, skip = res.get("chunks_ingested", 0), res.get("chunks_skipped", 0)
        total_ing += ing
        total_skip += skip
        flag = "+" if ing else "="
        print(f"  {flag} {e['document_id']:32} ingested={ing} skipped={skip}")

    print("-" * 72)
    print(f"DONE: {total_ing} chunks ingested, {total_skip} already present, "
          f"{len(failures)} failures.")
    print(f"legal_docs now holds {coll.count_documents({})} chunks.")
    if failures:
        print("FAILURES:", failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
