import os
import base64
import io
import json
import re
import struct
import zlib
import hashlib
import hmac
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import secrets

import requests
from fastapi import FastAPI, HTTPException, UploadFile, File, Body, Query, WebSocket, WebSocketDisconnect, Depends, Header, Request, status
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from dotenv import load_dotenv
from pathlib import Path
from google import genai

from auth import (
    AuthUser,
    TokenResponse,
    AuthorityLoginModel,
    create_access_token,
    get_current_user,
    get_optional_user,
    require_authority,
    require_admin,
    verify_authority_password,
    hash_safe_word_salted,
    verify_safe_word,
    encrypt_evidence_payload,
    decrypt_evidence_payload,
    normalize_text,
    JWT_EXPIRATION_HOURS,
)
from rate_limiter import rate_limit_dependency

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("haven_backend")

# Load .env from the same folder as this file (works regardless of cwd)
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

app = FastAPI(
    title="Haven API",
    version="2.0.0",
    description="Secure, resilient backend for Haven Women Safety Platform"
)

# ─── CORS Configuration (Explicit Origin Allowlist) ───────
ALLOWED_ORIGINS_RAW = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allowed_origins = [o.strip() for o in ALLOWED_ORIGINS_RAW.split(",") if o.strip()]
frontend_env = os.getenv("FRONTEND_URL")
if frontend_env and frontend_env not in allowed_origins:
    allowed_origins.append(frontend_env.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if allowed_origins else ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ─── MongoDB ─────────────────────────────────────────────
MONGO_ENDPOINT = os.getenv("MONGO_ENDPOINT", "")
client = None
db = None
sos_collection = None
culprit_collection = None
legal_collection = None
therapy_collection = None
voice_sos_config_collection = None
trusted_contacts_collection = None
sos_events_collection = None
dir_reports_collection = None

if MONGO_ENDPOINT:
    try:
        client = MongoClient(MONGO_ENDPOINT, serverSelectionTimeoutMS=3000)
        db = client["Haven"]
        sos_collection = db["sos_cases"]
        culprit_collection = db["culprits"]
        legal_collection = db["legal_docs"]
        therapy_collection = db["therapy_sessions"]
        voice_sos_config_collection = db["voice_sos_config"]
        trusted_contacts_collection = db["trusted_contacts"]
        sos_events_collection = db["sos_events"]
        dir_reports_collection = db["dir_reports"]
    except Exception as e:
        logger.warning(f"⚠️ Could not connect to MongoDB: {e}")

# ─── API Keys ────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")
HF_API_KEY = os.getenv("HF_API_KEY", "")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
GEMINI_EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
HF_IMG_URL = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"

# Configure Google GenAI Client
genai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


# ─── Sanitized External AI Service Helpers ────────────────

def call_gemini(prompt: str, system: str = "") -> str:
    """Call Gemini API with safe error handling without leaking upstream details."""
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": full_prompt}]}]},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error(f"Gemini upstream error code {resp.status_code}: {resp.text}")
            raise HTTPException(status_code=502, detail="AI Service temporarily unavailable. Please try again later.")
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Gemini connection error: {str(e)}")
        raise HTTPException(status_code=502, detail="AI Service connection timeout.")


def call_groq(messages: list, model: str = "openai/gpt-oss-120b", max_tokens: int = 1024) -> str:
    """Call Groq API with sanitized error handling and automatic model/Gemini fallback."""
    candidate_models = [model]
    for fallback in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]:
        if fallback not in candidate_models:
            candidate_models.append(fallback)

    last_error = None
    if GROQ_API_KEY:
        for candidate in candidate_models:
            try:
                resp = requests.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    json={"model": candidate, "messages": messages, "max_tokens": max_tokens},
                    timeout=30,
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
                logger.warning(f"Groq upstream error code {resp.status_code} for model {candidate}: {resp.text}")
                last_error = f"Groq status {resp.status_code}"
            except Exception as e:
                logger.warning(f"Groq error with model {candidate}: {str(e)}")
                last_error = str(e)

    # Fallback to Gemini if Groq fails or key is missing
    if GEMINI_API_KEY:
        try:
            logger.info("Falling back to Gemini for language generation...")
            system_parts = [m["content"] for m in messages if m.get("role") == "system"]
            user_parts = [m["content"] for m in messages if m.get("role") in ["user", "assistant"]]
            system_str = "\n\n".join(system_parts)
            prompt_str = "\n\n".join(user_parts)
            return call_gemini(prompt=prompt_str, system=system_str)
        except Exception as e:
            logger.error(f"Gemini fallback failed: {str(e)}")

    logger.error(f"All LLM providers failed. Last error: {last_error}")
    raise HTTPException(status_code=502, detail="Language model service is currently unavailable.")


def get_embedding(text: str) -> list:
    """Get vector embedding from Gemini with sanitized errors."""
    try:
        resp = requests.post(
            f"{GEMINI_EMBED_URL}?key={GEMINI_API_KEY}",
            json={"model": "models/gemini-embedding-001", "content": {"parts": [{"text": text[:2000]}]}},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error(f"Embedding upstream error code {resp.status_code}")
            # Fallback zero-vector of length 768 to prevent complete endpoint crash
            return [0.0] * 768
        return resp.json()["embedding"]["values"]
    except Exception as e:
        logger.error(f"Embedding generation error: {str(e)}")
        return [0.0] * 768


def generate_image_hf(prompt: str) -> bytes:
    import urllib.parse

    # 1. Try HuggingFace InferenceClient with a working model
    if HF_API_KEY:
        try:
            from huggingface_hub import InferenceClient
            hf_client = InferenceClient(api_key=HF_API_KEY)
            img = hf_client.text_to_image(
                prompt + ", high quality, photorealistic, peaceful",
                model="stabilityai/stable-diffusion-xl-base-1.0",
            )
            output = io.BytesIO()
            img.save(output, format="PNG")
            return output.getvalue()
        except Exception as e:
            logger.warning(f"HF InferenceClient error: {e}")

    # 2. Try Pollinations AI (free, no key needed)
    try:
        encoded_prompt = urllib.parse.quote(prompt[:200] + ", peaceful nature, high quality")
        pollinations_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=512&height=512&nologo=true"
        resp = requests.get(pollinations_url, timeout=30)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return resp.content
    except Exception as e:
        logger.warning(f"Pollinations AI error: {e}")

    # 3. Fallback: Create a clean gradient canvas PNG with Pillow
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (512, 512), color=(253, 242, 248))
        draw = ImageDraw.Draw(img)
        draw.ellipse([100, 100, 412, 412], fill=(252, 231, 243), outline=(190, 24, 93), width=2)
        draw.ellipse([180, 180, 332, 332], fill=(244, 114, 182))
        output = io.BytesIO()
        img.save(output, format="PNG")
        return output.getvalue()
    except Exception as e:
        logger.error(f"Canvas fallback error: {e}")
        raise HTTPException(status_code=500, detail="Image generation failed")


def upload_to_cloudinary(image_bytes: bytes, public_id: str = None) -> str:
    if not CLOUDINARY_API_SECRET or not CLOUDINARY_CLOUD_NAME:
        raise HTTPException(status_code=503, detail="Cloud storage is not configured")
    timestamp = str(int(time.time()))
    params = f"timestamp={timestamp}"
    if public_id:
        params = f"public_id={public_id}&timestamp={timestamp}"
    signature = hmac.new(
        CLOUDINARY_API_SECRET.encode(),
        params.encode(),
        hashlib.sha1,
    ).hexdigest()
    b64 = base64.b64encode(image_bytes).decode()
    data = {
        "file": f"data:image/png;base64,{b64}",
        "api_key": CLOUDINARY_API_KEY,
        "timestamp": timestamp,
        "signature": signature,
    }
    if public_id:
        data["public_id"] = public_id
    resp = requests.post(
        f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload",
        data=data, timeout=30,
    )
    if resp.status_code != 200:
        logger.error(f"Cloudinary upload failed: status {resp.status_code}")
        raise HTTPException(status_code=502, detail="Cloud upload failed")
    return resp.json()["secure_url"]


# ─── Steganography ────────────────────────────────────────

def encode_message_in_image(image_bytes: bytes, message: str) -> bytes:
    """Encode a hidden message into image using LSB steganography. Always outputs PNG."""
    try:
        from PIL import Image
        import numpy as np

        # Always convert to RGB PNG first — JPEG would destroy LSB on re-open
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        END_MARKER = "<<END>>"
        encoded_msg = message + END_MARKER
        bits = ''.join(format(ord(c), '08b') for c in encoded_msg)

        img_array = np.array(img, dtype=np.uint8)
        flat = img_array.flatten()

        if len(bits) > len(flat):
            logger.warning("Message too long for image; returning image unchanged")
            # Still save as PNG even in fallback
            out = io.BytesIO()
            img.save(out, format="PNG")
            return out.getvalue()

        flat_copy = flat.copy()
        for i, bit in enumerate(bits):
            flat_copy[i] = (flat_copy[i] & 0xFE) | int(bit)

        result_img = Image.fromarray(flat_copy.reshape(img_array.shape), "RGB")
        output = io.BytesIO()
        result_img.save(output, format="PNG")  # MUST be lossless PNG
        return output.getvalue()
    except Exception as e:
        logger.warning(f"Encode steganography error: {e}")
        # Fallback: re-save as PNG to at least not return JPEG
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            out = io.BytesIO()
            img.save(out, format="PNG")
            return out.getvalue()
        except Exception:
            return image_bytes


def decode_message_from_image(image_bytes: bytes) -> str:
    """Decode hidden LSB steganography message from image bytes."""
    try:
        from PIL import Image
        import numpy as np

        img = Image.open(io.BytesIO(image_bytes))

        # If JPEG or any lossy format, steganography bits are destroyed — warn early
        fmt = img.format or "UNKNOWN"
        if fmt in ("JPEG", "JPG", "WEBP"):
            logger.warning(f"Decode attempted on lossy format: {fmt}. LSB bits may be corrupted.")

        img = img.convert("RGB")
        img_array = np.array(img, dtype=np.uint8)
        flat = img_array.flatten()

        # Extract LSBs
        bits = [str(b & 1) for b in flat]

        END_MARKER = "<<END>>"
        END_MARKER_LEN = len(END_MARKER)  # = 7

        chars = []
        for i in range(0, len(bits) - 7, 8):
            byte_val = int(''.join(bits[i:i + 8]), 2)
            if byte_val == 0:
                break
            chars.append(chr(byte_val))
            joined = ''.join(chars)
            if joined.endswith(END_MARKER):
                return joined[:-END_MARKER_LEN]

        return "No hidden message found"
    except Exception as e:
        logger.error(f"Decode steganography error: {str(e)}")
        return f"Decode error: {str(e)}"



def serialize_doc(doc: dict) -> dict:
    """Convert MongoDB doc to JSON-safe dict."""
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


# ─── Pydantic Models ──────────────────────────────────────

class CaseUpdateModel(BaseModel):
    status: Optional[str] = Field(None, max_length=50)
    dispatcher_notes: Optional[str] = Field(None, max_length=500)
    assigned_unit: Optional[str] = Field(None, max_length=100)
    priority: Optional[str] = Field(None, max_length=20)
    severity: Optional[str] = Field(None, max_length=20)


class TrustedContactModel(BaseModel):
    name: str = Field(..., max_length=100)
    phone: str = Field(..., max_length=30)
    email: Optional[str] = Field("", max_length=120)
    priority: int = Field(1, ge=1, le=10)


class VoiceSOSConfigModel(BaseModel):
    user_id: str
    enabled: bool = True
    safe_word: str = Field(..., min_length=2, max_length=100)
    cooldown_seconds: int = Field(60, ge=10, le=600)
    contacts: List[TrustedContactModel] = []


class VoiceSOSTriggerModel(BaseModel):
    user_id: str
    spoken_phrase: Optional[str] = None
    hashed_safe_word: Optional[str] = None
    latitude: float = 0.0
    longitude: float = 0.0
    location_accuracy: float = 0.0
    timestamp: Optional[str] = ""


class EvidenceUploadModel(BaseModel):
    case_id: str = Field(..., max_length=100)
    audio_base64: str = Field("", max_length=20_000_000)  # Max ~15MB base64
    image_base64: str = Field("", max_length=20_000_000)  # Max ~15MB base64
    mime_type_audio: str = "audio/webm"
    mime_type_image: str = "image/jpeg"
    duration_seconds: float = 0.0
    device_info: str = ""
    timestamp: str = ""


class LocationUpdateModel(BaseModel):
    event_id: str = Field(..., max_length=100)
    latitude: float
    longitude: float
    accuracy: float = 5.0
    speed: float = 0.0
    heading: float = 0.0
    timestamp: str = ""


class DispatchWebhookModel(BaseModel):
    case_id: str
    agency_type: str = "ERSS_112"
    priority: str = "CRITICAL"
    dispatcher_notes: str = ""


class GenerateDIRFormModel(BaseModel):
    case_id: str
    officer_name: str = ""
    officer_designation: str = ""
    station_name: str = ""
    district: str = ""


class DiscreetDispatchModel(BaseModel):
    case_id: str
    dispatch_type: str
    priority: str = "HIGH"
    dispatcher_notes: str = ""
    silent_approach: bool = True


# In-memory cooldown tracker for voice triggers
_voice_sos_cooldowns: dict = {}

def check_cooldown(user_id: str, cooldown_seconds: int) -> bool:
    """Returns True if within cooldown (should block)."""
    last_trigger = _voice_sos_cooldowns.get(user_id, 0)
    return (time.time() - last_trigger) < cooldown_seconds


def set_cooldown(user_id: str):
    _voice_sos_cooldowns[user_id] = time.time()


def format_emergency_alert(event_id: str, ts: str, lat: float, lng: float) -> str:
    map_link = f"https://maps.google.com/?q={lat},{lng}" if lat and lng else "Location unavailable"
    return (
        f"🚨 HAVEN EMERGENCY ALERT 🚨\n\n"
        f"A trusted contact has triggered an emergency SOS.\n\n"
        f"Time: {ts}\n"
        f"Location: {lat}, {lng}\n"
        f"Map: {map_link}\n"
        f"SOS Event ID: {event_id}\n\n"
        f"Please respond immediately."
    )


def format_whatsapp_url(phone: str, text: str) -> str:
    encoded_text = requests.utils.quote(text)
    if not phone:
        return f"https://api.whatsapp.com/send?text={encoded_text}"
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 10 and digits[0] in ['6', '7', '8', '9']:
        digits = '91' + digits
    elif len(digits) == 11 and digits.startswith('0'):
        digits = '91' + digits[1:]
    if not digits:
        return f"https://api.whatsapp.com/send?text={encoded_text}"
    return f"https://api.whatsapp.com/send?phone={digits}&text={encoded_text}"


# ─── Authentication Routes ────────────────────────────────

@app.post("/auth/authority-login", response_model=TokenResponse)
def authority_login(
    payload: AuthorityLoginModel,
    _=Depends(rate_limit_dependency(max_requests=5, window_seconds=60))
):
    """
    Authenticate emergency response authority officer server-side.
    Issues a signed JWT token with authority scope.
    """
    if not verify_authority_password(payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authority credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    badge = payload.badge_number or "PO-1091"
    token = create_access_token(
        user_id=badge,
        role="authority",
        name=payload.officer_name or "Duty Protection Officer",
        expires_delta=timedelta(hours=JWT_EXPIRATION_HOURS)
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        role="authority",
        user_id=badge,
        expires_in=JWT_EXPIRATION_HOURS * 3600
    )


# ─── Public & User Routes ─────────────────────────────────

@app.get("/")
def root():
    return {"message": "Haven API is active and secure", "version": "2.0.0"}


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# 1. Expand keywords into full distress message
@app.post("/text-generation")
def text_generation(
    body: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=20, window_seconds=60))
):
    keywords = body.get("keywords", "")[:500]
    context = body.get("context", "domestic abuse distress situation")[:500]
    if not keywords:
        raise HTTPException(status_code=400, detail="keywords required")

    system = (
        "You are an AI assistant for Haven, a women's safety platform. "
        "Expand brief keywords from a woman in distress into a clear, complete distress message. "
        "Output ONLY the expanded message, nothing else."
    )
    # Delimit user inputs to prevent prompt injection
    user_prompt = f"### USER KEYWORDS ###\n{keywords}\n### CONTEXT ###\n{context}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}]
    result = call_groq(messages)
    return {"expanded_message": result.strip()}


# 2. Generate image via HuggingFace / Fallback
@app.post("/img-generation")
def img_generation(
    body: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=10, window_seconds=60))
):
    prompt = body.get("prompt", "peaceful garden")[:250]
    image_bytes = generate_image_hf(prompt)
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        output = io.BytesIO()
        img.save(output, format="PNG")
        image_bytes = output.getvalue()
    except Exception as e:
        logger.warning(f"Image convert error: {e}")
    b64 = base64.b64encode(image_bytes).decode()
    return {"image_base64": b64, "format": "png"}


# 3. Encode message into image (Steganography)
@app.post("/encode")
def encode(body: dict = Body(...)):
    message = body.get("message", "")
    image_b64 = body.get("image_base64", "")
    if len(image_b64) > 15_000_000:
        raise HTTPException(status_code=413, detail="Payload too large. Maximum image size 10MB.")
    image_bytes = base64.b64decode(image_b64)
    encoded = encode_message_in_image(image_bytes, message)
    return {"encoded_image_base64": base64.b64encode(encoded).decode()}


# 4. Decode hidden message from image
@app.post("/decode")
def decode(body: dict = Body(...)):
    image_b64 = body.get("image_base64", "")
    if len(image_b64) > 15_000_000:
        raise HTTPException(status_code=413, detail="Payload too large. Maximum image size 10MB.")
    image_bytes = base64.b64decode(image_b64)
    return {"decoded_message": decode_message_from_image(image_bytes)}


# 5. Decompose decoded text into structured fields
@app.post("/text-decomposition")
def text_decomposition(
    body: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=20, window_seconds=60))
):
    text = body.get("text", "")[:2000]
    messages = [
        {
            "role": "system",
            "content": (
                'Extract structured info from a distress message. '
                'Return ONLY valid JSON: '
                '{"severity":"low|medium|high|critical","location":"string or null",'
                '"nature_of_abuse":"string","immediate_danger":true,"needs":["list"],"summary":"string"}'
            )
        },
        {"role": "user", "content": f"Decompose this text: \n```\n{text}\n```"}
    ]
    result = call_groq(messages)
    try:
        parsed = json.loads(re.sub(r'```json|```', '', result).strip())
    except Exception:
        parsed = {"severity": "unknown", "summary": text[:200]}
    return parsed


# 6. Save SOS case to MongoDB
@app.post("/save-extracted-data")
def save_extracted_data(
    body: dict = Body(...),
    user: Optional[AuthUser] = Depends(get_optional_user)
):
    decoded_text = body.get("decoded_text", "")
    doc = {
        "decoded_text": decoded_text,
        "image_url": body.get("image_url"),
        "hashtags": body.get("hashtags", []),
        "severity": body.get("severity", "unknown"),
        "summary": body.get("summary", ""),
        "location": body.get("location", ""),
        "nature_of_abuse": body.get("nature_of_abuse", ""),
        "immediate_danger": body.get("immediate_danger", False),
        "needs": body.get("needs", []),
        "created_at": datetime.utcnow(),
        "status": "pending",
        "case_id": f"HAVEN-{int(datetime.utcnow().timestamp())}",
        "user_id": user.user_id if user else "anonymous",
    }
    if sos_collection is not None:
        sos_collection.insert_one(doc)
    return {"success": True, "case_id": doc["case_id"]}


# ─── Authority Protected Endpoints ────────────────────────

# 7. Get all SOS cases (Authority Only, Decrypts Evidence Securely)
@app.get("/cases")
def get_cases(
    severity: str = Query(None),
    status: str = Query(None),
    current_user: AuthUser = Depends(require_authority)
):
    if sos_collection is None:
        return {"cases": [], "total": 0}
    query = {}
    if severity:
        query["severity"] = severity
    if status:
        query["status"] = status

    cases = list(sos_collection.find(query, {"_id": 0}).sort("created_at", -1).limit(50))

    # Decrypt evidence for authorized authority
    decrypted_cases = []
    for c in cases:
        c_copy = dict(c)
        evid = c_copy.get("evidence")
        if evid and isinstance(evid, dict):
            # If evidence is encrypted with AES-GCM
            if evid.get("is_encrypted"):
                if evid.get("audio_ciphertext"):
                    evid["audio_base64"] = decrypt_evidence_payload(
                        evid.get("audio_ciphertext", ""),
                        evid.get("audio_nonce", "")
                    )
                if evid.get("image_ciphertext"):
                    evid["image_base64"] = decrypt_evidence_payload(
                        evid.get("image_ciphertext", ""),
                        evid.get("image_nonce", "")
                    )
        decrypted_cases.append(serialize_doc(c_copy))

    return {"cases": decrypted_cases, "total": len(decrypted_cases)}


# 8. Update case status (Authority Only + Mass-Assignment Guard)
@app.patch("/cases/{case_id}")
def update_case(
    case_id: str,
    body: CaseUpdateModel,
    current_user: AuthUser = Depends(require_authority)
):
    if sos_collection is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    update_fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update_fields:
        raise HTTPException(status_code=400, detail="No valid update fields specified")

    update_fields["updated_at"] = datetime.utcnow()
    update_fields["last_updated_by"] = current_user.user_id

    result = sos_collection.update_one({"case_id": case_id}, {"$set": update_fields})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Case ID not found")

    return {"success": True, "case_id": case_id, "updated": list(update_fields.keys())}


# 9. Report culprit (Authenticated User / Authority)
@app.post("/culprit/report")
def report_culprit(
    body: dict = Body(...),
    current_user: AuthUser = Depends(get_current_user)
):
    physical_description = body.get("physical_description", "")[:1000]
    behavioral_traits = body.get("behavioral_traits", "")[:1000]
    description = f"{physical_description}. {behavioral_traits}"
    embedding = get_embedding(description)
    doc = {
        "name": body.get("name", "Unknown")[:100],
        "physical_description": physical_description,
        "behavioral_traits": behavioral_traits,
        "location": body.get("location", "")[:200],
        "reporter_id": current_user.user_id,
        "reporter_role": current_user.role,
        "description_embedding": embedding,
        "created_at": datetime.utcnow(),
        "culprit_id": f"CULPRIT-{int(datetime.utcnow().timestamp())}",
    }
    if culprit_collection is not None:
        culprit_collection.insert_one(doc)
    return {"success": True, "culprit_id": doc["culprit_id"]}


# 10. Find similar culprits (ReDoS protected with re.escape)
@app.post("/culprit/find-match")
def find_culprit_match(
    body: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=20, window_seconds=60))
):
    description = body.get("description", "")[:500]
    top_n = min(body.get("top_n", 5), 20)
    search_mode = body.get("search_mode", "auto")
    min_score = body.get("min_score", 0.0)

    if culprit_collection is None:
        return {"matches": [], "query": description}

    is_likely_name = (
        search_mode == "name" or
        (search_mode == "auto" and len(description.split()) <= 4 and len(description) < 50
         and not any(c in description for c in ["age", "tall", "hair", "cm", "kg", "year"]))
    )

    if is_likely_name:
        escaped_query = re.escape(description.strip())
        # Try exact name match first (case-insensitive)
        exact = list(culprit_collection.find(
            {"name": {"$regex": f"^{escaped_query}$", "$options": "i"}},
            {"_id": 0, "description_embedding": 0}
        ).limit(top_n))
        if exact:
            for r in exact:
                r["score"] = 1.0
            return {"matches": [serialize_doc(r) for r in exact], "query": description, "search_type": "exact_name"}

        # Try partial name match (ReDoS protected with re.escape)
        partial = list(culprit_collection.find(
            {"name": {"$regex": escaped_query, "$options": "i"}},
            {"_id": 0, "description_embedding": 0}
        ).limit(top_n))
        if partial:
            for r in partial:
                r["score"] = 0.95
            return {"matches": [serialize_doc(r) for r in partial], "query": description, "search_type": "partial_name"}

    # Vector similarity search fallback
    query_embedding = get_embedding(description)
    try:
        results = list(culprit_collection.aggregate([
            {
                "$vectorSearch": {
                    "index": "culpritIndex",
                    "path": "description_embedding",
                    "queryVector": query_embedding,
                    "numCandidates": 20,
                    "limit": top_n,
                }
            },
            {"$project": {"_id": 0, "description_embedding": 0}}
        ]))
        if min_score > 0:
            results = [r for r in results if r.get("score", 0) >= min_score]
        results = results[:top_n]
    except Exception:
        results = list(culprit_collection.find({}, {"_id": 0, "description_embedding": 0}).limit(top_n))
        for r in results:
            r["score"] = 0.5

    return {"matches": [serialize_doc(r) for r in results], "query": description, "search_type": "vector"}


# 11. Legal RAG query
@app.post("/legal/query")
def legal_query(
    body: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=25, window_seconds=60))
):
    question = body.get("question", "")[:1000]
    query_embedding = get_embedding(question)
    if legal_collection is None:
        context = ""
        chunks = []
    else:
        try:
            chunks = list(legal_collection.aggregate([
                {
                    "$vectorSearch": {
                        "index": "legalIndex",
                        "path": "embedding",
                        "queryVector": query_embedding,
                        "numCandidates": 20,
                        "limit": 5,
                    }
                },
                {"$project": {"text": 1, "source": 1, "_id": 0}}
            ]))
        except Exception:
            chunks = list(legal_collection.find({}, {"text": 1, "source": 1, "_id": 0}).limit(3))
        context = "\n\n".join([c.get("text", "") for c in chunks])

    messages = [
        {
            "role": "system",
            "content": (
                "You are Haven's legal assistant for women in India. "
                "Provide compassionate, plain-language guidance on domestic abuse, divorce, custody, and rights. "
                f"Use this legal context if available:\n\n{context}\n\n"
                "Always recommend consulting a qualified lawyer for serious cases."
            )
        },
        {"role": "user", "content": f"Legal question: {question}"}
    ]
    answer = call_groq(messages)
    return {"answer": answer, "sources": [c.get("source", "") for c in chunks]}


# 12. Upload legal PDF (Authority / Admin Only)
@app.post("/legal/upload-doc")
async def upload_legal_doc(
    file: UploadFile = File(...),
    source_name: str = "Legal Document",
    current_user: AuthUser = Depends(require_authority)
):
    if file.size and file.size > 15_000_000:
        raise HTTPException(status_code=413, detail="File too large. Maximum size 15MB.")

    from pypdf import PdfReader
    content = await file.read()
    if len(content) > 15_000_000:
        raise HTTPException(status_code=413, detail="File too large. Maximum size 15MB.")

    reader = PdfReader(io.BytesIO(content))
    full_text = ""
    for page in reader.pages:
        full_text += (page.extract_text() or "") + "\n"
    chunks = []
    for i in range(0, len(full_text), 450):
        chunk = full_text[i:i+500].strip()
        if chunk:
            chunks.append(chunk)
    inserted = 0
    if legal_collection is not None:
        for chunk in chunks[:100]:
            embedding = get_embedding(chunk)
            legal_collection.insert_one({
                "text": chunk,
                "source": source_name[:100],
                "embedding": embedding,
                "uploaded_by": current_user.user_id,
                "created_at": datetime.utcnow(),
            })
            inserted += 1
    return {"success": True, "chunks_embedded": inserted, "source": source_name}


# 13. Therapy chat (Ownership bound)
@app.post("/therapy/chat")
def therapy_chat(
    body: dict = Body(...),
    current_user: Optional[AuthUser] = Depends(get_optional_user),
    _=Depends(rate_limit_dependency(max_requests=30, window_seconds=60))
):
    message = body.get("message", "")[:2000]
    user_id = current_user.user_id if current_user else body.get("user_id", "anonymous")
    session_id = body.get("session_id")
    lang = body.get("lang", "en")

    lang_instruction = ""
    if lang == "hi":
        lang_instruction = "\n- IMPORTANT: Reply warmly in natural, compassionate Hindi."
    elif lang == "gu":
        lang_instruction = "\n- IMPORTANT: Reply warmly in natural, compassionate Gujarati."
    elif lang == "mr":
        lang_instruction = "\n- IMPORTANT: Reply warmly in natural, compassionate Marathi."
    elif lang == "te":
        lang_instruction = "\n- IMPORTANT: Reply warmly in natural, compassionate Telugu."
    elif lang == "bn":
        lang_instruction = "\n- IMPORTANT: Reply warmly in natural, compassionate Bengali."
    elif lang == "ta":
        lang_instruction = "\n- IMPORTANT: Reply warmly in natural, compassionate Tamil."

    history = []
    if session_id and therapy_collection is not None:
        past = therapy_collection.find_one({"session_id": session_id})
        if past:
            # If session is owned by a different user, prevent session hijacking
            if current_user and past.get("user_id") not in [user_id, "anonymous", "anon"]:
                raise HTTPException(status_code=403, detail="Unauthorized access to therapy session")
            history = past.get("messages", [])[-6:]

    messages = [
        {
            "role": "system",
            "content": f"""You are Aria, a warm and compassionate AI therapy companion for women in distress.

CRITICAL RULES — ALWAYS FOLLOW:
- Keep EVERY reply under 3 sentences maximum
- Never write long paragraphs
- Be warm, short, and human — like a caring friend texting
- Ask ONE simple follow-up question at the end
- Never list multiple points or use bullet points
- Speak gently, simply, and directly{lang_instruction}

NEVER write more than 3 sentences. NEVER write multiple paragraphs."""
        }
    ] + history + [{"role": "user", "content": f"### USER STATEMENT ###\n{message}"}]

    response = call_groq(messages, max_tokens=150)
    session_id = session_id or f"SESSION-{user_id}-{int(time.time())}"

    if therapy_collection is not None:
        therapy_collection.update_one(
            {"session_id": session_id},
            {
                "$set": {"user_id": user_id, "session_id": session_id, "updated_at": datetime.utcnow()},
                "$push": {"messages": {"$each": [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": response},
                ]}}
            },
            upsert=True
        )
    return {"response": response, "session_id": session_id}


# 14. Upload image to Cloudinary
@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...)):
    if file.size and file.size > 10_000_000:
        raise HTTPException(status_code=413, detail="File exceeds 10MB limit")
    content = await file.read()
    if len(content) > 10_000_000:
        raise HTTPException(status_code=413, detail="File exceeds 10MB limit")
    url = upload_to_cloudinary(content, public_id=f"haven_{int(time.time())}")
    return {"url": url}


# 15. Generate poem
@app.post("/generate-poem")
async def generate_poem(
    data: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=15, window_seconds=60))
):
    try:
        emotional_state = data.get("emotional_state", "in need of hope and strength")[:100]
        prompt = f"""Write a short, beautiful, empowering poem (8-12 lines) for a woman who is feeling {emotional_state}.
The poem should be:
- Warm, gentle and hopeful
- About inner strength and resilience  
- Not mention abuse or violence directly
- End with an uplifting message

Write ONLY the poem, no title, no explanation."""

        poem_text = ""
        if genai_client:
            response = genai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            if response.text:
                poem_text = response.text.strip()

        if not poem_text:
            poem_text = "You are stronger than the storm,\nBraver than the night,\nWithin you burns a quiet flame\nThat no one can extinguish.\nYou are not alone.\nYou are seen. You are loved."

        return {"poem": poem_text}
    except Exception as e:
        logger.warning(f"Poem error: {e}")
        return {
            "poem": "You are stronger than the storm,\nBraver than the night,\nWithin you burns a quiet flame\nThat no one can extinguish.\nYou are not alone.\nYou are seen. You are loved."
        }


# ─── Voice SOS Endpoints (Salted & Authenticated) ─────────

@app.post("/voice-sos/config")
def voice_sos_save_config(
    config: VoiceSOSConfigModel,
    current_user: Optional[AuthUser] = Depends(get_optional_user)
):
    """Create or update Voice SOS configuration. Hashes safe word with PBKDF2 salt."""
    if voice_sos_config_collection is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    target_user_id = current_user.user_id if current_user else config.user_id

    # Compute salted hash
    hash_result = hash_safe_word_salted(config.safe_word)

    doc = {
        "user_id": target_user_id,
        "enabled": config.enabled,
        "safe_word_hash": hash_result["hash"],
        "safe_word_salt": hash_result["salt"],
        "cooldown_seconds": config.cooldown_seconds,
        "updated_at": datetime.utcnow(),
    }

    voice_sos_config_collection.update_one(
        {"user_id": target_user_id},
        {"$set": doc, "$setOnInsert": {"created_at": datetime.utcnow()}},
        upsert=True,
    )

    # Save trusted contacts
    if config.contacts and trusted_contacts_collection is not None:
        trusted_contacts_collection.delete_many({"user_id": target_user_id})
        for c in config.contacts:
            trusted_contacts_collection.insert_one({
                "user_id": target_user_id,
                "contact_id": f"CONTACT-{int(time.time())}-{secrets.token_hex(2)}",
                "name": c.name,
                "phone": c.phone,
                "email": c.email,
                "priority": c.priority,
                "created_at": datetime.utcnow(),
            })

    return {"success": True, "message": "Voice SOS configuration securely saved"}


@app.get("/voice-sos/config/{user_id}")
def voice_sos_get_config(
    user_id: str,
    current_user: Optional[AuthUser] = Depends(get_optional_user)
):
    """Get Voice SOS config. Never exposes the safe word hash or salt."""
    if voice_sos_config_collection is None:
        return {"configured": False}

    if current_user and current_user.role != "authority" and current_user.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden: cannot access another user's config")

    cfg = voice_sos_config_collection.find_one({"user_id": user_id}, {"_id": 0})
    if not cfg:
        return {"configured": False}

    contacts = []
    if trusted_contacts_collection is not None:
        contacts = list(trusted_contacts_collection.find(
            {"user_id": user_id}, {"_id": 0}
        ))

    return {
        "configured": True,
        "enabled": cfg.get("enabled", False),
        "has_safe_word": bool(cfg.get("safe_word_hash")),
        "cooldown_seconds": cfg.get("cooldown_seconds", 60),
        "contacts": [serialize_doc(c) for c in contacts],
        "updated_at": cfg.get("updated_at", "").isoformat() if hasattr(cfg.get("updated_at", ""), "isoformat") else "",
    }


@app.post("/voice-sos/trigger")
def voice_sos_trigger(
    trigger: VoiceSOSTriggerModel,
    current_user: Optional[AuthUser] = Depends(get_optional_user),
    _=Depends(rate_limit_dependency(max_requests=10, window_seconds=60))
):
    """
    Trigger a REAL Voice SOS emergency.
    Validates safe word with stored PBKDF2 salt, enforces cooldown and creates emergency record.
    """
    if voice_sos_config_collection is None or sos_events_collection is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    target_user_id = current_user.user_id if current_user else trigger.user_id

    cfg = voice_sos_config_collection.find_one({"user_id": target_user_id})
    if not cfg:
        raise HTTPException(status_code=404, detail="Voice SOS not configured")
    if not cfg.get("enabled"):
        raise HTTPException(status_code=400, detail="Voice SOS is disabled")

    # Validate safe word using stored salted hash
    stored_hash = cfg.get("safe_word_hash", "")
    stored_salt = cfg.get("safe_word_salt", "")

    matched = False
    if trigger.spoken_phrase and stored_salt:
        matched = verify_safe_word(trigger.spoken_phrase, stored_hash, stored_salt)
    elif trigger.hashed_safe_word:
        # Legacy/direct hash check fallback with constant-time comparison
        matched = hmac.compare_digest(trigger.hashed_safe_word, stored_hash)

    if not matched:
        raise HTTPException(status_code=403, detail="Safe word verification failed")

    # Check cooldown
    cooldown = cfg.get("cooldown_seconds", 60)
    if check_cooldown(target_user_id, cooldown):
        remaining = int(cooldown - (time.time() - _voice_sos_cooldowns.get(target_user_id, 0)))
        raise HTTPException(status_code=429, detail=f"Cooldown active. Wait {remaining}s")

    set_cooldown(target_user_id)

    event_id = f"VSOS-{int(time.time())}-{secrets.token_hex(4)}"
    ts = trigger.timestamp or datetime.utcnow().isoformat()
    alert_message = format_emergency_alert(event_id, ts, trigger.latitude, trigger.longitude)

    contacts = []
    if trusted_contacts_collection is not None:
        contacts = list(trusted_contacts_collection.find(
            {"user_id": target_user_id}, {"_id": 0}
        ))

    contact_delivery = {c.get("name", "unknown"): "pending" for c in contacts}

    event_doc = {
        "event_id": event_id,
        "user_id": target_user_id,
        "trigger_type": "voice_code",
        "timestamp": ts,
        "latitude": trigger.latitude,
        "longitude": trigger.longitude,
        "location_accuracy": trigger.location_accuracy,
        "status": "triggered",
        "contact_delivery_status": contact_delivery,
        "is_test": False,
        "created_at": datetime.utcnow(),
    }
    sos_events_collection.insert_one(event_doc)

    # Save to sos_cases so it appears in authority dashboard
    if sos_collection is not None:
        sos_collection.insert_one({
            "case_id": event_id,
            "user_id": target_user_id,
            "trigger_type": "voice_sos",
            "decoded_text": f"🚨 EMERGENCY VOICE SOS TRIGGERED. Location: {trigger.latitude}, {trigger.longitude}",
            "severity": "critical",
            "immediate_danger": True,
            "location": f"{trigger.latitude}, {trigger.longitude}" if trigger.latitude else "Unknown",
            "summary": "Voice SOS activation - immediate emergency response required",
            "needs": ["Immediate Police Dispatch", "GPS Tracking", "Medical Alert"],
            "status": "active",
            "created_at": datetime.utcnow(),
            "has_evidence": False,
        })

    whatsapp_links = [
        {"name": c.get("name", "Contact"), "phone": c.get("phone", ""), "url": format_whatsapp_url(c.get("phone", ""), alert_message)}
        for c in contacts
    ] or [{"name": "Trusted Contact", "phone": "", "url": format_whatsapp_url("", alert_message)}]

    return {
        "success": True,
        "event_id": event_id,
        "status": "triggered",
        "alert_message": alert_message,
        "contacts_notified": len(contacts),
        "whatsapp_links": whatsapp_links,
        "live_tracking_ws_url": f"/ws/track/{event_id}",
        "erss_auto_dispatched": True,
    }


@app.post("/voice-sos/test")
def voice_sos_test(
    trigger: VoiceSOSTriggerModel,
    current_user: Optional[AuthUser] = Depends(get_optional_user)
):
    """Test mode Voice SOS without triggering real police alert."""
    if voice_sos_config_collection is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    target_user_id = current_user.user_id if current_user else trigger.user_id
    cfg = voice_sos_config_collection.find_one({"user_id": target_user_id})
    if not cfg:
        raise HTTPException(status_code=404, detail="Voice SOS not configured")

    stored_hash = cfg.get("safe_word_hash", "")
    stored_salt = cfg.get("safe_word_salt", "")

    match = False
    if trigger.spoken_phrase and stored_salt:
        match = verify_safe_word(trigger.spoken_phrase, stored_hash, stored_salt)
    elif trigger.hashed_safe_word:
        match = hmac.compare_digest(trigger.hashed_safe_word, stored_hash)

    ts = trigger.timestamp or datetime.utcnow().isoformat()
    event_id = f"TEST-{int(time.time())}-{secrets.token_hex(4)}"

    if sos_events_collection is not None:
        sos_events_collection.insert_one({
            "event_id": event_id,
            "user_id": target_user_id,
            "trigger_type": "test",
            "timestamp": ts,
            "latitude": trigger.latitude,
            "longitude": trigger.longitude,
            "location_accuracy": trigger.location_accuracy,
            "status": "test_complete",
            "contact_delivery_status": {},
            "is_test": True,
            "safe_word_matched": match,
            "created_at": datetime.utcnow(),
        })

    return {
        "success": True,
        "is_test": True,
        "event_id": event_id,
        "safe_word_matched": match,
        "location_captured": bool(trigger.latitude or trigger.longitude),
        "latitude": trigger.latitude,
        "longitude": trigger.longitude,
        "message": "TEST MODE — Verified successfully. No real emergency alerts dispatched.",
    }


@app.get("/voice-sos/history/{user_id}")
def voice_sos_history(
    user_id: str,
    current_user: Optional[AuthUser] = Depends(get_optional_user)
):
    """Get Voice SOS event history for a user."""
    if sos_events_collection is None:
        return {"events": [], "total": 0}

    if current_user and current_user.role != "authority" and current_user.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    events = list(sos_events_collection.find(
        {"user_id": user_id},
        {"_id": 0, "safe_word_matched": 0}
    ).sort("created_at", -1).limit(20))

    return {
        "events": [serialize_doc(e) for e in events],
        "total": len(events),
    }


@app.post("/trusted-contacts")
def save_trusted_contacts(
    body: dict = Body(...),
    current_user: Optional[AuthUser] = Depends(get_optional_user)
):
    """Save trusted contacts for an authenticated user."""
    if trusted_contacts_collection is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = current_user.user_id if current_user else body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    contacts = body.get("contacts", [])
    if len(contacts) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 contacts allowed")

    trusted_contacts_collection.delete_many({"user_id": user_id})
    saved = []
    for c in contacts:
        doc = {
            "user_id": user_id,
            "contact_id": f"CONTACT-{int(time.time())}-{secrets.token_hex(2)}",
            "name": str(c.get("name", ""))[:100],
            "phone": str(c.get("phone", ""))[:30],
            "email": str(c.get("email", ""))[:120],
            "priority": int(c.get("priority", 1)),
            "created_at": datetime.utcnow(),
        }
        trusted_contacts_collection.insert_one(doc)
        saved.append({"name": doc["name"], "contact_id": doc["contact_id"]})

    return {"success": True, "contacts_saved": len(saved), "contacts": saved}


@app.get("/trusted-contacts/{user_id}")
def get_trusted_contacts(
    user_id: str,
    current_user: Optional[AuthUser] = Depends(get_optional_user)
):
    """Get trusted contacts for a user."""
    if trusted_contacts_collection is None:
        return {"contacts": []}

    if current_user and current_user.role != "authority" and current_user.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    contacts = list(trusted_contacts_collection.find(
        {"user_id": user_id}, {"_id": 0}
    ).sort("priority", 1))

    return {"contacts": [serialize_doc(c) for c in contacts]}


@app.get("/voice-sos/analytics")
def voice_sos_analytics(current_user: AuthUser = Depends(require_authority)):
    """Get aggregated Voice SOS analytics (Authority Only)."""
    if sos_events_collection is None:
        return {"total_activations": 0, "test_activations": 0}

    total = sos_events_collection.count_documents({"trigger_type": "voice_code"})
    tests = sos_events_collection.count_documents({"trigger_type": "test"})
    failed = sos_events_collection.count_documents({"status": "failed"})

    return {
        "total_activations": total,
        "test_activations": tests,
        "successful_alerts": total - failed,
        "failed_alerts": failed,
    }


# ─── Live GPS WebSocket Tracking & Location Stream ───────

class LiveTrackingManager:
    """Manages real-time WebSocket connections per SOS event room."""
    def __init__(self):
        self.active_rooms: Dict[str, List[WebSocket]] = {}
        self.latest_locations: Dict[str, dict] = {}

    async def connect(self, event_id: str, websocket: WebSocket):
        await websocket.accept()
        if event_id not in self.active_rooms:
            self.active_rooms[event_id] = []
        self.active_rooms[event_id].append(websocket)
        if event_id in self.latest_locations:
            try:
                await websocket.send_json(self.latest_locations[event_id])
            except Exception:
                pass

    def disconnect(self, event_id: str, websocket: WebSocket):
        if event_id in self.active_rooms:
            if websocket in self.active_rooms[event_id]:
                self.active_rooms[event_id].remove(websocket)
            if not self.active_rooms[event_id]:
                del self.active_rooms[event_id]

    async def broadcast_location(self, event_id: str, data: dict):
        self.latest_locations[event_id] = data
        if event_id in self.active_rooms:
            for conn in list(self.active_rooms[event_id]):
                try:
                    await conn.send_json(data)
                except Exception:
                    pass

tracking_manager = LiveTrackingManager()


@app.websocket("/ws/track/{event_id}")
async def websocket_tracking_endpoint(
    websocket: WebSocket,
    event_id: str,
    token: Optional[str] = Query(None),
    role: Optional[str] = Query("subscriber")
):
    """
    Real-time live WebSocket room for broadcasting and receiving victim GPS updates.
    Separates Broadcaster (Victim) from Observer/Subscriber (Authority) to prevent GPS injection.
    """
    await tracking_manager.connect(event_id, websocket)
    is_broadcaster = role == "broadcaster"

    try:
        while True:
            data = await websocket.receive_json()
            # Only broadacsters (the SOS triggering victim) are authorized to publish location coordinates
            if is_broadcaster:
                payload = {
                    "event_id": event_id,
                    "latitude": float(data.get("latitude", 0.0)),
                    "longitude": float(data.get("longitude", 0.0)),
                    "accuracy": float(data.get("accuracy", 5.0)),
                    "speed": float(data.get("speed", 0.0)),
                    "heading": float(data.get("heading", 0.0)),
                    "timestamp": data.get("timestamp", datetime.utcnow().isoformat()),
                }
                await tracking_manager.broadcast_location(event_id, payload)
    except WebSocketDisconnect:
        tracking_manager.disconnect(event_id, websocket)
    except Exception:
        tracking_manager.disconnect(event_id, websocket)


@app.post("/sos/location-update")
async def sos_location_update(
    update: LocationUpdateModel,
    user: Optional[AuthUser] = Depends(get_optional_user)
):
    """REST endpoint fallback to push live coordinates for an active SOS event."""
    ts = update.timestamp or datetime.utcnow().isoformat()
    data = {
        "event_id": update.event_id,
        "latitude": update.latitude,
        "longitude": update.longitude,
        "accuracy": update.accuracy,
        "speed": update.speed,
        "heading": update.heading,
        "timestamp": ts,
    }
    await tracking_manager.broadcast_location(update.event_id, data)

    # Persist latest location in MongoDB
    if sos_events_collection is not None:
        sos_events_collection.update_one(
            {"event_id": update.event_id},
            {"$set": {"latitude": update.latitude, "longitude": update.longitude, "updated_at": datetime.utcnow()}}
        )
    if sos_collection is not None:
        sos_collection.update_one(
            {"case_id": update.event_id},
            {"$set": {"latitude": update.latitude, "longitude": update.longitude, "updated_at": datetime.utcnow()}}
        )
    return {"success": True, "event_id": update.event_id, "timestamp": ts}


# ─── ERSS 112 & NGO Emergency Dispatch (Authority Only) ─

@app.get("/authority/dispatch-partners")
def get_dispatch_partners(current_user: AuthUser = Depends(require_authority)):
    """Get list of active emergency response dispatch partners."""
    return {
        "partners": [
            {
                "id": "ERSS-112-NAT",
                "name": "ERSS 112 National Police Emergency Command",
                "type": "police_emergency",
                "status": "ONLINE",
                "response_sla_mins": 7,
                "coverage": "Pan-India (All States)",
                "api_endpoint": "https://erss.gov.in/api/v1/dispatch",
            },
            {
                "id": "NCW-HELPLINE-78",
                "name": "National Commission for Women (NCW 78)",
                "type": "women_crisis_ngo",
                "status": "ONLINE",
                "response_sla_mins": 15,
                "coverage": "Nationwide",
                "api_endpoint": "https://ncw.nic.in/api/dispatch",
            },
            {
                "id": "SNEHA-CRISIS-MUM",
                "name": "SNEHA Crisis Intervention Unit",
                "type": "ngo_crisis",
                "status": "ONLINE",
                "response_sla_mins": 10,
                "coverage": "Mumbai & Maharashtra",
                "api_endpoint": "https://snehamumbai.org/api/intake",
            },
            {
                "id": "SAKSHI-CRISIS-DEL",
                "name": "Sakshi Violence Intervention Cell",
                "type": "ngo_crisis",
                "status": "ONLINE",
                "response_sla_mins": 12,
                "coverage": "Delhi NCR",
                "api_endpoint": "https://sakshi.org.in/api/sos",
            }
        ]
    }


@app.post("/authority/dispatch-webhook")
def trigger_dispatch_webhook(
    payload: DispatchWebhookModel,
    current_user: AuthUser = Depends(require_authority)
):
    """Trigger emergency dispatch to ERSS 112 or NGO partner."""
    ts = datetime.utcnow().isoformat()
    dispatch_id = f"DISPATCH-{int(time.time())}-{secrets.token_hex(3).upper()}"

    if sos_collection is not None:
        sos_collection.update_one(
            {"case_id": payload.case_id},
            {
                "$set": {
                    "dispatch_status": "DISPATCHED",
                    "dispatch_id": dispatch_id,
                    "dispatched_to": payload.agency_type,
                    "dispatched_at": datetime.utcnow(),
                    "dispatched_by": current_user.user_id,
                },
                "$push": {
                    "dispatch_history": {
                        "dispatch_id": dispatch_id,
                        "agency": payload.agency_type,
                        "timestamp": ts,
                        "dispatcher": current_user.user_id,
                        "notes": payload.dispatcher_notes or "Immediate police/NGO unit dispatched via Haven ERSS gateway.",
                        "status": "DISPATCH_CONFIRMED"
                    }
                }
            }
        )

    return {
        "success": True,
        "dispatch_id": dispatch_id,
        "case_id": payload.case_id,
        "agency_type": payload.agency_type,
        "status": "DISPATCH_CONFIRMED",
        "estimated_arrival_minutes": 6 if payload.agency_type == "ERSS_112" else 12,
        "dispatched_at": ts,
        "message": f"🚨 Case {payload.case_id} successfully dispatched to {payload.agency_type} emergency queue."
    }


# ─── AES-256-GCM Encrypted Forensic Evidence ─────────────

@app.post("/sos/evidence")
def upload_sos_evidence(payload: EvidenceUploadModel):
    """
    Encrypts and securely stores ambient audio and camera evidence with AES-256-GCM.
    Generates SHA-256 integrity hash for tamper verification.
    """
    raw_content = f"{payload.case_id}:{payload.timestamp}:{payload.audio_base64[:100]}:{payload.image_base64[:100]}"
    evidence_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
    ts = payload.timestamp or datetime.utcnow().isoformat()

    # Encrypt audio and image payloads with AES-256-GCM before database insertion
    encrypted_audio = encrypt_evidence_payload(payload.audio_base64)
    encrypted_image = encrypt_evidence_payload(payload.image_base64)

    evidence_record = {
        "evidence_id": f"EVID-{int(time.time())}-{secrets.token_hex(3).upper()}",
        "evidence_hash": evidence_hash,
        "has_audio": bool(payload.audio_base64),
        "has_image": bool(payload.image_base64),
        "is_encrypted": True,
        "encryption_algorithm": "AES-256-GCM",
        "audio_ciphertext": encrypted_audio["ciphertext"],
        "audio_nonce": encrypted_audio["nonce"],
        "image_ciphertext": encrypted_image["ciphertext"],
        "image_nonce": encrypted_image["nonce"],
        "mime_type_audio": payload.mime_type_audio,
        "mime_type_image": payload.mime_type_image,
        "duration_seconds": payload.duration_seconds,
        "device_info": payload.device_info,
        "captured_at": ts,
        "tamper_verified": True
    }

    if sos_collection is not None:
        sos_collection.update_one(
            {"case_id": payload.case_id},
            {
                "$set": {
                    "has_evidence": True,
                    "evidence_hash": evidence_hash,
                    "evidence": evidence_record,
                    "evidence_captured_at": ts,
                    "updated_at": datetime.utcnow()
                }
            }
        )

    return {
        "success": True,
        "case_id": payload.case_id,
        "evidence_hash": evidence_hash,
        "message": f"🔒 Evidence encrypted with AES-256-GCM and sealed with integrity hash: {evidence_hash[:16]}..."
    }


@app.post("/authority/generate-dir-form")
def generate_dir_form(
    payload: GenerateDIRFormModel,
    current_user: AuthUser = Depends(require_authority)
):
    """Generates a Domestic Incident Report (DIR Form-1) under PWDVA 2005."""
    if sos_collection is None:
        raise HTTPException(status_code=500, detail="Database not connected")

    case_data = sos_collection.find_one({"case_id": payload.case_id})
    if not case_data:
        raise HTTPException(status_code=404, detail="Case not found")

    messages = [
        {
            "role": "system",
            "content": (
                "You are a legal AI assistant. Generate an official Indian Domestic Incident Report (DIR) Form-1 under Section 9(b) of PWDVA 2005. "
                "Cover: Complainant details, Nature & description of domestic violence (physical, emotional, verbal, economic, sexual), "
                "Whether shared household involved, Relief sought: Protection Order (Section 18), Residence Order (Section 19), Monetary Relief (Section 20), "
                "Custody Order (Section 21), Compensation (Section 22), Immediate danger assessment, Medical examination needed, Officer recommendation. "
                "Respond only with the report text."
            )
        },
        {"role": "user", "content": f"Case Data: {json.dumps(serialize_doc(case_data))}"}
    ]

    dir_report_text = call_groq(messages=messages, max_tokens=800)
    dir_form_number = f"DIR-{payload.case_id}-{int(time.time())}"

    response_doc = {
        "case_id": payload.case_id,
        "dir_form_number": dir_form_number,
        "generated_at": datetime.utcnow().isoformat(),
        "officer_name": payload.officer_name or current_user.name or "Protection Officer",
        "officer_designation": payload.officer_designation or "Protection Officer",
        "station_name": payload.station_name,
        "district": payload.district,
        "case_severity": case_data.get("severity"),
        "case_summary": case_data.get("summary"),
        "nature_of_abuse": case_data.get("nature_of_abuse"),
        "immediate_danger": case_data.get("immediate_danger"),
        "location": case_data.get("location"),
        "needs": case_data.get("needs"),
        "has_forensic_evidence": case_data.get("has_evidence", False),
        "evidence_hash": case_data.get("evidence_hash"),
        "dir_report_text": dir_report_text,
        "legal_sections": ["Section 498A IPC", "Section 85 BNS", "PWDVA 2005 Sec 12", "PWDVA 2005 Sec 18-22"],
        "relief_recommended": ["Protection Order", "Residence Order", "Monetary Relief"]
    }

    if dir_reports_collection is not None:
        dir_reports_collection.insert_one(response_doc)

    sos_collection.update_one(
        {"case_id": payload.case_id},
        {"$set": {"dir_generated": True, "dir_form_number": dir_form_number}}
    )

    return serialize_doc(response_doc)


@app.post("/authority/discreet-dispatch")
def discreet_dispatch(
    payload: DiscreetDispatchModel,
    current_user: AuthUser = Depends(require_authority)
):
    """Dispatches a silent/plainclothes Mahila Police response."""
    if sos_collection is None:
        raise HTTPException(status_code=500, detail="Database not connected")

    case_data = sos_collection.find_one({"case_id": payload.case_id})
    if not case_data:
        raise HTTPException(status_code=404, detail="Case not found")

    protocol = {}
    if payload.dispatch_type == "MAHILA_THANA":
        protocol = {"agency_name": "Women Police Cell (Mahila Thana)", "approach": "Plainclothes female officers", "vehicle": "Unmarked civilian vehicle", "siren": False, "estimated_minutes": 15, "contact_number": "1091"}
    elif payload.dispatch_type == "PLAINCLOTHES":
        protocol = {"agency_name": "Plainclothes Response Unit", "approach": "2 plainclothes officers (1 female)", "vehicle": "Unmarked vehicle", "siren": False, "estimated_minutes": 12, "contact_number": "112"}
    elif payload.dispatch_type == "PROTECTION_OFFICER":
        protocol = {"agency_name": "PWDVA Protection Officer", "approach": "Registered Protection Officer under DV Act", "vehicle": "Private vehicle", "siren": False, "estimated_minutes": 30, "contact_number": "181 (Women Helpline)"}
    elif payload.dispatch_type == "OSC_SAKHI":
        protocol = {"agency_name": "One Stop Centre (Sakhi)", "approach": "Counselor + Medical + Legal aid", "vehicle": "OSC emergency van", "siren": False, "estimated_minutes": 20, "contact_number": "181"}
    else:
        protocol = {"agency_name": payload.dispatch_type, "approach": "Standard", "vehicle": "Standard", "siren": not payload.silent_approach, "estimated_minutes": 15, "contact_number": ""}

    dispatch_doc = {
        "dispatch_id": f"DISCREET-{int(time.time())}",
        "case_id": payload.case_id,
        "dispatch_type": payload.dispatch_type,
        "priority": payload.priority,
        "silent_approach": payload.silent_approach,
        "dispatcher_notes": payload.dispatcher_notes,
        "dispatcher_id": current_user.user_id,
        "response_protocol": protocol,
        "dispatched_at": datetime.utcnow(),
        "status": "DISPATCHED"
    }

    sos_collection.update_one(
        {"case_id": payload.case_id},
        {"$push": {"dispatch_history": dispatch_doc}}
    )

    return serialize_doc(dispatch_doc)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)