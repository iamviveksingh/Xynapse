import os
import time
import pytest
import numpy as np
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.main import app
from backend.config import settings
from backend.websocket.alert_socket import ws_manager
from backend.camera.camera_manager import CameraManager, redact_camera_source
from backend.evidence.snapshot import save_transit_snapshot
from backend.sync.sync_worker import sync_pending_events
from backend.database.database import SessionLocal, init_db

@pytest.fixture
def client():
    return TestClient(app, headers={"X-API-Key": settings.ADMIN_API_KEY})

# ==============================================================================
# 1. WEBSOCKET SINGLE-USE TICKET TESTS
# ==============================================================================

def test_websocket_missing_ticket_rejected(client):
    """Verify WebSocket connection without a ticket is rejected with close code 1008."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/alerts"):
            pass
    assert exc_info.value.code == 1008

def test_websocket_invalid_ticket_rejected(client):
    """Verify WebSocket connection with an unrecognized ticket is rejected with code 1008."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/alerts?ticket=fake_invalid_token_999"):
            pass
    assert exc_info.value.code == 1008

def test_websocket_valid_and_single_use_consumption(client):
    """
    Verify:
    1. Issue fresh ticket via POST /api/alerts/ws-ticket.
    2. Connect successfully.
    3. Reusing the same ticket fails (single-use enforced).
    """
    # 1. Obtain ticket
    resp = client.post("/api/alerts/ws-ticket")
    assert resp.status_code == 200
    ticket = resp.json()["ticket"]
    assert ticket.startswith("xws_")

    # 2. First connection succeeds
    with client.websocket_connect(f"/ws/alerts?ticket={ticket}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "SYSTEM_CONNECTED"

    # 3. Second connection with same ticket must be rejected (single-use)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/alerts?ticket={ticket}"):
            pass
    assert exc_info.value.code == 1008

def test_websocket_expired_ticket_rejected(client):
    """Verify that an expired ticket is rejected."""
    # Create an artificially expired ticket
    ticket = ws_manager.create_ticket(ttl_seconds=-1)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/alerts?ticket={ticket}"):
            pass
    assert exc_info.value.code == 1008

# ==============================================================================
# 2. RTSP CREDENTIAL REDACTION TESTS
# ==============================================================================

def test_rtsp_credential_redaction_function():
    """Verify redact_camera_source masks passwords while preserving hosts/ports/paths."""
    raw = "rtsp://admin:SecretPassword123@192.168.1.50:554/h264Preview_01_main"
    redacted = redact_camera_source(raw)
    assert "SecretPassword123" not in redacted
    assert "admin:***@192.168.1.50:554" in redacted

    # Safe names and device indices unchanged
    assert redact_camera_source("0") == "0"
    assert redact_camera_source("outpost_zulu_03") == "outpost_zulu_03"
    assert redact_camera_source("rtsp://192.168.1.50:554/live") == "rtsp://192.168.1.50:554/live"

def test_camera_status_dict_masks_rtsp_password():
    """Verify get_status_dict() never returns plaintext passwords."""
    raw_source = "rtsp://guard_user:TopSecretKey99@10.0.4.15:554/feed"
    cam = CameraManager(
        camera_id="CAM-SEC-TEST",
        name="Security Test Camera",
        source=raw_source
    )
    status = cam.get_status_dict()
    assert "TopSecretKey99" not in status["source"]
    assert "guard_user:***@10.0.4.15:554" in status["source"]

# ==============================================================================
# 3. HTTP SECURITY HEADERS TESTS
# ==============================================================================

def test_http_security_headers_present(client):
    """Verify defensive HTTP security headers are injected in all responses."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert resp.headers.get("X-XSS-Protection") == "1; mode=block"

# ==============================================================================
# 4. EVIDENCE & FILESYSTEM PATH TRAVERSAL TESTS
# ==============================================================================

def test_static_evidence_path_traversal_blocked(client):
    """Verify that path traversal attempts through /evidence cannot read system files."""
    # Attempt to read database or .env
    resp_db = client.get("/evidence/../xynapse.db")
    assert resp_db.status_code in (400, 404)

    resp_env = client.get("/evidence/../../.env")
    assert resp_env.status_code in (400, 404)

    resp_encoded = client.get("/evidence/%2e%2e%2fxynapse.db")
    assert resp_encoded.status_code in (400, 404)

def test_transit_snapshot_path_sanitization():
    """Verify save_transit_snapshot strips malicious directory traversal characters."""
    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
    malicious_event_id = "..\\..\\root_exploit:test"
    saved_url = save_transit_snapshot(dummy_frame, malicious_event_id, prefix="veh")
    assert saved_url is not None
    assert ".." not in saved_url
    assert "\\" not in saved_url
    assert saved_url.startswith("/evidence/transits/")

# ==============================================================================
# 5. HQ STORE-AND-FORWARD SCHEME VALIDATION TESTS
# ==============================================================================

def test_hq_sync_invalid_scheme_rejection():
    """Verify sync_pending_events rejects non-HTTP/HTTPS destinations."""
    init_db()
    db = SessionLocal()
    try:
        res_file = sync_pending_events(db, target_url="file:///etc/shadow")
        assert res_file["status"] == "INVALID_HQ_ENDPOINT"

        res_gopher = sync_pending_events(db, target_url="gopher://127.0.0.1:70")
        assert res_gopher["status"] == "INVALID_HQ_ENDPOINT"
    finally:
        db.close()

# ==============================================================================
# 6. CORS ORIGIN RESTRICTION TESTS
# ==============================================================================

def test_cors_trusted_vs_untrusted_origin(client):
    """Verify CORS permits trusted local origins and denies untrusted third-party origins."""
    # Trusted origin
    resp_trusted = client.options("/api/health", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET"
    })
    assert resp_trusted.headers.get("access-control-allow-origin") == "http://localhost:5173"

    # Untrusted origin
    resp_untrusted = client.options("/api/health", headers={
        "Origin": "https://malicious-external-site.com",
        "Access-Control-Request-Method": "GET"
    })
    assert resp_untrusted.headers.get("access-control-allow-origin") is None
