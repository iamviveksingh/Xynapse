import cv2
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from backend.detection.hud_renderer import draw_modern_pill_badge


class VirtualTripwireDetector:
    """
    Virtual Border Fence / Geofence Intrusion Detection Module.
    Supports:
    1. 1D Horizontal Virtual Tripwire line (line_y_ratio).
    2. 2D Multi-Point Polygon Virtual Fence (P1 -> P2 -> ... -> Pn).
    Tracks person reference point (bottom-center / foot contact point).
    Detects OUTSIDE -> INSIDE transitions to prevent duplicate alert storms.
    """

    def __init__(
        self,
        line_y_ratio: float = 0.65,
        enabled: bool = True,
        fence_type: str = "LINE",
        polygon_points: Optional[List[List[float]]] = None
    ):
        self.line_y_ratio = max(0.1, min(0.95, line_y_ratio))
        self.enabled = enabled
        self.fence_type = fence_type.upper() if fence_type else "LINE"
        self.is_breached = False
        self.last_breach_time: Optional[float] = None

        self.polygon_points: Optional[List[List[float]]] = None
        self.normalized_polygon_points: Optional[List[List[float]]] = None
        self.is_normalized: bool = False
        self._poly_np: Optional[np.ndarray] = None
        self._legacy_pixel_pts: Optional[List[List[float]]] = None
        self._cached_shape: Optional[Tuple[int, int]] = None
        self._cached_poly_np: Optional[np.ndarray] = None

        # Track ID state machine: track_id -> "OUTSIDE" | "INSIDE"
        self._track_states: Dict[Any, str] = {}
        self._active_track_ids: set = set()

        if polygon_points:
            self.set_polygon(polygon_points)

    def set_polygon(
        self,
        points: List[List[float]],
        reference_shape: Optional[Tuple[int, ...]] = None
    ) -> bool:
        """
        Configures a 2D perimeter geofence from an ordered list of (x, y) coordinates.
        Supports:
        - Normalized coordinates in [0.0, 1.0] (resolution-independent).
        - Legacy pixel coordinates (automatically migrated using reference_shape or legacy fallback).
        Validates:
        - At least 3 points required.
        - Numeric, finite, non-negative values.
        """
        if not points or not isinstance(points, (list, tuple)):
            raise ValueError("Polygon points must be a non-empty list of [x, y] coordinates.")

        if len(points) < 3:
            raise ValueError(f"Polygon requires at least 3 vertices, got {len(points)}.")

        clean_pts: List[List[float]] = []
        is_normalized = True

        for idx, pt in enumerate(points):
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                raise ValueError(f"Vertex {idx} must be a 2D coordinate [x, y], got {pt}.")
            try:
                x = float(pt[0])
                y = float(pt[1])
            except (ValueError, TypeError):
                raise ValueError(f"Vertex {idx} contains non-numeric coordinates: {pt}.")

            if np.isnan(x) or np.isnan(y) or np.isinf(x) or np.isinf(y):
                raise ValueError(f"Vertex {idx} contains NaN or Infinite coordinate.")

            if x < 0 or y < 0:
                raise ValueError(f"Vertex {idx} coordinates must be non-negative, got ({x}, {y}).")

            if x > 1.0 or y > 1.0:
                is_normalized = False

            clean_pts.append([x, y])

        self.polygon_points = clean_pts
        self.is_normalized = is_normalized
        self._cached_shape = None
        self._cached_poly_np = None

        if is_normalized:
            # Normalized coordinates in [0.0, 1.0]
            self.normalized_polygon_points = [[max(0.0, min(1.0, p[0])), max(0.0, min(1.0, p[1]))] for p in clean_pts]
            self._legacy_pixel_pts = None
            self._poly_np = None
        else:
            # Legacy pixel coordinates
            self._legacy_pixel_pts = clean_pts
            self._poly_np = np.array(clean_pts, dtype=np.int32).reshape((-1, 1, 2))
            if reference_shape is not None and len(reference_shape) >= 2:
                ref_h, ref_w = float(reference_shape[0]), float(reference_shape[1])
                self.normalized_polygon_points = [
                    [max(0.0, min(1.0, p[0] / ref_w)), max(0.0, min(1.0, p[1] / ref_h))]
                    for p in clean_pts
                ]
                self.is_normalized = True
                self._legacy_pixel_pts = None
            else:
                # Infer reference resolution from max extents or standard default
                max_x = max(p[0] for p in clean_pts)
                max_y = max(p[1] for p in clean_pts)
                ref_w = max(640.0, max_x)
                ref_h = max(480.0, max_y)
                self.normalized_polygon_points = [
                    [max(0.0, min(1.0, p[0] / ref_w)), max(0.0, min(1.0, p[1] / ref_h))]
                    for p in clean_pts
                ]

        self.fence_type = "POLYGON"
        return True

    def get_polygon(self) -> Optional[List[List[float]]]:
        """Returns the configured polygon vertices or None."""
        return [list(p) for p in self.polygon_points] if self.polygon_points else None

    def get_normalized_polygon(self) -> Optional[List[List[float]]]:
        """Returns resolution-independent normalized polygon coordinates in [0.0, 1.0]."""
        return [list(p) for p in self.normalized_polygon_points] if self.normalized_polygon_points else None

    def get_polygon_for_shape(self, frame_shape: Tuple[int, ...]) -> Optional[np.ndarray]:
        """
        Dynamically scales polygon vertices to current runtime frame dimensions (h, w).
        Uses normalized coordinates [0.0, 1.0] if available, with legacy pixel fallback.
        """
        if self.fence_type != "POLYGON":
            return None

        h, w = int(frame_shape[0]), int(frame_shape[1])
        if self._cached_shape == (h, w) and self._cached_poly_np is not None:
            return self._cached_poly_np

        if self.normalized_polygon_points and (self.is_normalized or self._legacy_pixel_pts is None):
            scaled_pts = [
                [int(round(p[0] * w)), int(round(p[1] * h))]
                for p in self.normalized_polygon_points
            ]
            poly_np = np.array(scaled_pts, dtype=np.int32).reshape((-1, 1, 2))
            self._cached_shape = (h, w)
            self._cached_poly_np = poly_np
            return poly_np

        # If legacy pixel coordinates without explicit normalization, return raw legacy poly_np
        if self._poly_np is not None:
            return self._poly_np

        return None

    def set_line(self, line_y_ratio: float) -> None:
        """Configures 1D horizontal tripwire line ratio."""
        self.line_y_ratio = max(0.1, min(0.95, float(line_y_ratio)))
        self.fence_type = "LINE"

    def check_point_inside(self, x: float, y: float, frame_shape: Tuple[int, ...]) -> bool:
        """
        Determines whether a point (x, y) lies inside or on the boundary of the virtual fence.
        - Polygon: scales to frame_shape at runtime and uses cv2.pointPolygonTest (dist >= 0)
        - Line: checks y >= line_y (derived from normalized line_y_ratio * frame_h)
        """
        if self.fence_type == "POLYGON":
            poly_np = self.get_polygon_for_shape(frame_shape)
            if poly_np is not None:
                dist = cv2.pointPolygonTest(poly_np, (float(x), float(y)), False)
                return dist >= 0.0
            return False
        else:
            h = frame_shape[0]
            line_y = int(h * self.line_y_ratio)
            return y >= line_y

    def check_intrusion(
        self,
        frame_shape: Tuple[int, ...],
        detections: List[Dict[str, Any]]
    ) -> Tuple[bool, List[Dict[str, Any]], Any]:
        """
        Checks if any detected person has stepped into the virtual fence / crossed the line.
        A person is evaluated using the bottom-center of their bounding box (foot contact point).

        Returns:
            (is_breached, list_of_breached_detections, line_y_or_poly_pts)
        Each breached detection dictionary is annotated with:
            - 'is_inside_fence': True
            - 'is_new_intrusion': True (if transitioning OUTSIDE -> INSIDE)
        """
        if not self.enabled or not detections:
            self.is_breached = False
            ref_geom = self._poly_np if self.fence_type == "POLYGON" else int(frame_shape[0] * self.line_y_ratio)
            return False, [], ref_geom

        h, w = frame_shape[:2]
        breached_detections = []
        current_seen_tracks = set()

        for det in detections:
            bbox = det.get("bbox")
            if not bbox or len(bbox) < 4:
                continue

            bx, by, bw, bh = bbox
            # Foot / ground contact point (bottom-center of bounding box)
            foot_x = bx + bw // 2
            foot_y = by + bh

            # Deterministic track identifier for deduplication
            track_id = det.get("track_id")
            if track_id is None:
                # Fallback spatial hash key
                track_id = f"{int(bx // 25)}_{int(by // 25)}"

            current_seen_tracks.add(track_id)
            prev_state = self._track_states.get(track_id, "OUTSIDE")

            # Check inside condition
            is_inside = self.check_point_inside(foot_x, foot_y, frame_shape)

            if is_inside:
                det["is_inside_fence"] = True
                # Detect transition: only OUTSIDE -> INSIDE constitutes a NEW breach event
                if prev_state != "INSIDE":
                    det["is_new_intrusion"] = True
                    self._track_states[track_id] = "INSIDE"
                else:
                    det["is_new_intrusion"] = False

                breached_detections.append(det)
            else:
                det["is_inside_fence"] = False
                det["is_new_intrusion"] = False
                self._track_states[track_id] = "OUTSIDE"

        # Prune stale tracks to prevent unbounded memory growth
        if len(self._track_states) > 500:
            stale_keys = [k for k in self._track_states if k not in current_seen_tracks]
            for sk in stale_keys[:250]:
                self._track_states.pop(sk, None)

        self.is_breached = len(breached_detections) > 0
        poly_geom = self.get_polygon_for_shape(frame_shape)
        ref_geom = poly_geom if self.fence_type == "POLYGON" else int(h * self.line_y_ratio)
        return self.is_breached, breached_detections, ref_geom

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

    def draw_tripwire(
        self,
        frame: np.ndarray,
        is_breached: bool = False,
        is_authorized_crossing: bool = False,
        is_wildlife_crossing: bool = False
    ) -> np.ndarray:
        """
        Renders sleek tactical HUD visualization:
        - If 2D Polygon: Glowing multi-vertex boundary with semi-transparent glass polygon fill.
        - If 1D Line: Glowing laser boundary line.
        """
        if not self.enabled or frame is None or frame.size == 0:
            return frame

        h, w = frame.shape[:2]
        annotated = frame.copy()

        # Determine theme colors and status text based on state
        if is_breached and not is_authorized_crossing and not is_wildlife_crossing:
            line_color = (68, 68, 239)     # Crimson Red
            glow_color = (30, 30, 160)
            accent_rgb = (239, 68, 68)
            status_text = "Perimeter Geofence Breach • Alert"
        elif is_wildlife_crossing:
            line_color = (40, 180, 220)    # Tactical Amber / Olive
            glow_color = (20, 90, 110)
            accent_rgb = (220, 180, 40)
            status_text = "Wildlife Transit Filtered • Siren Suppressed"
        elif is_authorized_crossing:
            line_color = (129, 185, 16)    # Emerald Green
            glow_color = (20, 80, 40)
            accent_rgb = (16, 185, 129)
            status_text = "Authorized Crossing • Pass"
        else:
            line_color = (212, 182, 6)     # Cyan
            glow_color = (100, 80, 0)
            accent_rgb = (6, 182, 212)
            status_text = "Restricted Perimeter Geofence • Zero-Line"

        # -------------------------------------------------------------
        # Mode A: 2D Polygon Geofence Rendering
        # -------------------------------------------------------------
        pts = self.get_polygon_for_shape(frame.shape)
        if self.fence_type == "POLYGON" and pts is not None and len(pts) >= 3:

            # 1. Fast crisp perimeter polyline (no full-frame copies or expensive full-frame blending)
            cv2.polylines(annotated, [pts], True, glow_color, 2, cv2.LINE_AA)
            cv2.polylines(annotated, [pts], True, line_color, 1, cv2.LINE_AA)

            # 2. Corner vertex reticles
            for pt in pts:
                px, py = int(pt[0][0]), int(pt[0][1])
                cv2.circle(annotated, (px, py), 3, line_color, -1, cv2.LINE_AA)

            # 3. HUD Pill badge placed at the topmost vertex
            top_pt = min(pts, key=lambda p: p[0][1])[0]
            bx = max(10, min(w - 240, int(top_pt[0]) - 80))
            by = max(10, int(top_pt[1]) - 28)
            draw_modern_pill_badge(
                annotated,
                x=bx,
                y=by,
                text=status_text,
                accent_rgb=accent_rgb,
                bg_rgba=(10, 15, 24, 215),
                radius=6,
                font_size=11
            )
            return annotated

        # -------------------------------------------------------------
        # Mode B: 1D Horizontal Virtual Tripwire Line Rendering
        # -------------------------------------------------------------
        line_y = int(h * self.line_y_ratio)

        # 1. Subtle glowing laser beam (hairline + glow bloom)
        cv2.line(annotated, (0, line_y), (w, line_y), glow_color, 3, cv2.LINE_AA)
        cv2.line(annotated, (0, line_y), (w, line_y), line_color, 1, cv2.LINE_AA)

        # 2. Terminal end reticles
        cv2.circle(annotated, (6, line_y), 3, line_color, -1, cv2.LINE_AA)
        cv2.circle(annotated, (w - 6, line_y), 3, line_color, -1, cv2.LINE_AA)

        # 3. Modern Anti-Aliased Glassmorphic Pill Badge
        draw_modern_pill_badge(
            annotated,
            x=20,
            y=max(4, line_y - 28),
            text=status_text,
            accent_rgb=accent_rgb,
            bg_rgba=(10, 15, 24, 215),
            radius=6,
            font_size=11
        )

        return annotated
