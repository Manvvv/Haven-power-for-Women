"""
Haven - MongoDB Atlas Vector Index Setup
Run this ONCE after connecting to MongoDB Atlas to create the necessary
vector search indexes for culprit matching and legal RAG.

Requirements:
- MongoDB Atlas M0 (free) or higher cluster
- pymongo installed
- MONGO_ENDPOINT set in .env

Usage:
  python backend/setup_indexes.py
"""

import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("MONGO_ENDPOINT"))
db = client["haven"]

print("Setting up Haven MongoDB indexes...")

# ── 1. Culprit vector index ──────────────────────────────
# This enables the /culprit/find-match endpoint via cosine similarity
print("\n[1/3] Creating culprit vector search index...")
try:
    db.command({
        "createSearchIndexes": "culprits",
        "indexes": [{
            "name": "culpritIndex",
            "definition": {
                "mappings": {
                    "dynamic": True,
                    "fields": {
                        "description_embedding": {
                            "type": "knnVector",
                            "dimensions": 768,  # Gemini text-embedding-004 output dims
                            "similarity": "cosine"
                        }
                    }
                }
            }
        }]
    })
    print("  ✓ culpritIndex created")
except Exception as e:
    print(f"  ⚠ culpritIndex may already exist or Atlas tier too low: {e}")

# ── 2. Legal documents vector index ─────────────────────
# This powers the /legal/query RAG endpoint
print("\n[2/3] Creating legal documents vector search index...")
try:
    db.command({
        "createSearchIndexes": "legal_docs",
        "indexes": [{
            "name": "legalIndex",
            "definition": {
                "mappings": {
                    "dynamic": True,
                    "fields": {
                        "embedding": {
                            "type": "knnVector",
                            "dimensions": 768,
                            "similarity": "cosine"
                        }
                    }
                }
            }
        }]
    })
    print("  ✓ legalIndex created")
except Exception as e:
    print(f"  ⚠ legalIndex may already exist: {e}")

# ── 3. Regular indexes for fast case queries ─────────────
print("\n[3/3] Creating standard indexes for SOS cases...")
db["sos_cases"].create_index([("severity", 1), ("status", 1)])
db["sos_cases"].create_index([("created_at", -1)])
db["sos_cases"].create_index([("case_id", 1)], unique=True, sparse=True)
db["culprits"].create_index([("culprit_id", 1)])
db["therapy_sessions"].create_index([("session_id", 1)])
db["therapy_sessions"].create_index([("user_id", 1)])
print("  ✓ Standard indexes created")

print("\n✅ Setup complete! Haven is ready to use.")
print("\nNext steps:")
print("  1. Upload legal PDFs via: POST /legal/upload-doc")
print("  2. Start backend: uvicorn backend.main:app --reload")
print("  3. Start frontend: npm run dev (inside frontend/)")
