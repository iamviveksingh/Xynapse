import os
# Prevent read-only config directory warnings on cloud platforms like Render
os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp")

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "XYNAPSE — Human Detection & Surveillance Intelligence"
    API_V1_STR: str = "/api"
    
    # Camera Configuration
    DEFAULT_CAMERA_ID: str = "CAM-01"
    DEFAULT_CAMERA_NAME: str = "Entrance Main (CAM-01)"
    CAMERA_SOURCE: str = "0"  # Webcam index "0" or RTSP URL
    
    # Detection & Alert Settings
    ALERT_COOLDOWN_SECONDS: int = 10
    DETECTION_CONFIDENCE: float = 0.60
    ENABLE_ALERT_SOUND: bool = True
    
    # Evidence / Storage
    BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    EVIDENCE_DIR: str = os.path.join(BASE_DIR, "evidence", "alerts")
    TRANSIT_EVIDENCE_DIR: str = os.path.join(BASE_DIR, "evidence", "transits")
    TRANSIT_RETENTION_DAYS: int = int(os.getenv("TRANSIT_RETENTION_DAYS", "30"))
    DATABASE_URL: str = f"sqlite:///{os.path.join(BASE_DIR, 'xynapse.db')}"

    # Central HQ Synchronization
    HQ_SYNC_URL: str = os.getenv("HQ_SYNC_URL", "")  # e.g. "http://localhost:8000/api/hq/ingest"

    # Security & Hardening Configuration
    HOST: str = os.getenv("HOST") or os.getenv("XYNAPSE_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT") or os.getenv("XYNAPSE_PORT", "8000"))
    ENVIRONMENT: str = os.getenv("XYNAPSE_ENV", "production")
    ENABLE_DIAGNOSTIC_MODE: bool = os.getenv("ENABLE_DIAGNOSTIC_MODE", "false").lower() in ("true", "1", "yes")
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5175,http://127.0.0.1:5175,http://localhost:8000,http://127.0.0.1:8000")
    INTERNAL_WORKER_SECRET: str = os.getenv("INTERNAL_WORKER_SECRET", "xynapse-internal-worker-auth-key-2026")
    ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "xynapse-admin-sih-2026")
    OPERATOR_API_KEY: str = os.getenv("OPERATOR_API_KEY", "xynapse-operator-sih-2026")

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

# Ensure evidence directories exist
os.makedirs(settings.EVIDENCE_DIR, exist_ok=True)
os.makedirs(settings.TRANSIT_EVIDENCE_DIR, exist_ok=True)
