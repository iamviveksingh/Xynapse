import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.config import settings
settings.CAMERA_SOURCE = "mock_camera"

from backend.api.cameras import camera_registry

@pytest.fixture(autouse=True)
def cleanup_camera_threads():
    """Ensures no orphan camera capture threads survive between pytest tests."""
    yield
    for cam in list(camera_registry.values()):
        try:
            cam.stop()
        except Exception:
            pass
    camera_registry.clear()
