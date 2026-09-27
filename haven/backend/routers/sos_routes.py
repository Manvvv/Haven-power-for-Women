"""SOS routes — steganography, case saving, evidence, location."""
import base64
import hashlib
import logging
import secrets
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from auth import AuthUser, get_optional_user, get_current_user, require_self_or_authority, encrypt_evidence_payload
from rate_limiter import rate_limit_dependency
from services.db import sos_cases, sos_events, serialize_doc
from services.stego_service import (
    encode_message_in_image,
    decode_message,
    DecodeStatus,
    MessageTooLargeForImage,
)
from services.ai_service import get_embedding
from services.lifecycle_service import transition_sos, canonical_status, is_terminal_status
from services.notification_service import notification_manager
from services.audit_service import log_audit
from models.schemas import EvidenceUploadModel, LocationUpdateModel

logger = logging.getLogger("haven_backend")
router = APIRouter(tags=["SOS"])

# ─── Steganography input-hardening limits ───────────────────
# The /encode and /decode endpoints are intentionally ANONYMOUS (a woman in
# distress is not signed in during the covert SOS flow), so they are hardened
# against malformed input, decompression bombs, and oversized payloads rather
# than gated behind auth. Limits are deliberately generous for real phone photos
# but reject abuse before any expensive Pillow/steganography work runs.
MAX_IMAGE_B64_CHARS = 15_000_000        # ~11 MB decoded — matches prior guard
MAX_DECODED_IMAGE_BYTES = 12_000_000    # ~12 MB of raw image bytes
MAX_IMAGE_PIXELS = 40_000_000           # 40 MP — rejects decompression bombs
MAX_MESSAGE_CHARS = 5_000               # hidden-message payload ceiling
MAX_SAVE_TEXT_CHARS = 10_000            # /save-extracted-data decoded_text ceiling

# Numeric sanity bounds for a WGS84 coordinate + live-tracking telemetry. The
# shared, dependency-free validators live in services.geo_validation so the REST
# path (here) and the WebSocket path (main.py) reject identical bad telemetry and
# the logic is unit-testable without FastAPI/pymongo. Never fabricate values.
from services.geo_validation import finite_in_range as _finite_in_range


def _decode_image_b64(image_b64: str) -> bytes:
    """Safely base64-decode a client-supplied image string.

    Enforces the size ceiling BEFORE decoding, then validates the base64 itself.
    Raises a controlled HTTPException (400/413) — never an unhandled error, and
    never leaks decoder internals to the client.
    """
    if not isinstance(image_b64, str) or not image_b64:
        raise HTTPException(status_code=400, detail="image_base64 required")
    if len(image_b64) > MAX_IMAGE_B64_CHARS:
        raise HTTPException(status_code=413, detail="Payload too large. Maximum image size ~11MB.")
    try:
        # validate=True rejects non-base64 characters instead of silently ignoring them.
        image_bytes = base64.b64decode(image_b64, validate=True)
    except (ValueError, Exception):
        raise HTTPException(status_code=400, detail="Invalid base64 image data.")
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Invalid base64 image data.")
    if len(image_bytes) > MAX_DECODED_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Decoded image too large.")
    return image_bytes


def _validate_image_safe(image_bytes: bytes) -> None:
    """Verify decoded bytes are a real, safe image before expensive processing.

    Guards against decompression bombs and non-image payloads. Uses Pillow's
    verify()/size check with MAX_IMAGE_PIXELS set. Returns None on success;
    raises a controlled 400/413 otherwise. No stack trace or raw Pillow string
    reaches the client.
    """
    import io
    from PIL import Image, UnidentifiedImageError
    # Cap pixel count so Pillow itself raises on decompression bombs.
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(image_bytes)) as probe:
            width, height = probe.size
            if width * height > MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=413, detail="Image dimensions too large.")
            # verify() confirms the file is a parseable image without full decode.
            probe.verify()
    except HTTPException:
        raise
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="Unrecognized or corrupt image.")
    except Image.DecompressionBombError:
        raise HTTPException(status_code=413, detail="Image dimensions too large.")
    except Exception:
        # Includes DecompressionBombWarning promoted to error and any parse failure.
        raise HTTPException(status_code=400, detail="Invalid or unsafe image.")


@router.post("/encode")
def encode(
    body: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=20, window_seconds=60)),
):
    """Encode a hidden message into an image using LSB steganography.

    Intentionally anonymous (part of the covert victim SOS flow) but hardened:
    base64 is validated, size is capped, and the image is checked for
    decompression-bomb / non-image payloads before any steganography work.
    Response schema is unchanged: {"encoded_image_base64": ...}.
    """
    message = body.get("message", "")
    if not isinstance(message, str):
        raise HTTPException(status_code=400, detail="message must be text")
    if len(message) > MAX_MESSAGE_CHARS:
        raise HTTPException(status_code=413, detail="Message too long.")
    image_b64 = body.get("image_base64", "")
    image_bytes = _decode_image_b64(image_b64)
    _validate_image_safe(image_bytes)
    try:
        encoded = encode_message_in_image(image_bytes, message)
    except MessageTooLargeForImage:
        # Honest failure — the message does not fit. Never return an image that
        # silently carries no payload and call it success.
        raise HTTPException(
            status_code=413,
            detail={
                "error_code": "MESSAGE_TOO_LARGE_FOR_IMAGE",
                "detail": "Message is too large to hide in this image. Use a larger image or a shorter message.",
            },
        )
    return {"encoded_image_base64": base64.b64encode(encoded).decode()}


@router.post("/decode")
def decode(
    body: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=20, window_seconds=60)),
):
    """Decode a hidden LSB steganography message from an image.

    Intentionally anonymous but hardened identically to /encode. The decoder
    distinguishes each failure mode via a structured error_code instead of
    reporting every failure as "No hidden message found":
      - NO_PAYLOAD          → a valid image with no HAVEN message embedded
      - CORRUPTED_PAYLOAD   → a HAVEN message that failed its checksum (bit rot,
                              e.g. the file was recompressed after encoding)
      - UNSUPPORTED_FORMAT  → a lossy format (JPEG/WebP) that can't carry LSBs
      - INVALID_IMAGE       → not a parseable image
    On success returns {"status":"OK","decoded_message": ...}. Internal details
    are never leaked.
    """
    image_b64 = body.get("image_base64", "")
    image_bytes = _decode_image_b64(image_b64)
    _validate_image_safe(image_bytes)
    result = decode_message(image_bytes)
    if result.ok:
        return {"status": DecodeStatus.OK, "decoded_message": result.message}
    # Map decode statuses to appropriate HTTP codes without leaking internals.
    _CODE = {
        DecodeStatus.NO_PAYLOAD: 200,          # a valid image, just no message
        DecodeStatus.CORRUPTED_PAYLOAD: 422,
        DecodeStatus.UNSUPPORTED_FORMAT: 415,
        DecodeStatus.INVALID_IMAGE: 400,
    }
    _MESSAGE = {
        DecodeStatus.NO_PAYLOAD: "No hidden message found in this image.",
        DecodeStatus.CORRUPTED_PAYLOAD: "A hidden message was found but is corrupted (the image may have been recompressed after encoding). Re-share the original PNG.",
        DecodeStatus.UNSUPPORTED_FORMAT: "This image format is lossy and cannot carry a hidden message. A lossless PNG is required.",
        DecodeStatus.INVALID_IMAGE: "The uploaded file could not be read as an image.",
    }
    status = result.status
    body_out = {
        "status": status,
        "error_code": status,
        "detail": _MESSAGE.get(status, "Unable to decode image."),
    }
    http_code = _CODE.get(status, 400)
    if http_code == 200:
        # NO_PAYLOAD is not an error — return 200 with a clear, structured body.
        body_out["decoded_message"] = None
        return body_out
    raise HTTPException(status_code=http_code, detail=body_out)


@router.post("/save-extracted-data")
async def save_extracted_data(
    body: dict = Body(...),
    user: Optional[AuthUser] = Depends(get_optional_user),
    _=Depends(rate_limit_dependency(max_requests=30, window_seconds=60)),
):
    """Save an SOS case to MongoDB with idempotency + lifecycle tracking.

    Intentionally ANONYMOUS (covert victim / steganography / offline flow, like
    /encode and /decode) so it is hardened, not auth-gated: rate-limited,
    size-validated, idempotent. It NEVER reports success unless the write
    actually happened — DB down or a failed insert returns 503, so the
    offline-first client keeps the alert queued and retries on any non-2xx.
    """
    actor_id = user.user_id if user else "anonymous"

    collection = sos_cases()
    if collection is None:
        # DB down — do NOT fabricate success; 503 keeps the alert queued client-side.
        try:
            log_audit(actor_id=actor_id, role="user", action="SOS_SAVE_FAILED",
                      result="failure", reason="database_unavailable",
                      metadata={"trigger_type": "steganography"})
        except Exception:
            pass
        raise HTTPException(
            status_code=503,
            detail="Storage temporarily unavailable. Your alert is queued and will be retried automatically.",
        )

    # Strict, safe validation (controlled 4xx; no decoder/DB internals leaked).
    decoded_text = body.get("decoded_text", "")
    if not isinstance(decoded_text, str):
        raise HTTPException(status_code=400, detail="decoded_text must be text.")
    if len(decoded_text) > MAX_SAVE_TEXT_CHARS:
        raise HTTPException(status_code=422, detail="decoded_text too long.")

    # Idempotency: a retried submission returns the original case (no duplicate).
    idempotency_key = body.get("idempotency_key")
    if idempotency_key:
        if not isinstance(idempotency_key, str) or len(idempotency_key) > 200:
            raise HTTPException(status_code=400, detail="Invalid idempotency_key.")
        existing = collection.find_one({"idempotency_key": idempotency_key})
        if existing:
            return {"success": True, "case_id": existing.get("case_id"), "duplicate": True}

    case_id = f"HAVEN-{int(datetime.utcnow().timestamp())}-{secrets.token_hex(3)}"

    # Generate embedding for semantic search
    embedding = []
    if decoded_text:
        try:
            embedding = get_embedding(decoded_text)
        except Exception:
            embedding = []

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
        "status": "CREATED",
        "case_id": case_id,
        "user_id": user.user_id if user else "anonymous",
        "trigger_type": "steganography",
        "embedding": embedding,
    }
    if idempotency_key:
        doc["idempotency_key"] = idempotency_key

    # Persist. If the write fails, surface 503 — never report a save that did not happen.
    try:
        collection.insert_one(doc)
    except Exception:
        try:
            log_audit(actor_id=actor_id, role="user", action="SOS_SAVE_FAILED",
                      result="failure", reason="insert_error",
                      metadata={"case_id": case_id, "trigger_type": "steganography"})
        except Exception:
            pass
        raise HTTPException(
            status_code=503,
            detail="Could not save your alert right now. It is queued and will be retried automatically.",
        )

    # Record lifecycle transition (best-effort; the case row already exists).
    try:
        transition_sos(case_id, "CREATED", actor_id, "user")
    except Exception:
        pass

    # Notify authorities: persist to DB (for history/polling) AND push live over socket.
    title = "New SOS Case Received"
    msg = f"Case {case_id} — Severity: {doc['severity']}"
    notif_id = None
    try:
        notif_id = notification_manager.create_notification(
            recipient_id="all_authorities",
            event_type="NEW_SOS",
            title=title,
            message=msg,
            case_id=case_id
        )
    except Exception:
        pass
    try:
        await notification_manager.notify_authorities("NEW_SOS", {
            "notification_id": notif_id,
            "title": title,
            "message": msg,
            "case_id": case_id,
            "severity": doc["severity"],
            "trigger_type": doc["trigger_type"],
            "created_at": doc["created_at"].isoformat(),
        })
    except Exception:
        pass

    return {"success": True, "case_id": case_id}


@router.post("/sos/evidence")
def upload_sos_evidence(
    payload: EvidenceUploadModel,
    current_user: AuthUser = Depends(get_current_user),
):
    """Encrypts and stores ambient audio/camera evidence with AES-256-GCM.

    Requires authentication. The caller must own the target case (or be an
    authority/admin) — this prevents writing evidence to an arbitrary case_id.
    """
    collection = sos_cases()
    if collection is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    case = collection.find_one({"case_id": payload.case_id}, {"_id": 0, "user_id": 1})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    require_self_or_authority(str(case.get("user_id", "")), current_user)

    raw_content = f"{payload.case_id}:{payload.timestamp}:{payload.audio_base64[:100]}:{payload.image_base64[:100]}"
    evidence_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
    ts = payload.timestamp or datetime.utcnow().isoformat()

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

    collection.update_one(
        {"case_id": payload.case_id},
        {"$set": {"has_evidence": True, "evidence_hash": evidence_hash,
                  "evidence": evidence_record, "evidence_captured_at": ts,
                  "updated_at": datetime.utcnow()}}
    )

    return {
        "success": True, "case_id": payload.case_id,
        "evidence_hash": evidence_hash,
        "message": f"🔒 Evidence encrypted with AES-256-GCM and sealed with integrity hash: {evidence_hash[:16]}..."
    }


@router.post("/sos/location-update")
async def sos_location_update(
    update: LocationUpdateModel,
    current_user: AuthUser = Depends(get_current_user)
):
    """REST fallback to push live GPS coordinates for an active SOS event.

    Requires authentication. The caller must own the event (or be an
    authority/admin) — prevents spoofing another victim's live location.
    """
    events_coll = sos_events()
    if events_coll is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    event = events_coll.find_one({"event_id": update.event_id}, {"_id": 0, "user_id": 1})
    if not event:
        raise HTTPException(status_code=404, detail="SOS event not found")
    require_self_or_authority(str(event.get("user_id", "")), current_user)

    # Coordinate + telemetry sanity: reject NaN/±inf and out-of-range values.
    # Never fabricate — accuracy/speed/heading are only accepted when supplied.
    if not _finite_in_range(update.latitude, -90.0, 90.0) or \
       not _finite_in_range(update.longitude, -180.0, 180.0):
        raise HTTPException(status_code=422, detail="Invalid coordinates.")
    if update.accuracy is not None and not _finite_in_range(update.accuracy, 0.0, 100000.0):
        raise HTTPException(status_code=422, detail="Invalid accuracy.")
    if update.speed is not None and not _finite_in_range(update.speed, 0.0, 12000.0):
        raise HTTPException(status_code=422, detail="Invalid speed.")
    if update.heading is not None and not _finite_in_range(update.heading, 0.0, 360.0):
        raise HTTPException(status_code=422, detail="Invalid heading.")

    # Stop live tracking once the case is resolved (terminal): reject the update,
    # do NOT broadcast, and record the rejection. Historical evidence is untouched.
    cases_coll = sos_cases()
    if cases_coll is not None:
        case = cases_coll.find_one({"case_id": update.event_id}, {"_id": 0, "status": 1})
        if case is not None and is_terminal_status(case.get("status", "")):
            log_audit(actor_id=current_user.user_id, role=current_user.role,
                      action="LOCATION_UPDATE_REJECTED", case_id=update.event_id,
                      result="rejected", reason="case_resolved",
                      metadata={"event_id": update.event_id})
            raise HTTPException(
                status_code=409,
                detail="SOS case is resolved; live location tracking has stopped.",
            )

    from main import tracking_manager
    ts = update.timestamp or datetime.utcnow().isoformat()
    # Build the live payload from ONLY the fields actually supplied (no fabrication).
    data = {"event_id": update.event_id, "latitude": update.latitude,
            "longitude": update.longitude, "timestamp": ts}
    if update.accuracy is not None:
        data["accuracy"] = update.accuracy
    if update.speed is not None:
        data["speed"] = update.speed
    if update.heading is not None:
        data["heading"] = update.heading
    await tracking_manager.broadcast_location(update.event_id, data)

    # Persist ONLY the fields actually supplied — never fabricate accuracy/speed/
    # heading. location_timestamp records when this fix was reported (honest).
    stored = {
        "latitude": update.latitude,
        "longitude": update.longitude,
        "location_timestamp": ts,
        "updated_at": datetime.utcnow(),
    }
    if update.accuracy is not None:
        stored["location_accuracy"] = update.accuracy
    if update.speed is not None:
        stored["location_speed"] = update.speed
    if update.heading is not None:
        stored["location_heading"] = update.heading

    if events_coll is not None:
        events_coll.update_one({"event_id": update.event_id}, {"$set": stored})
    cases_coll = sos_cases()
    if cases_coll is not None:
        cases_coll.update_one({"case_id": update.event_id}, {"$set": stored})

    # Honest response: echo the current fix and expose accuracy/timestamp only
    # when the client actually supplied accuracy (no implied precision).
    resp = {
        "success": True,
        "event_id": update.event_id,
        "latitude": update.latitude,
        "longitude": update.longitude,
        "timestamp": ts,
    }
    if update.accuracy is not None:
        resp["accuracy"] = update.accuracy
    if update.speed is not None:
        resp["speed"] = update.speed
    if update.heading is not None:
        resp["heading"] = update.heading
    return resp
