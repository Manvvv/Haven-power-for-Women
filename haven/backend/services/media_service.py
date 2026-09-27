import os
import io
import time
import base64
import hashlib
import hmac
import logging
import requests
from fastapi import HTTPException
from dotenv import load_dotenv
from pathlib import Path

logger = logging.getLogger("haven_backend")
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")
HF_API_KEY = os.getenv("HF_API_KEY", "")
HF_IMG_URL = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"

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
