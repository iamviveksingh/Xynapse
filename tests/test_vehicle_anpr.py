import os
import pytest
import numpy as np
import cv2
from fastapi.testclient import TestClient

from backend.main import app
from backend.detection.vehicle_detector import VehicleDetector
from backend.detection.anpr_engine import ANPREngine
from backend.alert.alert_engine import AlertEngine
from backend.database.database import SessionLocal, init_db
from backend.database.models import VehicleProfile, Alert


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    yield


def test_vehicle_detector_initialization():
    detector = VehicleDetector()
    assert detector._is_initialized is True
    assert detector.model is not None


def test_vehicle_detector_synthetic_frame():
    detector = VehicleDetector()
    dummy = np.zeros((480, 640, 3), dtype=np.uint8)
    detections = detector.detect(dummy)
    assert isinstance(detections, list)
    # Drawing on empty frame should succeed
    annotated = detector.draw_annotations(dummy, detections)
    assert annotated.shape == dummy.shape


def test_anpr_engine_plate_cleaning_and_matching():
    engine = ANPREngine()
    assert engine.clean_plate_text("dl-01 ab 1234") == "DL01AB1234"
    assert engine.clean_plate_text("jk 02c 5678#") == "JK02C5678"

    # Seed test vehicle profile
    db = SessionLocal()
    db.query(VehicleProfile).filter(VehicleProfile.plate_number == "TEST9999").delete(synchronize_session=False)
    db.commit()

    vp = VehicleProfile(
        plate_number="TEST9999",
        vehicle_type="Truck",
        owner_name="Test Transport",
        status="SUSPECT_STOLEN",
        notes="Border Smuggling Red Notice"
    )
    db.add(vp)
    db.commit()

    engine.reload_profiles()

    # Match plate
    match_res = engine.match_plate("TEST 9999")
    assert match_res["matched"] is True
    assert match_res["status"] == "SUSPECT_STOLEN"
    assert match_res["plate"] == "TEST9999"

    # Clean up
    db.delete(vp)
    db.commit()
    db.close()


def test_anpr_ocr_on_synthetic_plate():
    engine = ANPREngine()
    # Create high-contrast synthetic plate: white background, bold black text
    plate_img = np.ones((70, 240, 3), dtype=np.uint8) * 255
    cv2.putText(plate_img, "ARMY9988", (15, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 3, cv2.LINE_AA)

    detected = engine.extract_plate_from_crop(plate_img)
    assert detected is not None
    assert "ARMY" in detected or "9988" in detected


def test_vehicle_and_stolen_alerts():
    engine = AlertEngine(cooldown_seconds=1)
    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)

    # 1. Stolen vehicle alert
    alert1 = engine.trigger_stolen_vehicle_alert(
        camera_id="CAM-TEST",
        frame=dummy_frame,
        plate_number="DL01AB1234",
        vehicle_type="Truck",
        owner_name="Wanted Smuggler",
        notes="Red Notice"
    )
    assert alert1 is not None
    assert alert1["event_type"] == "SUSPECT_VEHICLE_INTERCEPT"
    assert alert1["severity"] == "CRITICAL"

    # 2. Civilian vehicle transit alert
    alert2 = engine.trigger_vehicle_alert(
        camera_id="CAM-TEST",
        frame=dummy_frame,
        vehicle_type="Car",
        plate_number="HR26DK8888"
    )
    assert alert2 is not None
    assert alert2["event_type"] == "VEHICLE_DETECTED"
    assert alert2["severity"] == "LOW"


def test_vehicles_api_endpoints():
    from backend.config import settings
    client = TestClient(app, headers={"X-API-Key": settings.ADMIN_API_KEY})

    # 1. List vehicles
    res = client.get("/api/vehicles")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # 2. Seed defaults (allowed when diagnostic mode enabled)
    from backend.config import settings
    orig_mode = settings.ENABLE_DIAGNOSTIC_MODE
    settings.ENABLE_DIAGNOSTIC_MODE = True
    try:
        res_seed = client.post("/api/vehicles/seed-defaults")
        assert res_seed.status_code == 200
    finally:
        settings.ENABLE_DIAGNOSTIC_MODE = orig_mode

    # 3. Get stats
    res_stats = client.get("/api/vehicles/stats")
    assert res_stats.status_code == 200
    data = res_stats.json()
    assert "total" in data
    assert "military_count" in data
    assert "stolen_count" in data

    # 4. Surveillance mode switch
    res_mode = client.post("/api/cameras/CAM-01/surveillance-mode", json={"mode": "CHECKPOST"})
    assert res_mode.status_code == 200
    assert res_mode.json()["surveillance_mode"] == "CHECKPOST"

    res_get_mode = client.get("/api/cameras/CAM-01/surveillance-mode")
    assert res_get_mode.status_code == 200
    assert res_get_mode.json()["surveillance_mode"] == "CHECKPOST"

    # Reset back to default PERIMETER
    client.post("/api/cameras/CAM-01/surveillance-mode", json={"mode": "PERIMETER"})


def test_plate_candidate_localization_synthetic():
    """Verify that classical CV localizer extracts candidate plate regions from vehicle image."""
    engine = ANPREngine()

    # Create synthetic vehicle crop (dark blue car body 240x320)
    veh_crop = np.zeros((240, 320, 3), dtype=np.uint8)
    veh_crop[:] = (120, 40, 20)  # Dark body

    # Draw rectangular white license plate in lower bumper zone (aspect ratio ~4.0)
    # y from 160 to 195 (h=35), x from 80 to 240 (w=160)
    cv2.rectangle(veh_crop, (80, 160), (240, 195), (255, 255, 255), -1)
    cv2.putText(veh_crop, "HR26DK8888", (88, 187), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 2, cv2.LINE_AA)

    # Localize candidate crops
    candidates = engine.localize_plate_candidates(veh_crop)
    assert len(candidates) > 0
    assert isinstance(candidates, list)

    # Process vehicle through ANPR pipeline
    dets = [{"bbox": [10, 10, 320, 240], "confidence": 0.92, "class_id": 2, "label": "car"}]
    full_frame = np.zeros((300, 350, 3), dtype=np.uint8)
    full_frame[10:250, 10:330] = veh_crop

    processed = engine.process_vehicles(full_frame, dets)
    assert len(processed) == 1
    # Check that plate was recognized or extracted without crash
    p_num = processed[0].get("plate_number")
    assert p_num is not None
    assert "HR26" in p_num or "8888" in p_num or len(p_num) >= 6


def test_plate_localization_fallback_and_no_plate():
    """Verify that when no plate is present, system safely falls back without fabricating numbers."""
    engine = ANPREngine()

    # Empty / featureless vehicle crop (no plate)
    plain_car = np.ones((200, 250, 3), dtype=np.uint8) * 60

    candidates = engine.localize_plate_candidates(plain_car)
    # Should safely return fallback bumper candidate without crashing
    assert len(candidates) > 0

    dets = [{"bbox": [20, 20, 250, 200], "confidence": 0.88, "class_id": 2, "label": "car"}]
    frame = np.zeros((300, 300, 3), dtype=np.uint8)
    frame[20:220, 20:270] = plain_car

    processed = engine.process_vehicles(frame, dets)
    assert len(processed) == 1
    # Must NOT fabricate a plate number
    assert processed[0]["plate_number"] is None
    assert processed[0]["plate_status"] == "CIVILIAN"

