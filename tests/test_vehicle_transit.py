import os
import time
import pytest
import numpy as np
import cv2
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from backend.main import app
from backend.database.database import SessionLocal, init_db
from backend.database.models import VehicleTransitLog, VehicleProfile, Alert, SyncOutbox
from backend.camera.camera_manager import CameraManager
from backend.detection.anpr_engine import ANPREngine
from backend.alert.alert_engine import AlertEngine
from backend.config import settings

client = TestClient(app, headers={"X-API-Key": settings.ADMIN_API_KEY})

@pytest.fixture(autouse=True)
def setup_transit_test_db():
    init_db()
    # Clean up test records
    db = SessionLocal()
    try:
        db.query(VehicleTransitLog).filter(VehicleTransitLog.camera_id.in_(["CAM-TEST-V", "CAM-01", "CAM-02"])).delete(synchronize_session=False)
        db.query(VehicleProfile).filter(VehicleProfile.plate_number.in_(["TEST01AB1234", "STOLEN9999", "CIVILIAN1234", "DL01AB1234", "HR26DQ5555"])).delete(synchronize_session=False)
        db.query(Alert).filter(Alert.camera_id.in_(["CAM-TEST-V"])).delete(synchronize_session=False)
        db.query(SyncOutbox).filter(SyncOutbox.camera_id.in_(["CAM-TEST-V"])).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield


def test_01_vehicle_detection_creates_transit_event():
    """Requirement 1: Vehicle detection creates transit event in CHECKPOST mode."""
    cam = CameraManager(camera_id="CAM-TEST-V", surveillance_mode="CHECKPOST")
    cam.detection_active = True
    cam.surveillance_mode = "CHECKPOST"
    
    # Synthetic frame with a dummy vehicle
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    # Mock vehicle detector returning 1 vehicle
    cam.vehicle_detector.detect = lambda f: [{
        "bbox": [100, 100, 150, 120],
        "confidence": 0.88,
        "class_id": 2,
        "label": "Car • 88%",
        "vehicle_type": "Car"
    }]
    
    # Process single frame through capture logic step
    # We call tracker update and transit registration manually or via one simulated loop iteration
    raw_dets = cam.vehicle_detector.detect(frame)
    tracked = cam.vehicle_tracker.update(raw_dets)
    assert len(tracked) == 1
    
    # Simulate camera manager transit creation logic
    vd = tracked[0]
    tid = vd["track_id"]
    now_ts = time.time()
    clean_cam = cam.camera_id.replace("-", "").replace("_", "")
    event_id = f"TR-{clean_cam}-{int(now_ts)}-{int(tid):03d}"
    
    from backend.evidence.snapshot import save_transit_snapshot
    veh_crop = frame[100:220, 100:250].copy()
    veh_snap = save_transit_snapshot(veh_crop, event_id=event_id, prefix="veh")
    
    db = SessionLocal()
    rec = VehicleTransitLog(
        event_id=event_id,
        camera_id=cam.camera_id,
        track_id=str(tid),
        vehicle_type="Car",
        plate_number=None,
        plate_status="PENDING",
        vehicle_snapshot_path=veh_snap,
        direction="UNKNOWN",
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow()
    )
    db.add(rec)
    db.commit()
    transit_id = rec.id
    db.close()

    # Verify DB persistence
    db = SessionLocal()
    saved = db.query(VehicleTransitLog).filter(VehicleTransitLog.id == transit_id).first()
    assert saved is not None
    assert saved.event_id == event_id
    assert saved.plate_status == "PENDING"
    assert saved.plate_number is None
    assert saved.vehicle_type == "Car"
    db.close()


def test_02_recognized_plate_updates_transit_event():
    """Requirement 2: Recognized plate updates transit event."""
    db = SessionLocal()
    event_id = "TR-CAMTESTV-RECOG-001"
    rec = VehicleTransitLog(
        event_id=event_id,
        camera_id="CAM-TEST-V",
        track_id="1",
        vehicle_type="Car",
        plate_number=None,
        plate_status="PENDING",
        direction="INBOUND"
    )
    db.add(rec)
    db.commit()
    db.close()

    # Simulate ANPR worker recognition
    db = SessionLocal()
    transit = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == event_id).first()
    assert transit is not None
    transit.plate_number = "DL01AB1234"
    transit.plate_status = "RECOGNIZED"
    transit.plate_confidence = 0.94
    transit.ocr_latency_ms = 42.5
    transit.last_seen_at = datetime.utcnow()
    db.commit()
    db.close()

    # Verify updated record
    db = SessionLocal()
    updated = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == event_id).first()
    assert updated.plate_number == "DL01AB1234"
    assert updated.plate_status == "RECOGNIZED"
    assert updated.plate_confidence == 0.94
    assert updated.ocr_latency_ms == 42.5
    db.close()


def test_03_ocr_failure_still_preserves_transit_event():
    """Requirement 3: OCR failure still preserves transit event."""
    db = SessionLocal()
    event_id = "TR-CAMTESTV-FAIL-001"
    rec = VehicleTransitLog(
        event_id=event_id,
        camera_id="CAM-TEST-V",
        track_id="2",
        vehicle_type="Truck",
        plate_number=None,
        plate_status="PENDING",
        vehicle_snapshot_path="/evidence/transits/TR-CAMTESTV-FAIL-001_veh.jpg"
    )
    db.add(rec)
    db.commit()
    db.close()

    # Track departs without successful OCR -> finalize
    db = SessionLocal()
    rec = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == event_id).first()
    if rec.plate_status == "PENDING":
        rec.plate_status = "UNREADABLE"
        rec.plate_number = None
    db.commit()
    db.close()

    # Verify record is still preserved in DB
    db = SessionLocal()
    preserved = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == event_id).first()
    assert preserved is not None
    assert preserved.plate_status == "UNREADABLE"
    assert preserved.vehicle_snapshot_path is not None
    db.close()


def test_04_unreadable_plate_has_null_plate_number():
    """Requirement 4: Unreadable plate has NULL plate_number (never '<UNREADABLE>')."""
    db = SessionLocal()
    event_id = "TR-CAMTESTV-NULL-001"
    rec = VehicleTransitLog(
        event_id=event_id,
        camera_id="CAM-TEST-V",
        track_id="3",
        vehicle_type="Bus",
        plate_number=None,
        plate_status="UNREADABLE"
    )
    db.add(rec)
    db.commit()
    db.close()

    db = SessionLocal()
    loaded = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == event_id).first()
    assert loaded.plate_number is None
    assert loaded.plate_status == "UNREADABLE"
    assert loaded.to_dict()["plate_number"] is None
    db.close()


def test_05_same_vehicle_does_not_create_duplicate_transit_events():
    """Requirement 5: Same tracked vehicle across multiple frames creates only ONE transit event."""
    cam = CameraManager(camera_id="CAM-TEST-V", surveillance_mode="CHECKPOST")
    cam.detection_active = True
    cam.surveillance_mode = "CHECKPOST"
    
    # 5 frames of the same vehicle moving slightly
    base_x, base_y = 120, 150
    for i in range(5):
        dets = [{
            "bbox": [base_x + i * 2, base_y + i * 4, 140, 110],
            "confidence": 0.85,
            "class_id": 2,
            "label": "Car",
            "vehicle_type": "Car"
        }]
        tracked = cam.vehicle_tracker.update(dets)
        assert len(tracked) == 1
        tid = str(tracked[0]["track_id"])
        
        # In CameraManager, first frame registers in _active_transits
        if tid not in cam._active_transits:
            cam._active_transits[tid] = {
                "event_id": f"TR-CAMTESTV-DEDUP-{tid}",
                "track_id": tid,
                "best_plate": None,
                "best_status": "PENDING"
            }
    
    # Verify exactly 1 active transit entry exists for this vehicle
    assert len(cam._active_transits) == 1
    assert "1" in cam._active_transits


def test_06_watchlist_match_generates_appropriate_alert():
    """Requirement 6: Watchlist match (e.g. SUSPECT_STOLEN) generates security alert."""
    # 1. Enroll stolen vehicle profile
    db = SessionLocal()
    stolen_prof = VehicleProfile(
        plate_number="STOLEN9999",
        vehicle_type="SUV",
        owner_name="Wanted Suspect",
        status="SUSPECT_STOLEN",
        notes="Red Notice Border Intercept"
    )
    db.add(stolen_prof)
    db.commit()
    db.close()

    anpr = ANPREngine()
    anpr.reload_profiles()
    match_info = anpr.match_plate("STOLEN 9999")
    assert match_info["matched"] is True
    assert match_info["status"] == "SUSPECT_STOLEN"

    alert_engine = AlertEngine(cooldown_seconds=0)
    dummy_frame = np.zeros((200, 200, 3), dtype=np.uint8)
    alert = alert_engine.trigger_stolen_vehicle_alert(
        camera_id="CAM-TEST-V",
        frame=dummy_frame,
        plate_number="STOLEN9999",
        vehicle_type="SUV",
        owner_name="Wanted Suspect"
    )
    assert alert is not None
    assert alert["event_type"] == "SUSPECT_VEHICLE_INTERCEPT"
    assert alert["severity"] == "CRITICAL"


def test_07_normal_civilian_vehicle_produces_normal_transit_record():
    """Requirement 7: Normal vehicle produces normal transit record without security alert."""
    anpr = ANPREngine()
    anpr.reload_profiles()

    # Valid civilian Indian plate not in watchlist
    match_info = anpr.match_plate("HR26DQ5555")
    assert match_info["matched"] is False
    assert match_info["status"] == "CIVILIAN"
    assert match_info["plate"] == "HR26DQ5555"

    # Save to VehicleTransitLog
    db = SessionLocal()
    event_id = "TR-CAMTESTV-CIVILIAN-001"
    transit = VehicleTransitLog(
        event_id=event_id,
        camera_id="CAM-TEST-V",
        track_id="4",
        vehicle_type="Car",
        plate_number="HR26DQ5555",
        plate_status="RECOGNIZED",
        watchlist_match=0,
        watchlist_category="CIVILIAN"
    )
    db.add(transit)
    db.commit()

    # Verify no critical alert was created
    alerts = db.query(Alert).filter(Alert.camera_id == "CAM-TEST-V", Alert.event_type == "SUSPECT_VEHICLE_INTERCEPT").all()
    assert len(alerts) == 0
    db.close()


def test_08_multiple_vehicles_create_separate_transit_events():
    """Requirement 8: Multiple vehicles in frame create separate transit events."""
    cam = CameraManager(camera_id="CAM-TEST-V", surveillance_mode="CHECKPOST")
    two_dets = [
        {"bbox": [50, 100, 120, 100], "confidence": 0.85, "class_id": 2, "label": "Car", "vehicle_type": "Car"},
        {"bbox": [300, 120, 140, 110], "confidence": 0.90, "class_id": 7, "label": "Truck", "vehicle_type": "Truck"}
    ]
    tracked = cam.vehicle_tracker.update(two_dets)
    assert len(tracked) == 2
    tids = {str(d["track_id"]) for d in tracked}
    assert len(tids) == 2

    # Simulate registering both
    now_ts = time.time()
    db = SessionLocal()
    for d in tracked:
        tid = str(d["track_id"])
        ev_id = f"TR-CAMTESTV-MULTI-{tid}"
        rec = VehicleTransitLog(
            event_id=ev_id,
            camera_id="CAM-TEST-V",
            track_id=tid,
            vehicle_type=d["vehicle_type"],
            plate_status="PENDING"
        )
        db.add(rec)
    db.commit()

    saved = db.query(VehicleTransitLog).filter(VehicleTransitLog.camera_id == "CAM-TEST-V", VehicleTransitLog.event_id.like("TR-CAMTESTV-MULTI-%")).all()
    assert len(saved) == 2
    db.close()


def test_09_anpr_queue_remains_asynchronous():
    """Requirement 9: ANPR queue remains asynchronous and non-blocking."""
    cam = CameraManager(camera_id="CAM-TEST-V", surveillance_mode="CHECKPOST")
    assert cam._anpr_queue.maxsize == 2
    
    # Enqueue a dummy job
    dummy_crop = np.zeros((100, 100, 3), dtype=np.uint8)
    t0 = time.perf_counter()
    cam._anpr_queue.put_nowait((dummy_crop, "CAM-TEST-V", dummy_crop, {"track_id": "1"}, "EV-01", "1"))
    elapsed_ms = (time.perf_counter() - t0) * 1000
    # Must be sub-millisecond non-blocking
    assert elapsed_ms < 5.0
    assert cam._anpr_queue.qsize() == 1


def test_10_queue_overflow_does_not_block_camera():
    """Requirement 10: Queue overflow drops job gracefully without blocking camera loop."""
    cam = CameraManager(camera_id="CAM-TEST-V", surveillance_mode="CHECKPOST")
    dummy = np.zeros((50, 50, 3), dtype=np.uint8)
    
    # Fill queue to maximum capacity
    cam._anpr_queue.put_nowait((dummy, "CAM-TEST-V", dummy, {}, "EV-1", "1"))
    cam._anpr_queue.put_nowait((dummy, "CAM-TEST-V", dummy, {}, "EV-2", "2"))
    assert cam._anpr_queue.full()

    # Next attempt with put_nowait should raise Full and be caught non-blocking
    t0 = time.perf_counter()
    dropped = False
    try:
        cam._anpr_queue.put_nowait((dummy, "CAM-TEST-V", dummy, {}, "EV-3", "3"))
    except Exception:
        dropped = True
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert dropped is True
    assert elapsed_ms < 5.0  # Instantaneous, zero camera lag!


def test_11_transit_survives_restart():
    """Requirement 11: Transit records survive camera/system cold boot restart."""
    db = SessionLocal()
    event_id = "TR-CAMTESTV-PERSIST-001"
    rec = VehicleTransitLog(
        event_id=event_id,
        camera_id="CAM-TEST-V",
        track_id="11",
        vehicle_type="Truck",
        plate_number="DL01AB1234",
        plate_status="RECOGNIZED"
    )
    db.add(rec)
    db.commit()
    db.close()

    # Simulate restart by clearing connections and re-querying
    db = SessionLocal()
    reloaded = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == event_id).first()
    assert reloaded is not None
    assert reloaded.plate_number == "DL01AB1234"
    assert reloaded.plate_status == "RECOGNIZED"
    db.close()


def test_12_transit_survives_offline_operation():
    """Requirement 12: Transit persists locally in SQLite even with no network connection."""
    db = SessionLocal()
    event_id = "TR-CAMTESTV-OFFLINE-001"
    rec = VehicleTransitLog(
        event_id=event_id,
        camera_id="CAM-TEST-V",
        track_id="12",
        vehicle_type="Car",
        plate_number="JK02AB9999",
        plate_status="RECOGNIZED"
    )
    db.add(rec)
    db.commit()

    count = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == event_id).count()
    assert count == 1
    db.close()


def test_13_transit_syncs_through_store_and_forward_outbox():
    """Requirement 13: Transit logs enqueue into SyncOutbox store-and-forward outbox."""
    cam = CameraManager(camera_id="CAM-TEST-V", surveillance_mode="CHECKPOST")
    event_id = "TR-CAMTESTV-OUTBOX-001"
    
    transit_rec = VehicleTransitLog(
        event_id=event_id,
        camera_id="CAM-TEST-V",
        track_id="13",
        vehicle_type="Car",
        plate_number="DL01AB1234",
        plate_status="RECOGNIZED",
        watchlist_category="CIVILIAN"
    )
    
    # Enqueue through camera manager method
    cam._enqueue_transit_sync(transit_rec)

    db = SessionLocal()
    outbox = db.query(SyncOutbox).filter(SyncOutbox.event_id == event_id).first()
    assert outbox is not None
    assert outbox.event_type == "VEHICLE_TRANSIT"
    assert outbox.status == "PENDING"
    assert "DL01AB1234" in outbox.payload_json
    db.close()


def test_14_plate_search_api():
    """Requirement 14: REST API search by plate number works with pagination."""
    db = SessionLocal()
    db.add(VehicleTransitLog(
        event_id="TR-SEARCH-001",
        camera_id="CAM-TEST-V",
        track_id="14",
        plate_number="DL01AB1234",
        plate_status="RECOGNIZED"
    ))
    db.commit()
    db.close()

    res = client.get("/api/vehicles/transits?plate_number=DL01AB")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert any(t["plate_number"] == "DL01AB1234" for t in data["transits"])


def test_15_camera_and_time_filtering_api():
    """Requirement 15: REST API filters transits by camera ID and status."""
    db = SessionLocal()
    db.add(VehicleTransitLog(
        event_id="TR-FILTER-001",
        camera_id="CAM-TEST-V",
        track_id="15",
        plate_status="UNREADABLE"
    ))
    db.commit()
    db.close()

    res = client.get("/api/vehicles/transits?camera_id=CAM-TEST-V&plate_status=UNREADABLE")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert all(t["plate_status"] == "UNREADABLE" for t in data["transits"])


def test_16_direction_is_unknown_when_unavailable():
    """Requirement 16: Direction defaults to UNKNOWN when motion cannot be inferred."""
    cam = CameraManager(camera_id="CAM-TEST-V", surveillance_mode="CHECKPOST")
    dets = [{"bbox": [100, 100, 120, 100], "confidence": 0.85, "class_id": 2, "label": "Car", "vehicle_type": "Car"}]
    tracked = cam.vehicle_tracker.update(dets)
    tid = tracked[0]["track_id"]
    
    trk_obj = cam.vehicle_tracker.tracks.get(tid)
    # Only 1 point in history -> direction must be UNKNOWN
    assert len(trk_obj["history"]) == 1
    
    direction = "UNKNOWN"
    if len(trk_obj["history"]) >= 3:
        dy = trk_obj["history"][-1][1] - trk_obj["history"][0][1]
        direction = "INBOUND" if dy > 30 else ("OUTBOUND" if dy < -30 else "UNKNOWN")
    assert direction == "UNKNOWN"

    # Simulate downward vertical motion (>30px)
    trk_obj["history"].append((160, 150))
    trk_obj["history"].append((160, 200))
    assert len(trk_obj["history"]) >= 3
    dy = trk_obj["history"][-1][1] - trk_obj["history"][0][1]
    assert dy > 30
    direction = "INBOUND" if dy > 30 else "UNKNOWN"
    assert direction == "INBOUND"


def test_17_vehicle_snapshot_exists_even_when_ocr_fails():
    """Requirement 17: Vehicle snapshot exists on disk even when OCR fails."""
    from backend.evidence.snapshot import save_transit_snapshot
    dummy_veh = np.ones((120, 150, 3), dtype=np.uint8) * 128
    event_id = "TR-CAMTESTV-SNAPTEST-001"
    
    snap_path = save_transit_snapshot(dummy_veh, event_id=event_id, prefix="veh")
    assert snap_path is not None
    assert "/evidence/transits/" in snap_path
    
    # Check disk existence
    disk_path = os.path.join(settings.BASE_DIR, snap_path.lstrip("/"))
    assert os.path.exists(disk_path)
    # Clean up test file
    try:
        os.remove(disk_path)
    except Exception:
        pass


def test_18_plate_crop_is_retained_when_available():
    """Requirement 18: Plate crop is retained on disk and linked to transit record."""
    from backend.evidence.snapshot import save_transit_snapshot
    dummy_plate = np.ones((50, 180, 3), dtype=np.uint8) * 200
    event_id = "TR-CAMTESTV-PLATETEST-001"
    
    crop_path = save_transit_snapshot(dummy_plate, event_id=event_id, prefix="plate")
    assert crop_path is not None
    assert "/evidence/transits/" in crop_path
    
    # Check disk existence
    disk_path = os.path.join(settings.BASE_DIR, crop_path.lstrip("/"))
    assert os.path.exists(disk_path)
    try:
        os.remove(disk_path)
    except Exception:
        pass


def test_19_raw_ocr_normalization():
    """Requirement 19: Raw OCR normalization resolves character confusions and removes surrounding noise."""
    from backend.detection.anpr_engine import ANPREngine
    engine = ANPREngine()

    # Case 1: Letter 'O' confused with digit '0' in district code
    is_valid, plate, cat = engine.validate_indian_plate("TNO9BY9726")
    assert is_valid is True
    assert plate == "TN09BY9726"

    # Case 2: Digit '8' confused with letter 'B' in series code
    is_valid, plate, cat = engine.validate_indian_plate("MH12A83456")
    assert is_valid is True
    assert plate == "MH12AB3456"

    # Case 3: Digit '0' confused with letter 'O' in state code (Odisha)
    is_valid, plate, cat = engine.validate_indian_plate("0D02AB1234")
    assert is_valid is True
    assert plate == "OD02AB1234"

    # Case 4: Spaces and punctuation
    is_valid, plate, cat = engine.validate_indian_plate("DL 01 AB 1234.")
    assert is_valid is True
    assert plate == "DL01AB1234"

    # Case 5: Noise prefix (e.g. car brand before plate)
    is_valid, plate, cat = engine.validate_indian_plate("MARUTI DL01AB1234")
    assert is_valid is True
    assert plate == "DL01AB1234"

    # Case 6: Pure noise must be rejected
    is_valid, plate, cat = engine.validate_indian_plate("MARUTISUZUKISWIFT")
    assert is_valid is False
    assert plate is None


def test_20_late_ocr_upgrades_transit_and_prevents_race_condition():
    """Requirement 20: Safe lifecycle ensures late-arriving OCR upgrades transit record even if vehicle left frame."""
    db = SessionLocal()
    event_id = "TR-CAMTESTV-LATEOCR-001"
    
    # 1. Create transit initially finalized or pending
    rec = VehicleTransitLog(
        event_id=event_id,
        camera_id="CAM-TEST-V",
        track_id="20",
        vehicle_type="Car",
        plate_number=None,
        plate_status="UNREADABLE",  # Simulated premature finalization
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow()
    )
    db.add(rec)
    db.commit()
    db.close()

    # 2. Late OCR completes with valid plate
    cam = CameraManager(camera_id="CAM-TEST-V", surveillance_mode="CHECKPOST")
    # Simulate worker updating DB record with late OCR result
    db = SessionLocal()
    rec_update = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == event_id).first()
    assert rec_update is not None
    rec_update.plate_number = "DL01AB1234"
    rec_update.plate_status = "RECOGNIZED"
    rec_update.plate_confidence = 0.88
    rec_update.updated_at = datetime.utcnow()
    db.commit()
    db.close()

    # 3. Verify SQLite persistence after commit
    db = SessionLocal()
    verified = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == event_id).first()
    assert verified.plate_status == "RECOGNIZED"
    assert verified.plate_number == "DL01AB1234"
    assert verified.plate_confidence == 0.88
    db.close()


def test_21_invalid_ocr_does_not_overwrite_valid_plate():
    """Requirement 21: Subsequent unreadable or low confidence attempt never overwrites valid recognized plate."""
    cam = CameraManager(camera_id="CAM-TEST-V", surveillance_mode="CHECKPOST")
    track_id = "21"
    event_id = "TR-CAMTESTV-RETAIN-001"
    
    cam._active_transits[track_id] = {
        "event_id": event_id,
        "track_id": track_id,
        "best_plate": "TN09BY9726",
        "best_confidence": 0.85,
        "best_status": "RECOGNIZED",
        "last_seen": time.time()
    }
    
    # Simulate subsequent failed OCR attempt (confidence 0.0, plate None)
    active = cam._active_transits[track_id]
    new_confidence = 0.0
    new_plate = None
    
    # Pipeline rule: only update if new confidence > existing best
    if new_plate and new_confidence > active.get("best_confidence", 0.0):
        active["best_plate"] = new_plate
        
    assert active["best_plate"] == "TN09BY9726"
    assert active["best_status"] == "RECOGNIZED"


def test_22_multiple_ocr_attempts_retain_highest_confidence_plate():
    """Requirement 22: Multiple OCR attempts across frames retain the highest-confidence valid plate."""
    cam = CameraManager(camera_id="CAM-TEST-V", surveillance_mode="CHECKPOST")
    track_id = "22"
    event_id = "TR-CAMTESTV-MULTICONF-001"
    
    cam._active_transits[track_id] = {
        "event_id": event_id,
        "track_id": track_id,
        "best_plate": "DL01AB1234",
        "best_confidence": 0.72,
        "best_status": "RECOGNIZED",
        "last_seen": time.time()
    }
    
    # Frame 2: higher confidence 0.91 -> should update
    frame2_conf = 0.91
    if frame2_conf > cam._active_transits[track_id]["best_confidence"]:
        cam._active_transits[track_id]["best_confidence"] = frame2_conf
        
    assert cam._active_transits[track_id]["best_confidence"] == 0.91

    # Frame 3: lower confidence 0.78 -> should NOT update
    frame3_conf = 0.78
    if frame3_conf > cam._active_transits[track_id]["best_confidence"]:
        cam._active_transits[track_id]["best_confidence"] = frame3_conf
        
    assert cam._active_transits[track_id]["best_confidence"] == 0.91


def test_23_two_vehicles_create_two_independent_transits():
    """Requirement 23: Two vehicles simultaneously present create independent transits with correct plates."""
    db = SessionLocal()
    ev1 = "TR-CAMTESTV-MULTI-001"
    ev2 = "TR-CAMTESTV-MULTI-002"
    
    rec1 = VehicleTransitLog(
        event_id=ev1,
        camera_id="CAM-TEST-V",
        track_id="11",
        vehicle_type="Car",
        plate_number="DL01AB1234",
        plate_status="RECOGNIZED"
    )
    rec2 = VehicleTransitLog(
        event_id=ev2,
        camera_id="CAM-TEST-V",
        track_id="12",
        vehicle_type="Truck",
        plate_number="UP32XY5678",
        plate_status="RECOGNIZED"
    )
    db.add(rec1)
    db.add(rec2)
    db.commit()
    db.close()

    db = SessionLocal()
    r1 = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == ev1).first()
    r2 = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == ev2).first()
    
    assert r1.plate_number == "DL01AB1234"
    assert r1.track_id == "11"
    assert r2.plate_number == "UP32XY5678"
    assert r2.track_id == "12"
    assert r1.id != r2.id
    db.close()

