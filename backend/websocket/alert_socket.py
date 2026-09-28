import json
import time
import secrets
import threading
import asyncio
from typing import List, Dict, Tuple, Optional
from fastapi import WebSocket, WebSocketDisconnect

class WebSocketManager:
    """
    Manages real-time client WebSocket connections for live alert broadcasting
    with single-use ticket authentication and expiration.
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._tickets: Dict[str, float] = {}  # ticket -> expiry_timestamp
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Explicitly records the running asyncio event loop for threadsafe dispatch."""
        self._loop = loop

    def create_ticket(self, ttl_seconds: int = 60) -> str:
        """
        Generates a secure, cryptographically random single-use ticket.
        """
        ticket = f"xws_{secrets.token_urlsafe(24)}"
        expiry = time.time() + ttl_seconds
        with self._lock:
            # Clean up old expired tickets
            now = time.time()
            expired_keys = [k for k, exp in self._tickets.items() if exp < now]
            for k in expired_keys:
                del self._tickets[k]
            self._tickets[ticket] = expiry
        return ticket

    def validate_and_consume_ticket(self, ticket: Optional[str]) -> Tuple[bool, str]:
        """
        Validates and immediately consumes a ticket.
        Enforces single-use semantics and expiration checking.
        """
        if not ticket or not ticket.strip():
            return False, "Missing authentication ticket"

        ticket = ticket.strip()
        with self._lock:
            if ticket not in self._tickets:
                return False, "Invalid or already consumed ticket"

            expiry = self._tickets.pop(ticket)
            if time.time() > expiry:
                return False, "Ticket expired"

            return True, "Ticket valid"

    async def connect(self, websocket: WebSocket):
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        await websocket.accept()
        self.active_connections.append(websocket)
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "SYSTEM_CONNECTED",
            "message": "Connected to Xynapse Real-Time Alert Stream"
        })

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Broadcasts a JSON message to all active WebSocket clients."""
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)

        for dead in dead_connections:
            self.disconnect(dead)

    def broadcast_threadsafe(self, message: dict) -> None:
        """
        Non-blocking thread-safe alert dispatch.
        Schedules broadcast directly on the FastAPI uvicorn event loop from worker threads
        without spinning up ad-hoc event loops or blocking camera frame capture.
        """
        if not self.active_connections:
            return
        if self._loop is not None and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(message), self._loop)
        else:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.broadcast(message))
            except RuntimeError:
                try:
                    asyncio.run(self.broadcast(message))
                except Exception as ex:
                    print(f"[WebSocketManager] Broadcast error: {ex}")

# Global singleton instance
ws_manager = WebSocketManager()
