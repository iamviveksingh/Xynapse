import os
import time
import json
import pytest
import numpy as np
import cv2
from datetime import datetime
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from unittest.mock import patch
from backend.main import app
from backend.config import settings
from backend.database.database import init_db, SessionLocal
from backend.database.models import Alert, VehicleProfile, FaceProfile, CameraConfig
from backend.websocket.alert_socket import ws_manager
from backend.camera.camera_manager import CameraManager

# Clients with different privilege tiers:
# 1. Unauthenticated client
# 2. Invalid credential client
# 3. Operator client (read-only / operational access)
# 4. Admin client (full configuration and mutation privileges)

@pytest.fixture
def unauth_client():
    return TestClient(app)

@pytest.fixture
def invalid_client():
    return TestClient(app, headers={"X-API-Key": "invalid-malicious-token-xyz"})

@pytest.fixture
def operator_client():
    return TestClient(app, headers={"X-API-Key": settings.OPERATOR_API_KEY})

@pytest.fixture
def admin_client():
    return TestClient(app, headers={"X-API-Key": settings.ADMIN_API_KEY})

@pytest.fixture(autouse=True)
def ensure_db():
    init_db()


# ==============================================================================
# 1. WEBSOCKET TICKET ISSUANCE & SINGLE-USE LIFECYCLE
# ==============================================================================

def test_ws_ticket_unauthenticated_rejected(unauth_client):
    """Case A: Unauthenticated request to ticket endpoint must be rejected with 401."""
    resp = unauth_client.post("/api/alerts/ws-ticket")
    assert resp.status_code == 401

def test_ws_ticket_invalid_credentials_rejected(invalid_client):
    """Case C: Invalid credentials must be rejected with 403."""
    resp = invalid_client.post("/api/alerts/ws-ticket")
    assert resp.status_code == 403

def test_ws_ticket_authorized_operator_and_admin(operator_client, admin_client):
    """Case B: Valid authorized client receives a short-lived single-use ticket."""
    # Operator can request ticket
    op_resp = operator_client.post("/api/alerts/ws-ticket")
    assert op_resp.status_code == 200
    op_ticket = op_resp.json()["ticket"]
    assert op_ticket.startswith("xws_")

    # Admin can request ticket
    adm_resp = admin_client.post("/api/alerts/ws-ticket")
    assert adm_resp.status_code == 200
    adm_ticket = adm_resp.json()["ticket"]
    assert adm_ticket.startswith("xws_")

def test_ws_ticket_single_use_consumption(operator_client, unauth_client):
    """Verify single-use ticket consumption: second connection with same ticket fails with 1008."""
    resp = operator_client.post("/api/alerts/ws-ticket")
    assert resp.status_code == 200
    ticket = resp.json()["ticket"]

    # 1. First connection succeeds
    with unauth_client.websocket_connect(f"/ws/alerts?ticket={ticket}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "SYSTEM_CONNECTED"

    # 2. Second connection fails (already consumed)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with unauth_client.websocket_connect(f"/ws/alerts?ticket={ticket}"):
            pass
    assert exc_info.value.code == 1008

def test_ws_ticket_expired_rejected(unauth_client):
    """Verify expired ticket is rejected with close code 1008."""
    expired_ticket = ws_manager.create_ticket(ttl_seconds=-5)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with unauth_client.websocket_connect(f"/ws/alerts?ticket={expired_ticket}"):
            pass
    assert exc_info.value.code == 1008


# ==============================================================================
# 2. CAMERA MUTATION AUTHORIZATION
# ==============================================================================

def test_camera_create_mutation_protection(unauth_client, operator_client, admin_client):
    """POST /api/cameras requires ADMIN privileges."""
    cam_id = f"CAM-AUTH-{int(time.time()*1000)}"
    payload = {
        "camera_id": cam_id,
        "name": "Auth Test Cam",
        "source": "0",
        "surveillance_mode": "PERIMETER"
    }
    # Unauthenticated -> 401
    assert unauth_client.post("/api/cameras", json=payload).status_code == 401

    # Operator (insufficient privileges) -> 403
    assert operator_client.post("/api/cameras", json=payload).status_code == 403

    # Admin -> 200
    with patch.object(CameraManager, "start"), patch.object(CameraManager, "stop"):
        res = admin_client.post("/api/cameras", json=payload)
        assert res.status_code == 200
        assert res.json()["camera_id"] == cam_id
        admin_client.delete(f"/api/cameras/{cam_id}")

def test_camera_source_mutation_protection(unauth_client, operator_client, admin_client):
    """POST /api/cameras/{id}/source requires ADMIN privileges."""
    # Unauthenticated -> 401
    assert unauth_client.post("/api/cameras/CAM-01/source", json={"source": "0"}).status_code == 401

    # Operator -> 403
    assert operator_client.post("/api/cameras/CAM-01/source", json={"source": "0"}).status_code == 403

    # Admin -> 200
    with patch.object(CameraManager, "start"), patch.object(CameraManager, "stop"):
        assert admin_client.post("/api/cameras/CAM-01/source", json={"source": "0"}).status_code == 200

def test_camera_delete_mutation_protection(unauth_client, operator_client, admin_client):
    """DELETE /api/cameras/{id} requires ADMIN privileges."""
    cam_id = f"CAM-DEL-{int(time.time()*1000)}"
    # Create temp camera record in DB
    db = SessionLocal()
    try:
        cfg = CameraConfig(camera_id=cam_id, name="Del Test", source="0")
        db.add(cfg)
        db.commit()
    finally:
        db.close()

    # Unauthenticated -> 401
    assert unauth_client.delete(f"/api/cameras/{cam_id}").status_code == 401

    # Operator -> 403
    assert operator_client.delete(f"/api/cameras/{cam_id}").status_code == 403

    # Admin -> 200
    assert admin_client.delete(f"/api/cameras/{cam_id}").status_code == 200


# ==============================================================================
# 3. PERIMETER & OPTICAL CONFIGURATION AUTHORIZATION
# ==============================================================================

def test_polygon_configuration_protection(unauth_client, operator_client, admin_client):
    """POST /api/cameras/{id}/polygon requires ADMIN privileges."""
    poly_payload = {"points": [[100, 100], [400, 100], [400, 400], [100, 400]], "enabled": True}

    # Unauthenticated -> 401
    assert unauth_client.post("/api/cameras/CAM-01/polygon", json=poly_payload).status_code == 401

    # Operator -> 403
    assert operator_client.post("/api/cameras/CAM-01/polygon", json=poly_payload).status_code == 403

    # Admin -> 200
    assert admin_client.post("/api/cameras/CAM-01/polygon", json=poly_payload).status_code == 200

def test_tripwire_configuration_protection(unauth_client, operator_client, admin_client):
    """POST /api/cameras/{id}/tripwire/config and /toggle require ADMIN privileges."""
    # Unauthenticated -> 401
    assert unauth_client.post("/api/cameras/CAM-01/tripwire/toggle").status_code == 401
    assert unauth_client.post("/api/cameras/CAM-01/tripwire/config", json={"enabled": True, "y_ratio": 0.5}).status_code == 401

    # Operator -> 403
    assert operator_client.post("/api/cameras/CAM-01/tripwire/toggle").status_code == 403
    assert operator_client.post("/api/cameras/CAM-01/tripwire/config", json={"enabled": True, "y_ratio": 0.5}).status_code == 403

    # Admin -> 200
    assert admin_client.post("/api/cameras/CAM-01/tripwire/config", json={"enabled": True, "y_ratio": 0.5}).status_code == 200
    assert admin_client.post("/api/cameras/CAM-01/tripwire/toggle").status_code == 200

def test_surveillance_and_optical_mode_protection(unauth_client, operator_client, admin_client):
    """POST /api/cameras/{id}/surveillance-mode and optical-mode require ADMIN privileges."""
    # Unauthenticated -> 401
    assert unauth_client.post("/api/cameras/CAM-01/surveillance-mode", json={"mode": "UNIFIED"}).status_code == 401
    assert unauth_client.post("/api/cameras/CAM-01/optical-mode", json={"mode": "LOW_LIGHT_ENHANCED"}).status_code == 401

    # Operator -> 403
    assert operator_client.post("/api/cameras/CAM-01/surveillance-mode", json={"mode": "UNIFIED"}).status_code == 403
    assert operator_client.post("/api/cameras/CAM-01/optical-mode", json={"mode": "LOW_LIGHT_ENHANCED"}).status_code == 403

    # Admin -> 200
    assert admin_client.post("/api/cameras/CAM-01/surveillance-mode", json={"mode": "UNIFIED"}).status_code == 200
    assert admin_client.post("/api/cameras/CAM-01/optical-mode", json={"mode": "STANDARD"}).status_code == 200


# ==============================================================================
# 4. VEHICLE WATCHLIST MUTATION AUTHORIZATION
# ==============================================================================

def test_vehicle_enrollment_and_deletion_protection(unauth_client, operator_client, admin_client):
    """POST /api/vehicles and DELETE /api/vehicles/{id} require ADMIN privileges."""
    payload = {
        "plate_number": "SEC01TEST",
        "vehicle_type": "Car",
        "owner_name": "Test Subject",
        "status": "CIVILIAN"
    }

    # Unauthenticated -> 401
    assert unauth_client.post("/api/vehicles", json=payload).status_code == 401

    # Operator -> 403
    assert operator_client.post("/api/vehicles", json=payload).status_code == 403

    # Admin -> 200
    res = admin_client.post("/api/vehicles", json=payload)
    assert res.status_code == 200
    veh_id = res.json()["id"]

    # Delete without admin -> 401, 403
    assert unauth_client.delete(f"/api/vehicles/{veh_id}").status_code == 401
    assert operator_client.delete(f"/api/vehicles/{veh_id}").status_code == 403

    # Admin delete -> 200
    assert admin_client.delete(f"/api/vehicles/{veh_id}").status_code == 200


# ==============================================================================
# 5. FACE REGISTRY MUTATION AUTHORIZATION
# ==============================================================================

def test_face_enrollment_and_deletion_protection(unauth_client, operator_client, admin_client):
    """POST /api/faces/enroll and DELETE /api/faces/{id} require ADMIN privileges."""
    # Create dummy image
    img = np.zeros((150, 150, 3), dtype=np.uint8)
    cv2.circle(img, (75, 75), 40, (200, 200, 200), -1)
    _, encoded = cv2.imencode('.jpg', img)
    files = {"file": ("test.jpg", encoded.tobytes(), "image/jpeg")}
    data = {"name": "Security Test Guard", "role": "AUTHORIZED_GUARD", "notes": "Test"}

    # Unauthenticated -> 401
    assert unauth_client.post("/api/faces/enroll", data=data, files=files).status_code == 401

    # Operator -> 403
    files = {"file": ("test.jpg", encoded.tobytes(), "image/jpeg")}
    assert operator_client.post("/api/faces/enroll", data=data, files=files).status_code == 403

    # Direct DB insertion of dummy face profile to test deletion
    db = SessionLocal()
    try:
        fp = FaceProfile(name="Del Test Guard", role="AUTHORIZED_GUARD", embedding_json=json.dumps([0.1]*128))
        db.add(fp)
        db.commit()
        db.refresh(fp)
        face_id = fp.id
    finally:
        db.close()

    # Unauthorized delete
    assert unauth_client.delete(f"/api/faces/{face_id}").status_code == 401
    assert operator_client.delete(f"/api/faces/{face_id}").status_code == 403

    # Admin delete
    assert admin_client.delete(f"/api/faces/{face_id}").status_code == 200


# ==============================================================================
# 6. ALERT LIFECYCLE & STATION CONFIG MUTATION AUTHORIZATION
# ==============================================================================

def test_alert_lifecycle_mutation_protection(unauth_client, operator_client, admin_client):
    """POST /api/alerts/{id}/acknowledge and /resolve require ADMIN privileges."""
    # Create test alert in DB
    db = SessionLocal()
    try:
        alert = Alert(
            camera_id="CAM-01",
            event_type="UNAUTHORIZED_HUMAN",
            severity="HIGH",
            status="PENDING",
            timestamp=datetime.utcnow()
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        alert_id = alert.id
    finally:
        db.close()

    # Unauthenticated -> 401
    assert unauth_client.post(f"/api/alerts/{alert_id}/acknowledge").status_code == 401
    assert unauth_client.post(f"/api/alerts/{alert_id}/resolve").status_code == 401

    # Operator -> 403
    assert operator_client.post(f"/api/alerts/{alert_id}/acknowledge").status_code == 403
    assert operator_client.post(f"/api/alerts/{alert_id}/resolve").status_code == 403

    # Admin -> 200
    res_ack = admin_client.post(f"/api/alerts/{alert_id}/acknowledge", json={"operator_id": "ADM-01", "decision": "CONFIRMED_THREAT"})
    assert res_ack.status_code == 200
    assert res_ack.json()["status"] == "ACKNOWLEDGED"

    res_res = admin_client.post(f"/api/alerts/{alert_id}/resolve", json={"operator_id": "ADM-01", "resolution_notes": "Resolved by team"})
    assert res_res.status_code == 200
    assert res_res.json()["status"] == "RESOLVED"

def test_station_config_mutation_protection(unauth_client, operator_client, admin_client):
    """POST /api/alerts/station-config requires ADMIN privileges."""
    cfg_payload = {"station_name": "Post Alpha", "operator_callsign": "Sierra 1", "audio_alert_enabled": True}

    # Unauthenticated -> 401
    assert unauth_client.post("/api/alerts/station-config", json=cfg_payload).status_code == 401

    # Operator -> 403
    assert operator_client.post("/api/alerts/station-config", json=cfg_payload).status_code == 403

    # Admin -> 200
    assert admin_client.post("/api/alerts/station-config", json=cfg_payload).status_code == 200


# ==============================================================================
# 7. SENSITIVE SURVEILLANCE READS AUTHORIZATION
# ==============================================================================

def test_sensitive_reads_require_operator_or_admin(unauth_client, operator_client, admin_client):
    """
    Verify sensitive surveillance read endpoints:
    - /api/alerts
    - /api/alerts/{id}
    - /api/alerts/export/csv
    - /api/vehicles/transits
    - /api/vehicles/transits/recent
    - /api/faces
    - /api/cameras/{id}/snapshot
    - /evidence/...
    All reject unauthenticated requests (401), and allow operator & admin (200).
    """
    sensitive_endpoints = [
        "/api/alerts",
        "/api/alerts/stats",
        "/api/alerts/export/csv",
        "/api/vehicles/transits",
        "/api/vehicles/transits/recent",
        "/api/faces",
        "/api/faces/stats",
        "/api/cameras/CAM-01/snapshot",
        "/api/blockchain/ledger"
    ]

    for ep in sensitive_endpoints:
        # Unauthenticated -> 401
        res_unauth = unauth_client.get(ep)
        assert res_unauth.status_code == 401, f"Expected 401 for unauthenticated {ep}, got {res_unauth.status_code}"

        # Operator -> 200
        res_op = operator_client.get(ep)
        assert res_op.status_code == 200, f"Expected 200 for operator on {ep}, got {res_op.status_code}"

        # Admin -> 200
        res_adm = admin_client.get(ep)
        assert res_adm.status_code == 200, f"Expected 200 for admin on {ep}, got {res_adm.status_code}"

def test_evidence_read_authorization_and_traversal(unauth_client, operator_client, admin_client):
    """Verify evidence file access requires authentication and blocks directory traversal."""
    # Ensure evidence test file exists
    test_evidence_file = os.path.join(settings.EVIDENCE_DIR, "test_auth_snap.jpg")
    with open(test_evidence_file, "wb") as f:
        f.write(b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xFF\xDB\x00C")

    # 1. Unauthenticated read -> 401
    assert unauth_client.get("/evidence/alerts/test_auth_snap.jpg").status_code == 401

    # 2. Invalid API key -> 403
    assert unauth_client.get("/evidence/alerts/test_auth_snap.jpg?api_key=bad-key").status_code == 403

    # 3. Authorized operator with query param (e.g. browser <img> tag) -> 200
    res_query = unauth_client.get(f"/evidence/alerts/test_auth_snap.jpg?api_key={settings.OPERATOR_API_KEY}")
    assert res_query.status_code == 200

    # 4. Authorized operator with header -> 200
    res_hdr = operator_client.get("/evidence/alerts/test_auth_snap.jpg")
    assert res_hdr.status_code == 200

    # 5. Directory traversal attempts -> 404
    assert unauth_client.get("/evidence/../xynapse.db").status_code in (400, 404)
    assert unauth_client.get("/evidence/%2e%2e/xynapse.db").status_code in (400, 404)

def test_public_health_endpoints_remain_public(unauth_client):
    """PUBLIC: Minimal health check must remain accessible without credentials."""
    resp = unauth_client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ==============================================================================
# 8. INTERNAL SERVICE AUTHENTICATION (WORKER / HQ SECRET)
# ==============================================================================

def test_internal_worker_secret_preservation(unauth_client):
    """Preserve existing worker secret authentication on /api/hq endpoints."""
    # 1. Missing secret -> 401
    r_missing = unauth_client.post("/api/hq/ingest", json={"event_id": "T1"})
    assert r_missing.status_code == 401

    # 2. Invalid secret -> 401
    r_bad = unauth_client.post("/api/hq/ingest", json={"event_id": "T1"}, headers={"X-Worker-Secret": "wrong"})
    assert r_bad.status_code == 401

    # 3. Valid secret -> 200
    payload = {
        "event_id": "TEST-INT-01",
        "camera_id": "CAM-01",
        "event_type": "UNAUTHORIZED_HUMAN",
        "severity": "HIGH",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {}
    }
    r_ok = unauth_client.post("/api/hq/ingest", json=payload, headers={"X-Worker-Secret": settings.INTERNAL_WORKER_SECRET})
    assert r_ok.status_code == 200


# ==============================================================================
# 9. CAMERA DEVICE DISCOVERY AUTHORIZATION (OPERATOR / ADMIN GATED)
# ==============================================================================

def test_camera_device_discovery_authorization(unauth_client, operator_client, admin_client):
    """GET /api/cameras/available-devices and /detected-devices require OPERATOR or ADMIN privileges."""
    # 1. Unauthenticated -> 401
    assert unauth_client.get("/api/cameras/available-devices").status_code == 401
    assert unauth_client.get("/api/cameras/detected-devices").status_code == 401

    # 2. Operator -> 200
    res_op_avail = operator_client.get("/api/cameras/available-devices")
    assert res_op_avail.status_code == 200
    assert isinstance(res_op_avail.json(), list)

    res_op_det = operator_client.get("/api/cameras/detected-devices")
    assert res_op_det.status_code == 200
    assert isinstance(res_op_det.json(), list)

    # 3. Admin -> 200
    res_adm = admin_client.get("/api/cameras/available-devices")
    assert res_adm.status_code == 200
    assert isinstance(res_adm.json(), list)
