from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, HTTPException
from typing import Optional
from services.db import notifications
from services.notification_service import manager
from auth import AuthUser, get_current_user, require_authority, decode_token

router = APIRouter(prefix="", tags=["Notifications"])

# WebSocket close codes (mirror the tracking endpoint in main.py).
_WS_UNAUTHENTICATED = 4401
_WS_FORBIDDEN = 4403
_WS_OBSERVER_ROLES = ("authority", "admin", "police", "protection_officer")


@router.get("/notifications/{user_id}")
def get_user_notifications(
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    current_user: AuthUser = Depends(get_current_user)
):
    # User can only see own notifications, but authority/admin can see all
    if current_user.role == "user" and current_user.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to view these notifications")

    collection = notifications()
    if collection is None:
        return []

    # Unread notifications
    query = {"recipient_id": user_id, "read": False}
    results = list(collection.find(query, {"_id": 0})
                   .sort("created_at", -1)
                   .limit(limit))
    return results

@router.patch("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: str,
    current_user: AuthUser = Depends(get_current_user)
):
    collection = notifications()
    if collection is None:
        return {"success": False}

    notification = collection.find_one({"notification_id": notification_id})
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    if current_user.role == "user" and current_user.user_id != notification.get("recipient_id"):
        raise HTTPException(status_code=403, detail="Not authorized to modify this notification")

    collection.update_one(
        {"notification_id": notification_id},
        {"$set": {"read": True}}
    )

    return {"success": True, "notification_id": notification_id}

@router.websocket("/ws/notifications/{user_id}")
async def websocket_notifications(
    websocket: WebSocket,
    user_id: str,
    token: Optional[str] = Query(None),
):
    """Live notification stream for a user or the authority dashboard.

    Authorization (never trusts the path user_id alone):
      * token is verified; missing/invalid/expired -> connection rejected.
      * authority/admin roles may subscribe to any channel (including the
        shared "auth_*" authority-broadcast rooms used by the dashboard).
      * a regular user may only subscribe to their OWN user_id channel.
    Without this, an anonymous client could open /ws/notifications/auth_x and
    receive live SOS broadcasts intended for authorities.
    """
    # Verify the token BEFORE accepting the handshake.
    if not token:
        await websocket.close(code=_WS_UNAUTHENTICATED)
        return
    try:
        claims = decode_token(token)
    except HTTPException:
        await websocket.close(code=_WS_UNAUTHENTICATED)
        return
    except Exception:
        await websocket.close(code=_WS_UNAUTHENTICATED)
        return

    token_uid = claims.get("user_id") or claims.get("sub")
    role = (claims.get("role") or "user").lower()
    is_observer = role in _WS_OBSERVER_ROLES
    # authority/admin may observe any channel; a plain user only their own.
    if not (is_observer or (token_uid and token_uid == user_id)):
        await websocket.close(code=_WS_FORBIDDEN)
        return

    await manager.connect(user_id, websocket)
    try:
        while True:
            # Keep connection open and wait for messages
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
