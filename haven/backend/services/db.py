import os
import logging
from pymongo import MongoClient
from dotenv import load_dotenv
from pathlib import Path

logger = logging.getLogger('haven_backend')
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / '.env')

MONGO_ENDPOINT = os.getenv('MONGO_ENDPOINT', '')

# Singleton connection
_client = None
_db = None

def get_db():
    global _client, _db
    if _db is None and MONGO_ENDPOINT:
        try:
            _client = MongoClient(MONGO_ENDPOINT, serverSelectionTimeoutMS=3000)
            _db = _client['Haven']
            logger.info('MongoDB connected successfully')
        except Exception as e:
            logger.warning(f'Could not connect to MongoDB: {e}')
    return _db

def get_collection(name: str):
    db = get_db()
    return db[name] if db is not None else None

# Collection accessors
def sos_cases(): return get_collection('sos_cases')
def culprits(): return get_collection('culprits')
def legal_docs(): return get_collection('legal_docs')
def therapy_sessions(): return get_collection('therapy_sessions')
def voice_sos_config(): return get_collection('voice_sos_config')
def trusted_contacts(): return get_collection('trusted_contacts')
def sos_events(): return get_collection('sos_events')
def dir_reports(): return get_collection('dir_reports')
def audit_logs(): return get_collection('audit_logs')
def notifications(): return get_collection('notifications')
def sos_status_history(): return get_collection('sos_status_history')
def privacy_records(): return get_collection('privacy_records')
def ai_analyses(): return get_collection('ai_analyses')
def authority_accounts(): return get_collection('authority_accounts')
# Mental-health module: stored ENCRYPTED at rest, user-controlled, minimized.
def safety_plans(): return get_collection('mh_safety_plans')
def mood_journal(): return get_collection('mh_mood_journal')
def mood_checkins(): return get_collection('mh_mood_checkins')

# Module-level collection references for direct import compatibility
_init_db = get_db()
sos_collection = _init_db["sos_cases"] if _init_db is not None else None
culprit_collection = _init_db["culprits"] if _init_db is not None else None
legal_collection = _init_db["legal_docs"] if _init_db is not None else None
therapy_collection = _init_db["therapy_sessions"] if _init_db is not None else None
voice_sos_config_collection = _init_db["voice_sos_config"] if _init_db is not None else None
trusted_contacts_collection = _init_db["trusted_contacts"] if _init_db is not None else None
sos_events_collection = _init_db["sos_events"] if _init_db is not None else None
dir_reports_collection = _init_db["dir_reports"] if _init_db is not None else None
audit_logs_collection = _init_db["audit_logs"] if _init_db is not None else None
notifications_collection = _init_db["notifications"] if _init_db is not None else None


def serialize_doc(doc: dict) -> dict:
    """Convert MongoDB doc to JSON-safe dict."""
    if not isinstance(doc, dict):
        return doc
    result = {}
    for k, v in doc.items():
        if k == '_id':
            continue
        elif hasattr(v, 'isoformat'):
            result[k] = v.isoformat()
        elif isinstance(v, list):
            result[k] = [serialize_doc(i) if isinstance(i, dict) else i for i in v]
        elif isinstance(v, dict):
            result[k] = serialize_doc(v)
        else:
            result[k] = v
    return result
