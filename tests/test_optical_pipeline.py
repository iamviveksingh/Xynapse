import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend.detection.optical_pipeline import OpticalPipeline
from backend.camera.camera_manager import CameraManager
from backend.main import app
from backend.config import settings

client = TestClient(app, headers={"X-API-Key": settings.ADMIN_API_KEY})

def test_optical_pipeline_modes():
    pipeline = OpticalPipeline()
    dummy_frame = np.ones((120, 160, 3), dtype=np.uint8) * 35  # Dim frame

    for mode in OpticalPipeline.MODES:
        out = pipeline.process_frame(dummy_frame, mode)
        assert out is not None
        assert out.shape == dummy_frame.shape
        assert out.dtype == np.uint8

def test_optical_pipeline_low_light_boost():
    pipeline = OpticalPipeline()
    # Dark frame with mean intensity ~20
    dark_frame = np.ones((100, 100, 3), dtype=np.uint8) * 20
    # Add small contrast variance
    dark_frame[20:50, 20:50] = 50

    enhanced = pipeline.process_frame(dark_frame, "LOW_LIGHT_ENHANCE")
    assert enhanced.shape == dark_frame.shape
    # CLAHE should boost contrast/luminance
    assert float(np.mean(enhanced)) >= float(np.mean(dark_frame))

def test_camera_manager_optical_mode():
    cam = CameraManager(camera_id="CAM-OPT-TEST", source="non_existent")
    assert cam.optical_mode == "STANDARD"

    cam.set_optical_mode("LOW_LIGHT_ENHANCE")
    assert cam.optical_mode == "LOW_LIGHT_ENHANCE"
    assert cam.get_status_dict()["optical_mode"] == "LOW_LIGHT_ENHANCE"

    cam.set_optical_mode("NVG_GREEN")
    assert cam.optical_mode == "NVG_GREEN"

    cam.set_optical_mode("FLIR_THERMAL")
    assert cam.optical_mode == "FLIR_THERMAL"

    # Invalid mode should not overwrite
    cam.set_optical_mode("INVALID_MODE")
    assert cam.optical_mode == "FLIR_THERMAL"

def test_api_optical_mode_endpoints():
    # Set optical mode via API
    resp = client.post("/api/cameras/CAM-01/optical-mode", json={"mode": "LOW_LIGHT_ENHANCE"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["optical_mode"] == "LOW_LIGHT_ENHANCE"

    # Get optical mode via API
    get_resp = client.get("/api/cameras/CAM-01/optical-mode")
    assert get_resp.status_code == 200
    assert get_resp.json()["optical_mode"] == "LOW_LIGHT_ENHANCE"

    # Reset back to STANDARD
    reset_resp = client.post("/api/cameras/CAM-01/optical-mode", json={"mode": "STANDARD"})
    assert reset_resp.status_code == 200
    assert reset_resp.json()["optical_mode"] == "STANDARD"


def test_low_light_detector_dark_and_bright():
    """Verify that LowLightDetector correctly identifies dark vs bright synthetic frames."""
    from backend.detection.optical_pipeline import LowLightDetector

    detector = LowLightDetector(enter_threshold=45.0, exit_threshold=58.0, consecutive_frames=2)

    # 1. Dark synthetic frame (luminance ~20)
    dark_frame = np.ones((120, 160, 3), dtype=np.uint8) * 20
    is_dark, lum = detector.classify_single_frame(dark_frame)
    assert is_dark is True
    assert lum < 45.0

    # 2. Bright synthetic frame (luminance ~180)
    bright_frame = np.ones((120, 160, 3), dtype=np.uint8) * 180
    is_dark_b, lum_b = detector.classify_single_frame(bright_frame)
    assert is_dark_b is False
    assert lum_b > 58.0


def test_low_light_detector_hysteresis_and_stability():
    """
    Verify dual-threshold hysteresis:
    - enter_threshold = 45.0
    - exit_threshold = 58.0
    Boundary region (45.0 to 58.0) must NOT cause mode flickering.
    """
    from backend.detection.optical_pipeline import LowLightDetector

    detector = LowLightDetector(
        enter_threshold=45.0,
        exit_threshold=58.0,
        smoothing_alpha=0.5,
        consecutive_frames=3
    )

    bright_frame = np.ones((120, 160, 3), dtype=np.uint8) * 120
    boundary_frame = np.ones((120, 160, 3), dtype=np.uint8) * 50  # Between 45 and 58
    dark_frame = np.ones((120, 160, 3), dtype=np.uint8) * 25

    # 1. Start in bright scene
    for _ in range(5):
        is_dark, lum, mode = detector.update(bright_frame)
    assert is_dark is False
    assert mode == "STANDARD"

    # 2. Boundary frame (50) while in STANDARD mode -> must NOT switch to low light (since 50 > 45)
    for _ in range(5):
        is_dark, lum, mode = detector.update(boundary_frame)
    assert is_dark is False
    assert mode == "STANDARD"

    # 3. Drops to deep dark (25) -> switches to LOW_LIGHT_ENHANCE after debounce
    for _ in range(4):
        is_dark, lum, mode = detector.update(dark_frame)
    assert is_dark is True
    assert mode == "LOW_LIGHT_ENHANCE"

    # 4. Illumination rises to boundary (50) while in LOW_LIGHT_ENHANCE -> must NOT switch back to bright (since 50 < 58)
    for _ in range(5):
        is_dark, lum, mode = detector.update(boundary_frame)
    assert is_dark is True  # Hysteresis keeps low-light active without flickering!
    assert mode == "LOW_LIGHT_ENHANCE"

    # 5. Full daytime recovery (120) -> recovers to STANDARD
    for _ in range(4):
        is_dark, lum, mode = detector.update(bright_frame)
    assert is_dark is False
    assert mode == "STANDARD"


def test_auto_optical_mode_api_and_telemetry():
    """Verify /api/cameras/{id}/auto-optical endpoint and telemetry reporting."""
    from backend.camera.camera_manager import CameraManager

    cam = CameraManager(camera_id="CAM-AUTO-OPT-TEST", source="0")
    assert cam.auto_optical_mode is True

    # Test API endpoint
    res_toggle = client.post("/api/cameras/CAM-01/auto-optical", json={"enabled": False})
    assert res_toggle.status_code == 200
    assert res_toggle.json()["auto_optical_mode"] is False

    res_toggle2 = client.post("/api/cameras/CAM-01/auto-optical", json={"enabled": True})
    assert res_toggle2.status_code == 200
    assert res_toggle2.json()["auto_optical_mode"] is True

    # Check status dict includes ambient luminance and is_low_light
    status = cam.get_status_dict()
    assert "auto_optical_mode" in status
    assert "ambient_luminance" in status
    assert "is_low_light" in status

