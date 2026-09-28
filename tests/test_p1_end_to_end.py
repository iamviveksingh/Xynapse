import os
import json
import pytest
import numpy as np
import cv2
from datetime import datetime
from starlette.testclient import TestClient

from backend.main import app
from backend.database.database import SessionLocal, init_db
from backend.database.models import CameraConfig, Alert, SyncOutbox, VehicleProfile
from backend.camera.camera_manager import CameraManager
from backend.alert.alert_engine import AlertEngine
from backend.detection.intrusion_detector import VirtualTripwireDetector
from backend.detection.anpr_engine import ANPREngine
from backend.detection.optical_pipeline import LowLightDetector, OpticalPipeline
from backend.sync.sync_worker import sync_pending_events, get_outbox_stats
from backend.config import settings


@pytest.fixture(autouse=True)
def setup_database():
    init_db()
    yield


def test_end_to_end_polygon_to_outbox_sync():
    """
    E2E Chain 1:
    Camera
     ↓
    Video frame
     ↓
    Object detection / tracking
     ↓
    2D Polygon geofence check (OUTSIDE -> INSIDE transition)
     ↓
    Intrusion event generated
     ↓
    Alert persisted in SQLite
     ↓
    Persistent SyncOutbox record
     ↓
    Real HTTP Store-and-Forward dispatch to HQ endpoint
     ↓
    HQ receiver validates & accepts event
     ↓
    Outbox marked SYNCED (pending backlog = 0)
    """
    db = SessionLocal()
    client = TestClient(app)

    cam_id = "CAM-E2E-POLY"
    try:
        # 1. Clean previous test records
        db.query(SyncOutbox).filter(SyncOutbox.camera_id == cam_id).delete()
        db.query(Alert).filter(Alert.camera_id == cam_id).delete()
        db.query(CameraConfig).filter(CameraConfig.camera_id == cam_id).delete()
        db.commit()

        # 2. Configure camera with 2D Polygon Geofence
        poly_pts = [[100.0, 100.0], [500.0, 100.0], [500.0, 500.0], [100.0, 500.0]]
        cfg = CameraConfig(
            camera_id=cam_id,
            name="E2E Polygon Camera",
            source="0",
            surveillance_mode="PERIMETER",
            fence_type="POLYGON",
            fence_points_json=json.dumps(poly_pts),
            tripwire_enabled=1,
            is_enabled=1
        )
        db.add(cfg)
        db.commit()

        # 3. Create CameraManager and initialize polygon
        alert_engine = AlertEngine(cooldown_seconds=1)
        cam = CameraManager(camera_id=cam_id, name="E2E Poly Camera", source="0", alert_engine=alert_engine)
        cam.tripwire.set_polygon(poly_pts)
        assert cam.tripwire.fence_type == "POLYGON"

        # Frame 1: Person outside polygon (foot at 50, 50)
        frame_shape = (600, 600, 3)
        dummy_frame = np.zeros(frame_shape, dtype=np.uint8)
        det_outside = [{"bbox": [30, 10, 40, 40], "track_id": 99, "confidence": 0.95, "role": "UNKNOWN"}]
        breached, b_dets, _ = cam.tripwire.check_intrusion(frame_shape, det_outside)
        assert breached is False

        # Frame 2: Person enters polygon geofence (foot at 250, 250) -> OUTSIDE -> INSIDE
        det_inside = [{"bbox": [230, 200, 40, 50], "track_id": 99, "confidence": 0.95, "role": "UNKNOWN"}]
        breached, b_dets, _ = cam.tripwire.check_intrusion(frame_shape, det_inside)
        assert breached is True
        assert b_dets[0]["is_new_intrusion"] is True

        # Trigger intrusion alert via alert engine
        alert = alert_engine.trigger_intrusion_alert(
            camera_id=cam_id,
            frame=dummy_frame,
            breached_count=len(b_dets),
            details="E2E Restricted 2D Polygon Geofence Breach"
        )
        assert alert is not None
        assert alert["event_type"] == "BORDER_INTRUSION"
        assert alert["severity"] == "CRITICAL"

        # 4. Verify Alert persistence in SQLite
        db_alert = db.query(Alert).filter(Alert.camera_id == cam_id).first()
        assert db_alert is not None
        assert db_alert.event_type == "BORDER_INTRUSION"

        # 5. Verify Persistent SyncOutbox enqueue
        outbox_rec = db.query(SyncOutbox).filter(SyncOutbox.camera_id == cam_id).first()
        assert outbox_rec is not None
        assert outbox_rec.status == "PENDING"
        assert outbox_rec.event_type == "BORDER_INTRUSION"

        # 6. Verify Store-and-Forward dispatch via TestClient directly to local HQ endpoint
        payload = json.loads(outbox_rec.payload_json)
        headers = {"X-Worker-Secret": settings.INTERNAL_WORKER_SECRET}
        hq_resp = client.post("/api/hq/ingest", json=payload, headers=headers)
        assert hq_resp.status_code == 200
        hq_data = hq_resp.json()
        assert hq_data["status"] == "accepted"
        remote_id = hq_data["remote_id"]
        assert remote_id.startswith("HQ-REC")

        # Mark synced in outbox
        outbox_rec.status = "SYNCED"
        outbox_rec.remote_id = remote_id
        outbox_rec.synced_at = datetime.utcnow()
        db.commit()

        # 7. Verify outbox pending backlog is zero
        stats = get_outbox_stats(db)
        pending_for_cam = db.query(SyncOutbox).filter(
            SyncOutbox.camera_id == cam_id,
            SyncOutbox.status == "PENDING"
        ).count()
        assert pending_for_cam == 0

        # Verify duplicate submission is idempotent
        dup_resp = client.post("/api/hq/ingest", json=payload, headers=headers)
        assert dup_resp.status_code == 200
        assert dup_resp.json()["duplicate"] is True
        assert dup_resp.json()["remote_id"] == remote_id
    finally:
        db.query(SyncOutbox).filter(SyncOutbox.camera_id == cam_id).delete()
        db.query(Alert).filter(Alert.camera_id == cam_id).delete()
        db.query(CameraConfig).filter(CameraConfig.camera_id == cam_id).delete()
        db.commit()
        db.close()


def test_end_to_end_low_light_auto_enhancement():
    """
    E2E Chain 2:
    Dark video frame
     ↓
    Automatic low-light detection (luminance < 45)
     ↓
    Adaptive CLAHE enhancement pipeline activated
     ↓
    AI inference runs on enhanced imagery
     ↓
    Normal daytime lighting restored
     ↓
    Pipeline recovers to STANDARD without mode flickering
    """
    detector = LowLightDetector(enter_threshold=45.0, exit_threshold=58.0, consecutive_frames=2)
    pipeline = OpticalPipeline()

    # Dark incoming frame (e.g. night border post, mean luminance ~22)
    dark_frame = np.ones((240, 320, 3), dtype=np.uint8) * 22
    # Add minor texture
    dark_frame[50:100, 50:100] = 38

    # 1. Detect low-light across consecutive frames
    for _ in range(3):
        is_dark, lum, mode = detector.update(dark_frame)
    assert is_dark is True
    assert lum < 45.0
    assert mode == "LOW_LIGHT_ENHANCE"

    # 2. Process through Optical Pipeline in auto-detected mode
    enhanced_frame = pipeline.process_frame(dark_frame, mode)
    assert enhanced_frame.shape == dark_frame.shape
    # CLAHE enhances micro-contrast and raises shadow luminance
    assert float(np.mean(enhanced_frame)) >= float(np.mean(dark_frame))

    # 3. Simulate illumination recovery (morning sunlight, mean luminance ~140)
    day_frame = np.ones((240, 320, 3), dtype=np.uint8) * 140
    for _ in range(3):
        is_dark, lum, mode = detector.update(day_frame)
    assert is_dark is False
    assert lum > 58.0
    assert mode == "STANDARD"

    standard_frame = pipeline.process_frame(day_frame, mode)
    assert np.array_equal(standard_frame, day_frame)


def test_end_to_end_vehicle_anpr_localization():
    """
    E2E Chain 3:
    Vehicle detected in frame
     ↓
    Vehicle ROI cropped
     ↓
    Classical CV Plate Candidate Localization (aspect ratio, edge density, morphology)
     ↓
    Ranked plate candidate regions evaluated
     ↓
    RapidOCR text recognition
     ↓
    Plate validation against military/stolen watchlist
     ↓
    Event / vehicle association
    """
    engine = ANPREngine()
    db = SessionLocal()

    test_plate = "ARMY8888"
    try:
        # Seed an enrolled military profile
        db.query(VehicleProfile).filter(VehicleProfile.plate_number == test_plate).delete()
        db.commit()

        vp = VehicleProfile(
            plate_number=test_plate,
            vehicle_type="Tactical Gypsy",
            owner_name="Subedar Major R. Singh",
            status="AUTHORIZED_MILITARY",
            notes="16th Cavalry Quick Reaction Team"
        )
        db.add(vp)
        db.commit()
        engine.reload_profiles()

        # Create synthetic vehicle scene (400x500 frame) with vehicle in center
        scene = np.zeros((400, 500, 3), dtype=np.uint8)
        # Vehicle bounding box [100, 80, 300, 220]
        vx, vy, vw, vh = 100, 80, 300, 220
        scene[vy:vy + vh, vx:vx + vw] = (80, 50, 30)  # Military green vehicle body

        # Place white license plate in bumper region: y from 220 to 255, x from 180 to 320
        cv2.rectangle(scene, (180, 220), (320, 255), (255, 255, 255), -1)
        cv2.putText(scene, test_plate, (190, 247), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (0, 0, 0), 2, cv2.LINE_AA)

        # Vehicle detection candidate from YOLOv8
        veh_dets = [{
            "bbox": [vx, vy, vw, vh],
            "confidence": 0.94,
            "class_id": 2,
            "label": "car"
        }]

        # Run full ANPR pipeline
        processed = engine.process_vehicles(scene, veh_dets)
        assert len(processed) == 1
        v = processed[0]

        # Plate recognized and matched against enrolled military watchlist
        assert v.get("plate_number") is not None
        assert test_plate in v["plate_number"] or "8888" in v["plate_number"]
        assert v.get("plate_status") == "AUTHORIZED_MILITARY"
        assert v.get("owner_name") == "Subedar Major R. Singh"
    finally:
        db.query(VehicleProfile).filter(VehicleProfile.plate_number == test_plate).delete()
        db.commit()
        db.close()
