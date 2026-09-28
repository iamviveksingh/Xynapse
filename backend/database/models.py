from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_code = Column(String(32), unique=True, index=True)  # XP-000001
    event_type = Column(String(64), default="PERSON_DETECTED")
    camera_id = Column(String(32), default="CAM-01")
    timestamp = Column(DateTime, default=datetime.utcnow)
    face_count = Column(Integer, default=1)
    confidence = Column(Float, default=0.0)
    objects_detected = Column(String(255), default="Person Face")
    snapshot_path = Column(String(255), nullable=True)
    evidence_hash = Column(String(64), nullable=True)  # SHA-256 integrity hash
    optical_mode = Column(String(32), default="DAY_RGB")  # DAY_RGB, NIGHT_CLAHE, NVG_GREEN, FLIR_THERMAL
    status = Column(String(32), default="NEW")  # NEW, ACKNOWLEDGED, RESOLVED
    severity = Column(String(32), default="MEDIUM")  # LOW, MEDIUM, HIGH, CRITICAL
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "alert_id": self.alert_code or f"XP-{self.id:06d}",
            "event_type": self.event_type,
            "camera_id": self.camera_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "face_count": self.face_count,
            "objects_detected": self.objects_detected or f"{self.face_count} Face(s) Detected",
            "confidence": round(float(self.confidence), 2),
            "snapshot": self.snapshot_path,
            "evidence_hash": getattr(self, "evidence_hash", None),
            "optical_mode": getattr(self, "optical_mode", "DAY_RGB") or "DAY_RGB",
            "status": self.status,
            "severity": getattr(self, "severity", "MEDIUM") or "MEDIUM",
            "created_at": self.created_at.isoformat() if self.created_at else None
        }



class FaceProfile(Base):
    __tablename__ = "face_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    role = Column(String(64), default="AUTHORIZED_GUARD")  # AUTHORIZED_GUARD, SUSPECT_WATCHLIST
    notes = Column(String(255), default="")
    photo_path = Column(String(255), nullable=True)
    embedding_json = Column(String, nullable=False)  # JSON-encoded 128 floats
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        url_path = self.photo_path
        if url_path:
            norm = url_path.replace("\\", "/")
            if "evidence/faces/" in norm:
                url_path = "/evidence/faces/" + norm.split("evidence/faces/")[-1]
            elif not url_path.startswith("/") and not url_path.startswith("http"):
                url_path = "/" + url_path
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "notes": self.notes,
            "photo_path": url_path,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class VehicleProfile(Base):
    __tablename__ = "vehicle_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plate_number = Column(String(32), unique=True, index=True, nullable=False)
    vehicle_type = Column(String(64), default="Car")  # Car, Truck, Bus, Motorcycle, Military
    owner_name = Column(String(128), default="Unknown")
    status = Column(String(64), default="CIVILIAN")  # AUTHORIZED_MILITARY, SUSPECT_STOLEN, CIVILIAN
    notes = Column(String(255), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "plate_number": self.plate_number,
            "vehicle_type": self.vehicle_type,
            "owner_name": self.owner_name,
            "status": self.status,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(Integer, nullable=True, index=True)
    alert_code = Column(String(32), nullable=True)
    stage = Column(String(64), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    operator = Column(String(128), default="AUTONOMOUS_AI_ENGINE")
    description = Column(String(500), nullable=False)
    evidence_hash = Column(String(64), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "alert_id": self.alert_id,
            "alert_code": self.alert_code,
            "stage": self.stage,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "timestamp_utc": self.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC") if self.timestamp else "",
            "operator": self.operator,
            "description": self.description,
            "evidence_hash": self.evidence_hash
        }


class StationConfig(Base):
    __tablename__ = "station_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bop_name = Column(String(128), default="Border Outpost Alpha — Zero-Line Sector 4")
    bop_code = Column(String(64), default="BOP-ALPHA-SEC04")
    coordinates = Column(String(128), default="32°43'28.4\"N 74°52'16.2\"E (Jammu-Samba Sector)")
    command_unit = Column(String(128), default="48 Bn BSF (Border Security Force)")
    watch_officer = Column(String(128), default="Duty Watch Commander")
    officer_rank = Column(String(64), default="Inspector / GD")
    station_terminal_id = Column(String(64), default="IBVAP-BOP-SEC04-TERM01")
    updated_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "bop_name": self.bop_name,
            "bop_code": self.bop_code,
            "coordinates": self.coordinates,
            "command_unit": self.command_unit,
            "watch_officer": self.watch_officer,
            "officer_rank": self.officer_rank,
            "station_terminal_id": self.station_terminal_id,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class BlockchainBlock(Base):
    """
    Tamper-Evident Cryptographic Audit Chain Block Ledger for Section 63, BSA 2023 Chain of Custody:
    Each alert incident and audit milestone is cryptographically chained to its predecessor with SHA-256 digests,
    making unauthorized post-facto database manipulation mathematically detectable.
    """
    __tablename__ = "blockchain_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    block_height = Column(Integer, unique=True, index=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    alert_id = Column(Integer, nullable=True, index=True)
    alert_code = Column(String(32), nullable=True)
    event_type = Column(String(64), nullable=False)
    camera_id = Column(String(32), default="CAM-01")
    payload_hash = Column(String(64), nullable=False)
    previous_hash = Column(String(64), nullable=False)
    block_hash = Column(String(64), unique=True, index=True, nullable=False)
    station_code = Column(String(64), default="BOP-ALPHA-SEC04")
    status = Column(String(32), default="SEALED")

    def to_dict(self):
        return {
            "block_height": self.block_height,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "alert_id": self.alert_id,
            "alert_code": self.alert_code,
            "event_type": self.event_type,
            "camera_id": self.camera_id,
            "payload_hash": self.payload_hash,
            "previous_hash": self.previous_hash,
            "block_hash": self.block_hash,
            "station_code": self.station_code,
            "status": self.status
        }


class CameraConfig(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(String(32), unique=True, index=True, nullable=False)
    name = Column(String(128), default="Camera")
    source = Column(String(255), default="0")
    surveillance_mode = Column(String(32), default="PERIMETER")
    optical_mode = Column(String(32), default="STANDARD")
    location = Column(String(128), default="Sector Zero")
    tripwire_enabled = Column(Integer, default=1)
    tripwire_y_ratio = Column(Float, default=0.65)
    fence_type = Column(String(32), default="LINE")  # "LINE" or "POLYGON"
    fence_points_json = Column(String, nullable=True)  # JSON-serialized [[x, y], ...]
    auto_optical_mode = Column(Integer, default=1)  # 1 = automatic low-light detection enabled
    is_enabled = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        import json
        points = None
        if self.fence_points_json:
            try:
                points = json.loads(self.fence_points_json)
            except Exception:
                points = None

        return {
            "id": self.id,
            "camera_id": self.camera_id,
            "name": self.name,
            "source": self.source,
            "surveillance_mode": self.surveillance_mode,
            "optical_mode": self.optical_mode,
            "location": self.location,
            "tripwire_enabled": bool(self.tripwire_enabled),
            "tripwire_y_ratio": self.tripwire_y_ratio,
            "fence_type": self.fence_type or "LINE",
            "fence_points": points,
            "auto_optical_mode": bool(self.auto_optical_mode),
            "is_enabled": bool(self.is_enabled),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SyncOutbox(Base):
    __tablename__ = "sync_outbox"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(64), unique=True, index=True, nullable=False)
    alert_id = Column(Integer, nullable=True, index=True)
    camera_id = Column(String(32), default="CAM-01")
    event_type = Column(String(64), nullable=False)
    severity = Column(String(32), default="MEDIUM")
    timestamp = Column(DateTime, default=datetime.utcnow)
    payload_json = Column(String, nullable=False)
    status = Column(String(32), default="PENDING", index=True)
    attempt_count = Column(Integer, default=0)
    last_attempt_at = Column(DateTime, nullable=True)
    next_retry_at = Column(DateTime, nullable=True)
    synced_at = Column(DateTime, nullable=True)
    remote_id = Column(String(128), nullable=True)
    last_error = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "event_id": self.event_id,
            "alert_id": self.alert_id,
            "camera_id": self.camera_id,
            "event_type": self.event_type,
            "severity": self.severity,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "status": self.status,
            "attempt_count": self.attempt_count,
            "last_attempt_at": self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "synced_at": self.synced_at.isoformat() if self.synced_at else None,
            "remote_id": self.remote_id,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class VehicleTransitLog(Base):
    """
    Persistent Checkpost Vehicle Passage & ANPR Transit Registry.
    Separates physical vehicle passage observation from watchlist alerts.
    Every vehicle entering a checkpoint creates a transit record regardless of ANPR outcome.
    """
    __tablename__ = "vehicle_transit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(64), unique=True, index=True, nullable=False)
    camera_id = Column(String(32), index=True, default="CAM-01")
    track_id = Column(String(32), index=True, nullable=False)
    vehicle_type = Column(String(64), default="Vehicle")
    plate_number = Column(String(32), nullable=True, index=True)
    plate_status = Column(String(32), default="PENDING")  # PENDING, RECOGNIZED, UNREADABLE, LOW_CONFIDENCE, OBSCURED
    plate_confidence = Column(Float, nullable=True)
    vehicle_snapshot_path = Column(String(255), nullable=True)
    plate_crop_path = Column(String(255), nullable=True)
    plate_crop_w = Column(Integer, nullable=True)
    plate_crop_h = Column(Integer, nullable=True)
    ocr_latency_ms = Column(Float, nullable=True)
    watchlist_match = Column(Integer, default=0)  # 0 = False, 1 = True (SQLite friendly)
    watchlist_profile_id = Column(Integer, nullable=True)
    watchlist_category = Column(String(64), nullable=True)  # SUSPECT_STOLEN, AUTHORIZED_MILITARY, CIVILIAN, UNREGISTERED
    direction = Column(String(32), default="UNKNOWN")  # INBOUND, OUTBOUND, UNKNOWN
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "event_id": self.event_id,
            "camera_id": self.camera_id,
            "track_id": self.track_id,
            "vehicle_type": self.vehicle_type,
            "plate_number": self.plate_number,
            "plate_status": self.plate_status,
            "plate_confidence": round(float(self.plate_confidence), 2) if self.plate_confidence is not None else None,
            "vehicle_snapshot_path": self.vehicle_snapshot_path,
            "plate_crop_path": self.plate_crop_path,
            "plate_crop_w": self.plate_crop_w,
            "plate_crop_h": self.plate_crop_h,
            "ocr_latency_ms": round(float(self.ocr_latency_ms), 1) if self.ocr_latency_ms is not None else None,
            "watchlist_match": bool(self.watchlist_match),
            "watchlist_profile_id": self.watchlist_profile_id,
            "watchlist_category": self.watchlist_category,
            "direction": self.direction or "UNKNOWN",
            "first_seen_at": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }





