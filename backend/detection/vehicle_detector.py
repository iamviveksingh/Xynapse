import os
import cv2
import numpy as np
from typing import List, Dict, Any, Optional
from backend.detection.base_detector import BaseDetector
from backend.detection.hud_renderer import draw_modern_pill_badge
from backend.detection.person_detector import _yolo_global_lock

class VehicleDetector(BaseDetector):
    """
    Real-Time Vehicle Detection and Classification Engine using YOLOv8 ONNX.
    Classifies Cars, Trucks, Buses, and Motorcycles at Border Check Posts (BOPs).
    """

    VEHICLE_CLASS_MAP = {
        2: "Car",
        3: "Motorcycle",
        5: "Bus",
        7: "Truck"
    }

    def __init__(self, min_confidence: float = 0.40, model_path: Optional[str] = None):
        self.min_confidence = min_confidence
        self.model_path = model_path
        self.model = None
        self._is_initialized = False
        self.initialize()

    def initialize(self) -> bool:
        """Loads YOLOv8 model reusing shared cached singleton."""
        try:
            from backend.detection.person_detector import get_shared_yolo_model
            shared_m = get_shared_yolo_model(self.model_path)
            if shared_m is not None:
                self.model = shared_m
                self._is_initialized = True
                return True
        except Exception as e:
            print(f"[VehicleDetector] Error fetching shared YOLO model: {e}")

        print("[VehicleDetector] No YOLO model found. Vehicle detection in bypass mode.")
        self._is_initialized = False
        return False

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Runs inference on frame and returns all detected vehicles.
        Returns:
            List of dicts: [
                {
                    "bbox": [x, y, w, h],
                    "confidence": 0.88,
                    "class_id": 2,
                    "label": "Car",
                    "vehicle_type": "Car"
                }
            ]
        """
        if not self._is_initialized or self.model is None or frame is None or frame.size == 0:
            return []

        h, w = frame.shape[:2]
        detections = []

        try:
            # Predict only target vehicle classes: 2:car, 3:motorcycle, 5:bus, 7:truck
            with _yolo_global_lock:
                results = self.model(
                    frame,
                    classes=list(self.VEHICLE_CLASS_MAP.keys()),
                    conf=self.min_confidence,
                    verbose=False,
                    imgsz=416
                )

            if results and len(results) > 0:
                boxes = results[0].boxes
                for box in boxes:
                    cls_id = int(box.cls[0].item())
                    conf = float(box.conf[0].item())
                    xywh = box.xywh[0].tolist()

                    cx, cy, bw, bh = xywh
                    x = max(0, int(cx - bw / 2))
                    y = max(0, int(cy - bh / 2))
                    box_w = min(w - x, int(bw))
                    box_h = min(h - y, int(bh))

                    if box_w > 20 and box_h > 20:
                        vtype = self.VEHICLE_CLASS_MAP.get(cls_id, "Vehicle")
                        detections.append({
                            "bbox": [x, y, box_w, box_h],
                            "confidence": round(conf, 2),
                            "class_id": cls_id,
                            "label": f"{vtype} • {int(conf * 100)}%",
                            "vehicle_type": vtype,
                            "plate_number": None,
                            "plate_status": "PENDING"
                        })
        except Exception as e:
            print(f"[VehicleDetector] Detection error: {e}")

        return detections

    def draw_annotations(self, frame: np.ndarray, detections: List[Dict[str, Any]]) -> np.ndarray:
        """
        Draws tactical defense reticles and TrueType pill badges on detected vehicles.
        """
        annotated = frame.copy()
        for det in detections:
            x, y, w, h = det["bbox"]
            vtype = det.get("vehicle_type", "Vehicle")
            conf = det.get("confidence", 0.0)
            conf_pct = int(conf * 100)
            plate_status = det.get("plate_status", "CIVILIAN")
            plate_num = det.get("plate_number")

            if plate_status == "AUTHORIZED_MILITARY":
                color_bgr = (129, 185, 16)      # Emerald Green
                accent_rgb = (16, 185, 129)
                badge_text = f"CONVOY • {plate_num} [STORED]" if plate_num else f"CONVOY • {vtype} [AUTHORIZED]"
            elif plate_status == "SUSPECT_STOLEN":
                color_bgr = (68, 68, 239)       # Crimson Alert
                accent_rgb = (239, 68, 68)
                badge_text = f"INTERCEPT • {plate_num} [RED ALERT]" if plate_num else f"INTERCEPT • {vtype} [WANTED]"
            elif plate_num:
                color_bgr = (129, 185, 16)      # Emerald Green (Recognized & Persisted)
                accent_rgb = (16, 185, 129)
                badge_text = f"{vtype.upper()} • {plate_num} [STORED]"
            elif plate_status == "UNREADABLE":
                color_bgr = (245, 158, 11)      # Amber Orange (Logged as Unreadable)
                accent_rgb = (245, 158, 11)
                badge_text = f"{vtype.upper()} • OBSCURED [STORED]"
            else:
                color_bgr = (212, 182, 6)       # Cyan
                accent_rgb = (6, 182, 212)
                badge_text = f"{vtype.upper()} • READING PLATE..."

            # Sleek corner brackets (┌ ┐ └ ┘)
            arm_w = max(14, min(36, int(w * 0.15)))
            arm_h = max(14, min(36, int(h * 0.15)))
            thick = 2

            # Top-Left
            cv2.line(annotated, (x, y), (x + arm_w, y), color_bgr, thick, cv2.LINE_AA)
            cv2.line(annotated, (x, y), (x, y + arm_h), color_bgr, thick, cv2.LINE_AA)
            # Top-Right
            cv2.line(annotated, (x + w, y), (x + w - arm_w, y), color_bgr, thick, cv2.LINE_AA)
            cv2.line(annotated, (x + w, y), (x + w, y + arm_h), color_bgr, thick, cv2.LINE_AA)
            # Bottom-Left
            cv2.line(annotated, (x, y + h), (x + arm_w, y + h), color_bgr, thick, cv2.LINE_AA)
            cv2.line(annotated, (x, y + h), (x, y + h - arm_h), color_bgr, thick, cv2.LINE_AA)
            # Bottom-Right
            cv2.line(annotated, (x + w, y + h), (x + w - arm_w, y + h), color_bgr, thick, cv2.LINE_AA)
            cv2.line(annotated, (x + w, y + h), (x + w, y + h - arm_h), color_bgr, thick, cv2.LINE_AA)

            # Modern Glassmorphic Badge
            badge_y = y - 28 if (y - 28 >= 4) else (y + 4)
            draw_modern_pill_badge(
                annotated,
                x=x,
                y=badge_y,
                text=badge_text,
                accent_rgb=accent_rgb,
                bg_rgba=(10, 15, 24, 215),
                radius=6,
                font_size=12
            )

        return annotated

    def release(self) -> None:
        self.model = None
        self._is_initialized = False
