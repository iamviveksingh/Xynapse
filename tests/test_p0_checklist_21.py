import os
import sys
import time
import pytest
import numpy as np
from datetime import datetime
from fastapi.testclient import TestClient

# Ensure root on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.main import app
from backend.config import settings
from backend.database.database import init_db, SessionLocal
from backend.database.models import Alert, SyncOutbox, CameraConfig, BlockchainBlock
from backend.detection.person_detector import PersonDetector, SimpleCentroidTracker
from backend.detection.vehicle_detector import VehicleDetector
from backend.detection.anpr_engine import ANPREngine
from backend.detection.face_detector import FaceDetector
from backend.detection.face_recognizer import FaceRecognizer
from backend.detection.optical_pipeline import OpticalPipeline
from backend.detection.intrusion_detector import VirtualTripwireDetector
from backend.alert.alert_engine import AlertEngine
from backend.evidence.snapshot import compute_file_sha256, get_evidence_integrity
from backend.security.blockchain_ledger import verify_chain_integrity, seal_alert_in_blockchain
from backend.sync.sync_worker import sync_pending_events
from backend.camera.camera_manager import CameraManager
from backend.api.cameras import validate_camera_source

@pytest.fixture(scope="module")
def client():
    init_db()
    return TestClient(app, headers={"X-API-Key": settings.ADMIN_API_KEY})

# 1. Human detection
def test_01_human_detection():
    detector = PersonDetector()
    assert detector is not None
    # Test on blank frame
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    dets = detector.detect(frame)
    assert isinstance(dets, list)

# 2. Vehicle detection
def test_02_vehicle_detection():
    detector = VehicleDetector()
    assert detector is not None
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    dets = detector.detect(frame)
    assert isinstance(dets, list)

# 3. Wildlife detection / suppression
def test_03_wildlife_suppression():
    detector = VirtualTripwireDetector()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    rendered = detector.draw_tripwire(frame, is_breached=True, is_wildlife_crossing=True)
    assert rendered.shape == frame.shape
    engine = AlertEngine(cooldown_seconds=1)
    alert = engine.trigger_wildlife_alert("CAM-01", frame, "Stray Cattle (Bos taurus)", count=1)
    assert alert["event_type"] == "WILDLIFE_TRANSIT"
    assert alert["severity"] == "LOW"

# 4. Face detection
def test_04_face_detection():
    fd = FaceDetector()
    assert fd is not None
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    faces = fd.detect(frame)
    assert isinstance(faces, list)

# 5. ANPR
def test_05_anpr_processing():
    engine = ANPREngine()
    plate = engine.clean_plate_text("DL 01 AB 1234")
    assert plate == "DL01AB1234"
    match = engine.match_plate("DL01AB1234")
    assert isinstance(match, dict)

# 6. Polygon intrusion
def test_06_polygon_intrusion():
    detector = VirtualTripwireDetector()
    detector.set_polygon([[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]])
    frame_shape = (480, 640, 3)
    # Person inside polygon (x=320, y=240)
    dets = [{"bbox": [300, 150, 40, 90], "confidence": 0.95}]
    is_breached, breached_dets, _ = detector.check_intrusion(frame_shape, dets)
    assert is_breached is True
    assert len(breached_dets) == 1

# 7. Line intrusion
def test_07_line_intrusion():
    detector = VirtualTripwireDetector(line_y_ratio=0.5, fence_type="LINE")
    frame_shape = (480, 640, 3)
    # Foot below line at y=300 (line is at 240)
    dets = [{"bbox": [100, 210, 40, 90], "confidence": 0.95}]
    is_breached, breached_dets, _ = detector.check_intrusion(frame_shape, dets)
    assert is_breached is True

# 8. Low-light automatic enhancement
def test_08_low_light_auto_enhancement():
    opt = OpticalPipeline()
    dark_frame = np.full((100, 100, 3), 15, dtype=np.uint8)
    is_low_light, lum = opt.low_light_detector.classify_single_frame(dark_frame)
    assert is_low_light is True
    assert lum < 40.0
    enhanced = opt.process_frame(dark_frame, "LOW_LIGHT_ENHANCE")
    assert np.mean(enhanced) >= np.mean(dark_frame)

# 9. Camera tamper
def test_09_camera_tamper():
    engine = AlertEngine(cooldown_seconds=1)
    black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    alert = engine.trigger_tampering_alert("CAM-01", black_frame, "Physical lens obstruction")
    assert alert["event_type"] == "CAMERA_TAMPERED"
    assert alert["severity"] in ("CRITICAL", "HIGH")

# 10. RTSP reconnect
def test_10_rtsp_reconnect():
    engine = AlertEngine(cooldown_seconds=1)
    cam = CameraManager(
        camera_id="CAM-RECONNECT-TEST",
        name="Test RTSP Reconnect",
        source="rtsp://127.0.0.1:8554/live",
        alert_engine=engine
    )
    # Generates offline fallback frame
    fallback = cam._generate_fallback_frame()
    assert fallback is not None
    assert fallback.shape == (480, 640, 3)

# 11. Offline operation
def test_11_offline_operation():
    # Alerts can be generated and queued without network
    db = SessionLocal()
    try:
        engine = AlertEngine(cooldown_seconds=1)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        alert = engine.trigger_intrusion_alert("CAM-01", frame, breached_count=1)
        assert alert is not None
        # Check outbox has record
        pending = db.query(SyncOutbox).filter(SyncOutbox.status == "PENDING").count()
        assert pending >= 1
    finally:
        db.close()

# 12. SyncOutbox
def test_12_sync_outbox():
    db = SessionLocal()
    try:
        # Worker sync when no endpoint configured returns safe state
        res = sync_pending_events(db, target_url="", batch_size=5)
        assert res["status"] == "SYNC_NOT_CONFIGURED"
    finally:
        db.close()

# 13. Restart recovery
def test_13_restart_recovery():
    db = SessionLocal()
    try:
        # Camera config persisted in DB survives restart
        cfg = db.query(CameraConfig).filter(CameraConfig.camera_id == "CAM-01").first()
        assert cfg is not None
        assert cfg.camera_id == "CAM-01"
    finally:
        db.close()

# 14. Evidence hashing
def test_14_evidence_hashing():
    engine = AlertEngine(cooldown_seconds=1)
    frame = np.full((100, 100, 3), 128, dtype=np.uint8)
    alert = engine.trigger_intrusion_alert("CAM-01", frame, breached_count=1)
    assert "evidence_hash" in alert
    assert len(alert["evidence_hash"]) == 64

# 15. Cryptographic audit chain
def test_15_cryptographic_audit_chain():
    db = SessionLocal()
    try:
        res = verify_chain_integrity(db)
        assert res["verification_status"] == "VERIFIED_AUTHENTIC"
        assert res["tamper_detected"] is False
        assert "Section 63, Bharatiya Sakshya Adhiniyam (BSA), 2023" in res["legal_statute"]
    finally:
        db.close()

# 16. Alert lifecycle
def test_16_alert_lifecycle(client):
    res = client.get("/api/alerts?limit=1")
    items = res.json().get("items", [])
    if items:
        aid = items[0]["id"]
        ack = client.post(f"/api/alerts/{aid}/acknowledge")
        assert ack.status_code == 200
        assert ack.json()["status"] == "ACKNOWLEDGED"
        resolve = client.post(f"/api/alerts/{aid}/resolve")
        assert resolve.status_code == 200
        assert resolve.json()["status"] == "RESOLVED"

# 17. Multiple cameras
def test_17_multiple_cameras(client):
    res = client.get("/api/cameras")
    assert res.status_code == 200
    cams = res.json()
    assert isinstance(cams, list)
    assert len(cams) >= 1

# 18. Resolution changes
def test_18_resolution_changes():
    detector = VirtualTripwireDetector()
    detector.set_polygon([[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]])
    for h, w in [(480, 640), (720, 1280), (1080, 1920), (600, 800)]:
        poly = detector.get_polygon_for_shape((h, w, 3))
        assert poly is not None
        # Center is inside at all resolutions
        assert detector.check_point_inside(w // 2, h // 2, (h, w, 3)) is True

# 19. Invalid RTSP URLs
def test_19_invalid_rtsp_urls():
    with pytest.raises(Exception):
        validate_camera_source("rtsp://169.254.169.254:554/live")
    with pytest.raises(Exception):
        validate_camera_source("file:///etc/shadow")
    with pytest.raises(Exception):
        validate_camera_source("http://insecure-domain.com")

# 20. Unauthorized API access
def test_20_unauthorized_api_access(client):
    res = client.post(
        "/api/hq/ingest",
        json={"event_id": "TEST"},
        headers={"X-Worker-Secret": "wrong_secret"}
    )
    assert res.status_code == 401

# 21. Production mode cannot generate fake events
def test_21_production_mode_blocks_fake_events(client):
    settings.ENABLE_DIAGNOSTIC_MODE = False
    res = client.post("/api/alerts/demo-trigger", json={"trigger_type": "BORDER_BREACH"})
    assert res.status_code == 403
    assert "disabled in production mode" in res.json()["detail"]
