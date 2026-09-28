import os
import json
import pytest
import numpy as np
import cv2
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import settings
from backend.detection.face_recognizer import FaceRecognizer
from backend.alert.alert_engine import AlertEngine
from backend.database.database import SessionLocal, init_db
from backend.database.models import FaceProfile, Alert

@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    yield

def test_face_recognizer_initialization():
    recognizer = FaceRecognizer()
    assert recognizer._is_initialized is True
    assert recognizer.sface is not None

def test_feature_extraction_and_cosine_matching():
    recognizer = FaceRecognizer()
    # Create synthetic test frame
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.circle(frame, (100, 100), 40, (200, 200, 200), -1)

    # Synthetic 15-float YuNet face: [x, y, w, h, 5 landmarks (x,y), conf]
    raw_face = np.array([
        60, 60, 80, 80,
        80, 80, 120, 80,
        100, 100,
        85, 120, 115, 120,
        0.98
    ], dtype=np.float32)

    feat1 = recognizer.extract_feature(frame, raw_face)
    assert feat1 is not None
    assert feat1.shape == (1, 128)

    # Matching same feature against itself gives similarity ~1.0
    sim = recognizer.sface.match(feat1, feat1, cv2.FaceRecognizerSF_FR_COSINE)
    assert sim >= 0.99

def test_profile_enrollment_and_classification():
    recognizer = FaceRecognizer()
    db = SessionLocal()

    # Clear test profiles
    db.query(FaceProfile).filter(FaceProfile.name.in_(["Officer Test", "Suspect Test"])).delete(synchronize_session=False)
    db.commit()

    # Create dummy 128-D embedding for Officer
    guard_emb = np.random.randn(1, 128).astype(np.float32)
    guard_emb = guard_emb / np.linalg.norm(guard_emb)

    p1 = FaceProfile(
        name="Officer Test",
        role="AUTHORIZED_GUARD",
        notes="Border Guard Patrol",
        photo_path=None,
        embedding_json=json.dumps(guard_emb.flatten().tolist())
    )
    db.add(p1)
    db.commit()

    recognizer.reload_profiles()

    # Match exact embedding
    match_res = recognizer.match_feature(guard_emb)
    assert match_res["matched"] is True
    assert match_res["name"] == "Officer Test"
    assert match_res["role"] == "AUTHORIZED_GUARD"
    assert match_res["similarity"] >= 0.99

    # Clean up
    db.delete(p1)
    db.commit()
    db.close()
    recognizer.reload_profiles()

def test_alert_engine_suspect_trigger():
    engine = AlertEngine(cooldown_seconds=1)
    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)

    alert = engine.trigger_suspect_alert(
        camera_id="CAM-TEST",
        frame=dummy_frame,
        suspect_name="Wanted Person Alpha",
        confidence=0.96,
        notes="High Priority Watchlist"
    )

    assert alert is not None
    assert alert["event_type"] == "SUSPECT_DETECTED"
    assert alert["severity"] == "CRITICAL"
    assert "Wanted Person Alpha" in alert["objects_detected"]

def test_faces_api_endpoints():
    client = TestClient(app, headers={"X-API-Key": settings.ADMIN_API_KEY})

    # 1. Get stats
    res_stats = client.get("/api/faces/stats")
    assert res_stats.status_code == 200
    data = res_stats.json()
    assert "total" in data
    assert "authorized_count" in data
    assert "suspect_count" in data

    # 2. List faces
    res_list = client.get("/api/faces")
    assert res_list.status_code == 200
    assert isinstance(res_list.json(), list)
    for p in res_list.json():
        if p.get("photo_path"):
            assert p["photo_path"].startswith("/evidence/faces/")

def test_camera_snapshot_endpoint():
    client = TestClient(app, headers={"X-API-Key": settings.ADMIN_API_KEY})
    res = client.get("/api/cameras/CAM-01/snapshot")
    assert res.status_code == 200
    assert "image/jpeg" in res.headers.get("content-type", "")
    assert len(res.content) > 100

