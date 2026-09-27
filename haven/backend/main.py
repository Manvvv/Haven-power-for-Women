"""Haven Women Safety Platform - Main Backend Application Entry Point."""
import os
import logging
from datetime import datetime
from typing import Optional, List, Dict
from pathlib import Path
from dotenv import load_dotenv

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

# Load .env
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("haven_backend")

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT in ("production", "prod")

# Initialize FastAPI App
app = FastAPI(
    title="Haven API",
    version="2.0.0",
    description="Secure, resilient backend for Haven Women Safety Platform"
)

# ─── Global Request Body Size Limit ─────────────────────────
# Rejects oversized HTTP request bodies at the ASGI boundary BEFORE any route
# runs, protecting against memory-exhaustion DoS. This is the OUTER ceiling only:
# the stricter per-endpoint limits stay in force (legal PDF 15MB, media 10MB,
# covert stego image ~11MB). The ceiling is sized for the LARGEST legitimate
# request — the authenticated /sos/evidence upload, which may carry
# audio_base64 (<=20MB) + image_base64 (<=20MB) together as one JSON body
# (~40MB + envelope). Default 50MB in development; production may override via
# MAX_REQUEST_BODY_BYTES. A value of 0 / negative / "unlimited" is REJECTED in
# production (fail-fast, mirroring auth._validate_production_config) so an
# operator can never silently disable the protection on a live deployment.
_DEFAULT_MAX_REQUEST_BODY_BYTES = 50 * 1024 * 1024  # 50 MB


def _resolve_max_request_body_bytes() -> int:
    raw = os.getenv("MAX_REQUEST_BODY_BYTES")
    if raw is None or not raw.strip():
        if IS_PRODUCTION:
            logger.info(
                "MAX_REQUEST_BODY_BYTES not set; using built-in %d-byte ceiling. "
                "Set it explicitly for production if a different limit is required.",
                _DEFAULT_MAX_REQUEST_BODY_BYTES,
            )
        return _DEFAULT_MAX_REQUEST_BODY_BYTES
    token = raw.strip().lower()
    invalid = token in ("0", "none", "null", "unlimited", "-1", "off", "false")
    value = None
    if not invalid:
        try:
            value = int(raw.strip())
        except ValueError:
            invalid = True
        else:
            if value <= 0:
                invalid = True
    if invalid or value is None:
        if IS_PRODUCTION:
            raise RuntimeError(
                "HAVEN refuses to start in production with an unlimited/invalid "
                "MAX_REQUEST_BODY_BYTES. Set it to a positive byte count "
                "(e.g. 52428800 for 50MB)."
            )
        logger.warning(
            "Ignoring invalid MAX_REQUEST_BODY_BYTES=%r; using development "
            "default of %d bytes.", raw, _DEFAULT_MAX_REQUEST_BODY_BYTES,
        )
        return _DEFAULT_MAX_REQUEST_BODY_BYTES
    return value


MAX_REQUEST_BODY_BYTES = _resolve_max_request_body_bytes()


class _RequestBodyTooLarge(Exception):
    """Internal signal raised while streaming when the body exceeds the ceiling."""


class BodySizeLimitMiddleware:
    """Pure-ASGI middleware enforcing a global request-body ceiling.

    Streaming-safe: it never buffers the whole body. It (1) fast-rejects an
    honest oversized Content-Length before any body is read, and (2) counts the
    actual bytes as they stream in, so a spoofed/absent Content-Length or a
    chunked transfer-encoding request is still bounded. WebSocket and lifespan
    scopes are passed through untouched. No internal detail is exposed to the
    client — only a stable 413 JSON body.
    """

    def __init__(self, app, max_body_bytes: int):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        limit = self.max_body_bytes

        # (1) Honest Content-Length fast-reject (no body read yet).
        declared = None
        for k, v in scope.get("headers") or []:
            if k == b"content-length":
                try:
                    declared = int(v)
                except (ValueError, TypeError):
                    declared = None
                break
        if declared is not None and declared > limit:
            await self._send_413(send)
            return

        # (2) Stream-count actual bytes — defeats a spoofed/missing
        #     Content-Length and bounds chunked transfer-encoding.
        total = 0
        response_started = False

        async def counting_receive():
            nonlocal total
            message = await receive()
            if message.get("type") == "http.request":
                total += len(message.get("body", b"") or b"")
                if total > limit:
                    raise _RequestBodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _RequestBodyTooLarge:
            # Only safe to emit a 413 if the app hasn't begun responding.
            if not response_started:
                await self._send_413(send)

    @staticmethod
    async def _send_413(send):
        import json as _json
        body = _json.dumps({"detail": "Request body too large."}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})


# Register the body-size guard BEFORE CORS so CORS remains the OUTERMOST
# middleware: a 413 therefore still carries the proper CORS headers and stays
# readable by the browser fetch layer.
app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=MAX_REQUEST_BODY_BYTES)
logger.info("Global request-body ceiling: %d bytes", MAX_REQUEST_BODY_BYTES)

# ─── CORS Configuration ─────────────────────────────────────
ALLOWED_ORIGINS_RAW = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allowed_origins = [o.strip() for o in ALLOWED_ORIGINS_RAW.split(",") if o.strip()]
frontend_env = os.getenv("FRONTEND_URL")
if frontend_env and frontend_env not in allowed_origins:
    allowed_origins.append(frontend_env.strip())

# Browsers reject `allow_origins=*` (or a ".*" regex) together with
# allow_credentials=True. Use the explicit allowlist so credentialed requests work.
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
logger.info(f"CORS allowlist: {allowed_origins}")

# ─── Live GPS WebSocket Tracking & Location Stream ──────────
# Shared, dependency-free telemetry validator (also used by the REST location
# path in routers/sos_routes.py) — never fabricate values the client did not send.
from services.geo_validation import finite_or_none as _finite_or_none


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

    def purge_location(self, event_id: str) -> bool:
        """Drop the cached last-known location once an event is resolved/cancelled.

        Called when an SOS case reaches a terminal state so that a late WebSocket
        subscriber cannot be served a stale live fix after tracking has stopped
        (issue #5 — latest_locations was never purged). This clears ONLY the
        in-memory live cache; the historical location persisted on the case/event
        rows is untouched, so evidence is preserved. Returns True if a cached
        location was actually present.
        """
        return self.latest_locations.pop(event_id, None) is not None

tracking_manager = LiveTrackingManager()


# WebSocket close codes (application-defined, 4000-4999 range).
WS_UNAUTHENTICATED = 4401
WS_FORBIDDEN = 4403
WS_EVENT_NOT_FOUND = 4404

# Roles permitted to OBSERVE another user's live location.
_WS_OBSERVER_ROLES = ("authority", "admin", "police", "protection_officer")


def _authorize_ws_event(token: Optional[str], event_id: str):
    """Verify the WS token and authorize it against the SOS event.

    Returns (auth_user, can_broadcast) on success. Raises a (code, reason) tuple
    (via ValueError) the caller turns into a clean close. No event_id trust:
    authorization is derived from the verified token + the event's owner.
    """
    from auth import decode_token
    from services.db import sos_events
    from fastapi import HTTPException as _HTTPException

    if not token:
        raise ValueError((WS_UNAUTHENTICATED, "missing token"))
    try:
        claims = decode_token(token)
    except _HTTPException:
        raise ValueError((WS_UNAUTHENTICATED, "invalid or expired token"))
    except Exception:
        raise ValueError((WS_UNAUTHENTICATED, "invalid token"))

    user_id = claims.get("user_id") or claims.get("sub")
    role = (claims.get("role") or "user").lower()

    events_coll = sos_events()
    if events_coll is None:
        raise ValueError((WS_EVENT_NOT_FOUND, "event store unavailable"))
    event = events_coll.find_one({"event_id": event_id}, {"_id": 0, "user_id": 1})
    if not event:
        raise ValueError((WS_EVENT_NOT_FOUND, "unknown event"))

    owner_id = str(event.get("user_id", ""))
    is_owner = bool(user_id) and user_id == owner_id
    is_observer = role in _WS_OBSERVER_ROLES

    if not (is_owner or is_observer):
        # Authenticated but not the owner and not an authority -> forbidden.
        raise ValueError((WS_FORBIDDEN, "not authorized for this event"))

    # Only the legitimate owner may broadcast coordinates; observers are read-only.
    return {"user_id": user_id, "role": role}, is_owner


@app.websocket("/ws/track/{event_id}")
async def websocket_tracking_endpoint(
    websocket: WebSocket,
    event_id: str,
    token: Optional[str] = Query(None),
):
    """
    Real-time WebSocket room for a victim's live GPS.

    Authorization (no reliance on event_id alone):
      * token is verified; invalid/expired/missing -> connection rejected.
      * the event's owner may BROADCAST and subscribe.
      * an authority/admin may SUBSCRIBE (read-only).
      * anyone else is rejected with a clean close.
    """
    try:
        _auth_user, can_broadcast = _authorize_ws_event(token, event_id)
    except ValueError as e:
        code, reason = e.args[0]
        # P2-1: audit the rejected connection. Only the outcome/reason/event_id
        # and close code are recorded — never the token or any GPS data.
        try:
            from services.audit_service import log_audit
            log_audit(
                actor_id="unknown", role="unknown",
                action="WS_CONNECT_REJECTED", result="denied", reason=str(reason),
                metadata={"event_id": event_id, "close_code": code},
                request=websocket,
            )
        except Exception:
            pass
        # Close BEFORE accept -> the handshake is rejected.
        await websocket.close(code=code)
        return

    # P2-1: audit the successful, authorized connection. Identity comes from the
    # verified token (via _authorize_ws_event); no GPS coordinates are logged.
    try:
        from services.audit_service import log_audit
        log_audit(
            actor_id=_auth_user.get("user_id") or "unknown",
            role=_auth_user.get("role") or "unknown",
            action="WS_CONNECTED", result="success",
            metadata={"event_id": event_id, "can_broadcast": can_broadcast},
            request=websocket,
        )
    except Exception:
        pass

    await tracking_manager.connect(event_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # Observers cannot inject coordinates — only the owner may broadcast.
            if not can_broadcast:
                continue
            # A live fix requires REAL coordinates. Reject NaN/±inf/out-of-range
            # and never fabricate a 0,0 "null island" location on missing data.
            lat = _finite_or_none(data.get("latitude"))
            lng = _finite_or_none(data.get("longitude"))
            if lat is None or not (-90.0 <= lat <= 90.0) or \
               lng is None or not (-180.0 <= lng <= 180.0):
                continue
            ts_in = data.get("timestamp")
            payload = {
                "event_id": event_id,
                "latitude": lat,
                "longitude": lng,
                "timestamp": ts_in if isinstance(ts_in, str) and ts_in else datetime.utcnow().isoformat(),
            }
            # Optional telemetry — included ONLY when the client actually supplies
            # a valid value (no fabricated accuracy=5.0 / speed=0 / heading=0).
            acc = _finite_or_none(data.get("accuracy"))
            if acc is not None and 0.0 <= acc <= 100000.0:
                payload["accuracy"] = acc
            spd = _finite_or_none(data.get("speed"))
            if spd is not None and 0.0 <= spd <= 12000.0:
                payload["speed"] = spd
            hdg = _finite_or_none(data.get("heading"))
            if hdg is not None and 0.0 <= hdg <= 360.0:
                payload["heading"] = hdg
            await tracking_manager.broadcast_location(event_id, payload)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        # Disconnect handling is unchanged (still called on every exit path);
        # P2-1 adds a disconnect audit event (no GPS payload is recorded).
        tracking_manager.disconnect(event_id, websocket)
        try:
            from services.audit_service import log_audit
            log_audit(
                actor_id=_auth_user.get("user_id") or "unknown",
                role=_auth_user.get("role") or "unknown",
                action="WS_DISCONNECTED", result="success",
                metadata={"event_id": event_id},
                request=websocket,
            )
        except Exception:
            pass


# ─── Root & Health Check ────────────────────────────────────
@app.get("/")
def root():
    return {"message": "Haven API is active and secure", "version": "2.0.0"}


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ─── Include Modular Routers ────────────────────────────────
from routers.auth_routes import router as auth_router
from routers.sos_routes import router as sos_router
from routers.voice_routes import router as voice_router, _voice_sos_cooldowns
from routers.ai_routes import router as ai_router
from routers.legal_routes import router as legal_router
from routers.therapy_routes import router as therapy_router
from routers.cases_routes import router as cases_router
from routers.authority_routes import router as authority_router
from routers.culprit_routes import router as culprit_router
from routers.media_routes import router as media_router
from routers.admin_routes import router as admin_router
from routers.notification_routes import router as notification_router
from routers.analytics_routes import router as analytics_router
from routers.privacy_routes import router as privacy_router
from routers.search_routes import router as search_router

app.include_router(auth_router)
app.include_router(sos_router)
app.include_router(voice_router)
app.include_router(ai_router)
app.include_router(legal_router)
app.include_router(therapy_router)
app.include_router(cases_router)
app.include_router(authority_router)
app.include_router(culprit_router)
app.include_router(media_router)
app.include_router(admin_router)
app.include_router(notification_router)
app.include_router(analytics_router)
app.include_router(privacy_router)
app.include_router(search_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)