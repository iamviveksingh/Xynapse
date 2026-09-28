import time
import threading
from typing import Dict

class CooldownTracker:
    """
    Thread-safe per-camera alert debouncer.
    Prevents alert flooding when an individual remains in the camera frame.
    """

    def __init__(self, cooldown_seconds: int = 10):
        self.cooldown_seconds = cooldown_seconds
        self._last_alert_times: Dict[str, float] = {}
        self._lock = threading.Lock()

    def is_cooled_down(self, camera_id: str) -> bool:
        with self._lock:
            last_time = self._last_alert_times.get(camera_id, 0.0)
            return (time.time() - last_time) >= self.cooldown_seconds

    def trigger(self, camera_id: str) -> None:
        with self._lock:
            self._last_alert_times[camera_id] = time.time()

    def get_remaining_cooldown(self, camera_id: str) -> float:
        with self._lock:
            last_time = self._last_alert_times.get(camera_id, 0.0)
            elapsed = time.time() - last_time
            return max(0.0, self.cooldown_seconds - elapsed)

    def reset(self, camera_id: str = None) -> None:
        with self._lock:
            if camera_id:
                self._last_alert_times.pop(camera_id, None)
            else:
                self._last_alert_times.clear()
