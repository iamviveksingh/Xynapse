import os
import cv2
import numpy as np
from typing import List, Dict, Any
from backend.detection.base_detector import BaseDetector
from backend.detection.hud_renderer import draw_modern_pill_badge

class FaceDetector(BaseDetector):
    """
    Advanced Multi-Face Deep Learning Detector.
    Uses OpenCV's YuNet ONNX neural network for robust multi-face detection at any angle,
    with automatic fallback to OpenCV's Haar Cascade if model is unavailable.
    """

    def __init__(self, min_confidence: float = 0.50):
        self.min_confidence = min_confidence
        self.yunet = None
        self.cascade = None
        self.use_yunet = False
        self._is_initialized = False

    def initialize(self) -> bool:
        if self._is_initialized and (self.yunet is not None or self.cascade is not None):
            return True
        # 1. Try loading YuNet Deep Learning Model
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model_paths = [
            os.path.join(script_dir, "models", "face_detection_yunet_2023mar.onnx"),
            os.path.join(os.getcwd(), "xynapse", "models", "face_detection_yunet_2023mar.onnx"),
            os.path.join(os.getcwd(), "models", "face_detection_yunet_2023mar.onnx"),
        ]

        for mp in model_paths:
            if os.path.exists(mp) and hasattr(cv2, "FaceDetectorYN"):
                try:
                    self.yunet = cv2.FaceDetectorYN.create(
                        model=mp,
                        config="",
                        input_size=(320, 320),
                        score_threshold=self.min_confidence,
                        nms_threshold=0.3,
                        top_k=5000
                    )
                    self.use_yunet = True
                    self._is_initialized = True
                    print(f"[FaceDetector] Loaded Deep Learning YuNet model from: {mp}")
                    return True
                except Exception as e:
                    print(f"[FaceDetector] Failed to load YuNet ({mp}): {e}")

        # 2. Fallback to Haar Cascade
        try:
            cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
            self.cascade = cv2.CascadeClassifier(cascade_path)
            self._is_initialized = not self.cascade.empty()
            self.use_yunet = False
            print("[FaceDetector] Running in Haar Cascade fallback mode.")
            return self._is_initialized
        except Exception as e:
            print(f"[FaceDetector] Cascade fallback failed: {e}")
            self._is_initialized = False
            return False

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detects all visible faces simultaneously in the given frame.
        Returns:
            List of dicts: [
                {
                    "bbox": [x, y, w, h],
                    "confidence": 0.96,
                    "label": "Person #1 Face",
                    "landmarks": [...]
                }
            ]
        """
        if not self._is_initialized or frame is None or frame.size == 0:
            return []

        h, w = frame.shape[:2]
        detections = []

        # A) YuNet Deep Learning Detection
        if self.use_yunet and self.yunet is not None:
            try:
                self.yunet.setInputSize((w, h))
                _, faces = self.yunet.detect(frame)
                if faces is not None:
                    for idx, face in enumerate(faces):
                        x = max(0, int(face[0]))
                        y = max(0, int(face[1]))
                        box_w = min(w - x, int(face[2]))
                        box_h = min(h - y, int(face[3]))
                        conf = float(face[14])

                        if conf >= self.min_confidence and box_w > 15 and box_h > 15:
                            # 5 landmark points: right eye, left eye, nose tip, right mouth corner, left mouth corner
                            landmarks = [
                                [int(face[4]), int(face[5])],
                                [int(face[6]), int(face[7])],
                                [int(face[8]), int(face[9])],
                                [int(face[10]), int(face[11])],
                                [int(face[12]), int(face[13])],
                            ]
                            detections.append({
                                "bbox": [x, y, box_w, box_h],
                                "confidence": round(conf, 2),
                                "label": f"Human #{idx + 1}",
                                "landmarks": landmarks,
                                "raw_face": face.copy()
                            })
                return detections
            except Exception as e:
                print(f"[FaceDetector] YuNet inference error: {e}")

        # B) Haar Cascade Fallback
        if self.cascade is not None and not self.cascade.empty():
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.equalizeHist(gray)
                rects, reject_levels, level_weights = self.cascade.detectMultiScale3(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=4,
                    minSize=(30, 30),
                    outputRejectLevels=True
                )
                if len(rects) > 0:
                    for idx, (x, y, bw, bh) in enumerate(rects):
                        weight = float(level_weights[idx]) if idx < len(level_weights) else 1.0
                        conf = min(0.99, max(0.50, weight / 10.0))
                        if conf >= self.min_confidence:
                            detections.append({
                                "bbox": [int(x), int(y), int(bw), int(bh)],
                                "confidence": round(conf, 2),
                                "label": f"Human #{idx + 1}",
                                "landmarks": []
                            })
            except Exception as e:
                print(f"[FaceDetector] Cascade detection error: {e}")

        return detections

    @staticmethod
    def _blend_roi(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, bg_color: tuple, alpha: float = 0.75) -> None:
        """Blends a semi-transparent colored glass rectangle onto an image region."""
        h, w = img.shape[:2]
        rx1, ry1 = max(0, int(x1)), max(0, int(y1))
        rx2, ry2 = min(w, int(x2)), min(h, int(y2))
        if rx2 <= rx1 or ry2 <= ry1:
            return
        sub = img[ry1:ry2, rx1:rx2]
        overlay = sub.copy()
        cv2.rectangle(overlay, (0, 0), (rx2 - rx1, ry2 - ry1), bg_color, -1)
        cv2.addWeighted(overlay, alpha, sub, 1.0 - alpha, 0.0, sub)

    def draw_annotations(self, frame: np.ndarray, detections: List[Dict[str, Any]]) -> np.ndarray:
        """
        Draws sleek, high-precision defense reticles:
        - 4 Minimalist Corner Brackets (┌ ┐ └ ┘) framing the face with zero visual clutter
        - Modern Anti-Aliased TrueType pill badge (Segoe UI / Arial) with glowing role indicator
        """
        annotated = frame.copy()
        for det in detections:
            x, y, w, h = det["bbox"]
            conf = det["confidence"]
            label = det["label"]
            role = det.get("role", "UNKNOWN")
            conf_pct = int(conf * 100)

            sim = det.get("similarity", 0.0)
            sim_pct = int(round(sim * 100))

            if role == "AUTHORIZED_GUARD":
                color_bgr = (129, 185, 16)      # Emerald Green
                accent_rgb = (16, 185, 129)
                person_name = det.get("matched_name") or label.replace("Authorized: ", "")
                tag_text = f"Authorized • {person_name} ({sim_pct}%)" if sim_pct > 0 else f"Authorized • {person_name}"
            elif role == "SUSPECT_WATCHLIST":
                color_bgr = (68, 68, 239)       # Crimson Alert
                accent_rgb = (239, 68, 68)
                person_name = det.get("matched_name") or label.replace("Suspect: ", "")
                tag_text = f"Wanted • {person_name} ({sim_pct}%)" if sim_pct > 0 else f"Wanted • {person_name}"
            else:
                color_bgr = (212, 182, 6)       # Electric Cyan
                accent_rgb = (6, 182, 212)
                tag_text = f"Person • {conf_pct}%"

            # 1. Sleek, high-precision corner brackets ONLY (┌ ┐ └ ┘) - NO heavy outer box
            arm_w = max(10, min(24, int(w * 0.18)))
            arm_h = max(10, min(24, int(h * 0.18)))
            bracket_thick = 2

            # Top-Left Bracket
            cv2.line(annotated, (x, y), (x + arm_w, y), color_bgr, bracket_thick, cv2.LINE_AA)
            cv2.line(annotated, (x, y), (x, y + arm_h), color_bgr, bracket_thick, cv2.LINE_AA)
            # Top-Right Bracket
            cv2.line(annotated, (x + w, y), (x + w - arm_w, y), color_bgr, bracket_thick, cv2.LINE_AA)
            cv2.line(annotated, (x + w, y), (x + w, y + arm_h), color_bgr, bracket_thick, cv2.LINE_AA)
            # Bottom-Left Bracket
            cv2.line(annotated, (x, y + h), (x + arm_w, y + h), color_bgr, bracket_thick, cv2.LINE_AA)
            cv2.line(annotated, (x, y + h), (x, y + h - arm_h), color_bgr, bracket_thick, cv2.LINE_AA)
            # Bottom-Right Bracket
            cv2.line(annotated, (x + w, y + h), (x + w - arm_w, y + h), color_bgr, bracket_thick, cv2.LINE_AA)
            cv2.line(annotated, (x + w, y + h), (x + w, y + h - arm_h), color_bgr, bracket_thick, cv2.LINE_AA)

            # 2. Modern Anti-Aliased Glassmorphic Pill Badge (Segoe UI TrueType font)
            badge_y = y - 28 if (y - 28 >= 4) else (y + 4)
            draw_modern_pill_badge(
                annotated,
                x=x,
                y=badge_y,
                text=tag_text,
                accent_rgb=accent_rgb,
                bg_rgba=(10, 15, 24, 215),
                radius=6,
                font_size=12
            )

        return annotated

    def release(self) -> None:
        self.yunet = None
        self.cascade = None
        self._is_initialized = False
