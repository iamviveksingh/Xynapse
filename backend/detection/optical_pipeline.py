import cv2
import numpy as np
from typing import Tuple, Optional


class LowLightDetector:
    """
    Automatic Ambient Luminance & Low-Light Detection Engine.
    Measures frame luminance using fast downsampled grayscale statistics.
    Implements dual-threshold hysteresis and debounce filtering to prevent rapid
    flickering between DAY and NIGHT enhancement modes at dusk/dawn illumination boundaries.

    Hysteresis Logic:
    - ENTER LOW LIGHT: smoothed luminance falls below enter_threshold (default 45.0/255).
    - EXIT LOW LIGHT: smoothed luminance rises above exit_threshold (default 58.0/255).
    Since enter_threshold < exit_threshold, minor fluctuations near boundary do not toggle state.
    """

    def __init__(
        self,
        enter_threshold: float = 45.0,
        exit_threshold: float = 58.0,
        smoothing_alpha: float = 0.25,
        consecutive_frames: int = 4
    ):
        if enter_threshold >= exit_threshold:
            raise ValueError(
                f"enter_threshold ({enter_threshold}) must be strictly less than exit_threshold ({exit_threshold})"
            )

        self.enter_threshold = float(enter_threshold)
        self.exit_threshold = float(exit_threshold)
        self.smoothing_alpha = float(smoothing_alpha)
        self.consecutive_frames = int(consecutive_frames)

        self.smoothed_luminance: Optional[float] = None
        self.current_luminance: float = 128.0
        self.is_low_light: bool = False

        self._enter_candidate_count: int = 0
        self._exit_candidate_count: int = 0

    @staticmethod
    def compute_luminance(frame: np.ndarray) -> float:
        """
        Computes mean grayscale luminance [0.0 to 255.0].
        Downsamples to 160x120 for sub-millisecond (<0.1ms) computational overhead.
        """
        if frame is None or frame.size == 0:
            return 128.0
        try:
            if len(frame.shape) == 3 and frame.shape[2] == 3:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                gray = frame

            # Fast downsampling for statistical luminance calculation
            small = cv2.resize(gray, (160, 120), interpolation=cv2.INTER_NEAREST)
            return float(np.mean(small))
        except Exception:
            return 128.0

    def classify_single_frame(self, frame: np.ndarray) -> Tuple[bool, float]:
        """Stateless one-shot classification (useful for unit tests and direct checks)."""
        lum = self.compute_luminance(frame)
        is_dark = lum < self.enter_threshold
        return is_dark, lum

    def update(self, frame: np.ndarray) -> Tuple[bool, float, str]:
        """
        Feeds incoming video frame, updates exponential moving average,
        evaluates hysteresis state transitions, and returns:
            (is_low_light, current_smoothed_luminance, recommended_mode)
        """
        instant_lum = self.compute_luminance(frame)
        self.current_luminance = instant_lum

        # Exponential Moving Average for illumination stability
        if self.smoothed_luminance is None:
            self.smoothed_luminance = instant_lum
        else:
            self.smoothed_luminance = (
                self.smoothing_alpha * instant_lum
                + (1.0 - self.smoothing_alpha) * self.smoothed_luminance
            )

        # State Transition Machine with Hysteresis
        if not self.is_low_light:
            # Condition to enter Low-Light Mode
            if self.smoothed_luminance < self.enter_threshold:
                self._enter_candidate_count += 1
                if self._enter_candidate_count >= self.consecutive_frames:
                    self.is_low_light = True
                    self._enter_candidate_count = 0
            else:
                self._enter_candidate_count = 0
        else:
            # Condition to exit Low-Light Mode back to Standard
            if self.smoothed_luminance > self.exit_threshold:
                self._exit_candidate_count += 1
                if self._exit_candidate_count >= self.consecutive_frames:
                    self.is_low_light = False
                    self._exit_candidate_count = 0
            else:
                self._exit_candidate_count = 0

        recommended_mode = "LOW_LIGHT_ENHANCE" if self.is_low_light else "STANDARD"
        return self.is_low_light, self.smoothed_luminance, recommended_mode

    def reset(self, initial_luminance: Optional[float] = None) -> None:
        """Resets detector state."""
        self.smoothed_luminance = initial_luminance
        self.is_low_light = False
        self._enter_candidate_count = 0
        self._exit_candidate_count = 0


class OpticalPipeline:
    """
    Tactical Multi-Band Optical Processing Engine for Border Surveillance.
    Supports:
    1. STANDARD: Natural Visible Light (Day / Color RGB).
    2. LOW_LIGHT_ENHANCE: Adaptive CLAHE Y-Luminance Boost for Dawn/Dusk/Night.
    3. NVG_GREEN: Military Night Vision Goggle (Green Phosphor PVS-14 simulation).
    4. FLIR_THERMAL: Long-Wave Infrared (LWIR) Ironbow False-Color Heatmap.
    """

    MODES = ["STANDARD", "LOW_LIGHT_ENHANCE", "NVG_GREEN", "FLIR_THERMAL"]

    def __init__(self):
        self._clahe = cv2.createCLAHE(clipLimit=3.2, tileGridSize=(8, 8))
        self.low_light_detector = LowLightDetector()

    def process_frame(self, frame: np.ndarray, mode: str = "STANDARD") -> np.ndarray:
        """Transforms input frame according to selected tactical optical mode."""
        if frame is None or frame.size == 0:
            return frame

        mode_upper = (mode or "STANDARD").upper()
        if mode_upper == "LOW_LIGHT_ENHANCE":
            return self._apply_clahe_enhancement(frame)
        elif mode_upper == "NVG_GREEN":
            return self._apply_nvg_green(frame)
        elif mode_upper == "FLIR_THERMAL":
            return self._apply_flir_thermal(frame)
        return frame

    def _apply_clahe_enhancement(self, frame: np.ndarray) -> np.ndarray:
        """Boosts shadow luminance and micro-contrast using YCrCb adaptive CLAHE."""
        try:
            ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
            y, cr, cb = cv2.split(ycrcb)
            y_eq = self._clahe.apply(y)
            merged = cv2.merge([y_eq, cr, cb])
            return cv2.cvtColor(merged, cv2.COLOR_YCrCb2BGR)
        except Exception:
            return frame

    def _apply_nvg_green(self, frame: np.ndarray) -> np.ndarray:
        """Simulates military PVS-14 green phosphor night vision optics."""
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray_eq = self._clahe.apply(gray)
            nvg = np.zeros_like(frame)
            nvg[:, :, 0] = (gray_eq * 0.15).astype(np.uint8)
            nvg[:, :, 1] = gray_eq
            nvg[:, :, 2] = (gray_eq * 0.10).astype(np.uint8)
            return nvg
        except Exception:
            return frame

    def _apply_flir_thermal(self, frame: np.ndarray) -> np.ndarray:
        """Simulates FLIR Ironbow thermal infrared sensor imagery."""
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray_eq = self._clahe.apply(gray)
            return cv2.applyColorMap(gray_eq, cv2.COLORMAP_INFERNO)
        except Exception:
            return frame
