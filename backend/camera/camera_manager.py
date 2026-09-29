import os
import time
import threading
import queue
import cv2
import numpy as np
import json
import urllib.parse
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

from backend.config import settings
from backend.database.database import SessionLocal
from backend.database.models import VehicleTransitLog, VehicleProfile, SyncOutbox
from backend.detection.face_detector import FaceDetector
from backend.detection.person_detector import PersonDetector, SimpleCentroidTracker
from backend.detection.intrusion_detector import VirtualTripwireDetector
from backend.detection.optical_pipeline import OpticalPipeline
from backend.detection.vehicle_detector import VehicleDetector
from backend.detection.anpr_engine import ANPREngine
from backend.alert.alert_engine import AlertEngine
from backend.evidence.snapshot import save_transit_snapshot

def redact_camera_source(source: str) -> str:
    """
    Redacts credentials embedded in RTSP / RTSPS URLs to prevent credential leakage.
    Example: rtsp://admin:secret123@192.168.1.50:554/live -> rtsp://admin:***@192.168.1.50:554/live
    Local indices and safe identifiers are returned unchanged.
    """
    if not source:
        return ""
    src_str = str(source).strip()
    if src_str.lower().startswith(("rtsp://", "rtsps://")):
        try:
            parsed = urllib.parse.urlsplit(src_str)
            if parsed.password:
                user_str = parsed.username or ""
                netloc = f"{user_str}:***@{parsed.hostname or ''}"
                if parsed.port:
                    netloc += f":{parsed.port}"
                return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
        except Exception:
            pass
    return src_str

class CameraManager:
    """
    Manages camera lifecycle, frame capture loop, real-time full-body human perception,
    multi-person spatial tracking, FPS computation, and MJPEG stream broadcasting.
    """

    _global_capture_lock = threading.Lock()

    def __init__(
        self,
        camera_id: str = "CAM-01",
        name: str = "Entrance Main (CAM-01)",
        source: str = "0",
        alert_engine: Optional[AlertEngine] = None,
        face_recognizer: Optional[Any] = None,
        surveillance_mode: str = "PERIMETER",
        optical_mode: str = "STANDARD"
    ):
        self.camera_id = camera_id
        self.name = name
        self.source = source
        self.alert_engine = alert_engine
        self.face_recognizer = face_recognizer
        self._initial_surveillance_mode = surveillance_mode
        self.optical_mode = optical_mode.upper() if optical_mode else "STANDARD"

        self.detector = PersonDetector(min_confidence=0.40)
        self.is_running = False
        self.status = "OFFLINE"  # ONLINE, OFFLINE, ERROR
        self.current_fps = 0.0
        self.current_face_count = 0
        self.latest_detections = []
        self.detection_active = True
        self.is_tampered = False
        self._tamper_start_time: Optional[float] = None
        self.latest_inference_latency_ms: float = 0.0

        # Cybersecurity Stream Integrity & Anti-Replay Engine
        self.is_stream_frozen = False
        self.stream_integrity = "SECURE"  # "SECURE" or "FROZEN_REPLAY_ATTACK"
        self._last_raw_gray: Optional[np.ndarray] = None
        self._frozen_frame_count: int = 0
        self._freeze_alert_sent = False

        # Face Recognition & Watchlist classification status
        self.is_authorized = False
        self.has_suspect = False
        self.active_suspects = []
        self._last_authorized_time: Optional[float] = None
        self._last_authorized_names: List[str] = []

        # Virtual Border Fence / Intrusion Detection
        self.tripwire = VirtualTripwireDetector(line_y_ratio=0.65, enabled=True)
        self.is_perimeter_breached = False

        # Tactical Multi-Band Optical Pipeline (STANDARD, LOW_LIGHT_ENHANCE, NVG_GREEN, FLIR_THERMAL)
        self.optical_pipeline = OpticalPipeline()
        self.optical_mode = "STANDARD"
        self.auto_optical_mode = True
        self.low_light_detector = self.optical_pipeline.low_light_detector
        self.ambient_luminance = 100.0
        self.is_low_light = False

        # C2 Surveillance Mode: "PERIMETER" (Human FRS / Tripwire), "CHECKPOST" (Vehicle / ANPR), "UNIFIED" (Both)
        self.surveillance_mode = (getattr(self, "_initial_surveillance_mode", None) or "PERIMETER").upper()
        self.vehicle_detector = VehicleDetector()
        self.anpr_engine = ANPREngine()
        self.latest_vehicles: List[Dict[str, Any]] = []
        self.has_suspect_vehicle = False
        self.active_suspect_vehicles: List[Dict[str, Any]] = []

        # Multi-Vehicle Persistent Spatial Tracker & Transit Registry (high stability for highway / checkpost speeds)
        self.vehicle_tracker = SimpleCentroidTracker(max_missed_frames=35, max_distance=180.0)
        self._active_transits: Dict[str, Dict[str, Any]] = {}
        self._pending_anpr_tasks: Dict[str, int] = {}
        self._recent_transits: Dict[str, Dict[str, Any]] = {}

        # Asynchronous Bounded ANPR Architecture
        # Decouples OCR from frame capture loop: bounded queue prevents camera latency spikes
        self._anpr_queue: queue.Queue = queue.Queue(maxsize=2)
        self._anpr_worker_thread: Optional[threading.Thread] = None
        self._vehicle_last_anpr: Dict[str, float] = {}
        self._anpr_cooldown_per_vehicle: float = 1.5  # 1.5s cooldown per tracked vehicle

        # Continuous human presence & dwell tracking
        self.dwell_seconds = 0.0
        self.is_loitering = False
        self._presence_start_time: Optional[float] = None
        self._last_presence_time: Optional[float] = None
        self.LOITER_THRESHOLD_SECONDS = 25.0

        self._cap = None
        self._thread: Optional[threading.Thread] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._raw_frame_lock = threading.Lock()
        self._latest_hardware_frame: Optional[np.ndarray] = None
        self._latest_hardware_frame_time: Optional[float] = None

        self._lock = threading.Lock()
        self._latest_jpeg: Optional[bytes] = None
        self._latest_raw_frame: Optional[np.ndarray] = None
        self._latest_annotated: Optional[np.ndarray] = None
        self.actual_width = 640
        self.actual_height = 480
        self.actual_backend = "DirectShow (DSHOW)"
        self._is_synthetic_feed = False

    def initialize(self) -> bool:
        """Initializes detector."""
        return self.detector.initialize()

    def start(self) -> bool:
        """Starts background frame acquisition thread and ANPR worker thread."""
        with self._lock:
            if self.is_running:
                return True

            self.is_running = True
            self.status = "ONLINE"
            self.detector.initialize()

            # Start asynchronous ANPR worker if not already running
            if self._anpr_worker_thread is None or not self._anpr_worker_thread.is_alive():
                self._anpr_worker_thread = threading.Thread(target=self._anpr_worker_loop, daemon=True)
                self._anpr_worker_thread.start()

            # Start dedicated ultra-low latency hardware frame reader
            if self._reader_thread is None or not self._reader_thread.is_alive():
                self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
                self._reader_thread.start()

            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._capture_loop, daemon=True)
                self._thread.start()
            return True

    def stop(self) -> None:
        """Stops the camera capture loop and ANPR worker."""
        self.is_running = False
        try:
            self._anpr_queue.put_nowait(None)
        except Exception:
            pass

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.4)
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=0.3)
        if self._anpr_worker_thread and self._anpr_worker_thread.is_alive():
            self._anpr_worker_thread.join(timeout=0.3)

        with self._lock:
            if self._cap:
                self._cap.release()
                self._cap = None
            with self._raw_frame_lock:
                self._latest_hardware_frame = None
                self._latest_hardware_frame_time = None
            self.status = "OFFLINE"
            self.current_fps = 0.0

    def _open_capture(self) -> bool:
        """Opens video capture device or stream."""
        if not self.is_running:
            return False
        with CameraManager._global_capture_lock:
            if not self.is_running:
                return False
            try:
                with self._lock:
                    if self._cap is not None:
                        try:
                            self._cap.release()
                        except Exception:
                            pass
                        self._cap = None

                src_str = str(self.source).strip()
                # Check if source is integer (webcam index)
                if src_str.isdigit():
                    if "PYTEST_CURRENT_TEST" in os.environ:
                        # Automated test environment: do not probe Windows DirectShow COM hardware
                        self.status = "DISCONNECTED" if self.is_running else "OFFLINE"
                        return False
                    cam_idx = int(src_str)
                    if cam_idx > 10:
                        self.status = "DISCONNECTED" if self.is_running else "OFFLINE"
                        return False
                    # On headless Linux cloud environments (e.g. Render), skip probe if device node doesn't exist
                    if os.name != "nt" and not os.path.exists(f"/dev/video{cam_idx}"):
                        self._is_synthetic_feed = True
                        self.status = "ONLINE" if self.is_running else "OFFLINE"
                        return False
                    try:
                        # On Windows, DirectShow (CAP_DSHOW) avoids MSMF error -1072873822
                        self._cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW)
                        if not self._cap.isOpened():
                            self._cap = cv2.VideoCapture(cam_idx)
                    except Exception:
                        self._cap = cv2.VideoCapture(cam_idx)
                elif src_str.startswith(("rtsp://", "http://", "https://")):
                    # RTSP Network Stream: enforce TCP transport and 2s network timeout to prevent frozen sockets
                    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;2000000"
                    self._cap = cv2.VideoCapture(src_str, cv2.CAP_FFMPEG)
                elif os.path.exists(src_str):
                    # Local video file path
                    self._cap = cv2.VideoCapture(src_str)
                else:
                    # Dummy/mock source or disconnected named source (e.g. "mock_camera", "outpost_zulu_03")
                    # Do NOT pass arbitrary invalid string to cv2.VideoCapture/FFmpeg which leaks sockets and corrupts CRT heap
                    self.status = "DISCONNECTED" if self.is_running else "OFFLINE"
                    return False

                if self._cap and self._cap.isOpened():
                    # Set buffer size to 1 to eliminate DirectShow / FFmpeg latency accumulation
                    try:
                        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    except Exception:
                        pass
                    # Set reasonable resolution for real-time responsiveness
                    self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    self.actual_width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
                    self.actual_height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
                    backend_code = self._cap.getBackendName() if hasattr(self._cap, "getBackendName") else "DirectShow"
                    self.actual_backend = f"OpenCV {backend_code} Hardware"
                    self.status = "ONLINE"
                    return True
                else:
                    self.status = "DISCONNECTED" if self.is_running else "OFFLINE"
                    return False
            except Exception as e:
                print(f"[CameraManager] Error opening camera {self.camera_id}: {e}")
                self.status = "DISCONNECTED" if self.is_running else "OFFLINE"
                return False

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

    def _draw_hud_banner(
        self,
        frame: np.ndarray,
        title: str,
        badge_label: str = "ALERT",
        color_bgr: tuple = (30, 30, 220)
    ) -> None:
        """Renders a sleek, floating glassmorphic defense HUD banner at the top of the frame."""
        h, w = frame.shape[:2]
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.44

        (tw, th), _ = cv2.getTextSize(title, font, font_scale, 1)
        (bw, bh), _ = cv2.getTextSize(badge_label, font, 0.36, 1)

        pad_x = 12
        pad_y = 6
        pill_h = max(th, bh) + pad_y * 2 + 4
        pill_w = bw + tw + pad_x * 3 + 16

        px1 = max(10, (w - pill_w) // 2)
        py1 = 10
        px2 = min(w - 10, px1 + pill_w)
        py2 = py1 + pill_h

        # 1. Semi-transparent glass pill backdrop
        self._blend_roi(frame, px1, py1, px2, py2, (10, 14, 22), alpha=0.85)

        # 2. Glowing accent border
        cv2.rectangle(frame, (px1, py1), (px2, py2), color_bgr, 1, cv2.LINE_AA)

        # 3. Inner badge chip on the left
        chip_x1 = px1 + 6
        chip_y1 = py1 + 4
        chip_x2 = chip_x1 + bw + 14
        chip_y2 = py2 - 4
        self._blend_roi(frame, chip_x1, chip_y1, chip_x2, chip_y2, color_bgr, alpha=0.25)
        cv2.rectangle(frame, (chip_x1, chip_y1), (chip_x2, chip_y2), color_bgr, 1, cv2.LINE_AA)
        cv2.circle(frame, (chip_x1 + 6, chip_y1 + (chip_y2 - chip_y1) // 2), 2, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.putText(
            frame,
            badge_label,
            (chip_x1 + 12, chip_y2 - 3),
            font,
            0.35,
            (255, 255, 255),
            1,
            cv2.LINE_AA
        )

        # 4. Clean crisp title text
        text_x = chip_x2 + 10
        text_y = py2 - pad_y - 2
        cv2.putText(
            frame,
            title,
            (text_x, text_y),
            font,
            font_scale,
            (255, 255, 255),
            1,
            cv2.LINE_AA
        )

    def _generate_fallback_frame(self, message: str = "CAM-01 • CAMERA OFFLINE") -> np.ndarray:
        """Generates high-tech CCTV test pattern frame with defense HUD aesthetics."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        # Deep space dark slate background
        frame[:] = (12, 16, 24)

        # Subtle tactical grid
        for y in range(0, 480, 48):
            cv2.line(frame, (0, y), (640, y), (20, 26, 38), 1)
        for x in range(0, 640, 48):
            cv2.line(frame, (x, 0), (x, 480), (20, 26, 38), 1)

        # Concentric radar rings
        center_pt = (320, 240)
        cv2.circle(frame, center_pt, 60, (26, 34, 50), 1, cv2.LINE_AA)
        cv2.circle(frame, center_pt, 130, (22, 30, 44), 1, cv2.LINE_AA)
        cv2.circle(frame, center_pt, 200, (18, 24, 36), 1, cv2.LINE_AA)

        # Reticle crosshair ticks
        cv2.line(frame, (320, 200), (320, 280), (212, 182, 6), 1, cv2.LINE_AA)
        cv2.line(frame, (280, 240), (360, 240), (212, 182, 6), 1, cv2.LINE_AA)

        # Top-left telemetry stamp
        now_str = time.strftime("%Y-%m-%d %H:%M:%S UTC")
        cv2.putText(frame, "XYNAPSE PERIMETER DEFENSE // FEED 01", (20, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (212, 182, 6), 1, cv2.LINE_AA)
        cv2.putText(frame, now_str, (20, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (120, 135, 150), 1, cv2.LINE_AA)

        # Central glassmorphic standby card
        card_w, card_h = 360, 72
        cx1 = (640 - card_w) // 2
        cy1 = (480 - card_h) // 2
        cx2 = cx1 + card_w
        cy2 = cy1 + card_h

        self._blend_roi(frame, cx1, cy1, cx2, cy2, (8, 12, 18), alpha=0.88)
        cv2.rectangle(frame, (cx1, cy1), (cx2, cy2), (40, 55, 75), 1, cv2.LINE_AA)

        # Corner bracket accents on the card
        bw = 12
        cv2.line(frame, (cx1, cy1), (cx1 + bw, cy1), (212, 182, 6), 2, cv2.LINE_AA)
        cv2.line(frame, (cx1, cy1), (cx1, cy1 + bw), (212, 182, 6), 2, cv2.LINE_AA)
        cv2.line(frame, (cx2, cy1), (cx2 - bw, cy1), (212, 182, 6), 2, cv2.LINE_AA)
        cv2.line(frame, (cx2, cy1), (cx2, cy1 + bw), (212, 182, 6), 2, cv2.LINE_AA)
        cv2.line(frame, (cx1, cy2), (cx1 + bw, cy2), (212, 182, 6), 2, cv2.LINE_AA)
        cv2.line(frame, (cx1, cy2), (cx1, cy2 - bw), (212, 182, 6), 2, cv2.LINE_AA)
        cv2.line(frame, (cx2, cy2), (cx2 - bw, cy2), (212, 182, 6), 2, cv2.LINE_AA)
        cv2.line(frame, (cx2, cy2), (cx2, cy2 - bw), (212, 182, 6), 2, cv2.LINE_AA)

        # Text in card
        cv2.circle(frame, (cx1 + 24, cy1 + 26), 4, (68, 68, 239), -1, cv2.LINE_AA)
        cv2.putText(frame, message, (cx1 + 38, cy1 + 31),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.44, (240, 245, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, "STANDBY MODE // OPTICAL SENSOR PAUSED", (cx1 + 38, cy1 + 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, (120, 140, 160), 1, cv2.LINE_AA)

        return frame

    def _check_tampering(self, frame: np.ndarray) -> bool:
        """
        Determines if the camera lens is occluded or covered.
        Checks:
        1. Complete blackout / dark coverage.
        2. Low variance / flat obstruction (hand, cloth, paper over lens).
        3. Severe loss of Laplacian edge frequency.
        """
        if frame is None or frame.size == 0:
            return False
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            std_dev = float(np.std(gray))
            mean_val = float(np.mean(gray))
            lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

            # A) Complete blackout or dark obstruction
            if mean_val < 18.0 and std_dev < 10.0:
                return True
            # B) Uniform or blurry obstruction (hand, cloth, paper over lens)
            if std_dev < 12.0 and lap_var < 15.0:
                return True
            # C) Severe edge loss with low contrast
            if lap_var < 6.0 and std_dev < 18.0:
                return True
            return False
        except Exception:
            return False

    def _check_stream_integrity(self, frame: np.ndarray) -> bool:
        """
        Anti-Replay & Video Freeze Detection (Cybersecurity).
        Detects adversarial replay loops, static video injection, or sensor driver freezes.
        Real optical sensors have constant physical shot noise (MAD > 0.3-1.5).
        If consecutive physical frames are bit-for-bit identical (MAD < 0.02) over ~3.0s,
        flags a stream replay / freeze cyber anomaly.
        """
        if frame is None or frame.size == 0:
            return False
        try:
            # Downsample to 160x120 grayscale for ultra-fast <0.2ms difference calculation
            small_gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 120))
            if self._last_raw_gray is None:
                self._last_raw_gray = small_gray
                self._frozen_frame_count = 0
                return False

            mad = float(np.mean(np.abs(small_gray.astype(np.float32) - self._last_raw_gray.astype(np.float32))))
            self._last_raw_gray = small_gray

            # Natural camera sensors never have MAD < 0.02 without video freeze / replay loop
            if mad < 0.02:
                self._frozen_frame_count += 1
                if self._frozen_frame_count >= 60:  # ~2.5 - 3 seconds at 20-25 FPS
                    return True
            else:
                self._frozen_frame_count = max(0, self._frozen_frame_count - 5)
            return False
        except Exception:
            return False

    def _enqueue_transit_sync(self, transit_rec: VehicleTransitLog) -> None:
        """Enqueues finalized vehicle transit to persistent store-and-forward outbox."""
        try:
            db = SessionLocal()
            try:
                existing = db.query(SyncOutbox).filter(SyncOutbox.event_id == transit_rec.event_id).first()
                if not existing:
                    payload = transit_rec.to_dict()
                    outbox_entry = SyncOutbox(
                        event_id=transit_rec.event_id,
                        camera_id=self.camera_id,
                        event_type="VEHICLE_TRANSIT",
                        severity="CRITICAL" if transit_rec.watchlist_category == "SUSPECT_STOLEN" else "LOW",
                        timestamp=transit_rec.created_at or datetime.utcnow(),
                        payload_json=json.dumps(payload),
                        status="PENDING"
                    )
                    db.add(outbox_entry)
                    db.commit()
            finally:
                db.close()
        except Exception as e:
            print(f"[CameraManager] Error syncing transit outbox: {e}")

    def _anpr_worker_loop(self) -> None:
        """
        Dedicated Asynchronous ANPR Worker Thread.
        Decoupled from camera frame capture loop to guarantee zero FPS drop on video feeds.
        Pulls vehicle crops from bounded queue, runs candidate plate localization & RapidOCR,
        strictly validates Indian license plate format, updates VehicleTransitLog, checks
        watchlist, and dispatches security alerts only when warranted.
        """
        while self.is_running:
            try:
                item = self._anpr_queue.get(timeout=0.5)
            except Exception:
                continue

            if item is None or not self.is_running:
                break

            if len(item) == 6:
                veh_crop, cam_id, raw_frame, vd, event_id, track_id = item
            elif len(item) == 5:
                veh_crop, cam_id, raw_frame, vd, event_id = item
                track_id = str(vd.get("track_id", "1"))
            else:
                veh_crop, cam_id, raw_frame, vd = item
                event_id = None
                track_id = str(vd.get("track_id", "1"))

            if veh_crop is None or getattr(veh_crop, "size", 0) == 0 or self.anpr_engine is None:
                continue

            t0 = time.time()
            veh_type = vd.get("vehicle_type", "Vehicle")
            print(f"[ANPR] OCR_STARTED=1 camera_id={cam_id} track_id={track_id} TRANSIT_ID={event_id}")

            # Save debug vehicle crop for Step 3 verification
            debug_dir = os.path.join(settings.BASE_DIR, "debug", "anpr")
            try:
                os.makedirs(debug_dir, exist_ok=True)
                if event_id:
                    cv2.imwrite(os.path.join(debug_dir, f"{event_id}_vehicle.jpg"), veh_crop)
            except Exception:
                pass

            try:
                # 1. Classical candidate localization & OCR with diagnostics
                candidates = self.anpr_engine.localize_plate_candidates(veh_crop)
                best_diag = None
                best_cand_crop = None

                for cand in candidates[:2]:
                    diag = self.anpr_engine.extract_plate_with_diagnostics(cand)
                    if diag.get("plate"):
                        best_diag = diag
                        best_cand_crop = cand
                        break
                    elif diag.get("status") in ("LOW_CONFIDENCE", "OBSCURED") and best_diag is None:
                        best_diag = diag
                        best_cand_crop = cand

                # Fallback to full vehicle crop only if candidate localization failed and crop is large enough
                if (best_diag is None or not best_diag.get("plate")) and veh_crop.shape[1] >= 120 and veh_crop.shape[0] >= 90:
                    fallback_diag = self.anpr_engine.extract_plate_with_diagnostics(veh_crop)
                    if fallback_diag.get("plate"):
                        best_diag = fallback_diag
                        best_cand_crop = veh_crop
                    elif best_diag is None:
                        best_diag = fallback_diag
                        # Default to bumper candidate if available rather than entire car
                        best_cand_crop = candidates[0] if candidates else veh_crop

                ocr_lat_ms = (time.time() - t0) * 1000.0

                # Save candidate plate crop if available
                plate_crop_path = None
                if best_cand_crop is not None and getattr(best_cand_crop, "size", 0) > 0 and event_id:
                    plate_crop_path = save_transit_snapshot(best_cand_crop, event_id=event_id, prefix="plate")
                    try:
                        cv2.imwrite(os.path.join(debug_dir, f"{event_id}_plate.jpg"), best_cand_crop)
                    except Exception:
                        pass

                detected_plate = best_diag.get("plate") if best_diag else None
                confidence = best_diag.get("confidence", 0.0) if best_diag else 0.0
                cand_w = best_diag.get("crop_w") if best_diag else None
                cand_h = best_diag.get("crop_h") if best_diag else None
                raw_ocr_text = best_diag.get("raw_text", "") if best_diag else ""

                print(f"[ANPR] RAW_OCR='{raw_ocr_text}' CONF={confidence:.2f}")
                print(f"[ANPR] OCR_RESULT='{detected_plate}' STATUS={best_diag.get('status') if best_diag else 'UNREADABLE'}")

                # 2. Strict Watchlist Match & Format Validation
                if detected_plate:
                    match_info = self.anpr_engine.match_plate(detected_plate)
                    p_status = match_info.get("status", "CIVILIAN")
                    p_num = match_info.get("plate") or detected_plate
                    is_matched = bool(match_info.get("matched", False))
                    prof_id = match_info.get("id")
                    print(f"[ANPR] VALIDATED_PLATE='{p_num}' MATCH={is_matched}")

                    # Check multi-frame confidence against active transit
                    active_transit = self._active_transits.get(track_id)
                    should_update = True
                    if active_transit and active_transit.get("best_plate") and active_transit.get("best_confidence", 0.0) > confidence:
                        # Existing detection had higher confidence
                        should_update = False

                    if should_update:
                        if active_transit:
                            active_transit["best_plate"] = p_num
                            active_transit["best_confidence"] = confidence
                            active_transit["best_status"] = "RECOGNIZED"
                            if plate_crop_path:
                                active_transit["plate_crop_path"] = plate_crop_path
                            active_transit["plate_crop_w"] = cand_w
                            active_transit["plate_crop_h"] = cand_h
                            active_transit["ocr_latency_ms"] = ocr_lat_ms
                            active_transit["watchlist_match"] = is_matched
                            active_transit["watchlist_category"] = p_status
                            active_transit["watchlist_profile_id"] = prof_id

                        # Update database record (upgrades PENDING or prematurely finalized UNREADABLE to RECOGNIZED)
                        if event_id:
                            db = SessionLocal()
                            try:
                                rec = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == event_id).first()
                                if rec:
                                    rec.plate_number = p_num
                                    rec.plate_status = "RECOGNIZED"
                                    rec.plate_confidence = confidence
                                    if plate_crop_path:
                                        rec.plate_crop_path = plate_crop_path
                                    rec.plate_crop_w = cand_w
                                    rec.plate_crop_h = cand_h
                                    rec.ocr_latency_ms = ocr_lat_ms
                                    rec.watchlist_match = 1 if is_matched else 0
                                    rec.watchlist_profile_id = prof_id
                                    rec.watchlist_category = p_status
                                    rec.last_seen_at = datetime.utcnow()
                                    rec.updated_at = datetime.utcnow()
                                    db.commit()
                                    print(f"[ANPR] DB_UPDATE=OK DB_COMMIT=OK TRANSIT_ID={event_id} PLATE={p_num} STATUS=RECOGNIZED CONF={confidence:.2f}")
                                    self._enqueue_transit_sync(rec)
                            except Exception as e:
                                print(f"[ANPR Worker] DB update error: {e}")
                            finally:
                                db.close()

                        # Update detection dict for HUD overlay
                        vd["plate_number"] = p_num
                        vd["plate_status"] = p_status
                        vd["owner_name"] = match_info.get("owner_name", "")

                    print(
                        f"[ANPR Pipeline] Camera={cam_id} Track={track_id} Event={event_id} "
                        f"Plate={p_num} Status={p_status} Matched={is_matched} Conf={confidence:.2f} Latency={ocr_lat_ms:.1f}ms"
                    )

                    # 3. Security Alert Trigger:
                    # ONLY trigger high-priority alert for SUSPECT_STOLEN watchlist intercept!
                    # Normal civilian vehicle transit is logged silently without firing alarm!
                    if p_status == "SUSPECT_STOLEN" and self.alert_engine:
                        with self._lock:
                            self.has_suspect_vehicle = True
                            if vd not in self.active_suspect_vehicles:
                                self.active_suspect_vehicles.append(vd)

                        veh_optical_mode = {
                            "STANDARD": "DAY_RGB",
                            "LOW_LIGHT_ENHANCE": "NIGHT_CLAHE",
                            "NVG_GREEN": "NVG_GREEN",
                            "FLIR_THERMAL": "FLIR_THERMAL"
                        }.get(self.optical_mode, "DAY_RGB")
                        self.alert_engine.trigger_stolen_vehicle_alert(
                            camera_id=cam_id,
                            frame=raw_frame,
                            plate_number=p_num,
                            vehicle_type=veh_type,
                            owner_name=match_info.get("owner_name", ""),
                            notes=match_info.get("notes", "Stolen Vehicle / Border Intercept"),
                            confidence=vd.get("confidence", 0.95),
                            optical_mode=veh_optical_mode
                        )
                else:
                    # Plate was not recognized in this attempt
                    active_transit = self._active_transits.get(track_id)
                    if active_transit and active_transit.get("best_status") == "PENDING" and event_id:
                        if plate_crop_path:
                            active_transit["plate_crop_path"] = plate_crop_path
                            active_transit["plate_crop_w"] = cand_w
                            active_transit["plate_crop_h"] = cand_h
                        active_transit["ocr_latency_ms"] = ocr_lat_ms

                        db = SessionLocal()
                        try:
                            rec = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == event_id).first()
                            if rec and rec.plate_status == "PENDING":
                                if plate_crop_path:
                                    rec.plate_crop_path = plate_crop_path
                                rec.plate_crop_w = cand_w
                                rec.plate_crop_h = cand_h
                                rec.ocr_latency_ms = ocr_lat_ms
                                rec.last_seen_at = datetime.utcnow()
                                rec.updated_at = datetime.utcnow()
                                db.commit()
                                print(f"[ANPR] DB_UPDATE=DIAG DB_COMMIT=OK TRANSIT_ID={event_id}")
                        except Exception as e:
                            print(f"[ANPR Worker] Diagnostic DB update error: {e}")
                        finally:
                            db.close()

            except Exception as e:
                print(f"[ANPR Worker] Error processing vehicle crop: {e}")
            finally:
                if event_id and event_id in self._pending_anpr_tasks:
                    self._pending_anpr_tasks[event_id] = max(0, self._pending_anpr_tasks[event_id] - 1)

    def _reader_loop(self) -> None:
        """
        Dedicated zero-latency hardware frame acquisition loop.
        Continuously drains the DirectShow buffer as fast as the hardware sensor delivers frames,
        guaranteeing that the neural vision pipeline always operates on real-time live frames (<30ms).
        """
        while self.is_running:
            if getattr(self, "_is_synthetic_feed", False):
                time.sleep(0.5)
                continue
            cap = self._cap
            if cap is not None and cap.isOpened():
                try:
                    ret, frame = cap.read()
                    if ret and frame is not None and frame.size > 0:
                        with self._raw_frame_lock:
                            self._latest_hardware_frame = frame
                            self._latest_hardware_frame_time = time.time()
                    else:
                        # If a local video file reaches EOF, loop back to frame 0
                        src_str = str(self.source).strip()
                        if not src_str.isdigit() and not src_str.startswith(("rtsp://", "rtsps://", "http://", "https://")):
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        time.sleep(0.005)
                except Exception:
                    time.sleep(0.01)
            else:
                time.sleep(0.05)

    def _capture_loop(self) -> None:
        """Continuous frame processing and human detection loop."""
        if not self.is_running:
            return
        opened = self._open_capture()
        fps_counter = 0
        fps_timer = time.time()
        last_reconnect_time = time.time()

        while self.is_running:
            if getattr(self, "_is_synthetic_feed", False):
                # Headless cloud environment (e.g. Render) without physical video device node.
                # Serve high-tech CCTV test pattern feed directly at ~20 FPS.
                # Avoid repeated V4L2 reconnect attempts and keep camera ONLINE.
                raw_frame = self._generate_fallback_frame()
                ret, jpeg = cv2.imencode(".jpg", raw_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                if ret:
                    with self._lock:
                        self._latest_jpeg = jpeg.tobytes()
                        self._latest_raw_frame = raw_frame
                        self._latest_annotated = raw_frame
                        self.status = "ONLINE"
                        self.current_fps = 20.0
                        self.current_face_count = 0
                        self.latest_detections = []
                        self.latest_vehicles = []
                time.sleep(0.05)
                continue

            raw_frame = None
            is_hardware_frame = False

            # Periodic background auto-reconnect if device/stream dropped
            if not opened or self._cap is None or not self._cap.isOpened():
                if not self.is_running:
                    self.status = "OFFLINE"
                now_t = time.time()
                if now_t - last_reconnect_time >= 2.0:
                    last_reconnect_time = now_t
                    opened = self._open_capture()

            if opened and self._cap and self._cap.isOpened():
                hw_frame = None
                hw_time = None
                with self._raw_frame_lock:
                    if self._latest_hardware_frame is not None:
                        hw_frame = self._latest_hardware_frame.copy()
                        hw_time = self._latest_hardware_frame_time

                # Zero-latency ingestion: use latest live frame from reader thread
                if hw_frame is not None and hw_time is not None and (time.time() - hw_time < 2.0):
                    raw_frame = hw_frame
                    is_hardware_frame = True
                    self.actual_width = raw_frame.shape[1]
                    self.actual_height = raw_frame.shape[0]
                    self.status = "ONLINE"
                elif hw_time is not None and (time.time() - hw_time >= 2.0):
                    # Sensor stalled or disconnected
                    self.status = "DISCONNECTED"
                    opened = False
                else:
                    # Fallback on initial device spin-up before reader thread populates frame
                    ret, frame = self._cap.read()
                    if ret and frame is not None and frame.size > 0:
                        raw_frame = frame
                        is_hardware_frame = True
                        self.actual_width = frame.shape[1]
                        self.actual_height = frame.shape[0]
                        self.status = "ONLINE"
                    else:
                        self.status = "DISCONNECTED"
                        opened = False

            if raw_frame is None:
                # Use CCTV test pattern if camera isn't delivering physical frames
                raw_frame = self._generate_fallback_frame()
                is_hardware_frame = False

            if not is_hardware_frame:
                # Standby CCTV graphic: encode frame directly and continue.
                # DO NOT execute neural detection, FRS, or ANPR on synthetic graphics!
                ret, jpeg = cv2.imencode(".jpg", raw_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                if ret:
                    with self._lock:
                        self._latest_jpeg = jpeg.tobytes()
                        self._latest_raw_frame = raw_frame
                        self._latest_annotated = raw_frame
                        self.status = "ONLINE"
                        self.current_fps = 25.0
                        self.current_face_count = 0
                        self.latest_detections = []
                        self.latest_vehicles = []
                time.sleep(0.04)  # ~25 FPS standby sleep
                continue

            # Automatic Ambient Luminance & Low-Light Detection
            if self.auto_optical_mode:
                is_dark, lum, rec_mode = self.low_light_detector.update(raw_frame)
                self.ambient_luminance = lum
                self.is_low_light = is_dark
                effective_optical_mode = rec_mode if self.optical_mode == "STANDARD" else self.optical_mode
            else:
                effective_optical_mode = self.optical_mode

            alert_optical_mode = {
                "STANDARD": "DAY_RGB",
                "LOW_LIGHT_ENHANCE": "NIGHT_CLAHE",
                "NVG_GREEN": "NVG_GREEN",
                "FLIR_THERMAL": "FLIR_THERMAL"
            }.get(effective_optical_mode, "DAY_RGB")

            # Check camera tampering / lens occlusion (ONLY on physical camera frames, not synthetic fallback)
            if is_hardware_frame:
                is_occluded = self._check_tampering(raw_frame)
                if is_occluded:
                    if self._tamper_start_time is None:
                        self._tamper_start_time = time.time()
                    elif time.time() - self._tamper_start_time >= 2.0:
                        self.is_tampered = True
                        if self.alert_engine:
                            self.alert_engine.trigger_tampering_alert(
                                camera_id=self.camera_id,
                                frame=raw_frame,
                                reason="Camera Lens Occlusion / Tampering Detected",
                                optical_mode=alert_optical_mode
                            )
                else:
                    self._tamper_start_time = None
                    self.is_tampered = False

                # Cybersecurity Stream Integrity & Anti-Replay Detection
                is_frozen = self._check_stream_integrity(raw_frame)
                if is_frozen:
                    self.is_stream_frozen = True
                    self.stream_integrity = "FROZEN_REPLAY_ATTACK"
                    if self.alert_engine and not self._freeze_alert_sent:
                        self.alert_engine.trigger_cyber_tamper_alert(
                            camera_id=self.camera_id,
                            frame=raw_frame,
                            reason="Cyber Security Alert: Frozen Feed / Video Replay Attack Detected",
                            optical_mode=alert_optical_mode
                        )
                        self._freeze_alert_sent = True
                else:
                    self.is_stream_frozen = False
                    self.stream_integrity = "SECURE"
                    self._freeze_alert_sent = False
            else:
                self._tamper_start_time = None
                self.is_tampered = False
                self.is_stream_frozen = False
                self.stream_integrity = "SECURE"

            # Apply Tactical Multi-Band Optical Pipeline (STANDARD, LOW_LIGHT_ENHANCE, NVG_GREEN, FLIR_THERMAL)
            display_frame = self.optical_pipeline.process_frame(raw_frame, effective_optical_mode)

            # Run real-time human detection (only in PERIMETER or UNIFIED mode)
            detections = []
            match_summary = {
                "all_authorized": False,
                "has_suspect": False,
                "suspects": [],
                "authorized_count": 0,
                "unknown_count": 0
            }

            now = time.time()
            t_infer_start = time.perf_counter()
            if self.detection_active and self.surveillance_mode in ("PERIMETER", "UNIFIED"):
                detections = self.detector.detect(display_frame)
                if self.face_recognizer and len(detections) > 0:
                    match_summary = self.face_recognizer.process_frame_detections(display_frame, detections)
            t_infer_end = time.perf_counter()
            self.latest_inference_latency_ms = round((t_infer_end - t_infer_start) * 1000, 1)

            auth_count = match_summary.get("authorized_count", 0)
            unk_count = match_summary.get("unknown_count", 0)
            susp_list = match_summary.get("suspects", [])

            if auth_count > 0 and len(susp_list) == 0:
                self._last_authorized_time = now
                self._last_authorized_names = [
                    d.get("matched_name", "Officer")
                    for d in detections if d.get("role") == "AUTHORIZED_GUARD"
                ]

            # Brief grace window for camera status when an authorized officer turns away or blinks,
            # BUT ONLY if no unknown persons or suspects are in frame.
            in_auth_grace = (
                self._last_authorized_time is not None
                and (now - self._last_authorized_time) < 1.5
                and len(susp_list) == 0
                and unk_count == 0
            )

            # Room authorization logic:
            # - If all detected faces are authorized: Authorized
            # - If any unknown person is in frame: NEVER authorized (prevents security bypass)
            # - If officer briefly turns away and NO one else is in frame: Keep grace
            if auth_count > 0 and unk_count == 0 and len(susp_list) == 0:
                self.is_authorized = True
            elif in_auth_grace and len(detections) == 0:
                self.is_authorized = True
            else:
                self.is_authorized = False

            # IMPORTANT: NEVER propagate or leak identity onto other faces.
            # Each face strictly preserves its own biometric match result.

            self.has_suspect = match_summary.get("has_suspect", False)
            self.active_suspects = susp_list

            # Vehicle & ANPR Detection (active in CHECKPOST or UNIFIED mode)
            vehicle_dets = []
            if self.detection_active and self.vehicle_detector:
                raw_veh_dets = []
                if self.surveillance_mode in ("CHECKPOST", "UNIFIED"):
                    raw_veh_dets = self.vehicle_detector.detect(display_frame)

                now_ts = time.time()
                if len(raw_veh_dets) > 0:
                    # Persistent multi-vehicle tracking across frames
                    vehicle_dets = self.vehicle_tracker.update(raw_veh_dets)
                    h_f, w_f = display_frame.shape[:2]

                    for vd in vehicle_dets:
                        tid = vd.get("track_id")
                        track_id = str(tid) if tid is not None else f"{int(vd['bbox'][0] // 30)}_{int(vd['bbox'][1] // 30)}"
                        vd["track_id"] = track_id
                        vtype = vd.get("vehicle_type", "Vehicle")
                        vx, vy, vw, vh = vd["bbox"]

                        y1 = max(0, vy)
                        y2 = min(h_f, vy + vh)
                        x1 = max(0, vx)
                        x2 = min(w_f, vx + vw)

                        # Determine direction from spatial history if available
                        direction = "UNKNOWN"
                        trk_obj = self.vehicle_tracker.tracks.get(tid) if tid is not None else None
                        if trk_obj and len(trk_obj.get("history", [])) >= 3:
                            dy = trk_obj["history"][-1][1] - trk_obj["history"][0][1]
                            if dy > 30:
                                direction = "INBOUND"
                            elif dy < -30:
                                direction = "OUTBOUND"

                        # 1. Vehicle First Seen: Create VehicleTransitLog event record & snapshot
                        if track_id not in self._active_transits:
                            clean_cam = self.camera_id.replace("-", "").replace("_", "")
                            event_id = f"TR-{clean_cam}-{int(now_ts)}-{int(tid or 1):03d}"

                            veh_crop = display_frame[y1:y2, x1:x2].copy() if (y2 > y1 and x2 > x1) else None
                            veh_snap_path = save_transit_snapshot(veh_crop, event_id=event_id, prefix="veh") if veh_crop is not None else None

                            # Insert initial PENDING transit record into database
                            db = SessionLocal()
                            try:
                                transit_rec = VehicleTransitLog(
                                    event_id=event_id,
                                    camera_id=self.camera_id,
                                    track_id=track_id,
                                    vehicle_type=vtype,
                                    plate_number=None,
                                    plate_status="PENDING",
                                    plate_confidence=None,
                                    vehicle_snapshot_path=veh_snap_path,
                                    plate_crop_path=None,
                                    plate_crop_w=None,
                                    plate_crop_h=None,
                                    ocr_latency_ms=None,
                                    watchlist_match=0,
                                    watchlist_profile_id=None,
                                    watchlist_category=None,
                                    direction=direction,
                                    first_seen_at=datetime.utcnow(),
                                    last_seen_at=datetime.utcnow(),
                                    created_at=datetime.utcnow()
                                )
                                db.add(transit_rec)
                                db.commit()
                            except Exception as e:
                                print(f"[CameraManager] Error creating transit record: {e}")
                            finally:
                                db.close()

                            self._active_transits[track_id] = {
                                "event_id": event_id,
                                "track_id": track_id,
                                "vehicle_type": vtype,
                                "best_plate": None,
                                "best_confidence": 0.0,
                                "best_status": "PENDING",
                                "vehicle_snapshot_path": veh_snap_path,
                                "plate_crop_path": None,
                                "plate_crop_w": None,
                                "plate_crop_h": None,
                                "ocr_latency_ms": None,
                                "watchlist_match": False,
                                "watchlist_category": None,
                                "watchlist_profile_id": None,
                                "direction": direction,
                                "first_seen": now_ts,
                                "last_seen": now_ts,
                                "last_anpr_time": 0.0,
                                "ocr_attempts": 0
                            }
                        else:
                            # Update existing track telemetry
                            self._active_transits[track_id]["last_seen"] = now_ts
                            if direction != "UNKNOWN":
                                self._active_transits[track_id]["direction"] = direction

                            # Reflect best plate on detection object for HUD overlay
                            if self._active_transits[track_id].get("best_plate"):
                                vd["plate_number"] = self._active_transits[track_id]["best_plate"]
                                vd["plate_status"] = self._active_transits[track_id]["watchlist_category"] or "CIVILIAN"
                            elif self._active_transits[track_id].get("best_status") == "UNREADABLE":
                                vd["plate_status"] = "UNREADABLE"
                            else:
                                vd["plate_status"] = "PENDING"

                        # 2. Multi-Frame ANPR: Enqueue job if plate not yet recognized with high confidence
                        active_tr = self._active_transits[track_id]
                        ev_id = active_tr["event_id"]
                        pending_for_this_veh = self._pending_anpr_tasks.get(ev_id, 0)

                        if self.anpr_engine and (active_tr["best_status"] != "RECOGNIZED" or active_tr["best_confidence"] < 0.85):
                            # Do not enqueue duplicate jobs while worker is already computing OCR on this vehicle
                            if pending_for_this_veh == 0 and (now_ts - active_tr["last_anpr_time"] >= self._anpr_cooldown_per_vehicle):
                                active_tr["last_anpr_time"] = now_ts
                                active_tr["ocr_attempts"] += 1
                                if y2 > y1 and x2 > x1:
                                    veh_crop = display_frame[y1:y2, x1:x2].copy()
                                    try:
                                        self._anpr_queue.put_nowait((
                                            veh_crop,
                                            self.camera_id,
                                            raw_frame.copy(),
                                            vd,
                                            active_tr["event_id"],
                                            track_id
                                        ))
                                        self._pending_anpr_tasks[ev_id] = self._pending_anpr_tasks.get(ev_id, 0) + 1
                                        print(
                                            f"[ANPR] camera_id={self.camera_id} surveillance_mode={self.surveillance_mode} "
                                            f"vehicle_track_id={track_id} vehicle_bbox={vd['bbox']} "
                                            f"vehicle_crop_size=({veh_crop.shape[1]}x{veh_crop.shape[0]}) "
                                            f"queue_enqueue=OK TRANSIT_ID={ev_id}"
                                        )
                                    except queue.Full:
                                        # Bounded queue: drop job if full to guarantee zero frame rate degradation
                                        pass
                else:
                    # Age out tracker if no vehicles detected
                    self.vehicle_tracker.update([])

                # 3. Finalize and evict departed vehicle tracks (safe lifecycle: never finalize while OCR pending)
                active_tracker_ids = {str(k) for k in self.vehicle_tracker.tracks.keys()}
                for tid_str, trans in list(self._active_transits.items()):
                    ev_id = trans["event_id"]
                    pending_tasks = self._pending_anpr_tasks.get(ev_id, 0)
                    time_departed = now_ts - trans["last_seen"]

                    # Only finalize if vehicle has left tracker AND grace period elapsed AND no pending OCR workers
                    if (tid_str not in active_tracker_ids or time_departed > 4.0) and pending_tasks == 0:
                        db = SessionLocal()
                        try:
                            rec = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == ev_id).first()
                            if rec:
                                if rec.plate_status == "PENDING":
                                    rec.plate_status = "UNREADABLE"
                                    rec.plate_number = None
                                rec.last_seen_at = datetime.utcnow()
                                rec.updated_at = datetime.utcnow()
                                if trans.get("direction") and trans["direction"] != "UNKNOWN":
                                    rec.direction = trans["direction"]
                                db.commit()
                                self._enqueue_transit_sync(rec)
                                print(f"[ANPR] FINALIZED TRANSIT_ID={ev_id} STATUS={rec.plate_status} PLATE={rec.plate_number}")
                        except Exception as e:
                            print(f"[CameraManager] Error finalizing transit {ev_id}: {e}")
                        finally:
                            db.close()

                        # Cache in recent transits so telemetry / lookups still have context
                        self._recent_transits[ev_id] = dict(trans)
                        if len(self._recent_transits) > 100:
                            self._recent_transits.pop(next(iter(self._recent_transits)), None)
                        self._active_transits.pop(tid_str, None)

            self.latest_vehicles = vehicle_dets
            if len(vehicle_dets) == 0:
                self.has_suspect_vehicle = False
                self.active_suspect_vehicles = []

            if self.detection_active:
                if self.surveillance_mode == "CHECKPOST":
                    annotated_frame = self.vehicle_detector.draw_annotations(display_frame, vehicle_dets)
                elif self.surveillance_mode == "UNIFIED":
                    annotated_frame = self.detector.draw_annotations(display_frame, detections)
                    annotated_frame = self.vehicle_detector.draw_annotations(annotated_frame, vehicle_dets)
                else:
                    # PERIMETER mode
                    annotated_frame = self.detector.draw_annotations(display_frame, detections)
                    if len(vehicle_dets) > 0:
                        annotated_frame = self.vehicle_detector.draw_annotations(annotated_frame, vehicle_dets)
            else:
                annotated_frame = display_frame.copy()

            # Partition detections into humans and border wildlife
            human_dets = [d for d in detections if not d.get("is_animal")]
            wildlife_dets = [d for d in detections if d.get("is_animal")]
            self.current_face_count = len(human_dets)
            self.current_wildlife_count = len(wildlife_dets)
            self.latest_detections = detections

            # Track continuous human presence & dwell time for loitering detection (only in PERIMETER or UNIFIED mode)
            if self.surveillance_mode in ("PERIMETER", "UNIFIED") and len(human_dets) > 0:
                if self._presence_start_time is None:
                    self._presence_start_time = now
                self._last_presence_time = now
                self.dwell_seconds = round(now - self._presence_start_time, 1)

                # Suppress loitering alarm if the person is an authorized guard
                if self.dwell_seconds >= self.LOITER_THRESHOLD_SECONDS and not self.is_authorized and not self.has_suspect:
                    self.is_loitering = True
                    if self.alert_engine:
                        self.alert_engine.check_loitering(
                            camera_id=self.camera_id,
                            frame=raw_frame,
                            dwell_seconds=self.dwell_seconds,
                            optical_mode=alert_optical_mode
                        )
                else:
                    self.is_loitering = False
            else:
                # If no human detected for > 4.0 seconds, reset dwell time
                if self._last_presence_time and (now - self._last_presence_time > 4.0):
                    self._presence_start_time = None
                    self._last_presence_time = None
                    self.dwell_seconds = 0.0
                    self.is_loitering = False

            # Virtual Border Fence / Intrusion Check (only in PERIMETER or UNIFIED mode)
            is_breached = False
            breached_dets = []
            has_unauth_breach = False

            if self.tripwire.enabled and self.surveillance_mode in ("PERIMETER", "UNIFIED") and len(detections) > 0:
                is_breached, breached_dets, _ = self.tripwire.check_intrusion(raw_frame.shape, detections)
                has_wildlife_breach = False
                if is_breached:
                    for bd in breached_dets:
                        if bd.get("is_animal") or bd.get("role") == "WILDLIFE":
                            has_wildlife_breach = True
                        elif bd.get("role") != "AUTHORIZED_GUARD" and not self.is_authorized:
                            has_unauth_breach = True
                            break

            self.is_perimeter_breached = has_unauth_breach
            is_wildlife_crossing = (is_breached and has_wildlife_breach and not has_unauth_breach)

            # Draw tactical virtual border fence line (only in PERIMETER or UNIFIED mode)
            if self.tripwire.enabled and self.surveillance_mode in ("PERIMETER", "UNIFIED"):
                annotated_frame = self.tripwire.draw_tripwire(
                    annotated_frame,
                    is_breached=is_breached,
                    is_authorized_crossing=(is_breached and self.is_authorized and not has_unauth_breach),
                    is_wildlife_crossing=is_wildlife_crossing
                )

            # If border wildlife crossed the tripwire, log quiet non-threat transit (suppress armed siren)
            if is_wildlife_crossing and self.alert_engine:
                anim_dets = [bd for bd in breached_dets if bd.get("is_animal") or bd.get("role") == "WILDLIFE"]
                anim_type = anim_dets[0].get("animal_type", "Cattle") if anim_dets else "Cattle"
                self.alert_engine.trigger_wildlife_alert(
                    camera_id=self.camera_id,
                    frame=raw_frame,
                    animal_type=anim_type,
                    count=len(anim_dets),
                    confidence=anim_dets[0].get("confidence", 0.85) if anim_dets else 0.85,
                    optical_mode=alert_optical_mode
                )


            # Dispatch human alerts (only in PERIMETER or UNIFIED mode)
            if self.surveillance_mode in ("PERIMETER", "UNIFIED"):
                # 1. If suspect identified on watchlist, dispatch immediate CRITICAL alert
                if self.has_suspect and self.alert_engine:
                    for susp in self.active_suspects:
                        self.alert_engine.trigger_suspect_alert(
                            camera_id=self.camera_id,
                            frame=raw_frame,
                            suspect_name=susp["name"],
                            confidence=susp.get("similarity", 0.95),
                            notes=susp.get("notes", ""),
                            optical_mode=alert_optical_mode
                        )

                # 2. If unauthorized human border intrusion, dispatch CRITICAL intrusion alert
                if self.is_perimeter_breached and self.alert_engine and not self.has_suspect:
                    unauth_human_breaches = [bd for bd in breached_dets if not bd.get("is_animal")]
                    has_new_transition = any(bd.get("is_new_intrusion", True) for bd in unauth_human_breaches)
                    if has_new_transition or self.alert_engine.cooldown_tracker.is_cooled_down(f"{self.camera_id}_INTRUSION"):
                        b_cnt = len(unauth_human_breaches) if unauth_human_breaches else len(breached_dets)
                        fence_label = "2D Polygon Geofence" if self.tripwire.fence_type == "POLYGON" else "Zero-Line Tripwire"
                        self.alert_engine.trigger_intrusion_alert(
                            camera_id=self.camera_id,
                            frame=raw_frame,
                            breached_count=b_cnt,
                            details=f"Restricted {fence_label} Breached: {b_cnt} unauthorized human subject(s) crossed boundary",
                            optical_mode=alert_optical_mode
                        )

                # 3. If all visible persons are authorized guards, SUPPRESS standard alarm
                # 4. Otherwise (unknown visitor / intruder), evaluate normal alert engine
                if len(human_dets) > 0 and self.alert_engine:
                    if not self.is_authorized and not self.has_suspect and not self.is_perimeter_breached:
                        self.alert_engine.process_detections(
                            camera_id=self.camera_id,
                            frame=raw_frame,
                            detections=human_dets,
                            annotated_frame=annotated_frame,
                            optical_mode=alert_optical_mode
                        )

            # Prominent Tactical Cybersecurity & Tampering Banners on HUD
            if self.is_stream_frozen:
                self._draw_hud_banner(annotated_frame, "CYBER REPLAY ATTACK // VIDEO FROZEN", "CRITICAL", (30, 30, 220))
            elif self.is_tampered:
                self._draw_hud_banner(annotated_frame, "OPTICAL TAMPERING // LENS BLOCKED", "WARNING", (0, 140, 255))
            elif self.has_suspect_vehicle and self.active_suspect_vehicles:
                p_text = self.active_suspect_vehicles[0].get("plate_number") or "WANTED"
                self._draw_hud_banner(annotated_frame, f"INTERCEPT // RED NOTICE VEHICLE [{p_text}]", "CRITICAL", (30, 30, 220))

            # Encode annotated frame as JPEG for MJPEG stream
            ret_enc, jpeg = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ret_enc:
                with self._lock:
                    self._latest_raw_frame = raw_frame
                    self._latest_annotated = annotated_frame
                    self._latest_jpeg = jpeg.tobytes()

            # Dynamic FPS computation
            fps_counter += 1
            if time.time() - fps_timer >= 1.0:
                self.current_fps = round(fps_counter / (time.time() - fps_timer), 1)
                fps_counter = 0
                fps_timer = time.time()

        # Clean release
        if self._cap:
            self._cap.release()
            self._cap = None
        self.status = "OFFLINE"

    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    def get_current_raw_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            if self._latest_raw_frame is not None:
                return self._latest_raw_frame.copy()
        return None

    def get_status_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "name": self.name,
            "source": redact_camera_source(self.source),
            "status": self.status,
            "is_tampered": self.is_tampered,
            "is_loitering": self.is_loitering,
            "dwell_seconds": self.dwell_seconds,
            "is_authorized": self.is_authorized,
            "has_suspect": self.has_suspect,
            "active_suspects": self.active_suspects,
            "fps": self.current_fps,
            "inference_latency_ms": getattr(self, "latest_inference_latency_ms", 0.0),
            "face_count": self.current_face_count,
            "human_count": self.current_face_count,
            "wildlife_count": getattr(self, "current_wildlife_count", 0),
            "detections": [
                {k: v for k, v in d.items() if k != "raw_face"}
                for d in self.latest_detections
            ],
            "tripwire_enabled": self.tripwire.enabled,
            "tripwire_y_ratio": self.tripwire.line_y_ratio,
            "fence_type": self.tripwire.fence_type,
            "fence_points": self.tripwire.get_polygon(),
            "is_perimeter_breached": self.is_perimeter_breached,
            "detection_active": self.detection_active,
            "optical_mode": self.optical_mode,
            "auto_optical_mode": self.auto_optical_mode,
            "ambient_luminance": round(self.ambient_luminance, 1),
            "is_low_light": self.is_low_light,
            "surveillance_mode": self.surveillance_mode,
            "resolution": f"{getattr(self, 'actual_width', 640)}x{getattr(self, 'actual_height', 480)}",
            "actual_backend": "Tactical Synthetic Feed (Headless Cloud)" if getattr(self, "_is_synthetic_feed", False) else getattr(self, "actual_backend", "DirectShow (DSHOW)"),
            "vehicle_count": len(self.latest_vehicles),
            "vehicles": self.latest_vehicles,
            "has_suspect_vehicle": self.has_suspect_vehicle,
            "active_suspect_vehicles": self.active_suspect_vehicles,
            "is_stream_frozen": self.is_stream_frozen,
            "stream_integrity": self.stream_integrity
        }

    def set_polygon_fence(self, points: List[List[float]], reference_shape: Optional[Tuple[int, ...]] = None) -> bool:
        """Configures and activates resolution-independent 2D polygon virtual fence."""
        ref = reference_shape or (getattr(self, "actual_height", getattr(self, "frame_height", 480)), getattr(self, "actual_width", getattr(self, "frame_width", 640)))
        return self.tripwire.set_polygon(points, reference_shape=ref)

    def get_polygon_fence(self) -> Optional[List[List[float]]]:
        """Returns active 2D polygon virtual fence points."""
        return self.tripwire.get_polygon()

    def get_normalized_polygon_fence(self) -> Optional[List[List[float]]]:
        """Returns active 2D polygon virtual fence normalized ratio points [0, 1]."""
        return self.tripwire.get_normalized_polygon()

    def set_auto_optical_mode(self, enabled: bool) -> bool:
        """Toggles automatic low-light enhancement detection."""
        self.auto_optical_mode = bool(enabled)
        return self.auto_optical_mode

    def set_surveillance_mode(self, mode: str) -> str:
        """Sets active C2 surveillance mode: PERIMETER, CHECKPOST, or UNIFIED."""
        mode_upper = (mode or "").upper().strip()
        if mode_upper in ("PERIMETER", "CHECKPOST", "UNIFIED"):
            self.surveillance_mode = mode_upper
            print(f"[CameraManager] Switched C2 Surveillance Mode to: {self.surveillance_mode}")
        return self.surveillance_mode

    def set_optical_mode(self, mode: str) -> str:
        """Sets active optical band mode (STANDARD, LOW_LIGHT_ENHANCE, NVG_GREEN, FLIR_THERMAL)."""
        mode_upper = (mode or "").upper()
        if mode_upper in OpticalPipeline.MODES:
            self.optical_mode = mode_upper
        return self.optical_mode

    def set_tripwire_enabled(self, enabled: bool) -> bool:
        """Toggles virtual border tripwire / fence on/off."""
        self.tripwire.enabled = enabled
        if not enabled:
            self.is_perimeter_breached = False
        return self.tripwire.enabled

    def set_tripwire_y(self, y_ratio: float) -> float:
        """Sets vertical position of tripwire line (0.2 to 0.9)."""
        self.tripwire.set_line(y_ratio)
        return self.tripwire.line_y_ratio

    def generate_mjpeg_stream(self):
        """Generator function for FastAPI StreamingResponse."""
        if not self.is_running:
            try:
                self.start()
            except Exception:
                pass

        # Yield immediate initial frame to prevent client connection timeouts or img.onerror
        init_frame = self.get_latest_jpeg()
        if not init_frame:
            fallback = self._generate_fallback_frame(f"{self.camera_id} • INITIALIZING...")
            ret, enc = cv2.imencode('.jpg', fallback, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ret:
                init_frame = enc.tobytes()
        if init_frame:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + init_frame + b"\r\n"
            )

        try:
            while self.is_running:
                frame_bytes = self.get_latest_jpeg()
                if frame_bytes:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                    )
                else:
                    fallback = self._generate_fallback_frame()
                    ret, enc = cv2.imencode('.jpg', fallback, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if ret:
                        yield (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n\r\n" + enc.tobytes() + b"\r\n"
                        )
                time.sleep(0.033)  # ~30 FPS stream rate
        except (GeneratorExit, ConnectionResetError, BrokenPipeError):
            pass
