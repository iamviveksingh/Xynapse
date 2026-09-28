import os
import json
import time
import threading
import cv2
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from backend.database.database import SessionLocal
from backend.database.models import FaceProfile


class FaceRecognizer:
    """
    SFace Deep Learning Face Recognition Engine.
    Uses OpenCV's FaceRecognizerSF model (128-D embeddings) paired with YuNet landmarks
    for real-time face matching (Authorized Guard Whitelist vs. Suspect Watchlist).
    """

    # SFace cosine match threshold: Official benchmark is 0.363.
    # 0.38 provides high-precision separation, preventing false positive matches on friends/visitors.
    MATCH_THRESHOLD_COSINE = float(os.getenv("XYNAPSE_COSINE_THRESHOLD", "0.38"))

    def __init__(self, model_path: Optional[str] = None):
        self._lock = threading.Lock()
        self.sface: Optional[cv2.FaceRecognizerSF] = None
        self.yunet: Optional[cv2.FaceDetectorYN] = None
        self.yunet_path: Optional[str] = None
        self._profiles: List[Dict[str, Any]] = []
        self._is_initialized = False
        self.model_path = model_path
        self.initialize()

    def initialize(self) -> bool:
        """Finds and loads both SFace recognition model and YuNet detection model."""
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidate_sface_paths = [
            self.model_path,
            os.path.join(os.getcwd(), "models", "face_recognition_sface_2021dec.onnx"),
            os.path.join(os.getcwd(), "xynapse", "models", "face_recognition_sface_2021dec.onnx"),
            os.path.join(os.path.dirname(script_dir), "models", "face_recognition_sface_2021dec.onnx"),
            os.path.join(script_dir, "models", "face_recognition_sface_2021dec.onnx"),
        ]

        candidate_yunet_paths = [
            os.path.join(os.getcwd(), "models", "face_detection_yunet_2023mar.onnx"),
            os.path.join(os.getcwd(), "xynapse", "models", "face_detection_yunet_2023mar.onnx"),
            os.path.join(os.path.dirname(script_dir), "models", "face_detection_yunet_2023mar.onnx"),
            os.path.join(script_dir, "models", "face_detection_yunet_2023mar.onnx"),
        ]

        # 1. Load SFace
        loaded_sface = None
        for p in candidate_sface_paths:
            if p and os.path.exists(p) and hasattr(cv2, "FaceRecognizerSF"):
                try:
                    self.sface = cv2.FaceRecognizerSF.create(p, "")
                    loaded_sface = p
                    self._is_initialized = True
                    break
                except Exception as e:
                    print(f"[FaceRecognizer] Failed to load SFace at {p}: {e}")

        # 2. Load YuNet for face enrollment
        for yp in candidate_yunet_paths:
            if yp and os.path.exists(yp) and hasattr(cv2, "FaceDetectorYN"):
                try:
                    self.yunet = cv2.FaceDetectorYN.create(
                        model=yp,
                        config="",
                        input_size=(320, 320),
                        score_threshold=0.40,
                        nms_threshold=0.3,
                        top_k=10
                    )
                    self.yunet_path = yp
                    break
                except Exception as e:
                    print(f"[FaceRecognizer] Failed to load YuNet at {yp}: {e}")

        if self._is_initialized:
            print(f"[FaceRecognizer] SFace 128-D Model Loaded from: {loaded_sface}")
            if self.yunet:
                print(f"[FaceRecognizer] YuNet Enrollment Detector Loaded from: {self.yunet_path}")
            self.reload_profiles()
            return True
        else:
            print("[FaceRecognizer] SFace model not found. Face recognition in bypass mode.")
            return False

    def reload_profiles(self) -> int:
        """Loads all enrolled face profiles and embeddings from SQLite into memory for O(1) matching."""
        db = SessionLocal()
        try:
            records = db.query(FaceProfile).all()
            profiles = []
            for rec in records:
                try:
                    emb_list = json.loads(rec.embedding_json)
                    emb_array = np.array(emb_list, dtype=np.float32).reshape(1, 128)
                    profiles.append({
                        "id": rec.id,
                        "name": rec.name,
                        "role": rec.role,
                        "notes": rec.notes or "",
                        "photo_path": rec.photo_path,
                        "embedding": emb_array
                    })
                except Exception as ex:
                    print(f"[FaceRecognizer] Error parsing embedding for profile {rec.id}: {ex}")
            self._profiles = profiles
            print(f"[FaceRecognizer] Loaded {len(self._profiles)} enrolled face profile(s) into memory.")
            return len(self._profiles)
        except Exception as e:
            print(f"[FaceRecognizer] DB Error loading profiles: {e}")
            return 0
        finally:
            db.close()

    def extract_feature(self, frame: np.ndarray, raw_face: np.ndarray) -> Optional[np.ndarray]:
        """Aligns face using 5 YuNet landmarks and extracts 128-D L2-normalized feature vector."""
        if not self._is_initialized or self.sface is None or frame is None or raw_face is None:
            return None
        with self._lock:
            # 1. Primary: Align crop using 5 landmarks
            try:
                aligned = self.sface.alignCrop(frame, raw_face)
                if aligned is not None and aligned.size > 0:
                    feature = self.sface.feature(aligned)
                    if feature is not None and not np.isnan(feature).any():
                        return feature
            except Exception as e:
                print(f"[FaceRecognizer] Landmark alignment failed: {e}")

            # 2. Fallback: Direct bounding box crop with slight margin resized to (112, 112)
            try:
                h, w = frame.shape[:2]
                fx, fy, fw, fh = int(raw_face[0]), int(raw_face[1]), int(raw_face[2]), int(raw_face[3])
                pad_w = int(fw * 0.12)
                pad_h = int(fh * 0.12)
                x1 = max(0, fx - pad_w)
                y1 = max(0, fy - pad_h)
                x2 = min(w, fx + fw + pad_w)
                y2 = min(h, fy + fh + pad_h)
                if x2 > x1 and y2 > y1:
                    crop = frame[y1:y2, x1:x2]
                    if crop.size > 0:
                        resized = cv2.resize(crop, (112, 112), interpolation=cv2.INTER_LINEAR)
                        feature = self.sface.feature(resized)
                        if feature is not None and not np.isnan(feature).any():
                            return feature
            except Exception as e:
                print(f"[FaceRecognizer] Direct crop fallback failed: {e}")

            return None

    def match_feature(self, feature: np.ndarray, threshold: Optional[float] = None) -> Dict[str, Any]:
        """Compares a 128-D feature vector against all enrolled profiles in memory."""
        th = threshold if threshold is not None else self.MATCH_THRESHOLD_COSINE
        if feature is None or not self._profiles or self.sface is None:
            return {"matched": False, "name": "Unknown", "role": "UNKNOWN", "similarity": 0.0}

        best_sim = -1.0
        best_profile = None

        with self._lock:
            for prof in self._profiles:
                try:
                    sim = float(self.sface.match(feature, prof["embedding"], cv2.FaceRecognizerSF_FR_COSINE))
                    if sim > best_sim:
                        best_sim = sim
                        best_profile = prof
                except Exception as e:
                    print(f"[FaceRecognizer] Match calculation error: {e}")

        if best_profile and best_sim >= th:
            return {
                "matched": True,
                "id": best_profile["id"],
                "name": best_profile["name"],
                "role": best_profile["role"],
                "notes": best_profile["notes"],
                "similarity": round(best_sim, 2)
            }

        return {
            "matched": False,
            "name": "Unknown",
            "role": "UNKNOWN",
            "similarity": round(max(0.0, best_sim), 2)
        }

    def process_frame_detections(self, frame: np.ndarray, detections: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Takes detected faces from FaceDetector, matches them against the roster,
        and annotates them with classification results.
        Returns aggregate status (all_authorized, has_suspect, suspects, etc.).
        """
        suspects = []
        authorized_count = 0
        unknown_count = 0

        for d in detections:
            # If detection has a human face, it is definitively a Human!
            if d.get("raw_face") is not None:
                d["is_animal"] = False
                if d.get("role") == "WILDLIFE":
                    d["role"] = "UNKNOWN"
            elif d.get("is_animal") or d.get("role") == "WILDLIFE":
                # Strictly protect wildlife/animals (e.g. dogs, cattle) from being classified as human intruders
                continue

            raw_face = d.get("raw_face")
            if raw_face is not None and self._is_initialized and len(self._profiles) > 0:
                feat = self.extract_feature(frame, raw_face)
                if feat is not None:
                    match_res = self.match_feature(feat)
                    if match_res["matched"]:
                        d["is_recognized"] = True
                        d["matched_name"] = match_res["name"]
                        d["role"] = match_res["role"]
                        d["similarity"] = match_res["similarity"]
                        if match_res["role"] == "AUTHORIZED_GUARD":
                            d["label"] = f"Authorized: {match_res['name']}"
                            authorized_count += 1
                        elif match_res["role"] == "SUSPECT_WATCHLIST":
                            d["label"] = f"SUSPECT: {match_res['name']}"
                            suspects.append({
                                "name": match_res["name"],
                                "notes": match_res["notes"],
                                "similarity": match_res["similarity"],
                                "bbox": d["bbox"]
                            })
                        else:
                            d["label"] = f"{match_res['name']}"
                        continue

            # Fallback if unrecognised human
            d["is_recognized"] = False
            d["matched_name"] = None
            d["role"] = "UNKNOWN"
            d["similarity"] = 0.0
            d["label"] = "Unknown Person"
            unknown_count += 1

        human_detections = [d for d in detections if not (d.get("is_animal") or d.get("role") == "WILDLIFE")]
        total_faces = len(human_detections)
        all_authorized = (total_faces > 0 and authorized_count == total_faces and len(suspects) == 0)
        has_suspect = len(suspects) > 0

        return {
            "total_faces": total_faces,
            "authorized_count": authorized_count,
            "unknown_count": unknown_count,
            "all_authorized": all_authorized,
            "has_suspect": has_suspect,
            "suspects": suspects
        }

    def enroll_from_image(
        self,
        image: np.ndarray,
        name: str,
        role: str,
        notes: str = "",
        yunet_detector = None,
        save_photo_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Enrolls a new face from a camera image or uploaded file.
        Detects face, extracts 128-D embedding, saves record to SQLite, and updates cache.
        """
        if image is None or image.size == 0:
            raise ValueError("Invalid image: Image data is empty.")

        # Ensure image is resized down to sensible dimensions for YuNet
        max_dim = 1280
        h, w = image.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / float(max(h, w))
            image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            h, w = image.shape[:2]

        # Use provided YuNet detector or self.yunet
        detector = yunet_detector or self.yunet
        if detector is None:
            raise RuntimeError("Face detection model (YuNet) is not initialized.")

        # Detect face in image
        detector.setInputSize((w, h))
        _, faces = detector.detect(image)
        if faces is None or len(faces) == 0:
            # Try with reduced threshold for low-contrast / dim photos
            try:
                detector.setScoreThreshold(0.25)
                _, faces = detector.detect(image)
            finally:
                detector.setScoreThreshold(0.40)

        if faces is None or len(faces) == 0:
            raise ValueError("No clear face found in photo. Please upload a clear, front-facing portrait with good lighting.")

        # Sort candidate faces: prioritize larger face area (w * h) and higher confidence
        sorted_faces = sorted(
            faces,
            key=lambda f: (float(f[2]) * float(f[3]), float(f[14])),
            reverse=True
        )

        # Extract embedding from most prominent face
        feature = None
        best_face = None
        for cand in sorted_faces:
            cand_feat = self.extract_feature(image, cand)
            if cand_feat is not None:
                feature = cand_feat
                best_face = cand
                break

        if feature is None:
            raise ValueError("Failed to extract facial features from image.")

        # Save photo to disk if requested (crops a clean portrait avatar around the detected face)
        rel_photo_path = None
        if save_photo_path:
            os.makedirs(os.path.dirname(save_photo_path), exist_ok=True)
            saved_img = image
            if best_face is not None:
                try:
                    fx, fy, fw, fh = int(best_face[0]), int(best_face[1]), int(best_face[2]), int(best_face[3])
                    pad_x = int(fw * 0.40)
                    pad_y = int(fh * 0.45)
                    x1 = max(0, fx - pad_x)
                    y1 = max(0, fy - pad_y)
                    x2 = min(image.shape[1], fx + fw + pad_x)
                    y2 = min(image.shape[0], fy + fh + int(pad_y * 0.8))
                    crop = image[y1:y2, x1:x2]
                    if crop.size > 0 and crop.shape[0] >= 30 and crop.shape[1] >= 30:
                        saved_img = crop
                except Exception as crop_err:
                    print(f"[FaceRecognizer] Face crop failed, saving full image: {crop_err}")
            cv2.imwrite(save_photo_path, saved_img)
            filename = os.path.basename(save_photo_path)
            rel_photo_path = f"/evidence/faces/{filename}"

        # Persist to SQLite
        embedding_list = feature.flatten().tolist()
        db = SessionLocal()
        try:
            profile = FaceProfile(
                name=name.strip(),
                role=role.strip().upper(),
                notes=notes.strip() if notes else "",
                photo_path=rel_photo_path,
                embedding_json=json.dumps(embedding_list),
                created_at=datetime.utcnow()
            )
            db.add(profile)
            db.commit()
            db.refresh(profile)
            profile_dict = profile.to_dict()
        except Exception as e:
            db.rollback()
            raise RuntimeError(f"Database error saving face profile: {e}")
        finally:
            db.close()

        # Refresh in-memory profiles
        self.reload_profiles()
        return profile_dict
