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
db = client["Haven"]

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
db["sos_cases"].create_index([("trigger_type", 1)])
db["therapy_sessions"].create_index([("session_id", 1)])
db["therapy_sessions"].create_index([("user_id", 1)])
print("  ✓ Standard indexes created")

# ── 3b. Profile (culprits) lookup indexes ─────────────────
# Speed up deterministic name search, profile-id / case / location lookups and
# duplicate detection (requirement 24). All idempotent. The public culprit_id is
# made unique+sparse; if a legacy non-unique index already exists with the same
# key, we keep it (a unique rebuild needs a manual drop and dedupe first).
print("\n[3b] Creating profile lookup indexes...")
try:
    db["culprits"].create_index([("culprit_id", 1)], unique=True, sparse=True)
    print("  ✓ culprit_id unique index")
except Exception as e:
    # Fall back to a plain (non-unique) index so lookups are still fast.
    try:
        db["culprits"].create_index([("culprit_id", 1)])
    except Exception:
        pass
    print(f"  ⚠ culprit_id unique index not applied (legacy index present?): {e}")
db["culprits"].create_index([("name", 1)])
db["culprits"].create_index([("location", 1)])
db["culprits"].create_index([("created_at", -1)])
db["culprits"].create_index([("associated_cases.case_id", 1)])
print("  ✓ Profile lookup indexes created")

# ── 4. Voice SOS indexes ──────────────────────────────────
print("\n[4/5] Creating Voice SOS indexes...")
db["voice_sos_config"].create_index([("user_id", 1)], unique=True)
db["trusted_contacts"].create_index([("user_id", 1)])
db["sos_events"].create_index([("user_id", 1)])
db["sos_events"].create_index([("event_id", 1)], unique=True, sparse=True)
db["sos_events"].create_index([("created_at", -1)])
print("  ✓ Voice SOS indexes created")

# ── 5. Enterprise, Security & Audit indexes ───────────────
print("\n[5/5] Creating Audit, Notification, Lifecycle & Privacy indexes...")
db["audit_logs"].create_index([("timestamp", -1)])
db["audit_logs"].create_index([("action", 1)])
db["audit_logs"].create_index([("actor_id", 1)])
db["audit_logs"].create_index([("case_id", 1)])

db["notifications"].create_index([("recipient_id", 1), ("read", 1)])
db["notifications"].create_index([("created_at", -1)])

db["sos_status_history"].create_index([("case_id", 1), ("timestamp", 1)])
db["privacy_records"].create_index([("user_id", 1)])
db["ai_analyses"].create_index([("case_id", 1)], unique=True, sparse=True)

# Cases Vector Search Index for semantic search
try:
    db.command({
        "createSearchIndexes": "sos_cases",
        "indexes": [{
            "name": "casesIndex",
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
    print("  ✓ casesIndex created")
except Exception as e:
    print(f"  ⚠ casesIndex may already exist: {e}")

print("  ✓ Audit, Notification, Lifecycle & Privacy indexes created")

print("\n✅ Setup complete! Haven is ready to use.")
print("\nNext steps:")
print("  1. Upload legal PDFs via: POST /legal/upload-doc")
print("  2. Start backend: uvicorn backend.main:app --reload")
print("  3. Start frontend: npm run dev (inside frontend/)")
