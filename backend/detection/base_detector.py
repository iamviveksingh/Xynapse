from abc import ABC, abstractmethod
from typing import List, Dict, Any
import numpy as np

class BaseDetector(ABC):
    """
    Abstract detection interface for Xynapse.
    Allows seamlessly swapping detectors (FaceDetector, PersonDetector,
    VehicleDetector, YOLO, MediaPipe, etc.) without altering the surveillance pipeline.
    """

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize models, weights, or cascades."""
        pass

    @abstractmethod
    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detect objects in frame.
        Returns a list of detections:
        [
            {
                "bbox": [x, y, w, h],
                "confidence": 0.94,
                "label": "FACE"
            }
        ]
        """
        pass

    @abstractmethod
    def release(self) -> None:
        """Free model memory or resources."""
        pass
