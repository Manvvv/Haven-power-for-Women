import json
from typing import Dict, List
from fastapi import WebSocket
from datetime import datetime
from services.db import notifications
import secrets
import time

class NotificationManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, user_id: str, websocket: WebSocket):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def notify_authorities(self, event_type: str, case_data: dict):
        """
        Push a live notification to all connected authority sockets.

        Authority sockets are identified by a user_id beginning with "auth_"
        (the authority dashboard connects as auth_<id>). The payload is shaped
        to match the frontend `useNotifications` Notification interface so it can
        render directly, while also carrying event_type + data for richer clients.
        """
        payload = {
            "id": case_data.get("notification_id") or f"live-{int(time.time()*1000)}",
            "type": event_type,
            "event_type": event_type,
            "title": case_data.get("title", "New notification"),
            "message": case_data.get("message", ""),
            "case_id": case_data.get("case_id"),
            "timestamp": datetime.utcnow().isoformat(),
            "read": False,
            "data": case_data,
        }
        message = json.dumps(payload)
        for user_id, sockets in list(self.active_connections.items()):
            if user_id.startswith("auth_"):
                for ws in list(sockets):
                    try:
                        await ws.send_text(message)
                    except Exception:
                        pass

    async def notify_user(self, user_id: str, event_type: str, data: dict):
        """Push to specific user."""
        if user_id in self.active_connections:
            message = json.dumps({"event_type": event_type, "data": data})
            for ws in self.active_connections[user_id]:
                try:
                    await ws.send_text(message)
                except Exception:
                    pass

    def create_notification(self, recipient_id: str, event_type: str, title: str, message: str, case_id: str):
        """Persist to DB."""
        coll = notifications()
        if coll is None:
            return None
        doc = {
            "notification_id": f"NOTIF-{int(time.time())}-{secrets.token_hex(4)}",
            "recipient_id": recipient_id,
            "event_type": event_type,
            "title": title,
            "message": message,
            "case_id": case_id,
            "read": False,
            "created_at": datetime.utcnow()
        }
        coll.insert_one(doc)
        return doc["notification_id"]

manager = NotificationManager()
notification_manager = manager
