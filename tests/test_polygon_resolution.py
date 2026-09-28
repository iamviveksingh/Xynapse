import pytest
import numpy as np
from backend.detection.intrusion_detector import VirtualTripwireDetector

def test_polygon_normalized_representation():
    """Verify polygon points can be initialized in [0.0, 1.0] and retrieved cleanly."""
    norm_pts = [[0.1, 0.2], [0.9, 0.2], [0.8, 0.85], [0.2, 0.85]]
    detector = VirtualTripwireDetector()
    detector.set_polygon(norm_pts)

    assert detector.fence_type == "POLYGON"
    assert detector.is_normalized is True
    retrieved = detector.get_normalized_polygon()
    assert retrieved is not None
    assert len(retrieved) == 4
    for orig, ret in zip(norm_pts, retrieved):
        assert abs(orig[0] - ret[0]) < 1e-5
        assert abs(orig[1] - ret[1]) < 1e-5

def test_polygon_multi_resolution_consistency():
    """
    P0-2 Requirement:
    Verify that the exact same normalized logical fence remains spatially consistent
    across 640x480, 1280x720, 1920x1080, and 800x600 (non-standard).
    """
    # Define a logical fence in normalized ratio space: center box [0.25, 0.25] to [0.75, 0.75]
    norm_pts = [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]
    detector = VirtualTripwireDetector()
    detector.set_polygon(norm_pts)

    test_resolutions = [
        (480, 640),    # 640x480 standard SD (4:3)
        (720, 1280),   # 1280x720 HD (16:9)
        (1080, 1920),  # 1920x1080 Full HD (16:9)
        (600, 800),    # 800x600 SVGA non-standard (4:3)
    ]

    for h, w in test_resolutions:
        frame_shape = (h, w, 3)

        # 1. Scaled runtime polygon vertices check
        poly_pts = detector.get_polygon_for_shape(frame_shape)
        assert poly_pts is not None
        assert len(poly_pts) == 4

        # Expected corner pixels
        expected_top_left = (int(round(0.25 * w)), int(round(0.25 * h)))
        expected_bottom_right = (int(round(0.75 * w)), int(round(0.75 * h)))
        assert (poly_pts[0][0][0], poly_pts[0][0][1]) == expected_top_left
        assert (poly_pts[2][0][0], poly_pts[2][0][1]) == expected_bottom_right

        # 2. Centroid point (50%, 50%) MUST be inside across all resolutions
        cx, cy = int(0.50 * w), int(0.50 * h)
        assert detector.check_point_inside(cx, cy, frame_shape) is True, f"Failed at {w}x{h}"

        # 3. Outer points (10%, 10%) and (90%, 90%) MUST be outside across all resolutions
        out_x1, out_y1 = int(0.10 * w), int(0.10 * h)
        out_x2, out_y2 = int(0.90 * w), int(0.90 * h)
        assert detector.check_point_inside(out_x1, out_y1, frame_shape) is False, f"Failed at {w}x{h}"
        assert detector.check_point_inside(out_x2, out_y2, frame_shape) is False, f"Failed at {w}x{h}"

        # 4. Boundary points (25%, 50%) MUST be considered inside/on-edge across all resolutions
        bx, by = int(round(0.25 * w)), int(round(0.50 * h))
        assert detector.check_point_inside(bx, by, frame_shape) is True, f"Failed boundary at {w}x{h}"

def test_polygon_drawing_across_resolutions():
    """Verify that drawing the virtual fence succeeds without distortion on varying resolutions."""
    detector = VirtualTripwireDetector()
    detector.set_polygon([[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]])

    resolutions = [(480, 640), (720, 1280), (1080, 1920), (600, 800)]
    for h, w in resolutions:
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        rendered = detector.draw_tripwire(frame, is_breached=False)
        assert rendered.shape == (h, w, 3)
        # Verify rendered frame is not empty (contains HUD markings)
        assert np.count_nonzero(rendered) > 0

def test_line_fence_across_resolutions():
    """Verify that LINE fence type also scales dynamically across all resolutions."""
    detector = VirtualTripwireDetector(line_y_ratio=0.60, fence_type="LINE")

    resolutions = [(480, 640), (720, 1280), (1080, 1920), (600, 800)]
    for h, w in resolutions:
        frame_shape = (h, w, 3)
        # Above line (y = 50% of h) -> not breached
        assert detector.check_point_inside(w // 2, int(0.50 * h), frame_shape) is False
        # Below line (y = 70% of h) -> breached
        assert detector.check_point_inside(w // 2, int(0.70 * h), frame_shape) is True

def test_legacy_pixel_migration():
    """Verify legacy pixel coordinates (e.g. from 640x480) migrate safely to normalized space."""
    legacy_pts = [[160, 120], [480, 120], [480, 360], [160, 360]]
    detector = VirtualTripwireDetector()
    detector.set_polygon(legacy_pts, reference_shape=(480, 640))

    norm_pts = detector.get_normalized_polygon()
    assert norm_pts is not None
    # 160/640 = 0.25, 120/480 = 0.25, 480/640 = 0.75, 360/480 = 0.75
    assert abs(norm_pts[0][0] - 0.25) < 1e-4
    assert abs(norm_pts[0][1] - 0.25) < 1e-4
    assert abs(norm_pts[1][0] - 0.75) < 1e-4
    assert abs(norm_pts[1][1] - 0.25) < 1e-4

    # When tested on a 1920x1080 frame, the migrated fence should scale to (480, 270) -> (1440, 810)
    scaled_1080 = detector.get_polygon_for_shape((1080, 1920, 3))
    assert scaled_1080[0][0][0] == int(round(0.25 * 1920))  # 480
    assert scaled_1080[0][0][1] == int(round(0.25 * 1080))  # 270
