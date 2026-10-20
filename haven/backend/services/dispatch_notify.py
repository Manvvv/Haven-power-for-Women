"""Side-effect boundary: push dispatch_service "notification intents" over sockets.

dispatch_service is deliberately SYNC and side-effect-pure beyond persistence +
durable notifications: it returns a list of live notification INTENTS and never
touches the event loop itself. This tiny module is the ONE place that turns those
intents into real WebSocket pushes, so the engine stays unit-testable without an
event loop while the live fan-out lives next to the loop that owns it.

Intent shapes (produced by dispatch_service):
  {"kind": "authorities", "event_type": str, "data": {title, message, case_id, dispatch_id}}
  {"kind": "user", "target": <user_id>, "event_type": str, "data": {...}}

No secrets, tokens, GPS history, or victim PII are ever added here — the intents
are already minimized by the engine; this module only transports them.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from services.notification_service import manager as notification_manager

logger = logging.getLogger("haven_backend")

# The server's main asyncio loop, captured at startup. Used ONLY so a SYNC route
# running in a threadpool (e.g. the case-resolution hook) can still schedule a
# live push. It is never required for correctness — durable notifications are
# always persisted by the engine regardless of whether a live push lands.
_MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _MAIN_LOOP
    _MAIN_LOOP = loop


async def emit_intents(intents: Optional[List[Dict[str, Any]]]) -> None:
    """Push each intent to its audience. Best-effort: one bad push never aborts the rest."""
    for intent in intents or []:
        try:
            kind = intent.get("kind")
            if kind == "authorities":
                await notification_manager.notify_authorities(
                    intent.get("event_type") or "dispatch_update", intent.get("data") or {})
            elif kind == "user":
                target = intent.get("target")
                if target:
                    await notification_manager.notify_user(
                        target, intent.get("event_type") or "dispatch_update", intent.get("data") or {})
        except Exception:
            # A single unreachable socket must not break notifying the others.
            pass


def emit_intents_threadsafe(intents: Optional[List[Dict[str, Any]]]) -> None:
    """Fire-and-forget live push from a SYNC context (threadpool route / sweeper).

    Schedules emit_intents on the captured main loop. If the loop is unavailable
    (e.g. during tests, or before startup), this is a silent no-op: the durable
    notifications persisted by the engine are the reliable channel; the live push
    is only an enhancement.
    """
    if not intents:
        return
    loop = _MAIN_LOOP
    if loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(emit_intents(intents), loop)
    except Exception:
        pass
