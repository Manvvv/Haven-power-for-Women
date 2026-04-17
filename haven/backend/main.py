"""
Haven Backend - FastAPI
NO pydantic - uses plain dicts + Body() for Python 3.14 compatibility
Replaces: AWS Bedrock → Google Gemini + Groq
Replaces: AWS S3 → Cloudinary (free tier)
"""

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
from datetime import datetime
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, UploadFile, File, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from dotenv import load_dotenv
from pathlib import Path

# Load .env from the same folder as this file (works regardless of cwd)
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

app = FastAPI(title="Haven API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── MongoDB ─────────────────────────────────────────────
MONGO_ENDPOINT = os.getenv("MONGO_ENDPOINT", "")
if MONGO_ENDPOINT:
    client = MongoClient(MONGO_ENDPOINT)
    db = client["Haven"]
    sos_collection = db["sos_cases"]
    culprit_collection = db["culprits"]
    legal_collection = db["legal_docs"]
    therapy_collection = db["therapy_sessions"]
else:
    client = None
    db = None
    sos_collection = None
    culprit_collection = None
    legal_collection = None
    therapy_collection = None

# ─── API Keys ────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")
HF_API_KEY = os.getenv("HF_API_KEY", "")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
GEMINI_EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
HF_IMG_URL = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"


# ─── Helpers ─────────────────────────────────────────────

def call_gemini(prompt: str, system: str = "") -> str:
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    resp = requests.post(
        f"{GEMINI_URL}?key={GEMINI_API_KEY}",
        json={"contents": [{"parts": [{"text": full_prompt}]}]},
        timeout=30,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Gemini error: {resp.text}")
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def call_groq(messages: list, model: str = "llama-3.3-70b-versatile", max_tokens: int = 1024) -> str:
    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "max_tokens": max_tokens},
        timeout=30,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Groq error: {resp.text}")
    return resp.json()["choices"][0]["message"]["content"]


def get_embedding(text: str) -> list:
    resp = requests.post(
        f"{GEMINI_EMBED_URL}?key={GEMINI_API_KEY}",
        json={"model": "models/gemini-embedding-001", "content": {"parts": [{"text": text}]}},
        timeout=30,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Embedding error: {resp.text}")
    return resp.json()["embedding"]["values"]


def generate_image_hf(prompt: str) -> bytes:
    for attempt in range(3):  # retry up to 3 times
        resp = requests.post(
            HF_IMG_URL,
            headers={"Authorization": f"Bearer {HF_API_KEY}"},
            json={"inputs": prompt + ", high quality, photorealistic, peaceful"},
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.content
        if resp.status_code == 503:
            time.sleep(20)  # model is loading, wait and retry
            continue
        raise HTTPException(status_code=500, detail=f"Image gen error: {resp.text}")
    raise HTTPException(status_code=500, detail="Image generation timed out, try again")


def upload_to_cloudinary(image_bytes: bytes, public_id: str = None) -> str:
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
        raise HTTPException(status_code=500, detail=f"Cloudinary error: {resp.text}")
    return resp.json()["secure_url"]


# ─── Steganography ────────────────────────────────────────

def encode_message_in_image(image_bytes: bytes, message: str) -> bytes:
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        encoded_msg = message + "<<END>>"
        bits = ''.join(format(ord(c), '08b') for c in encoded_msg)
        pixels = list(img.getdata())
        if len(bits) > len(pixels) * 3:
            return image_bytes
        new_pixels = []
        bit_idx = 0
        for pixel in pixels:
            new_pixel = list(pixel)
            for channel in range(3):
                if bit_idx < len(bits):
                    new_pixel[channel] = (new_pixel[channel] & ~1) | int(bits[bit_idx])
                    bit_idx += 1
            new_pixels.append(tuple(new_pixel))
        img.putdata(new_pixels)
        output = io.BytesIO()
        img.save(output, format="PNG")
        return output.getvalue()
    except Exception as e:
        print(f"Encode error: {e}")
        return image_bytes


def decode_message_from_image(image_bytes: bytes) -> str:
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        pixels = list(img.getdata())
        bits = []
        for pixel in pixels:
            for channel in range(3):
                bits.append(str(pixel[channel] & 1))
        chars = []
        for i in range(0, len(bits) - 7, 8):
            byte_val = int(''.join(bits[i:i+8]), 2)
            if byte_val == 0:
                break
            chars.append(chr(byte_val))
            if ''.join(chars).endswith('<<END>>'):
                return ''.join(chars)[:-7]
        return "No hidden message found"
    except Exception as e:
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
        else:
            result[k] = v
    return result


# ─── Routes ──────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "Haven API is running", "version": "1.0.0"}


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# 1. Expand keywords into full distress message
@app.post("/text-generation")
def text_generation(body: dict = Body(...)):
    keywords = body.get("keywords", "")
    context = body.get("context", "domestic abuse distress situation")
    if not keywords:
        raise HTTPException(status_code=400, detail="keywords required")
    system = (
        "You are an AI assistant for Haven, a women's safety platform. "
        "Expand brief keywords from a woman in distress into a clear, complete distress message. "
        "Output ONLY the expanded message, nothing else."
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": f"Expand these keywords: '{keywords}'\nContext: {context}"}]
    result = call_groq(messages, model="llama-3.3-70b-versatile")
    return {"expanded_message": result.strip()}


# 2. Generate image via HuggingFace
@app.post("/img-generation")
def img_generation(body: dict = Body(...)):
    prompt = body.get("prompt", "peaceful garden")
    image_bytes = generate_image_hf(prompt)
    # Convert to PNG regardless of what HF returns
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        output = io.BytesIO()
        img.save(output, format="PNG")
        image_bytes = output.getvalue()
    except Exception as e:
        print(f"Image convert error: {e}")
    b64 = base64.b64encode(image_bytes).decode()
    return {"image_base64": b64, "format": "png"}


# 3. Encode message into image
@app.post("/encode")
def encode(body: dict = Body(...)):
    message = body.get("message", "")
    image_b64 = body.get("image_base64", "")
    image_bytes = base64.b64decode(image_b64)
    print(f"DEBUG encode: input_size={len(image_bytes)}, first4={image_bytes[:4]}")
    encoded = encode_message_in_image(image_bytes, message)
    print(f"DEBUG encode: output_size={len(encoded)}, first4={encoded[:4]}, same={image_bytes==encoded}")
    return {"encoded_image_base64": base64.b64encode(encoded).decode()}


# 4. Decode hidden message from image
@app.post("/decode")
def decode(body: dict = Body(...)):
    image_b64 = body.get("image_base64", "")
    image_bytes = base64.b64decode(image_b64)
    return {"decoded_message": decode_message_from_image(image_bytes)}


# 5. Decompose decoded text into structured fields
@app.post("/text-decomposition")
def text_decomposition(body: dict = Body(...)):
    text = body.get("text", "")
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
        {"role": "user", "content": f"Decompose: {text}"}
    ]
    result = call_groq(messages)
    try:
        parsed = json.loads(re.sub(r'```json|```', '', result).strip())
    except Exception:
        parsed = {"severity": "unknown", "summary": text[:200]}
    return parsed


# 6. Save SOS case to MongoDB
@app.post("/save-extracted-data")
def save_extracted_data(body: dict = Body(...)):
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
    }
    if sos_collection is not None:
        sos_collection.insert_one(doc)
    return {"success": True, "case_id": doc["case_id"]}


# 7. Get all SOS cases
@app.get("/cases")
def get_cases(severity: str = Query(None), status: str = Query(None)):
    if sos_collection is None:
        return {"cases": [], "total": 0}
    query = {}
    if severity:
        query["severity"] = severity
    if status:
        query["status"] = status
    cases = list(sos_collection.find(query, {"_id": 0}).sort("created_at", -1).limit(50))
    return {"cases": [serialize_doc(c) for c in cases], "total": len(cases)}


# 8. Update case status
@app.patch("/cases/{case_id}")
def update_case(case_id: str, body: dict = Body(...)):
    if sos_collection is not None:
        sos_collection.update_one({"case_id": case_id}, {"$set": body})
    return {"success": True}


# 9. Report culprit
@app.post("/culprit/report")
def report_culprit(body: dict = Body(...)):
    physical_description = body.get("physical_description", "")
    behavioral_traits = body.get("behavioral_traits", "")
    description = f"{physical_description}. {behavioral_traits}"
    embedding = get_embedding(description)
    doc = {
        "name": body.get("name", "Unknown"),
        "physical_description": physical_description,
        "behavioral_traits": behavioral_traits,
        "location": body.get("location", ""),
        "reporter_id": body.get("reporter_id", "anonymous"),
        "description_embedding": embedding,
        "created_at": datetime.utcnow(),
        "culprit_id": f"CULPRIT-{int(datetime.utcnow().timestamp())}",
    }
    if culprit_collection is not None:
        culprit_collection.insert_one(doc)
    return {"success": True, "culprit_id": doc["culprit_id"]}


# 10. Find similar culprits
@app.post("/culprit/find-match")
def find_culprit_match(body: dict = Body(...)):
    description = body.get("description", "")
    top_n = body.get("top_n", 5)
    search_mode = body.get("search_mode", "auto")  # "name", "description", "auto"
    min_score = body.get("min_score", 0.0)          # minimum similarity score filter

    if culprit_collection is None:
        return {"matches": [], "query": description}

    # ── Name search mode ──────────────────────────────────
    # If mode is "name" or auto-detect looks like a person name (short, no special chars)
    is_likely_name = (
        search_mode == "name" or
        (search_mode == "auto" and len(description.split()) <= 4 and len(description) < 50
         and not any(c in description for c in ["age", "tall", "hair", "cm", "kg", "year"]))
    )

    if is_likely_name:
        # Try exact name match first (case-insensitive)
        exact = list(culprit_collection.find(
            {"name": {"$regex": f"^{re.escape(description.strip())}$", "$options": "i"}},
            {"_id": 0, "description_embedding": 0}
        ).limit(top_n))
        if exact:
            for r in exact:
                r["score"] = 1.0  # exact match = 100%
            return {"matches": [serialize_doc(r) for r in exact], "query": description, "search_type": "exact_name"}

        # Try partial name match
        partial = list(culprit_collection.find(
            {"name": {"$regex": description.strip(), "$options": "i"}},
            {"_id": 0, "description_embedding": 0}
        ).limit(top_n))
        if partial:
            for r in partial:
                r["score"] = 0.95  # partial match
            return {"matches": [serialize_doc(r) for r in partial], "query": description, "search_type": "partial_name"}

    # ── Vector similarity search ──────────────────────────
    query_embedding = get_embedding(description)
    if not query_embedding:
        # Gemini quota hit — fall back to text search
        fallback = list(culprit_collection.find(
            {"$or": [
                {"name": {"$regex": description.strip(), "$options": "i"}},
                {"physical_description": {"$regex": description.strip(), "$options": "i"}},
                {"behavioral_traits": {"$regex": description.strip(), "$options": "i"}},
            ]},
            {"_id": 0, "description_embedding": 0}
        ).limit(top_n))
        for r in fallback:
            r["score"] = 0.9
        return {"matches": [serialize_doc(r) for r in fallback], "query": description, "search_type": "text_fallback"}

    try:
        results = list(culprit_collection.aggregate([
            {
                "$vectorSearch": {
                    "index": "culpritIndex",
                    "path": "description_embedding",
                    "queryVector": query_embedding,
                    "numCandidates": 100,
                    "limit": top_n * 3,  # fetch more, then filter by score
                }
            },
            {"$project": {
                "name": 1, "physical_description": 1, "behavioral_traits": 1,
                "location": 1, "culprit_id": 1, "created_at": 1, "_id": 0,
                "score": {"$meta": "vectorSearchScore"}
            }}
        ]))
        # Filter by minimum score threshold and limit
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
def legal_query(body: dict = Body(...)):
    question = body.get("question", "")
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
        {"role": "user", "content": question}
    ]
    answer = call_groq(messages, model="llama-3.3-70b-versatile")
    return {"answer": answer, "sources": [c.get("source", "") for c in chunks]}


# 12. Upload legal PDF
@app.post("/legal/upload-doc")
async def upload_legal_doc(file: UploadFile = File(...), source_name: str = "Legal Document"):
    from pypdf import PdfReader
    content = await file.read()
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
                "text": chunk, "source": source_name,
                "embedding": embedding, "created_at": datetime.utcnow(),
            })
            inserted += 1
    return {"success": True, "chunks_embedded": inserted, "source": source_name}


# 13. Therapy chat
@app.post("/therapy/chat")
def therapy_chat(body: dict = Body(...)):
    message = body.get("message", "")
    user_id = body.get("user_id", "anonymous")
    session_id = body.get("session_id")
    history = []
    if session_id and therapy_collection is not None:
        past = therapy_collection.find_one({"session_id": session_id})
        if past:
            history = past.get("messages", [])[-6:]
    messages = [
        {
            "role": "system",
            "content": """You are Aria, a warm and compassionate AI therapy companion for women in distress.

CRITICAL RULES — ALWAYS FOLLOW:
- Keep EVERY reply under 3 sentences maximum
- Never write long paragraphs
- Be warm, short, and human — like a caring friend texting
- Ask ONE simple follow-up question at the end
- Never list multiple points or use bullet points
- If you want to say many things, pick only the most important one
- Speak gently, simply, and directly

Examples of GOOD short replies:
"I hear you, and I'm so sorry you're going through this. You are not alone in this moment. Can you tell me a little more about what happened?"

"That sounds really scary. You were so brave to reach out. What are you feeling right now?"

"You don't have to face this alone — I'm right here with you. Take a deep breath. What would feel helpful right now?"

NEVER write more than 3 sentences. NEVER write multiple paragraphs."""
        }
    ] + history + [{"role": "user", "content": message}]
    response = call_groq(messages, model="llama-3.3-70b-versatile", max_tokens=150)
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
    content = await file.read()
    url = upload_to_cloudinary(content, public_id=f"haven_{int(time.time())}")
    return {"url": url}


# 15. Generate poem
@app.post("/generate-poem")
async def generate_poem(data: dict = Body(...)):
    try:
        emotional_state = data.get("emotional_state", "in need of hope and strength")
        
        prompt = f"""Write a short, beautiful, empowering poem (8-12 lines) for a woman who is feeling {emotional_state}.
The poem should be:
- Warm, gentle and hopeful
- About inner strength and resilience  
- Not mention abuse or violence directly
- End with an uplifting message

Write ONLY the poem, no title, no explanation."""

        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)
        
        # Safe text extraction
        poem_text = ""
        if hasattr(response, 'text') and response.text:
            poem_text = response.text.strip()
        elif response.candidates:
            poem_text = response.candidates[0].content.parts[0].text.strip()
        
        if not poem_text:
            poem_text = "You are stronger than the storm,\nBraver than the night,\nWithin you burns a quiet flame\nThat no one can extinguish.\nYou are not alone.\nYou are seen. You are loved."
        
        return {"poem": poem_text}
        
    except Exception as e:
        print(f"Poem error: {e}")
        # Always return a fallback poem, never crash
        return {
            "poem": "You are stronger than the storm,\nBraver than the night,\nWithin you burns a quiet flame\nThat no one can extinguish.\nYou are not alone.\nYou are seen. You are loved."
        }
