import os
import time
import math
from collections import deque
from typing import List, Dict, Any, Optional, Tuple
import cv2
import numpy as np

from backend.detection.base_detector import BaseDetector
from backend.detection.hud_renderer import draw_modern_pill_badge
from backend.detection.face_detector import FaceDetector
import threading

# Global inference lock to prevent PyTorch C++ MKL/OpenMP race conditions across concurrent capture threads
_yolo_global_lock = threading.Lock()


class SimpleCentroidTracker:
    """
    Lightweight, high-speed multi-person persistent tracker using IoU and centroid distance.
    Maintains persistent IDs (Person #01, Person #02) across frames and traces movement history.
    """

    def __init__(self, max_missed_frames: int = 15, max_distance: float = 85.0):
        self.next_id = 1
        self.tracks: Dict[int, Dict[str, Any]] = {}
        self.max_missed_frames = max_missed_frames
        self.max_distance = max_distance

    @staticmethod
    def _compute_iou(boxA: List[int], boxB: List[int]) -> float:
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[0] + boxA[2], boxB[0] + boxB[2])
        yB = min(boxA[1] + boxA[3], boxB[1] + boxB[3])
        inter_w = max(0, xB - xA)
        inter_h = max(0, yB - yA)
        inter_area = inter_w * inter_h
        areaA = boxA[2] * boxA[3]
        areaB = boxB[2] * boxB[3]
        union_area = float(areaA + areaB - inter_area)
        return (inter_area / union_area) if union_area > 0 else 0.0

    def update(self, detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        now = time.time()

        # If no active detections, age all tracks
        if len(detections) == 0:
            dead_ids = []
            for tid, trk in self.tracks.items():
                trk["missed"] += 1
                if trk["missed"] > self.max_missed_frames:
                    dead_ids.append(tid)
            for tid in dead_ids:
                del self.tracks[tid]
            return []

        # If no existing tracks, initialize all detections
        if len(self.tracks) == 0:
            for det in detections:
                tid = self.next_id
                self.next_id += 1
                bx, by, bw, bh = det["bbox"]
                cx = int(bx + bw / 2)
                cy = int(by + bh / 2)
                history = deque(maxlen=25)
                history.append((cx, cy))
                is_anim = det.get("is_animal", False)
                anim_type = det.get("animal_type", "Wildlife") if is_anim else None
                self.tracks[tid] = {
                    "id": tid,
                    "bbox": det["bbox"],
                    "centroid": (cx, cy),
                    "history": history,
                    "first_seen": now,
                    "last_seen": now,
                    "missed": 0,
                    "role": "WILDLIFE" if is_anim else det.get("role", "UNKNOWN"),
                    "matched_name": det.get("matched_name", None),
                    "is_animal": is_anim,
                    "animal_type": anim_type
                }
                det["track_id"] = tid
                det["is_animal"] = is_anim
                det["animal_type"] = anim_type
                det["label"] = f"{anim_type} #{tid:02d}" if is_anim else f"Person #{tid:02d}"
                det["dwell_seconds"] = 0.0
                det["history"] = list(history)
                det["role"] = self.tracks[tid]["role"]
                det["matched_name"] = self.tracks[tid]["matched_name"]
            return detections

        # Match existing tracks to new detections via IoU and distance
        track_ids = list(self.tracks.keys())
        cost_matrix = []
        for tid in track_ids:
            trk = self.tracks[tid]
            tcx, tcy = trk["centroid"]
            row = []
            for det in detections:
                bx, by, bw, bh = det["bbox"]
                dcx = bx + bw / 2
                dcy = by + bh / 2
                dist = math.hypot(tcx - dcx, tcy - dcy)
                iou = self._compute_iou(trk["bbox"], det["bbox"])
                # Combined metric: high IoU reduces distance cost
                effective_cost = dist - (iou * 60.0)
                row.append(effective_cost)
            cost_matrix.append(row)

        used_tracks = set()
        used_dets = set()

        # Greedy association
        for _ in range(min(len(track_ids), len(detections))):
            min_val = float("inf")
            best_t_idx = -1
            best_d_idx = -1
            for t_idx in range(len(track_ids)):
                if t_idx in used_tracks:
                    continue
                for d_idx in range(len(detections)):
                    if d_idx in used_dets:
                        continue
                    if cost_matrix[t_idx][d_idx] < min_val:
                        min_val = cost_matrix[t_idx][d_idx]
                        best_t_idx = t_idx
                        best_d_idx = d_idx

            if min_val <= self.max_distance and best_t_idx >= 0 and best_d_idx >= 0:
                tid = track_ids[best_t_idx]
                det = detections[best_d_idx]
                bx, by, bw, bh = det["bbox"]
                cx = int(bx + bw / 2)
                cy = int(by + bh / 2)

                trk = self.tracks[tid]
                trk["bbox"] = det["bbox"]
                trk["centroid"] = (cx, cy)
                trk["history"].append((cx, cy))
                trk["last_seen"] = now
                # Role updates from face recognizer or detection
                if det.get("role") and det["role"] not in ("UNKNOWN", "WILDLIFE"):
                    trk["role"] = det["role"]
                    trk["matched_name"] = det.get("matched_name")

                # Animal vs Human persistence
                if det.get("is_animal"):
                    trk["is_animal"] = True
                    trk["animal_type"] = det.get("animal_type", "Wildlife")
                    trk["role"] = "WILDLIFE"
                else:
                    trk["is_animal"] = False
                    trk["animal_type"] = None
                    if trk.get("role") == "WILDLIFE":
                        trk["role"] = det.get("role", "UNKNOWN")
                    if det.get("role") and det["role"] != "WILDLIFE":
                        trk["role"] = det["role"]
                        trk["matched_name"] = det.get("matched_name")

                dwell = round(now - trk["first_seen"], 1)
                det["track_id"] = tid
                is_anim = trk.get("is_animal", False)
                det["is_animal"] = is_anim
                det["animal_type"] = trk.get("animal_type") if is_anim else None
                det["label"] = f"{det['animal_type']} #{tid:02d}" if is_anim else f"Person #{tid:02d}"
                det["dwell_seconds"] = dwell
                det["history"] = list(trk["history"])
                det["role"] = trk["role"]
                det["matched_name"] = trk["matched_name"]

                used_tracks.add(best_t_idx)
                used_dets.add(best_d_idx)
            else:
                break

        # Unmatched tracks
        for t_idx, tid in enumerate(track_ids):
            if t_idx not in used_tracks:
                self.tracks[tid]["missed"] += 1

        # Delete expired tracks
        dead_ids = [tid for tid, trk in self.tracks.items() if trk["missed"] > self.max_missed_frames]
        for tid in dead_ids:
            del self.tracks[tid]

        # New detections get fresh tracks
        for d_idx, det in enumerate(detections):
            if d_idx not in used_dets:
                tid = self.next_id
                self.next_id += 1
                bx, by, bw, bh = det["bbox"]
                cx = int(bx + bw / 2)
                cy = int(by + bh / 2)
                history = deque(maxlen=25)
                history.append((cx, cy))
                is_anim = det.get("is_animal", False)
                anim_type = det.get("animal_type", "Wildlife") if is_anim else None
                self.tracks[tid] = {
                    "id": tid,
                    "bbox": det["bbox"],
                    "centroid": (cx, cy),
                    "history": history,
                    "first_seen": now,
                    "last_seen": now,
                    "missed": 0,
                    "role": "WILDLIFE" if is_anim else det.get("role", "UNKNOWN"),
                    "matched_name": det.get("matched_name", None),
                    "is_animal": is_anim,
                    "animal_type": anim_type
                }
                det["track_id"] = tid
                det["is_animal"] = is_anim
                det["animal_type"] = anim_type
                det["label"] = f"{anim_type} #{tid:02d}" if is_anim else f"Person #{tid:02d}"
                det["dwell_seconds"] = 0.0
                det["history"] = list(history)
                det["role"] = self.tracks[tid]["role"]
                det["matched_name"] = self.tracks[tid]["matched_name"]

        return detections


ANIMAL_CLASS_NAMES = {
    14: "Bird",
    15: "Cat",
    16: "Dog",
    17: "Horse",
    18: "Sheep",
    19: "Cattle",
    20: "Elephant",
    21: "Wildlife",
    22: "Zebra",
    23: "Giraffe"
}
PERCEPTION_CLASSES = [0] + list(ANIMAL_CLASS_NAMES.keys())


class PersonDetector(BaseDetector):
    """
    Intelligent Full-Body Human & Wildlife Perception Engine.
    Powered by YOLOv8 deep neural network optimized for CPU execution.
    Detects humans (walking, crouching, crawling, masked) and isolates border wildlife
    (cattle, dogs, horses) to eliminate tripwire false alarms as mandated by SSB/MHA.
    Integrates persistent ID tracking and motion trajectories.
    """

    def __init__(self, min_confidence: float = 0.40, model_path: Optional[str] = None):
        self.min_confidence = min_confidence
        self.model_path = model_path
        self.model = None
        self.tracker = SimpleCentroidTracker()
        self.fallback_face_detector = FaceDetector(min_confidence=0.45)
        self.use_yolo = False
        self._is_initialized = False
        self.initialize()

    def initialize(self) -> bool:
        """Finds and loads YOLOv8 model for full-body human perception."""
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidate_paths = [
            self.model_path,
            os.path.join(os.getcwd(), "models", "yolov8n.pt"),
            os.path.join(os.getcwd(), "xynapse", "models", "yolov8n.pt"),
            os.path.join(script_dir, "models", "yolov8n.pt"),
            os.path.join(os.path.dirname(script_dir), "models", "yolov8n.pt"),
            os.path.join(os.getcwd(), "models", "yolov8n.onnx"),
            os.path.join(os.getcwd(), "xynapse", "models", "yolov8n.onnx"),
            os.path.join(script_dir, "models", "yolov8n.onnx"),
        ]

        for p in candidate_paths:
            if p and os.path.exists(p):
                try:
                    from ultralytics import YOLO
                    self.model = YOLO(p)
                    self.use_yolo = True
                    self._is_initialized = True
                    print(f"[PersonDetector] Loaded YOLOv8 Full-Body Human & Wildlife Model from: {p}")
                    # Warm up face fallback detector as well for FRS association
                    self.fallback_face_detector.initialize()
                    return True
                except Exception as e:
                    print(f"[PersonDetector] Failed to load YOLO ({p}): {e}")

        # Fallback to FaceDetector if YOLO isn't available
        print("[PersonDetector] YOLOv8 unavailable. Falling back to FaceDetector.")
        self.use_yolo = False
        self._is_initialized = self.fallback_face_detector.initialize()
        return self._is_initialized

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Runs perception on the input frame for both humans and wildlife.
        Returns persistent tracked detections with IDs and movement history.
        """
        if not self._is_initialized or frame is None or frame.size == 0:
            return []

        h, w = frame.shape[:2]
        raw_detections = []

        # A) YOLOv8 Perception (Human: 0, Wildlife: 14-23)
        if self.use_yolo and self.model is not None:
            try:
                with _yolo_global_lock:
                    results = self.model(
                        frame,
                        classes=PERCEPTION_CLASSES,
                        conf=self.min_confidence,
                        verbose=False,
                        imgsz=320             # Highly optimized for 25-30+ FPS CPU throughput
                    )

                if results and len(results) > 0:
                    boxes = results[0].boxes
                    for box in boxes:
                        conf = float(box.conf[0].item())
                        cls_id = int(box.cls[0].item())
                        xywh = box.xywh[0].tolist()
                        cx, cy, bw, bh = xywh
                        x = max(0, int(cx - bw / 2))
                        y = max(0, int(cy - bh / 2))
                        box_w = min(w - x, int(bw))
                        box_h = min(h - y, int(bh))

                        # Filter out tiny noise artifacts
                        if box_w > 18 and box_h > 24:
                            is_candidate_animal = cls_id in ANIMAL_CLASS_NAMES
                            if conf < self.min_confidence:
                                continue

                            # Biometric discrimination:
                            # Check if a genuine human face is visible in the upper region of the bounding box
                            found_human_face = None
                            if self.fallback_face_detector and self.fallback_face_detector._is_initialized:
                                uh = max(30, int(box_h * 0.65))
                                upper_roi = frame[y:y+uh, x:x+box_w]
                                if upper_roi.size > 0:
                                    try:
                                        roi_faces = self.fallback_face_detector.detect(upper_roi)
                                        if roi_faces:
                                            rf = roi_faces[0]
                                            face_conf = rf.get("confidence", 0.0)
                                            raw_f = rf.get("raw_face")
                                            # Verified human face with high confidence (> 0.50)
                                            if face_conf >= 0.50 and raw_f is not None:
                                                shifted_f = raw_f.copy()
                                                shifted_f[0] += x
                                                shifted_f[1] += y
                                                for l_idx in range(4, 14, 2):
                                                    shifted_f[l_idx] += x
                                                    shifted_f[l_idx + 1] += y
                                                landmarks_shifted = [
                                                    [lx + x, ly + y] for lx, ly in rf.get("landmarks", [])
                                                ]
                                                found_human_face = {
                                                    "confidence": face_conf,
                                                    "raw_face": shifted_f,
                                                    "landmarks": landmarks_shifted
                                                }
                                    except Exception:
                                        pass

                            # Absolute rule: If a verified human face is present, it is ALWAYS a Human!
                            if found_human_face is not None:
                                is_animal = False
                            elif is_candidate_animal:
                                is_animal = True
                            else:
                                is_animal = False

                            if is_animal:
                                animal_name = ANIMAL_CLASS_NAMES.get(cls_id, "Wildlife")
                                det_item = {
                                    "bbox": [x, y, box_w, box_h],
                                    "confidence": round(conf, 2),
                                    "label": f"Wildlife • {animal_name}",
                                    "detection_type": "WILDLIFE",
                                    "is_animal": True,
                                    "animal_type": animal_name,
                                    "role": "WILDLIFE",
                                    "landmarks": [],
                                    "raw_face": None
                                }
                            else:
                                det_item = {
                                    "bbox": [x, y, box_w, box_h],
                                    "confidence": round(conf, 2),
                                    "label": "Human",
                                    "detection_type": "FULL_BODY",
                                    "is_animal": False,
                                    "landmarks": found_human_face["landmarks"] if found_human_face else [],
                                    "raw_face": found_human_face["raw_face"] if found_human_face else None
                                }
                            raw_detections.append(det_item)
            except Exception as ex:
                print(f"[PersonDetector] YOLO inference error: {ex}")

        # Human Priority Suppression: Suppress any animal box that overlaps with a human
        human_boxes = [d["bbox"] for d in raw_detections if not d.get("is_animal")]
        filtered_detections = []
        for d in raw_detections:
            if d.get("is_animal"):
                overlaps_human = False
                for hb in human_boxes:
                    if SimpleCentroidTracker._compute_iou(d["bbox"], hb) > 0.10:
                        overlaps_human = True
                        break
                if not overlaps_human:
                    filtered_detections.append(d)
            else:
                filtered_detections.append(d)

        # Fallback full-frame YuNet face detector:
        # Run ONLY if no human was detected. AND if an animal is already detected in the frame,
        # ignore any face that overlaps with the animal's bounding box to prevent dog snout false-positives!
        has_human = any(not d.get("is_animal") for d in filtered_detections)
        animal_boxes = [d["bbox"] for d in filtered_detections if d.get("is_animal")]
        if not has_human and self.fallback_face_detector:
            face_dets = self.fallback_face_detector.detect(frame)
            for fd in face_dets:
                fx, fy, fw, fh = fd["bbox"]
                # Guard against animal false-positives:
                # If this detected face falls inside or overlaps an animal bounding box, suppress it
                overlaps_animal = False
                for ab in animal_boxes:
                    ax, ay, aw, ah = ab
                    fcx, fcy = fx + fw / 2, fy + fh / 2
                    if ax <= fcx <= ax + aw and ay <= fcy <= ay + ah:
                        overlaps_animal = True
                        break
                    if SimpleCentroidTracker._compute_iou([fx, fy, fw, fh], ab) > 0.15:
                        overlaps_animal = True
                        break
                if overlaps_animal:
                    continue

                bx = max(0, fx - int(fw * 0.5))
                by = max(0, fy - int(fh * 0.2))
                bw = min(w - bx, int(fw * 2.0))
                bh = min(h - by, int(fh * 3.5))
                filtered_detections.append({
                    "bbox": [bx, by, bw, bh],
                    "confidence": fd.get("confidence", 0.90),
                    "label": "Human",
                    "landmarks": fd.get("landmarks", []),
                    "raw_face": fd.get("raw_face"),
                    "detection_type": "FACE_AUGMENTED",
                    "is_animal": False
                })

        # Apply multi-person persistent tracking
        tracked_detections = self.tracker.update(filtered_detections)
        return tracked_detections

    def draw_annotations(self, frame: np.ndarray, detections: List[Dict[str, Any]]) -> np.ndarray:
        """
        Renders mission-critical tactical HUD elements:
        - Sleek defense corner brackets around the human silhouette
        - Glowing motion trajectory ribbon (showing entry route)
        - Modern anti-aliased Segoe UI pill badge with live dwell time
        """
        annotated = frame.copy()

        for det in detections:
            x, y, w, h = det["bbox"]
            conf = det.get("confidence", 0.90)
            conf_pct = int(conf * 100)
            label = det.get("label", "Person")
            dwell = det.get("dwell_seconds", 0.0)
            role = det.get("role", "UNKNOWN")
            history = det.get("history", [])

            # Theme colors based on role
            if role == "AUTHORIZED_GUARD":
                color_bgr = (129, 185, 16)      # Emerald Green
                accent_rgb = (16, 185, 129)
                person_name = det.get("matched_name") or "Authorized Guard"
                tag_text = f"Authorized • {person_name} [{dwell}s]"
            elif role == "SUSPECT_WATCHLIST":
                color_bgr = (68, 68, 239)       # Crimson Alert
                accent_rgb = (239, 68, 68)
                person_name = det.get("matched_name") or "Wanted Suspect"
                tag_text = f"Wanted • {person_name} [{dwell}s]"
            elif det.get("is_animal"):
                color_bgr = (40, 180, 220)       # Tactical Amber / Olive
                accent_rgb = (220, 180, 40)
                anim_name = det.get("animal_type") or "Wildlife"
                tag_text = f"Wildlife • {anim_name} [Non-Threat]"
            else:
                color_bgr = (212, 182, 6)       # Electric Cyan
                accent_rgb = (6, 182, 212)
                tag_text = f"{label} • {conf_pct}% [{dwell}s]"

            # 1. Motion Trajectory Ribbon (Traces human walking path)
            if len(history) > 1:
                pts = np.array(history, dtype=np.int32).reshape((-1, 1, 2))
                # Glowing trail: subtle semi-transparent background trail
                cv2.polylines(annotated, [pts], False, color_bgr, 1, cv2.LINE_AA)
                # Small directional pulse dot at recent centroid
                last_pt = history[-1]
                cv2.circle(annotated, last_pt, 3, (255, 255, 255), -1, cv2.LINE_AA)

            # 2. Sleek Defense Corner Brackets (┌ ┐ └ ┘)
            arm_w = max(12, min(36, int(w * 0.16)))
            arm_h = max(12, min(36, int(h * 0.16)))
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

            # 3. Modern Anti-Aliased Glassmorphic Pill Badge (Segoe UI TrueType font)
            badge_y = y - 28 if (y - 28 >= 6) else (y + 6)
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
        self.model = None
        self._is_initialized = False
