import os
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.config import settings
from backend.database.database import init_db
from backend.api.health import router as health_router
from backend.api.cameras import router as cameras_router, get_or_create_default_camera, camera_registry
from backend.api.alerts import router as alerts_router
from backend.api.faces import router as faces_router
from backend.api.vehicles import router as vehicles_router
from backend.api.blockchain import router as blockchain_router
from backend.api.hq_receiver import router as hq_router
from backend.websocket.alert_socket import ws_manager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize database tables
    init_db()
    import asyncio
    try:
        ws_manager.set_event_loop(asyncio.get_running_loop())
    except Exception:
        pass
    # Pre-warm default camera
    get_or_create_default_camera()
    print("[Xynapse] Surveillance Platform Online.")

    # Secret hygiene check for local edge deployment
    if settings.INTERNAL_WORKER_SECRET == "xynapse-internal-worker-auth-key-2026":
        print("[Xynapse Security Advisory] Operating with default development INTERNAL_WORKER_SECRET. In production edge deployments, configure a unique secret via environment variable.")
    if settings.ADMIN_API_KEY == "xynapse-admin-sih-2026":
        print("[Xynapse Security Advisory] Operating with default development ADMIN_API_KEY.")

    yield
    # Shutdown: stop camera background threads
    print("[Xynapse] Shutting down cameras...")
    for cam in camera_registry.values():
        cam.stop()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Surveillance Perception, Human Detection, and Real-Time Threat Alerting API",
    lifespan=lifespan
)

# HTTP Security Headers Middleware (Pure ASGI to prevent BaseHTTPMiddleware streaming buffer errors)
class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_security_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"x-frame-options", b"DENY"))
                headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
                headers.append((b"x-xss-protection", b"1; mode=block"))
                path = scope.get("path", "")
                if path in ("/", "/index.html") or path.endswith(".html"):
                    headers.append((b"cache-control", b"no-cache, no-store, must-revalidate"))
                    headers.append((b"pragma", b"no-cache"))
                    headers.append((b"expires", b"0"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


class EvidenceProtectionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").startswith("/evidence"):
            raw_path = scope.get("path", "")
            # Check for directory traversal attempts
            if ".." in raw_path or "%2e%2e" in raw_path.lower():
                from starlette.responses import JSONResponse
                response = JSONResponse(status_code=404, content={"detail": "Not found"})
                return await response(scope, receive, send)

            # Authenticate operator or admin access
            from backend.security.auth import extract_api_key
            from starlette.requests import Request
            from starlette.responses import JSONResponse
            req = Request(scope, receive)
            key = extract_api_key(req)
            if not key:
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required. Provide X-API-Key, Authorization header, or api_key parameter."}
                )
                return await response(scope, receive, send)
            if key not in (settings.OPERATOR_API_KEY, settings.ADMIN_API_KEY):
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "Invalid API key."}
                )
                return await response(scope, receive, send)

        await self.app(scope, receive, send)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(EvidenceProtectionMiddleware)

# CORS configuration - restricted origins to prevent cross-origin exploitation
allowed_origins_list = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins_list,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Static file serving for evidence snapshots
evidence_base = os.path.dirname(settings.EVIDENCE_DIR)
os.makedirs(settings.EVIDENCE_DIR, exist_ok=True)
app.mount("/evidence", StaticFiles(directory=evidence_base), name="evidence")

# Include REST API Routers
app.include_router(health_router, prefix=settings.API_V1_STR)
app.include_router(cameras_router, prefix=settings.API_V1_STR)
app.include_router(alerts_router, prefix=settings.API_V1_STR)
app.include_router(faces_router, prefix=settings.API_V1_STR)
app.include_router(vehicles_router, prefix=settings.API_V1_STR)
app.include_router(blockchain_router, prefix=settings.API_V1_STR)
app.include_router(hq_router, prefix=settings.API_V1_STR)

# Real-Time WebSocket for alerts with single-use ticket authentication
@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket, ticket: Optional[str] = Query(None)):
    # Validate and immediately consume single-use authentication ticket
    is_valid, reason = ws_manager.validate_and_consume_ticket(ticket)
    if not is_valid:
        await websocket.close(code=1008, reason=reason)
        return

    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep-alive loop
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)

# Mount frontend production build if present
frontend_dist = os.path.join(settings.BASE_DIR, "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=getattr(settings, "HOST", "127.0.0.1"), port=getattr(settings, "PORT", 8000), reload=False)

