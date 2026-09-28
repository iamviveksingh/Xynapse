import os
import sys
import numpy as np
import cv2
import pytest

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.detection.face_detector import FaceDetector
from backend.detection.person_detector import PersonDetector, SimpleCentroidTracker

def test_detector_initialization():
    detector = FaceDetector()
    success = detector.initialize()
    assert success is True
    assert detector._is_initialized is True
    detector.release()
    assert detector._is_initialized is False

def test_person_detector_initialization():
    p_detector = PersonDetector()
    assert p_detector._is_initialized is True
    p_detector.release()
    assert p_detector._is_initialized is False

def test_detector_empty_frame():
    detector = FaceDetector()
    detector.initialize()
    blank = np.zeros((300, 300, 3), dtype=np.uint8)
    detections = detector.detect(blank)
    assert isinstance(detections, list)
    assert len(detections) == 0
    detector.release()

def test_person_detector_tracking():
    tracker = SimpleCentroidTracker()
    det1 = [{"bbox": [100, 100, 50, 100], "confidence": 0.92}]
    res1 = tracker.update(det1)
    assert len(res1) == 1
    assert res1[0]["track_id"] == 1
    assert "Person #01" in res1[0]["label"]

    # Frame 2: person slightly moved
    det2 = [{"bbox": [105, 102, 50, 100], "confidence": 0.94}]
    res2 = tracker.update(det2)
    assert len(res2) == 1
    assert res2[0]["track_id"] == 1  # Same persistent ID!
    assert len(res2[0]["history"]) == 2

def test_detector_draw_annotations():
    detector = FaceDetector()
    detector.initialize()
    frame = np.zeros((400, 400, 3), dtype=np.uint8)
    dummy_detections = [
        {"bbox": [50, 50, 100, 100], "confidence": 0.94, "label": "FACE"}
    ]
    annotated = detector.draw_annotations(frame, dummy_detections)
    assert annotated is not None
    assert annotated.shape == frame.shape
    # Frame was modified (not all zero anymore)
    assert np.any(annotated != 0)
    detector.release()

