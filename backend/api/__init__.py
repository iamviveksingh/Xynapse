from backend.api.health import router as health_router
from backend.api.cameras import router as cameras_router
from backend.api.alerts import router as alerts_router

__all__ = ["health_router", "cameras_router", "alerts_router"]
