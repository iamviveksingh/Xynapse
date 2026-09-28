import pytest
import numpy as np
from backend.detection.intrusion_detector import VirtualTripwireDetector
from backend.database.database import init_db

@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    yield

def test_tripwire_initialization():
    detector = VirtualTripwireDetector(line_y_ratio=0.65, enabled=True)
    assert detector.enabled is True
    assert detector.line_y_ratio == 0.65
    assert detector.is_breached is False

def test_tripwire_no_detections():
    detector = VirtualTripwireDetector(line_y_ratio=0.50, enabled=True)
    frame_shape = (480, 640, 3)
    is_breached, breached_dets, line_y = detector.check_intrusion(frame_shape, [])
    assert is_breached is False
    assert len(breached_dets) == 0
    assert line_y == 240

def test_tripwire_unbreached_detection():
    detector = VirtualTripwireDetector(line_y_ratio=0.60, enabled=True)
    frame_shape = (480, 640, 3)
    # Person standing high in frame: feet at y = 100 + 80 = 180 (line is at 480 * 0.6 = 288)
    detections = [{"bbox": [100, 100, 50, 80], "confidence": 0.95, "role": "UNKNOWN"}]
    is_breached, breached_dets, line_y = detector.check_intrusion(frame_shape, detections)
    assert is_breached is False
    assert len(breached_dets) == 0

def test_tripwire_breached_detection():
    detector = VirtualTripwireDetector(line_y_ratio=0.50, enabled=True)
    frame_shape = (480, 640, 3)
    # Person standing across line: feet at y = 200 + 100 = 300 (line is at 480 * 0.5 = 240)
    detections = [{"bbox": [100, 200, 50, 100], "confidence": 0.95, "role": "UNKNOWN"}]
    is_breached, breached_dets, line_y = detector.check_intrusion(frame_shape, detections)
    assert is_breached is True
    assert len(breached_dets) == 1

def test_tripwire_drawing():
    detector = VirtualTripwireDetector(line_y_ratio=0.50, enabled=True)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    out_clear = detector.draw_tripwire(frame, is_breached=False)
    assert out_clear.shape == frame.shape
    out_breached = detector.draw_tripwire(frame, is_breached=True)
    assert out_breached.shape == frame.shape
    out_auth = detector.draw_tripwire(frame, is_breached=True, is_authorized_crossing=True)
    assert out_auth.shape == frame.shape


def test_polygon_validation():
    """Verify validation of 2D polygon vertices."""
    detector = VirtualTripwireDetector()

    # Valid polygon (quadrilateral)
    pts = [[100, 100], [400, 100], [400, 400], [100, 400]]
    assert detector.set_polygon(pts) is True
    assert detector.fence_type == "POLYGON"
    assert detector.get_polygon() == [[100.0, 100.0], [400.0, 100.0], [400.0, 400.0], [100.0, 400.0]]

    # Fewer than 3 points must be rejected
    with pytest.raises(ValueError, match="at least 3 vertices"):
        detector.set_polygon([[100, 100], [200, 200]])

    # Empty list must be rejected
    with pytest.raises(ValueError):
        detector.set_polygon([])

    # Non-numeric / malformed coordinates must be rejected
    with pytest.raises(ValueError):
        detector.set_polygon([["abc", 100], [200, 200], [300, 300]])

    # Negative coordinates must be rejected
    with pytest.raises(ValueError):
        detector.set_polygon([[-50, 100], [200, 200], [300, 300]])


def test_polygon_inside_outside_and_boundary():
    """Verify pointPolygonTest logic for inside, outside, and boundary."""
    detector = VirtualTripwireDetector()
    pts = [[100, 100], [400, 100], [400, 400], [100, 400]]
    detector.set_polygon(pts)
    frame_shape = (500, 500, 3)

    # 1. Point strictly inside
    assert detector.check_point_inside(250, 250, frame_shape) is True

    # 2. Point strictly outside
    assert detector.check_point_inside(50, 50, frame_shape) is False
    assert detector.check_point_inside(450, 250, frame_shape) is False

    # 3. Point exactly on boundary (dist == 0 -> considered inside / breached)
    assert detector.check_point_inside(100, 250, frame_shape) is True
    assert detector.check_point_inside(400, 400, frame_shape) is True


def test_polygon_track_transition_and_deduplication():
    """
    Verify track transition behavior:
    1. Person OUTSIDE -> no breach.
    2. Person enters polygon (OUTSIDE -> INSIDE) -> is_new_intrusion == True.
    3. Person remains inside (INSIDE -> INSIDE) -> is_new_intrusion == False (no duplicate storm).
    4. Person leaves polygon (INSIDE -> OUTSIDE) -> no breach.
    5. Person re-enters (OUTSIDE -> INSIDE) -> is_new_intrusion == True.
    """
    detector = VirtualTripwireDetector()
    pts = [[100, 100], [400, 100], [400, 400], [100, 400]]
    detector.set_polygon(pts)
    frame_shape = (500, 500, 3)

    # Frame 1: Person #1 outside polygon (foot at 50, 50)
    det_f1 = [{"bbox": [30, 10, 40, 40], "track_id": 1, "confidence": 0.95}]
    breached, b_dets, _ = detector.check_intrusion(frame_shape, det_f1)
    assert breached is False
    assert len(b_dets) == 0

    # Frame 2: Person #1 steps inside (foot at 250, 250) -> OUTSIDE -> INSIDE transition!
    det_f2 = [{"bbox": [230, 200, 40, 50], "track_id": 1, "confidence": 0.95}]
    breached, b_dets, _ = detector.check_intrusion(frame_shape, det_f2)
    assert breached is True
    assert len(b_dets) == 1
    assert b_dets[0]["is_inside_fence"] is True
    assert b_dets[0]["is_new_intrusion"] is True

    # Frame 3: Person #1 remains inside (foot at 260, 260) -> INSIDE -> INSIDE
    det_f3 = [{"bbox": [240, 210, 40, 50], "track_id": 1, "confidence": 0.95}]
    breached, b_dets, _ = detector.check_intrusion(frame_shape, det_f3)
    assert breached is True
    assert len(b_dets) == 1
    assert b_dets[0]["is_inside_fence"] is True
    assert b_dets[0]["is_new_intrusion"] is False  # Deduplicated!

    # Frame 4: Person #1 leaves polygon (foot at 50, 50) -> INSIDE -> OUTSIDE
    det_f4 = [{"bbox": [30, 10, 40, 40], "track_id": 1, "confidence": 0.95}]
    breached, b_dets, _ = detector.check_intrusion(frame_shape, det_f4)
    assert breached is False

    # Frame 5: Person #1 re-enters polygon (foot at 250, 250) -> OUTSIDE -> INSIDE
    det_f5 = [{"bbox": [230, 200, 40, 50], "track_id": 1, "confidence": 0.95}]
    breached, b_dets, _ = detector.check_intrusion(frame_shape, det_f5)
    assert breached is True
    assert b_dets[0]["is_new_intrusion"] is True  # New alert generated on re-entry!


def test_polygon_drawing():
    """Verify HUD drawing of 2D polygon virtual fence."""
    detector = VirtualTripwireDetector()
    pts = [[100, 100], [400, 100], [400, 400], [100, 400]]
    detector.set_polygon(pts)

    frame = np.zeros((500, 500, 3), dtype=np.uint8)
    out_clear = detector.draw_tripwire(frame, is_breached=False)
    assert out_clear.shape == frame.shape

    out_breached = detector.draw_tripwire(frame, is_breached=True)
    assert out_breached.shape == frame.shape
    # Breached frame should have modified pixels in the red/alert channel
    assert not np.array_equal(out_breached, frame)


def test_polygon_api_and_persistence():
    """Verify polygon configuration endpoint, input validation, and restart persistence."""
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.config import settings
    from backend.api.cameras import init_camera_system, camera_registry

    client = TestClient(app, headers={"X-API-Key": settings.ADMIN_API_KEY})

    # 1. Invalid polygon (only 2 points) -> must return 422
    res_bad = client.post("/api/cameras/CAM-01/polygon", json={"points": [[100, 100], [200, 200]]})
    assert res_bad.status_code == 422

    # 2. Valid polygon configuration
    test_poly = [[120, 180], [500, 160], [570, 400], [150, 430]]
    res = client.post("/api/cameras/CAM-01/polygon", json={"points": test_poly, "enabled": True})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "configured"
    assert data["fence_type"] == "POLYGON"
    assert len(data["points"]) == 4

    # 3. Query polygon via GET endpoint
    res_get = client.get("/api/cameras/CAM-01/polygon")
    assert res_get.status_code == 200
    get_data = res_get.json()
    assert get_data["fence_type"] == "POLYGON"
    assert get_data["points"] == [[120.0, 180.0], [500.0, 160.0], [570.0, 400.0], [150.0, 430.0]]

    # 4. Simulate backend restart: clear in-memory camera registry and re-initialize from DB
    for c in list(camera_registry.values()):
        c.stop()
    camera_registry.clear()
    init_camera_system()

    assert "CAM-01" in camera_registry
    cam = camera_registry["CAM-01"]
    assert cam.tripwire.fence_type == "POLYGON"
    assert cam.tripwire.get_polygon() == [[120.0, 180.0], [500.0, 160.0], [570.0, 400.0], [150.0, 430.0]]

