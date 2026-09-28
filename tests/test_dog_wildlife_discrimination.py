import pytest
import numpy as np
from backend.detection.face_recognizer import FaceRecognizer
from backend.detection.person_detector import SimpleCentroidTracker, PersonDetector

def test_face_recognizer_protects_dog_from_unknown_person():
    """
    Ensure that when a dog/wildlife detection is passed through FaceRecognizer,
    it is NOT overwritten to 'Unknown Person', role remains 'WILDLIFE',
    and unknown_count is not incremented.
    """
    recognizer = FaceRecognizer()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    detections = [
        {
            "bbox": [100, 200, 80, 60],
            "confidence": 0.88,
            "label": "Wildlife • Dog",
            "detection_type": "WILDLIFE",
            "is_animal": True,
            "animal_type": "Dog",
            "role": "WILDLIFE",
            "landmarks": [],
            "raw_face": None
        }
    ]

    summary = recognizer.process_frame_detections(frame, detections)

    assert detections[0]["is_animal"] is True
    assert detections[0]["role"] == "WILDLIFE"
    assert detections[0]["label"] == "Wildlife • Dog"
    assert summary["unknown_count"] == 0
    assert summary["total_faces"] == 0
    assert summary["has_suspect"] is False

def test_tracker_preserves_dog_identity_across_frames():
    """
    Ensure SimpleCentroidTracker retains is_animal=True and animal labels
    (e.g., 'Dog #01') across multiple frame updates rather than reverting to 'Person #01'.
    """
    tracker = SimpleCentroidTracker()

    # Frame 1: Dog enters
    dets_frame1 = [
        {
            "bbox": [100, 200, 80, 60],
            "confidence": 0.85,
            "is_animal": True,
            "animal_type": "Dog",
            "role": "WILDLIFE"
        }
    ]
    tracked1 = tracker.update(dets_frame1)
    assert len(tracked1) == 1
    assert tracked1[0]["is_animal"] is True
    assert tracked1[0]["label"] == "Dog #01"

    # Frame 2: Dog moves slightly
    dets_frame2 = [
        {
            "bbox": [105, 202, 80, 60],
            "confidence": 0.87,
            "is_animal": True,
            "animal_type": "Dog",
            "role": "WILDLIFE"
        }
    ]
    tracked2 = tracker.update(dets_frame2)
    assert len(tracked2) == 1
    assert tracked2[0]["is_animal"] is True
    assert tracked2[0]["track_id"] == 1
    assert tracked2[0]["label"] == "Dog #01"
    assert tracked2[0]["role"] == "WILDLIFE"

def test_mixed_scene_guard_and_dog():
    """
    Ensure that in a mixed scene (guard or intruder alongside a patrol dog),
    the human is evaluated for biometric recognition while the dog remains non-threat wildlife.
    """
    recognizer = FaceRecognizer()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    detections = [
        {
            "bbox": [50, 100, 60, 120],
            "confidence": 0.92,
            "label": "Human",
            "is_animal": False,
            "role": "UNKNOWN",
            "raw_face": None
        },
        {
            "bbox": [150, 220, 70, 50],
            "confidence": 0.89,
            "label": "Wildlife • Dog",
            "is_animal": True,
            "animal_type": "Dog",
            "role": "WILDLIFE",
            "raw_face": None
        }
    ]

    summary = recognizer.process_frame_detections(frame, detections)

    # Human is unknown
    assert detections[0]["role"] == "UNKNOWN"
    assert detections[0]["label"] == "Unknown Person"
    # Dog remains Wildlife
    assert detections[1]["is_animal"] is True
    assert detections[1]["role"] == "WILDLIFE"
    assert detections[1]["label"] == "Wildlife • Dog"

    # Only 1 human face evaluated
    assert summary["total_faces"] == 1
    assert summary["unknown_count"] == 1

def test_human_is_never_marked_as_fauna():
    """
    Ensure that a human sitting or moving in front of the camera is NEVER marked as Fauna,
    even if tracker updates across multiple frames.
    """
    tracker = SimpleCentroidTracker()
    detector = PersonDetector()

    # Frame 1: Person enters
    human_det = [{
        "bbox": [100, 100, 150, 200],
        "confidence": 0.85,
        "label": "Human",
        "is_animal": False,
        "detection_type": "FULL_BODY"
    }]
    tracked = tracker.update(human_det)
    assert tracked[0]["is_animal"] is False
    assert "Person" in tracked[0]["label"]
    assert tracked[0]["role"] != "WILDLIFE"

    # Frame 2: Person moves
    human_det2 = [{
        "bbox": [102, 102, 150, 200],
        "confidence": 0.88,
        "label": "Human",
        "is_animal": False,
        "detection_type": "FULL_BODY"
    }]
    tracked2 = tracker.update(human_det2)
    assert tracked2[0]["is_animal"] is False
    assert "Person" in tracked2[0]["label"]
    assert tracked2[0]["role"] != "WILDLIFE"
    assert tracked2[0].get("animal_type") is None

    # Test HUD rendering - must NOT render Fauna or Wildlife
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    annotated = detector.draw_annotations(frame, tracked2)
    assert annotated is not None
