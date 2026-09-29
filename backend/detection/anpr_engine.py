import re
import cv2
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

import threading

from backend.database.database import SessionLocal
from backend.database.models import VehicleProfile


_shared_ocr_engine = None
_ocr_singleton_lock = threading.Lock()

def get_shared_ocr_engine():
    """Singleton getter for OCR engine to prevent loading multiple 150MB+ models in cloud RAM."""
    global _shared_ocr_engine
    if _shared_ocr_engine is not None:
        return _shared_ocr_engine
    with _ocr_singleton_lock:
        if _shared_ocr_engine is not None:
            return _shared_ocr_engine
        try:
            from rapidocr_onnxruntime import RapidOCR
            _shared_ocr_engine = RapidOCR()
            print("[ModelCache] Loaded Shared RapidOCR ONNX engine into singleton.")
            return _shared_ocr_engine
        except Exception as e:
            print(f"[ANPREngine] Failed to initialize RapidOCR: {e}")
            try:
                import easyocr
                _shared_ocr_engine = easyocr.Reader(['en'], gpu=False)
                print("[ModelCache] Loaded Shared EasyOCR fallback into singleton.")
                return _shared_ocr_engine
            except Exception as ex2:
                print(f"[ANPREngine] OCR fallback also failed: {ex2}")
                return None

class ANPREngine:
    """
    Real-Time Automatic Number Plate Recognition (ANPR) Engine.
    Uses RapidOCR (PP-OCRv4 ONNX) with candidate plate localization
    to extract vehicle registration numbers and check them against
    the Border Check Post Watchlist (Military Convoy vs Stolen/Suspect).
    """

    INDIAN_PLATE_REGEX = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$")

    def __init__(self):
        self.ocr_engine = None
        self._is_initialized = False
        self._profiles: List[Dict[str, Any]] = []
        self.reload_profiles()

    def initialize(self) -> bool:
        """Initializes RapidOCR ONNX engine and loads vehicle profiles."""
        if self._is_initialized and self.ocr_engine is not None:
            return True
        engine = get_shared_ocr_engine()
        if engine is not None:
            self.ocr_engine = engine
            self._is_initialized = True
            self.reload_profiles()
            return True
        self._is_initialized = False
        return False

    def reload_profiles(self) -> int:
        """Loads vehicle profiles (Stolen Watchlist & Military Fleet) from SQLite."""
        db = SessionLocal()
        try:
            records = db.query(VehicleProfile).all()
            profiles = []
            for rec in records:
                profiles.append({
                    "id": rec.id,
                    "plate_number": rec.plate_number.strip().upper().replace(" ", "").replace("-", ""),
                    "vehicle_type": rec.vehicle_type,
                    "owner_name": rec.owner_name or "Unknown",
                    "status": rec.status,
                    "notes": rec.notes or ""
                })
            self._profiles = profiles
            print(f"[ANPREngine] Loaded {len(self._profiles)} enrolled vehicle profile(s) into memory.")
            return len(self._profiles)
        except Exception as e:
            print(f"[ANPREngine] DB Error loading vehicle profiles: {e}")
            return 0
        finally:
            db.close()

    INDIAN_STATE_CODES = {
        "AN", "AP", "AR", "AS", "BR", "CH", "CG", "DD", "DN", "DL",
        "GA", "GJ", "HR", "HP", "JH", "JK", "KA", "KL", "LA", "LD",
        "MP", "MH", "MN", "ML", "MZ", "NL", "OD", "PB", "PY", "RJ",
        "SK", "TN", "TS", "TR", "UP", "UK", "UA", "WB"
    }

    @staticmethod
    def clean_plate_text(raw_text: str) -> str:
        """Sanitizes OCR text into standardized alphanumeric plate format."""
        if not raw_text:
            return ""
        # Remove anything except uppercase letters and digits
        cleaned = re.sub(r"[^A-Z0-9]", "", raw_text.upper())
        return cleaned

    DIGIT_TO_LETTER = {'0': 'O', '1': 'I', '2': 'Z', '5': 'S', '8': 'B'}
    LETTER_TO_DIGIT = {'O': '0', 'Q': '0', 'D': '0', 'I': '1', 'L': '1', 'Z': '2', 'S': '5', 'G': '6', 'B': '8'}

    @classmethod
    def _normalize_standard_candidate(cls, cand: str) -> Optional[Tuple[str, str]]:
        """
        Applies positional character repair according to MoRTH plate grammar:
        [State: 2 letters] [District: 1-2 digits] [Series: 0-3 letters] [Number: 4 digits]
        """
        cand = cand.upper()
        if len(cand) < 7 or len(cand) > 11:
            return None

        # Registration digits (last 4 characters) must be digits or convertible to digits
        num_part = cand[-4:]
        norm_num = ''.join(cls.LETTER_TO_DIGIT.get(ch, ch) for ch in num_part)
        if not norm_num.isdigit():
            return None

        # State code (first 2 characters) must be letters or convertible to valid state
        state_part = cand[:2]
        norm_state = ''.join(cls.DIGIT_TO_LETTER.get(ch, ch) for ch in state_part)
        if norm_state not in cls.INDIAN_STATE_CODES:
            return None

        middle = cand[2:-4]
        # District digits (1-2) + Series letters (0-3)
        for dist_len in (2, 1):
            if len(middle) >= dist_len:
                dist_raw = middle[:dist_len]
                series_raw = middle[dist_len:]
                if len(series_raw) <= 3:
                    norm_dist = ''.join(cls.LETTER_TO_DIGIT.get(ch, ch) for ch in dist_raw)
                    norm_series = ''.join(cls.DIGIT_TO_LETTER.get(ch, ch) for ch in series_raw)
                    if norm_dist.isdigit() and (len(norm_series) == 0 or norm_series.isalpha()):
                        return f"{norm_state}{norm_dist}{norm_series}{norm_num}", "STANDARD_INDIAN"
        return None

    @classmethod
    def validate_indian_plate(cls, text: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validates and normalizes Indian License Plate strings against MoRTH & Motor Vehicles Act standards:
        1. Standard Private/Commercial: ^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$ (e.g. DL01AB1234, TN87C5106, MH12AB3456)
        2. Bharat (BH) Series: ^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$ (e.g. 22BH1234AA)
        3. Military / Defence Fleet: ^(ARMY[A-Z0-9]{4,7}|[0-9]{2}[A-Z][0-9]{4,6}[A-Z0-9]?)$ (e.g. ARMY01X9988, ARMY9988)
        4. Diplomatic (CD/CC): ^[0-9]{2}(CD|CC)[0-9]{4}$

        Returns:
            (is_valid, normalized_plate, plate_category)
        """
        if not text:
            return False, None, None

        cleaned = re.sub(r"[^A-Z0-9]", "", text.upper())
        if cleaned.startswith("IND") and len(cleaned) > 5:
            cleaned = cleaned[3:]

        # Direct Check 1: Standard Indian State Plate (exact alphanumeric)
        m_std = re.match(r"^([A-Z]{2})([0-9]{1,2})([A-Z]{0,3})([0-9]{4})$", cleaned)
        if m_std and m_std.group(1) in cls.INDIAN_STATE_CODES:
            return True, cleaned, "STANDARD_INDIAN"

        # Direct Check 2: Bharat (BH) Series
        m_bh = re.match(r"^([0-9]{2})BH([0-9]{4})([A-Z]{1,2})$", cleaned)
        if m_bh:
            return True, cleaned, "BHARAT_SERIES"

        # Direct Check 3: Military / Defence Fleet
        m_mil = re.match(r"^(ARMY[A-Z0-9]{4,7}|[0-9]{2}[A-Z][0-9]{4,6}[A-Z0-9]?)$", cleaned)
        if m_mil:
            return True, cleaned, "MILITARY_FLEET"

        # Direct Check 4: Diplomatic (CD/CC)
        m_dip = re.match(r"^([0-9]{2})(CD|CC)([0-9]{4})$", cleaned)
        if m_dip:
            return True, cleaned, "DIPLOMATIC"

        # Positional character recovery for full string
        norm_res = cls._normalize_standard_candidate(cleaned)
        if norm_res:
            return True, norm_res[0], norm_res[1]

        # Substring scanning if string contains surrounding noise (e.g. MARUTI DL01AB1234 or dealer text)
        if len(cleaned) > 7:
            for l in range(min(11, len(cleaned)), 6, -1):
                for i in range(len(cleaned) - l + 1):
                    sub = cleaned[i:i + l]
                    if sub.startswith("IND") and len(sub) > 6:
                        sub = sub[3:]
                    m_sub = re.match(r"^([A-Z]{2})([0-9]{1,2})([A-Z]{0,3})([0-9]{4})$", sub)
                    if m_sub and m_sub.group(1) in cls.INDIAN_STATE_CODES:
                        return True, sub, "STANDARD_INDIAN"
                    sub_norm = cls._normalize_standard_candidate(sub)
                    if sub_norm:
                        return True, sub_norm[0], sub_norm[1]

        return False, None, None

    def extract_plate_with_diagnostics(self, crop: np.ndarray) -> Dict[str, Any]:
        """
        Runs OCR on an image crop and returns plate recognition metadata and diagnostics:
        - plate: normalized valid plate string or None
        - raw_text: candidate raw string
        - confidence: confidence score (0.0 to 1.0)
        - status: "RECOGNIZED", "LOW_CONFIDENCE", "UNREADABLE", or "OBSCURED"
        - crop_w: candidate crop width
        - crop_h: candidate crop height
        - category: e.g. "STANDARD_INDIAN", "BHARAT_SERIES", "MILITARY_FLEET", etc.
        """
        if not self._is_initialized or self.ocr_engine is None:
            if not self.initialize():
                return {
                    "plate": None,
                    "raw_text": "",
                    "confidence": 0.0,
                    "status": "UNREADABLE",
                    "crop_w": 0,
                    "crop_h": 0,
                    "category": None
                }

        if crop is None or getattr(crop, "size", 0) == 0:
            return {
                "plate": None,
                "raw_text": "",
                "confidence": 0.0,
                "status": "UNREADABLE",
                "crop_w": 0,
                "crop_h": 0,
                "category": None
            }

        crop_h, crop_w = crop.shape[:2]

        # Check for severe blur / occlusion in crop
        try:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
            lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            if lap_var < 5.0 and float(np.std(gray)) < 10.0:
                return {
                    "plate": None,
                    "raw_text": "",
                    "confidence": 0.0,
                    "status": "OBSCURED",
                    "crop_w": crop_w,
                    "crop_h": crop_h,
                    "category": None
                }
        except Exception:
            pass

        try:
            raw_candidates: List[Tuple[str, float]] = []
            # Optimize image size for faster OCR if excessively large
            ocr_input = crop
            if crop_h > 120 or crop_w > 480:
                scale = min(100.0 / crop_h, 440.0 / crop_w)
                ocr_input = cv2.resize(crop, (max(32, int(crop_w * scale)), max(32, int(crop_h * scale))), interpolation=cv2.INTER_AREA)

            # 1. RapidOCR invocation (use_cls=False avoids unnecessary 180-deg classifier, 50% faster)
            if hasattr(self.ocr_engine, "__call__"):
                try:
                    results, _ = self.ocr_engine(ocr_input, use_cls=False)
                except TypeError:
                    results, _ = self.ocr_engine(ocr_input)
                if results:
                    for line in results:
                        text = line[1]
                        score = float(line[2]) if len(line) > 2 else 0.85
                        raw_candidates.append((text, score))

            # 2. EasyOCR fallback
            elif hasattr(self.ocr_engine, "readtext"):
                res = self.ocr_engine.readtext(crop)
                if res:
                    for r in res:
                        score = float(r[2]) if len(r) > 2 else 0.85
                        raw_candidates.append((r[1], score))

            if not raw_candidates:
                return {
                    "plate": None,
                    "raw_text": "",
                    "confidence": 0.0,
                    "status": "UNREADABLE",
                    "crop_w": crop_w,
                    "crop_h": crop_h,
                    "category": None
                }

            # A. First pass: individual lines for valid Indian plate
            for rc, score in raw_candidates:
                is_valid, norm_plate, cat = self.validate_indian_plate(rc)
                if is_valid and norm_plate:
                    status = "RECOGNIZED" if score >= 0.45 else "LOW_CONFIDENCE"
                    return {
                        "plate": norm_plate,
                        "raw_text": rc,
                        "confidence": score,
                        "status": status,
                        "crop_w": crop_w,
                        "crop_h": crop_h,
                        "category": cat
                    }

            # B. Second pass: joined text
            if len(raw_candidates) > 1:
                joined = "".join(self.clean_plate_text(c[0]) for c in raw_candidates)
                avg_score = sum(c[1] for c in raw_candidates) / len(raw_candidates)
                is_valid, norm_plate, cat = self.validate_indian_plate(joined)
                if is_valid and norm_plate:
                    status = "RECOGNIZED" if avg_score >= 0.45 else "LOW_CONFIDENCE"
                    return {
                        "plate": norm_plate,
                        "raw_text": joined,
                        "confidence": avg_score,
                        "status": status,
                        "crop_w": crop_w,
                        "crop_h": crop_h,
                        "category": cat
                    }

            # C. Third pass: check against enrolled profiles (e.g. military/stolen)
            for rc, score in raw_candidates:
                c_text = self.clean_plate_text(rc)
                c_no_ind = c_text[3:] if c_text.startswith("IND") and len(c_text) > 5 else c_text
                c_norm = self._normalize_ocr_confusions(c_no_ind)
                for prof in self._profiles:
                    p_clean = prof["plate_number"]
                    p_norm = self._normalize_ocr_confusions(p_clean)
                    if c_no_ind == p_clean or c_norm == p_norm:
                        return {
                            "plate": prof["plate_number"],
                            "raw_text": rc,
                            "confidence": max(score, 0.90),
                            "status": "RECOGNIZED",
                            "crop_w": crop_w,
                            "crop_h": crop_h,
                            "category": "WATCHLIST_MATCH"
                        }

            # If candidates were extracted but didn't pass strict regex:
            best_raw, best_conf = max(raw_candidates, key=lambda x: x[1])
            clean_cand = self.clean_plate_text(best_raw)
            status = "LOW_CONFIDENCE" if len(clean_cand) >= 4 else "UNREADABLE"
            return {
                "plate": None,
                "raw_text": best_raw,
                "confidence": best_conf,
                "status": status,
                "crop_w": crop_w,
                "crop_h": crop_h,
                "category": None
            }

        except Exception as e:
            print(f"[ANPREngine] OCR diagnostic error: {e}")
            return {
                "plate": None,
                "raw_text": "",
                "confidence": 0.0,
                "status": "UNREADABLE",
                "crop_w": crop_w,
                "crop_h": crop_h,
                "category": None
            }

    def extract_plate_from_crop(self, crop: np.ndarray) -> Optional[str]:
        """Runs OCR on an image crop to detect license plate alphanumeric string."""
        diag = self.extract_plate_with_diagnostics(crop)
        return diag.get("plate")

    @staticmethod
    def _normalize_ocr_confusions(text: str) -> str:
        """
        Normalizes commonly confused OCR characters in license plates:
        O -> 0, I -> 1, Z -> 2, S -> 5, B -> 8
        """
        mapping = str.maketrans({
            "O": "0",
            "I": "1",
            "Z": "2",
            "S": "5",
            "B": "8"
        })
        return text.translate(mapping)

    def match_plate(self, plate_number: str) -> Dict[str, Any]:
        """
        Checks detected plate against in-memory vehicle watchlist with:
        1. Exact match.
        2. Cleaned match (no spaces/hyphens).
        3. Prefix-stripped match (e.g. "IND" country prefix on Indian HSRP plates).
        4. OCR confusion normalization (O/0, I/1, Z/2, S/5, B/8).
        5. Live database query fallback.
        """
        cleaned = self.clean_plate_text(plate_number)
        if not cleaned:
            return {"matched": False, "status": "INVALID", "plate": None, "owner_name": "", "notes": "Empty text"}

        # Strip "IND" country identifier if prepended by Indian HSRP plates
        clean_no_ind = cleaned[3:] if cleaned.startswith("IND") and len(cleaned) > 5 else cleaned
        norm_cleaned = self._normalize_ocr_confusions(clean_no_ind)

        def _check_profile_match(p_prof: str) -> bool:
            p_clean = self.clean_plate_text(p_prof)
            p_norm = self._normalize_ocr_confusions(p_clean)

            # 1. Exact match (with and without IND)
            if clean_no_ind == p_clean or cleaned == p_clean:
                return True

            # 2. Normalized OCR character confusion exact match
            if norm_cleaned == p_norm:
                return True

            return False

        # 1. Check in-memory profiles first
        for prof in self._profiles:
            if _check_profile_match(prof["plate_number"]):
                return {
                    "matched": True,
                    "id": prof["id"],
                    "plate": prof["plate_number"],
                    "vehicle_type": prof["vehicle_type"],
                    "owner_name": prof["owner_name"],
                    "status": prof["status"],
                    "notes": prof["notes"]
                }

        # 2. Real-time DB lookup fallback (guarantees newly added profiles are NEVER missed)
        db = SessionLocal()
        try:
            records = db.query(VehicleProfile).all()
            for rec in records:
                if _check_profile_match(rec.plate_number):
                    # Cache in memory for subsequent frames
                    self.reload_profiles()
                    return {
                        "matched": True,
                        "id": rec.id,
                        "plate": rec.plate_number,
                        "vehicle_type": rec.vehicle_type,
                        "owner_name": rec.owner_name or "Unknown",
                        "status": rec.status,
                        "notes": rec.notes or ""
                    }
        except Exception as e:
            print(f"[ANPREngine] DB fallback error: {e}")
        finally:
            db.close()

        # 3. Not in watchlist - validate if it is a genuine civilian Indian plate
        is_valid, valid_plate, _ = self.validate_indian_plate(clean_no_ind)
        if is_valid:
            return {
                "matched": False,
                "status": "CIVILIAN",
                "plate": valid_plate,
                "owner_name": "Unregistered",
                "notes": "Civilian Border Transit"
            }

        # If it fails format validation and is not in watchlist, reject as invalid
        return {
            "matched": False,
            "status": "INVALID",
            "plate": None,
            "owner_name": "",
            "notes": "Non-plate text rejected"
        }

    def localize_plate_candidates(self, vehicle_crop: np.ndarray) -> List[np.ndarray]:
        """
        Classical Computer Vision License Plate Region Localizer.
        Extracts and scores candidate plate crops from a vehicle image using:
        1. Vertical edge gradient density (Sobel-X) & Blackhat morphology.
        2. Morphological grouping with horizontal structuring kernel.
        3. Otsu adaptive thresholding.
        4. Contour geometry filtering (rectangular aspect ratio ~1.8 to 6.2, area constraints).
        5. Geometric and variance scoring to rank high-probability plate candidate regions.
        6. Preserves bumper ROI crop as fallback candidate.
        """
        if vehicle_crop is None or vehicle_crop.size == 0:
            return []

        vh, vw = vehicle_crop.shape[:2]
        if vh < 25 or vw < 35:
            return [vehicle_crop]

        candidates: List[Tuple[float, np.ndarray]] = []

        # 1. Bumper ROI candidate (Standard baseline crop: lower 55%, center 80%)
        by1 = max(0, int(vh * 0.45))
        by2 = vh
        bx1 = max(0, int(vw * 0.10))
        bx2 = min(vw, int(vw * 0.90))
        bumper_crop = vehicle_crop[by1:by2, bx1:bx2]
        if bumper_crop.size > 0:
            candidates.append((0.50, bumper_crop))

        # 2. Search region for morphological contour analysis (lower 65% of vehicle)
        sy1 = max(0, int(vh * 0.35))
        search_roi = vehicle_crop[sy1:vh, 0:vw]
        s_h, s_w = search_roi.shape[:2]

        if s_h >= 24 and s_w >= 48:
            try:
                gray = cv2.cvtColor(search_roi, cv2.COLOR_BGR2GRAY)

                # Contrast CLAHE enhancement + Bilateral filtering
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                contrast = clahe.apply(gray)
                blurred = cv2.bilateralFilter(contrast, 7, 50, 50)

                # Vertical edge gradient (character vertical strokes)
                grad_x = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
                grad_x = np.absolute(grad_x)
                min_v, max_v = np.min(grad_x), np.max(grad_x)
                if max_v > min_v:
                    grad_norm = (255 * ((grad_x - min_v) / (max_v - min_v))).astype(np.uint8)
                else:
                    grad_norm = blurred

                # Close horizontally to connect alphanumeric characters into a solid rectangular blob
                close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 3))
                closed = cv2.morphologyEx(grad_norm, cv2.MORPH_CLOSE, close_kernel)

                # Otsu thresholding
                _, thresh = cv2.threshold(closed, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

                # Clean stray noise
                erode_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
                cleaned = cv2.erode(thresh, erode_kernel, iterations=1)
                dilated = cv2.dilate(cleaned, close_kernel, iterations=1)

                contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                for cnt in contours:
                    cx, cy, cw, ch = cv2.boundingRect(cnt)
                    if ch == 0:
                        continue
                    ar = cw / float(ch)
                    area = cw * ch

                    # Aspect ratio of standard Indian / global plates: ~1.8 to 6.2
                    # Minimum plate dimensions: at least 35px wide, 10px high
                    if 1.8 <= ar <= 6.2 and cw >= 35 and ch >= 10:
                        # Area constraint
                        if 350 <= area <= 0.60 * (s_h * s_w):
                            # a) Aspect ratio score (closeness to ideal ~3.8)
                            ar_score = 1.0 - min(1.0, abs(ar - 3.8) / 3.8)
                            # b) Contrast / variance score inside candidate
                            crop_gray = gray[cy:cy + ch, cx:cx + cw]
                            var_score = min(1.0, float(np.std(crop_gray)) / 45.0) if crop_gray.size > 0 else 0.0
                            # c) Position score: centered horizontally, lower vertically
                            center_score = 1.0 - min(1.0, abs((cx + cw / 2.0) - (s_w / 2.0)) / (s_w / 2.0))
                            pos_score = cy / float(s_h)

                            total_score = ar_score * 0.40 + var_score * 0.35 + center_score * 0.15 + pos_score * 0.10

                            # Add generous margin padding around plate to prevent edge character truncation
                            pad_x = max(6, int(cw * 0.18))
                            pad_y = max(5, int(ch * 0.22))
                            py1 = max(0, cy - pad_y)
                            py2 = min(s_h, cy + ch + pad_y)
                            px1 = max(0, cx - pad_x)
                            px2 = min(s_w, cx + cw + pad_x)

                            cand_crop = search_roi[py1:py2, px1:px2]
                            if cand_crop.size > 0:
                                candidates.append((total_score, cand_crop))
            except Exception:
                pass

        # Sort candidates by score descending
        candidates.sort(key=lambda c: c[0], reverse=True)
        return [c[1] for c in candidates]

    def process_vehicles(self, frame: np.ndarray, vehicle_detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Processes each detected vehicle:
        1. Crops vehicle ROI.
        2. Applies classical CV plate candidate localizer.
        3. Evaluates ranked candidate crops through RapidOCR.
        4. Falls back to bumper ROI and full vehicle crop if needed.
        5. Validates and matches plate against database watchlist.
        """
        if not self._is_initialized:
            self.initialize()

        if not self._is_initialized or frame is None or len(vehicle_detections) == 0:
            return vehicle_detections

        h, w = frame.shape[:2]

        for v in vehicle_detections:
            vx, vy, vw, vh = v["bbox"]
            y1 = max(0, vy)
            y2 = min(h, vy + vh)
            x1 = max(0, vx)
            x2 = min(w, vx + vw)

            if y2 <= y1 or x2 <= x1:
                v["plate_number"] = None
                v["plate_status"] = "CIVILIAN"
                continue

            veh_crop = frame[y1:y2, x1:x2]

            # 1. Classical candidate localization
            candidates = self.localize_plate_candidates(veh_crop)

            detected_plate = None
            for cand in candidates:
                detected_plate = self.extract_plate_from_crop(cand)
                if detected_plate:
                    break

            # 2. Fallback: try full vehicle crop if candidates failed
            if not detected_plate and vw >= 100 and vh >= 80:
                detected_plate = self.extract_plate_from_crop(veh_crop)

            if detected_plate:
                match_info = self.match_plate(detected_plate)
                v["plate_number"] = match_info["plate"]
                v["plate_status"] = match_info["status"]
                v["owner_name"] = match_info.get("owner_name", "")
                v["plate_notes"] = match_info.get("notes", "")
            else:
                v["plate_number"] = None
                v["plate_status"] = "CIVILIAN"

        return vehicle_detections
