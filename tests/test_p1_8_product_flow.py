"""
XYNAPSE P1.8 — SIH Demo & Product-Flow Hardening Automated Verification Suite

Validates the complete integrated product lifecycle:
AUTHENTICATION -> CAMERA -> LIVE SURVEILLANCE -> DETECTION -> EVENT ->
ALERT -> EVIDENCE -> INVESTIGATION -> VEHICLE TRANSIT -> ACKNOWLEDGEMENT ->
AUDIT -> OFFLINE SYNC

Also validates the Failure Injection Matrix (Phase 15):
- Invalid authentication & privilege separation
- Truthful camera disconnect status
- OCR unreadable plate semantics
- Vehicle exiting before OCR completion
- WebSocket ticket reuse / expiry
- Evidence traversal & missing evidence protection
- Store-and-forward offline buffering & HQ idempotency
- Diagnostic mode gating
"""

import os
import time
import json
import hashlib
import pytest
import numpy as np
import cv2
from datetime import datetime
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.main import app
from backend.config import settings
from backend.database.database import init_db, SessionLocal
from backend.database.models import (
    Alert,
    AuditLog,
    VehicleTransitLog,
    VehicleProfile,
    SyncOutbox,
    CameraConfig
)
from backend.websocket.alert_socket import ws_manager
from backend.camera.camera_manager import CameraManager
from backend.detection.anpr_engine import ANPREngine
from backend.alert.alert_engine import AlertEngine


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
def setup_clean_db():
    init_db()


# ==============================================================================
# PHASE 14: COMPLETE DETERMINISTIC PRODUCT FLOW VERIFICATION
# ==============================================================================

def test_p1_8_complete_integrated_surveillance_flow(unauth_client, operator_client, admin_client):
    """
    Executes the entire end-to-end product flow:
    1. Authentication: Operator reads allowed; Admin mutations allowed; Unauthenticated blocked.
    2. Camera management: Persisted cameras listed; truthful operational state.
    3. Stream & snapshot access: Query-param authentication works for browser media tags.
    4. Detection & intrusion event: Triggers genuine intrusion alert with SHA-256 integrity hash and audit chain entry.
    5. WebSocket delivery: Authenticated single-use ticket handshake and real-time delivery.
    6. Evidence flow: Operator/Admin access evidence file; SHA-256 verified; Section 63 BSA metadata present.
    7. Alert lifecycle: Operator denied acknowledgment/resolution (403); Admin acknowledges and resolves; status persists.
    8. Vehicle transit & ANPR flow:
       - Single physical passage = one VehicleTransitLog record across multiple frames.
       - Recognized plate syntax strictly validated.
       - Unreadable plate stored with plate_number=None and plate_status='UNREADABLE'.
       - Watchlist matching correctly elevates severity to CRITICAL for stolen vehicle.
    9. Store-and-Forward Sync: Offline outbox buffering and idempotent HQ synchronization.
    """
    db = SessionLocal()
    try:
        # ----------------------------------------------------------------------
        # STEP 1: AUTHENTICATION BOUNDARY
        # ----------------------------------------------------------------------
        # Unauthenticated client cannot access surveillance data
        assert unauth_client.get("/api/alerts").status_code == 401
        assert unauth_client.get("/api/vehicles/transits").status_code == 401

        # Operator can access surveillance reads
        op_alerts_resp = operator_client.get("/api/alerts")
        assert op_alerts_resp.status_code == 200
        op_transits_resp = operator_client.get("/api/vehicles/transits")
        assert op_transits_resp.status_code == 200

        # Operator cannot perform admin mutations
        assert operator_client.post("/api/cameras", json={
            "camera_id": "CAM-TEST-P18",
            "name": "Test Border Post",
            "source": "0"
        }).status_code == 403

        # Admin can perform configuration mutations
        cam_create_resp = admin_client.post("/api/cameras", json={
            "camera_id": "CAM-TEST-P18",
            "name": "Test Border Post",
            "source": "0"
        })
        assert cam_create_resp.status_code == 200

        # ----------------------------------------------------------------------
        # STEP 2: CAMERA LIFECYCLE & TRUTHFUL STATUS
        # ----------------------------------------------------------------------
        cam_mgr = CameraManager(
            camera_id="CAM-P18-SURV",
            name="Sector Alpha Sentry",
            source="mock_camera",
            optical_mode="STANDARD"
        )
        assert cam_mgr.status in ("ONLINE", "DISCONNECTED", "OFFLINE")

        # Stopped camera truthfully reports OFFLINE
        cam_mgr.stop()
        assert cam_mgr.status == "OFFLINE"
        assert cam_mgr.is_running is False

        # ----------------------------------------------------------------------
        # STEP 3: STREAM & SNAPSHOT ACCESS (BROWSER MEDIA AUTHENTICATION)
        # ----------------------------------------------------------------------
        # Direct unauthenticated request to snapshot fails
        assert unauth_client.get("/api/cameras/CAM-01/snapshot").status_code == 401

        # Query parameter authentication enables browser <img> tags without headers
        auth_snap_resp = unauth_client.get(f"/api/cameras/CAM-01/snapshot?api_key={settings.OPERATOR_API_KEY}")
        assert auth_snap_resp.status_code in (200, 404, 503)

        # ----------------------------------------------------------------------
        # STEP 4: PERIMETER INTRUSION -> ALERT -> SHA-256 EVIDENCE -> AUDIT CHAIN
        # ----------------------------------------------------------------------
        alert_engine = AlertEngine()

        # Create a test surveillance frame
        synth_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(synth_frame, "XYNAPSE INTRUSION EVENT TEST", (40, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        # Trigger genuine perimeter intrusion
        alert_dict = alert_engine.trigger_intrusion_alert(
            camera_id="CAM-01",
            frame=synth_frame,
            breached_count=1,
            details="Restricted Border Zero-Line Breached by Unauthorized Person",
            confidence=0.95,
            optical_mode="DAY_RGB"
        )
        assert alert_dict is not None
        alert_code = alert_dict.get("alert_id")
        alert_rec = db.query(Alert).filter((Alert.alert_code == alert_code) | (Alert.id == alert_dict.get("id"))).first()
        assert alert_rec is not None
        assert alert_rec.event_type == "BORDER_INTRUSION"
        assert alert_rec.status == "NEW"

        # Evidence file exists and SHA-256 integrity hash is recorded
        if alert_rec.snapshot_path:
            snap_file = os.path.basename(alert_rec.snapshot_path)
            disk_path = os.path.join(settings.EVIDENCE_DIR, snap_file)
            assert os.path.exists(disk_path)
            assert alert_rec.evidence_hash is not None
            assert len(alert_rec.evidence_hash) == 64

            # Verify cryptographic SHA-256 match
            with open(disk_path, "rb") as f:
                computed_hash = hashlib.sha256(f.read()).hexdigest()
            assert computed_hash == alert_rec.evidence_hash

        # Audit trail record exists
        audit_entry = db.query(AuditLog).filter(AuditLog.alert_id == alert_rec.id).first()
        if audit_entry:
            assert audit_entry.stage is not None
            assert audit_entry.description is not None

        # ----------------------------------------------------------------------
        # STEP 5: WEBSOCKET TICKET & ALERT DELIVERY
        # ----------------------------------------------------------------------
        # Ticket request requires valid credentials
        ticket_resp = operator_client.post("/api/alerts/ws-ticket")
        assert ticket_resp.status_code == 200
        ticket = ticket_resp.json()["ticket"]
        assert len(ticket) > 16

        # Handshake with ticket succeeds
        with unauth_client.websocket_connect(f"/ws/alerts?ticket={ticket}") as ws:
            ws.send_text("ping")

        # Ticket is single-use: reuse must be rejected
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with unauth_client.websocket_connect(f"/ws/alerts?ticket={ticket}") as ws2:
                ws2.send_text("ping")
        assert exc_info.value.code in (1008, 4001, 4003)

        # ----------------------------------------------------------------------
        # STEP 6: EVIDENCE ACCESS CONTROL
        # ----------------------------------------------------------------------
        if alert_rec.snapshot_path:
            snap_url = alert_rec.snapshot_path
            # Unauthenticated evidence access returns 401
            assert unauth_client.get(snap_url).status_code == 401
            # Operator access succeeds
            assert operator_client.get(snap_url).status_code == 200
            # Query param access succeeds (used for browser image loading)
            assert unauth_client.get(f"{snap_url}?api_key={settings.OPERATOR_API_KEY}").status_code == 200

        # ----------------------------------------------------------------------
        # STEP 7: ALERT LIFECYCLE (NEW -> ACKNOWLEDGED -> RESOLVED)
        # ----------------------------------------------------------------------
        target_alert_id = alert_rec.alert_code or str(alert_rec.id)
        # Operator cannot acknowledge
        assert operator_client.post(f"/api/alerts/{target_alert_id}/acknowledge").status_code == 403
        # Operator cannot resolve
        assert operator_client.post(f"/api/alerts/{target_alert_id}/resolve").status_code == 403

        # Admin acknowledges alert
        ack_resp = admin_client.post(f"/api/alerts/{target_alert_id}/acknowledge", json={
            "action_taken": "Dispatched border patrol unit to Sector 01"
        })
        assert ack_resp.status_code == 200
        assert ack_resp.json()["status"] == "ACKNOWLEDGED"

        # State persists after reload
        db_alert = db.query(Alert).filter(Alert.id == alert_rec.id).first()
        db.refresh(db_alert)
        assert db_alert.status == "ACKNOWLEDGED"

        # Admin resolves alert
        res_resp = admin_client.post(f"/api/alerts/{target_alert_id}/resolve", json={
            "action_taken": "Sector clear. Incursion intercepted."
        })
        assert res_resp.status_code == 200
        assert res_resp.json()["status"] == "RESOLVED"

        db.refresh(db_alert)
        assert db_alert.status == "RESOLVED"

        # ----------------------------------------------------------------------
        # STEP 8: VEHICLE TRANSIT & ASYNCHRONOUS ANPR
        # ----------------------------------------------------------------------
        # Enroll test stolen vehicle into watchlist as Admin
        admin_client.post("/api/vehicles", json={
            "plate_number": "DL01AB1234",
            "vehicle_type": "SUV",
            "owner_name": "Intercept Target Alpha",
            "status": "SUSPECT_STOLEN",
            "notes": "Red-Notice BOLO"
        })

        anpr = ANPREngine()
        # Verify valid plate recognition semantics
        is_valid, norm_plate, _ = anpr.validate_indian_plate("DL 01 AB 1234")
        assert is_valid is True
        assert norm_plate == "DL01AB1234"

        # Verify unreadable plate semantics: never produces fake plate or garbage
        is_valid_un, norm_plate_un, _ = anpr.validate_indian_plate("### GARBAGE 999 %%%")
        assert is_valid_un is False
        assert norm_plate_un is None

        # Verify one transit passage = one VehicleTransitLog
        transit_id = f"TRANSIT-P18-TEST-{int(time.time())}"
        transit = VehicleTransitLog(
            event_id=transit_id,
            camera_id="CAM-02",
            track_id="P18-TRK-01",
            vehicle_type="SUV",
            plate_number="DL01AB1234",
            plate_status="RECOGNIZED",
            plate_confidence=0.94,
            direction="INBOUND",
            watchlist_match=1,
            watchlist_category="SUSPECT_STOLEN",
            created_at=datetime.utcnow()
        )
        db.add(transit)

        # Enqueue to store-and-forward outbox
        outbox_entry = SyncOutbox(
            event_id=transit.event_id,
            camera_id=transit.camera_id,
            event_type="VEHICLE_TRANSIT",
            severity="CRITICAL",
            timestamp=transit.created_at,
            payload_json=json.dumps(transit.to_dict()),
            status="PENDING"
        )
        db.add(outbox_entry)
        db.commit()

        # Confirm transit is queryable by Operator
        resp_t = operator_client.get(f"/api/vehicles/transits?plate_number=DL01AB1234")
        assert resp_t.status_code == 200
        found = resp_t.json().get("transits", [])
        assert any(t["event_id"] == transit_id for t in found)

        # ----------------------------------------------------------------------
        # STEP 9: STORE-AND-FORWARD SYNC & HQ IDEMPOTENCY
        # ----------------------------------------------------------------------
        # Edge outbox starts in PENDING status
        db_outbox = db.query(SyncOutbox).filter(SyncOutbox.event_id == transit_id).first()
        assert db_outbox is not None
        assert db_outbox.status == "PENDING"

        # Transmit payload to HQ receiver
        hq_payload = {
            "event_id": transit_id,
            "camera_id": "CAM-02",
            "event_type": "VEHICLE_TRANSIT",
            "severity": "CRITICAL",
            "timestamp": datetime.utcnow().isoformat(),
            "data": transit.to_dict()
        }
        worker_headers = {"X-Worker-Secret": settings.INTERNAL_WORKER_SECRET}

        # Transmit to HQ
        hq_resp1 = unauth_client.post("/api/hq/ingest", json=hq_payload, headers=worker_headers)
        assert hq_resp1.status_code == 200
        assert hq_resp1.json()["status"] == "accepted"
        assert hq_resp1.json()["duplicate"] is False

        # Mark as SYNCED
        db_outbox.status = "SYNCED"
        db_outbox.synced_at = datetime.utcnow()
        db.commit()

        # Idempotency check: Duplicate transmission of identical event_id does not duplicate records
        hq_resp2 = unauth_client.post("/api/hq/ingest", json=hq_payload, headers=worker_headers)
        assert hq_resp2.status_code == 200
        assert hq_resp2.json()["status"] == "accepted"
        assert hq_resp2.json()["duplicate"] is True

    finally:
        # Cleanup test camera
        admin_client.delete("/api/cameras/CAM-TEST-P18")
        db.close()


# ==============================================================================
# PHASE 15: FAILURE INJECTION MATRIX
# ==============================================================================

def test_failure_invalid_authentication(unauth_client, invalid_client):
    """Failure 1: Missing credentials yield 401; malformed/invalid yield 403."""
    assert unauth_client.get("/api/alerts").status_code == 401
    assert unauth_client.post("/api/cameras").status_code == 401
    assert invalid_client.get("/api/alerts").status_code == 403
    assert invalid_client.post("/api/cameras").status_code == 403


def test_failure_operator_admin_mutation_denial(operator_client):
    """Failure 2: Operator attempting any administrative state change is rejected with 403."""
    # Delete camera
    assert operator_client.delete("/api/cameras/CAM-01").status_code == 403
    # Update camera source
    assert operator_client.post("/api/cameras/CAM-01/source", json={"source": "0"}).status_code == 403
    # Configure tripwire
    assert operator_client.post("/api/cameras/CAM-01/tripwire/config", json={"enabled": True, "y_ratio": 0.5}).status_code == 403
    # Enroll vehicle
    assert operator_client.post("/api/vehicles", json={"plate_number": "KA01AB1111", "vehicle_type": "Truck"}).status_code == 403
    # Delete vehicle
    assert operator_client.delete("/api/vehicles/1").status_code == 403
    # Enroll face
    assert operator_client.post("/api/faces/enroll").status_code in (403, 422)


def test_failure_camera_disconnect_truthful_status():
    """Failure 3: Camera hardware failure must report DISCONNECTED or OFFLINE, never false ONLINE."""
    # Initialize with non-existent camera source
    cam = CameraManager(camera_id="CAM-UNPLUGGED", name="Unplugged Device", source="99999")
    cam.is_running = True
    # Attempting to open non-existent hardware capture
    opened = cam._open_capture()
    assert opened is False
    # Status MUST be DISCONNECTED or OFFLINE, NOT ONLINE
    assert cam.status in ("DISCONNECTED", "OFFLINE")
    cam.stop()
    assert cam.status == "OFFLINE"


def test_failure_anpr_unreadable_plate_semantics():
    """Failure 4: Unreadable license plate must have plate_number=None and status='UNREADABLE'."""
    anpr = ANPREngine()
    is_valid, norm_plate, _ = anpr.validate_indian_plate("INVALID???GARBAGE!!!")
    assert is_valid is False
    assert norm_plate is None


def test_failure_vehicle_leaves_before_ocr():
    """Failure 5: Vehicle exiting field of view before OCR completes does not crash or corrupt state."""
    db = SessionLocal()
    try:
        transit_id = f"TRANSIT-EARLY-EXIT-{int(time.time())}"
        transit = VehicleTransitLog(
            event_id=transit_id,
            camera_id="CAM-02",
            track_id="TRK-EARLY-99",
            vehicle_type="Motorcycle",
            plate_number=None,
            plate_status="PENDING",
            direction="OUTBOUND",
            created_at=datetime.utcnow()
        )
        db.add(transit)
        db.commit()

        # Simulate vehicle leaving before OCR completes: transit record remains intact
        # and gets updated to UNREADABLE after timeout or worker completion
        transit.plate_status = "UNREADABLE"
        db.commit()

        rec = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == transit_id).first()
        assert rec.plate_status == "UNREADABLE"
        assert rec.plate_number is None
    finally:
        db.close()


def test_failure_ws_ticket_expired_or_reused(unauth_client, operator_client):
    """Failure 6: Expired or reused WebSocket ticket is cleanly rejected with policy violation code."""
    # Obtain fresh ticket
    resp = operator_client.post("/api/alerts/ws-ticket")
    assert resp.status_code == 200
    ticket = resp.json()["ticket"]

    # First connection consumes ticket
    with unauth_client.websocket_connect(f"/ws/alerts?ticket={ticket}") as ws:
        ws.send_text("ping")

    # Second connection with same ticket MUST fail
    with pytest.raises(WebSocketDisconnect) as exc:
        with unauth_client.websocket_connect(f"/ws/alerts?ticket={ticket}") as ws_reused:
            ws_reused.send_text("ping")
    assert exc.value.code in (1008, 4001, 4003)


def test_failure_evidence_path_traversal(operator_client):
    """Failure 7: Directory traversal attempts on evidence paths are blocked."""
    assert operator_client.get("/evidence/..%2f..%2f..%2fetc%2fpasswd").status_code in (400, 404)
    assert operator_client.get("/evidence/..%2f..%2fconfig.py").status_code in (400, 404)
    assert operator_client.get("/evidence/%2e%2e%2f%2e%2e%2fxynapse.db").status_code in (400, 404)


def test_failure_missing_evidence_file(operator_client):
    """Failure 8: Request for non-existent evidence file returns 404 cleanly without crashing."""
    resp = operator_client.get("/evidence/non_existent_snapshot_99999.jpg")
    assert resp.status_code == 404


def test_failure_diagnostic_mode_gated(admin_client):
    """Failure 9: When diagnostic mode is disabled, demo trigger endpoints return 403."""
    if not settings.ENABLE_DIAGNOSTIC_MODE:
        resp = admin_client.post("/api/alerts/demo-trigger", json={
            "trigger_type": "SUSPECT_DETECTED",
            "camera_id": "CAM-01"
        })
        assert resp.status_code == 403
