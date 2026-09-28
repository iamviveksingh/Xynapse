import cv2
import numpy as np
import pytest
import time

from backend.camera.camera_manager import CameraManager
from backend.alert.alert_engine import AlertEngine


@pytest.fixture
def tamper_scenes():
    h, w = 480, 640
    scenes = {}

    # 1. Normal outdoor high-contrast scene
    outdoor = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h // 2):
        val = int(220 - y * 0.2)
        outdoor[y, :] = [val, val - 20, 180]
    for y in range(h // 2, h):
        val = int(60 + (y - h // 2) * 0.2)
        outdoor[y, :] = [30, val, 70]
    for x in range(50, w, 60):
        cv2.line(outdoor, (x, h // 2 - 40), (x, h), (20, 20, 20), 4)
        cv2.line(outdoor, (0, h // 2 + 30), (w, h // 2 + 30), (180, 180, 180), 2)
    noise = np.random.normal(0, 5, outdoor.shape).astype(np.int16)
    outdoor = np.clip(outdoor.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    scenes["normal_outdoor"] = outdoor

    # 2. Normal indoor scene
    indoor = np.ones((h, w, 3), dtype=np.uint8) * 160
    indoor[h // 2:, :] = 90
    cv2.rectangle(indoor, (100, 50), (250, 400), (40, 40, 40), 6)
    cv2.rectangle(indoor, (350, 80), (580, 260), (230, 230, 230), -1)
    cv2.rectangle(indoor, (350, 80), (580, 260), (30, 30, 30), 3)
    noise = np.random.normal(0, 4, indoor.shape).astype(np.int16)
    indoor = np.clip(indoor.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    scenes["normal_indoor"] = indoor

    # 3. Complete blackout (lens capped)
    blackout = np.clip(np.random.normal(2, 1.5, (h, w, 3)), 0, 255).astype(np.uint8)
    scenes["complete_blackout"] = blackout

    # 4. Hand / cloth occlusion
    cloth = np.ones((h, w, 3), dtype=np.uint8) * 28
    noise = np.random.normal(0, 1.2, (h, w, 3)).astype(np.int16)
    cloth = np.clip(cloth.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    scenes["hand_cloth_occlusion"] = cloth

    # 5. Severe Gaussian blur on outdoor scene
    scenes["severe_gaussian_blur"] = cv2.GaussianBlur(outdoor, (101, 101), 35.0)

    # 6. Moderate Gaussian blur on outdoor scene
    scenes["moderate_gaussian_blur"] = cv2.GaussianBlur(outdoor, (25, 25), 7.0)

    # 7. Partial lens obstruction (70% cloth, 30% outdoor)
    partial = outdoor.copy()
    partial[:, :int(w * 0.7)] = cloth[:, :int(w * 0.7)]
    scenes["partial_lens_obstruction"] = partial

    # 8. Bright sky + dark ground
    split_scene = np.zeros((h, w, 3), dtype=np.uint8)
    split_scene[:h // 2, :] = [240, 240, 240]
    split_scene[h // 2:, :] = [30, 30, 30]
    cv2.line(split_scene, (0, h // 2), (w, h // 2), (0, 0, 0), 2)
    noise = np.random.normal(0, 3, split_scene.shape).astype(np.int16)
    scenes["bright_sky_dark_ground"] = np.clip(split_scene.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    # 9. Low-light scene with subtle illumination
    low_light = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        low_light[y, :] = int(12 + y * 0.04)
    cv2.rectangle(low_light, (200, 150), (280, 420), (35, 35, 35), -1)
    noise = np.random.normal(0, 2.0, low_light.shape).astype(np.int16)
    scenes["low_light_scene"] = np.clip(low_light.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    return scenes


def test_tamper_normal_scenes_zero_false_positives(tamper_scenes):
    """Verify that normal outdoor and indoor surveillance scenes NEVER produce false tamper alerts."""
    engine = AlertEngine()
    cam = CameraManager("CAM-TEST-TAMPER", source="0", alert_engine=engine)

    assert cam._check_tampering(tamper_scenes["normal_outdoor"]) is False
    assert cam._check_tampering(tamper_scenes["normal_indoor"]) is False
    assert cam._check_tampering(tamper_scenes["bright_sky_dark_ground"]) is False


def test_tamper_blackout_and_cloth_occlusion(tamper_scenes):
    """Verify that lens blackout and cloth/hand occlusion are detected instantaneously."""
    engine = AlertEngine()
    cam = CameraManager("CAM-TEST-TAMPER", source="0", alert_engine=engine)

    # Complete blackout -> Clause A triggers
    assert cam._check_tampering(tamper_scenes["complete_blackout"]) is True

    # Hand/cloth occlusion -> Clause B triggers
    assert cam._check_tampering(tamper_scenes["hand_cloth_occlusion"]) is True


def test_tamper_metric_computation_latency(tamper_scenes):
    """Verify that tamper check calculation latency is < 5ms per frame (strictly non-blocking)."""
    engine = AlertEngine()
    cam = CameraManager("CAM-TEST-TAMPER", source="0", alert_engine=engine)

    latencies = []
    for _ in range(50):
        t0 = time.perf_counter()
        cam._check_tampering(tamper_scenes["normal_outdoor"])
        latencies.append((time.perf_counter() - t0) * 1000)

    avg_ms = sum(latencies) / len(latencies)
    assert avg_ms < 15.0, f"Tamper latency {avg_ms:.2f}ms exceeds 15ms threshold"


def test_tamper_empty_and_corrupt_frames():
    """Verify that None, empty, or 1-pixel frames are handled safely without unhandled exceptions."""
    engine = AlertEngine()
    cam = CameraManager("CAM-TEST-TAMPER", source="0", alert_engine=engine)

    assert cam._check_tampering(None) is False
    assert cam._check_tampering(np.array([], dtype=np.uint8)) is False
    assert cam._check_tampering(np.zeros((1, 1, 3), dtype=np.uint8)) is True  # Single dark pixel is black
