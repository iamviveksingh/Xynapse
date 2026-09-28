import os
import sys
import time
import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.alert.alert_engine import AlertEngine
from backend.alert.cooldown import CooldownTracker
from backend.database.database import init_db

def test_cooldown_tracker():
    tracker = CooldownTracker(cooldown_seconds=1)
    cam = "TEST-CAM"

    assert tracker.is_cooled_down(cam) is True
    tracker.trigger(cam)
    assert tracker.is_cooled_down(cam) is False

    # Wait for cooldown to expire
    time.sleep(1.1)
    assert tracker.is_cooled_down(cam) is True

def test_alert_engine_creation_and_debounce(tmp_path):
    init_db()
    engine = AlertEngine(cooldown_seconds=2)
    cam = "CAM-01"

    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    detections = [{"bbox": [20, 20, 50, 50], "confidence": 0.95, "label": "FACE"}]

    # Dispatched alert capture
    dispatched = []
    engine.register_listener(lambda msg: dispatched.append(msg))

    # 1. First detection creates an alert
    alert1 = engine.process_detections(cam, frame, detections)
    assert alert1 is not None
    assert alert1["event_type"] == "PERSON_DETECTED"
    assert alert1["camera_id"] == cam
    assert alert1["confidence"] == 0.95
    assert len(dispatched) == 1
    assert dispatched[0]["type"] == "PERSON_DETECTED"
    assert os.path.exists(os.path.join(os.path.dirname(__file__), "..", alert1["snapshot"].lstrip("/")))

    # 2. Immediate second detection is suppressed by cooldown
    alert2 = engine.process_detections(cam, frame, detections)
    assert alert2 is None
    assert len(dispatched) == 1  # No new broadcast

def test_tampering_alert_generation():
    init_db()
    engine = AlertEngine(cooldown_seconds=2)
    cam = "CAM-TAMPER-TEST"
    black_frame = np.zeros((200, 200, 3), dtype=np.uint8)

    dispatched = []
    engine.register_listener(lambda msg: dispatched.append(msg))

    # 1. Tampering alert triggers successfully
    alert = engine.trigger_tampering_alert(cam, black_frame)
    assert alert is not None
    assert alert["event_type"] == "CAMERA_TAMPERED"
    assert alert["camera_id"] == cam
    assert alert["confidence"] == 0.99
    assert len(dispatched) == 1
    assert dispatched[0]["type"] == "CAMERA_TAMPERED"

    # 2. Immediate second tampering is debounced
    alert2 = engine.trigger_tampering_alert(cam, black_frame)
    assert alert2 is None
    assert len(dispatched) == 1

def test_severity_classification():
    """Verify severity is computed correctly for different event types and face counts."""
    # Camera tampered is always CRITICAL
    assert AlertEngine._compute_severity("CAMERA_TAMPERED", 0, 0.99) == "CRITICAL"
    # Loitering is always HIGH
    assert AlertEngine._compute_severity("SUSPICIOUS_LOITERING", 3, 0.95) == "HIGH"
    # Multiple humans = HIGH
    assert AlertEngine._compute_severity("PERSON_DETECTED", 3, 0.85) == "HIGH"
    assert AlertEngine._compute_severity("PERSON_DETECTED", 2, 0.80) == "HIGH"
    # Single human with good confidence = MEDIUM
    assert AlertEngine._compute_severity("PERSON_DETECTED", 1, 0.85) == "MEDIUM"
    # Low confidence = LOW
    assert AlertEngine._compute_severity("PERSON_DETECTED", 1, 0.55) == "LOW"

def test_loitering_detection():
    """Verify that repeated detections trigger a SUSPICIOUS_LOITERING alert."""
    init_db()
    engine = AlertEngine(cooldown_seconds=1)
    cam = "CAM-LOITER-TEST"
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    dispatched = []
    engine.register_listener(lambda msg: dispatched.append(msg))

    # Simulate 3 rapid detections (exceeds LOITER_THRESHOLD)
    engine.check_loitering(cam, frame)
    engine.check_loitering(cam, frame)
    result = engine.check_loitering(cam, frame)

    assert result is not None
    assert result["event_type"] == "SUSPICIOUS_LOITERING"
    loiter_msgs = [m for m in dispatched if m["type"] == "SUSPICIOUS_LOITERING"]
    assert len(loiter_msgs) == 1

def test_loitering_dwell_time():
    """Verify that continuous dwell time (>=25s) triggers SUSPICIOUS_LOITERING alert."""
    init_db()
    engine = AlertEngine(cooldown_seconds=1)
    cam = "CAM-DWELL-TEST"
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    dispatched = []
    engine.register_listener(lambda msg: dispatched.append(msg))

    # Single call with dwell_seconds >= 25.0
    result = engine.check_loitering(cam, frame, dwell_seconds=30.0)
    assert result is not None
    assert result["event_type"] == "SUSPICIOUS_LOITERING"
    assert "30s" in result["objects_detected"]
    assert len(dispatched) == 1

