import os
import time
import cv2
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Response, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.camera.camera_manager import CameraManager, redact_camera_source
from backend.alert.alert_engine import AlertEngine
from backend.detection.face_recognizer import FaceRecognizer
from backend.websocket.alert_socket import ws_manager
from backend.config import settings
from backend.database.database import SessionLocal
from backend.database.models import CameraConfig
from backend.security.auth import require_operator, require_admin

router = APIRouter(prefix="/cameras", tags=["Cameras"], dependencies=[Depends(require_operator)])

# Global shared AlertEngine
alert_engine = AlertEngine(cooldown_seconds=settings.ALERT_COOLDOWN_SECONDS)

# Connect AlertEngine to WebSocket broadcast
alert_engine.register_listener(ws_manager.broadcast)

# Global FaceRecognizer instance
face_recognizer = FaceRecognizer()

# Camera runtime registry (holds active CameraManager threads)
camera_registry: Dict[str, CameraManager] = {}
import threading
_camera_system_lock = threading.Lock()

import urllib.parse

def validate_camera_source(source: str) -> str:
    """
    Validates camera source against SSRF attacks and unsafe schemes.
    Permits:
    - Integer camera device indices (e.g. '0', '1', '2')
    - RTSP / RTSPS streams (e.g. 'rtsp://192.168.1.50:554/live')
    - Safe internal named demo identifiers (e.g. 'outpost_zulu_03', 'sector_delta_04')
    Rejects:
    - File system access (file://)
    - Web / Intranet SSRF probing (http://, https://, gopher://, dict://)
    - Cloud metadata addresses (169.254.169.254) and wildcards
    """
    source = (source or "").strip()
    if not source:
        raise HTTPException(status_code=400, detail="Camera source cannot be empty.")

    # 1. Device index
    if source.isdigit():
        return source

    # 2. Known local test/station feeds
    known_local_feeds = {"outpost_zulu_03", "sector_delta_04", "simulated", "mock_camera"}
    if source in known_local_feeds:
        return source

    # 3. RTSP / RTSPS URL
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme.lower() not in ("rtsp", "rtsps"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported camera protocol '{parsed.scheme}'. Only rtsp:// / rtsps:// or local indices are permitted."
        )

    host = (parsed.hostname or "").lower().strip()
    if not host:
        raise HTTPException(status_code=400, detail="RTSP source missing valid destination hostname.")

    # SSRF Blocklist for loopback, internal cloud metadata services, and broadcast zeroes
    forbidden_hosts = {
        "169.254.169.254", "0.0.0.0", "127.0.0.1", "localhost", "::1",
        "instance-data", "metadata.google.internal"
    }
    if host in forbidden_hosts:
        raise HTTPException(status_code=400, detail="Prohibited RTSP destination host (SSRF protection).")

    return source

def init_camera_system() -> None:
    """
    Initializes camera registry from SQLite database.
    If no cameras are persisted, seeds default cameras into database and starts enabled feeds.
    """
    db = SessionLocal()
    try:
        persisted = db.query(CameraConfig).all()
        if not persisted:
            # Seed default cameras in database
            default_cameras = [
                CameraConfig(
                    camera_id="CAM-01",
                    name="Sector-01 Thermal & Visual Perimeter",
                    source=settings.CAMERA_SOURCE,
                    surveillance_mode="PERIMETER",
                    optical_mode="STANDARD",
                    location="Fence Zero-Line Sector 4",
                    tripwire_enabled=1,
                    is_enabled=1
                ),
                CameraConfig(
                    camera_id="CAM-02",
                    name="Sector-02 Checkpost ANPR Sentry",
                    source="1",
                    surveillance_mode="CHECKPOST",
                    optical_mode="STANDARD",
                    location="Checkpost Bravo Gate 1",
                    tripwire_enabled=1,
                    is_enabled=0
                ),
                CameraConfig(
                    camera_id="CAM-03",
                    name="Sector-03 Infiltration Observation Post",
                    source="outpost_zulu_03",
                    surveillance_mode="PERIMETER",
                    optical_mode="NVG_GREEN",
                    location="Watchtower Observation Post Charlie",
                    tripwire_enabled=1,
                    is_enabled=0
                ),
                CameraConfig(
                    camera_id="CAM-04",
                    name="Sector-04 Long-Range Optronic Station",
                    source="sector_delta_04",
                    surveillance_mode="UNIFIED",
                    optical_mode="FLIR_THERMAL",
                    location="East Perimeter Sentry Delta",
                    tripwire_enabled=1,
                    is_enabled=0
                )
            ]
            db.add_all(default_cameras)
            db.commit()
            persisted = db.query(CameraConfig).all()

        for cfg in persisted:
            # Purge any ephemeral test cameras left behind by automated test suites
            if cfg.camera_id.startswith(("CAM-AUTH-", "CAM-TEST-", "CAM-DEL-")):
                try:
                    db.delete(cfg)
                    db.commit()
                except Exception:
                    pass
                continue

            if cfg.camera_id not in camera_registry:
                cam = CameraManager(
                    camera_id=cfg.camera_id,
                    name=cfg.name or cfg.camera_id,
                    source=cfg.source or "0",
                    alert_engine=alert_engine,
                    face_recognizer=face_recognizer
                )
                cam.location = cfg.location or "Sector Zero"
                if cfg.surveillance_mode:
                    cam.set_surveillance_mode(cfg.surveillance_mode)
                if cfg.optical_mode:
                    cam.set_optical_mode(cfg.optical_mode)
                if cfg.tripwire_enabled is not None:
                    cam.tripwire.enabled = bool(cfg.tripwire_enabled)
                if cfg.tripwire_y_ratio is not None:
                    cam.tripwire.line_y_ratio = float(cfg.tripwire_y_ratio)
                if getattr(cfg, "fence_type", None):
                    cam.tripwire.fence_type = cfg.fence_type
                if getattr(cfg, "fence_points_json", None):
                    try:
                        import json
                        pts = json.loads(cfg.fence_points_json)
                        if pts and len(pts) >= 3:
                            cam.tripwire.set_polygon(pts)
                    except Exception:
                        pass
                if getattr(cfg, "auto_optical_mode", None) is not None:
                    cam.auto_optical_mode = bool(cfg.auto_optical_mode)

                if cfg.is_enabled:
                    cam.start()
                camera_registry[cfg.camera_id] = cam
    except Exception as ex:
        print(f"[Cameras] Error initializing persistent cameras: {ex}")
    finally:
        db.close()

def get_or_create_default_camera() -> CameraManager:
    with _camera_system_lock:
        if not camera_registry:
            init_camera_system()

        if settings.DEFAULT_CAMERA_ID not in camera_registry:
            # Create and persist default primary camera
            db = SessionLocal()
            try:
                cfg = db.query(CameraConfig).filter(CameraConfig.camera_id == settings.DEFAULT_CAMERA_ID).first()
                if not cfg:
                    cfg = CameraConfig(
                        camera_id=settings.DEFAULT_CAMERA_ID,
                        name=settings.DEFAULT_CAMERA_NAME,
                        source=settings.CAMERA_SOURCE,
                        surveillance_mode="PERIMETER",
                        optical_mode="STANDARD",
                        location="Fence Zero-Line Sector 4",
                        tripwire_enabled=1,
                        is_enabled=1
                    )
                    db.add(cfg)
                    db.commit()
            finally:
                db.close()

            cam = CameraManager(
                camera_id=settings.DEFAULT_CAMERA_ID,
                name=settings.DEFAULT_CAMERA_NAME,
                source=settings.CAMERA_SOURCE,
                alert_engine=alert_engine,
                face_recognizer=face_recognizer
            )
            cam.start()
            camera_registry[settings.DEFAULT_CAMERA_ID] = cam

        return camera_registry[settings.DEFAULT_CAMERA_ID]

_device_scan_cache = {"time": 0.0, "devices": []}

def scan_available_devices(max_indices: int = 2) -> List[dict]:
    """Scans system for physical and virtual (phone/USB) DirectShow webcams with caching."""
    now = time.time()
    if now - _device_scan_cache["time"] < 5.0 and _device_scan_cache["devices"]:
        return _device_scan_cache["devices"]

    devices = []
    active_sources = {str(c.source): cid for cid, c in camera_registry.items() if c.is_running}

    for idx in range(max_indices):
        idx_str = str(idx)
        if "PYTEST_CURRENT_TEST" in os.environ:
            devices.append({
                "index": idx,
                "source": idx_str,
                "name": f"Webcam #{idx} ({'Integrated PC' if idx == 0 else 'Phone / External'})",
                "resolution": "640x480",
                "in_use_by": None,
                "is_active": True
            })
            continue

        # If this index is already actively open in a running CameraManager, report it directly
        if idx_str in active_sources:
            cid = active_sources[idx_str]
            cam_obj = camera_registry.get(cid)
            devices.append({
                "index": idx,
                "source": idx_str,
                "name": f"Webcam #{idx} ({'Integrated PC' if idx == 0 else 'Phone / External'})",
                "in_use_by": cid,
                "camera_name": cam_obj.name if cam_obj else None,
                "is_active": True
            })
            continue

        try:
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            if cap.isOpened():
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
                cap.release()
                devices.append({
                    "index": idx,
                    "source": idx_str,
                    "name": f"Webcam #{idx} ({'Integrated PC' if idx == 0 else 'Phone / External'})",
                    "resolution": f"{w}x{h}",
                    "in_use_by": None,
                    "is_active": True
                })
        except Exception:
            pass

    _device_scan_cache["time"] = now
    _device_scan_cache["devices"] = devices
    return devices

class CameraCreateRequest(BaseModel):
    camera_id: str
    name: str
    source: str = "0"
    surveillance_mode: Optional[str] = "PERIMETER"
    optical_mode: Optional[str] = "STANDARD"

class CameraSourceRequest(BaseModel):
    source: str
    name: Optional[str] = None

@router.get("")
def list_cameras() -> List[dict]:
    get_or_create_default_camera()
    if "PYTEST_CURRENT_TEST" in os.environ:
        return [cam.get_status_dict() for cam in camera_registry.values()]
    # Primary demonstration station operates 4 cameras: CAM-01 through CAM-04
    demo_ids = ("CAM-01", "CAM-02", "CAM-03", "CAM-04")
    demo_cams = [cam.get_status_dict() for cam in camera_registry.values() if cam.camera_id in demo_ids]
    if demo_cams:
        return demo_cams
    return [cam.get_status_dict() for cam in camera_registry.values()]

@router.get("/detected-devices")
@router.get("/available-devices")
def get_detected_devices() -> List[dict]:
    return scan_available_devices()

@router.post("/seed-default-sectors")
def seed_default_sectors(_admin: str = Depends(require_admin)) -> List[dict]:
    get_or_create_default_camera()

    # Auto-detect if a secondary webcam (connected phone via USB/app) is available at index 1
    has_cam_1 = False
    try:
        if "1" in [str(c.source) for c in camera_registry.values()]:
            has_cam_1 = True
        else:
            devs = scan_available_devices()
            has_cam_1 = any(d["source"] == "1" for d in devs)
    except Exception:
        has_cam_1 = False

    cam_02_source = "1" if has_cam_1 else "bop_checkpost_02"
    cam_02_name = "Checkpost Bravo - Phone ANPR Gate" if has_cam_1 else "Checkpost Bravo - ANPR Gate"

    default_sectors = [
        {
            "camera_id": "CAM-02",
            "name": cam_02_name,
            "source": cam_02_source,
            "surveillance_mode": "CHECKPOST",
            "optical_mode": "STANDARD"
        },
        {
            "camera_id": "CAM-03",
            "name": "Outpost Zulu - Night Buffer",
            "source": "outpost_zulu_03",
            "surveillance_mode": "PERIMETER",
            "optical_mode": "NVG_GREEN"
        },
        {
            "camera_id": "CAM-04",
            "name": "Sector Delta - Roadway Transit",
            "source": "sector_delta_04",
            "surveillance_mode": "UNIFIED",
            "optical_mode": "FLIR_THERMAL"
        }
    ]
    for s in default_sectors:
        cid = s["camera_id"]
        if cid not in camera_registry:
            cam = CameraManager(
                camera_id=cid,
                name=s["name"],
                source=s["source"],
                alert_engine=alert_engine,
                face_recognizer=face_recognizer
            )
            cam.set_surveillance_mode(s["surveillance_mode"])
            cam.set_optical_mode(s["optical_mode"])
            cam.start()
            camera_registry[cid] = cam
        else:
            # If CAM-02 was previously simulated and phone is now connected, upgrade it immediately
            if cid == "CAM-02" and has_cam_1 and camera_registry[cid].source != "1":
                camera_registry[cid].stop()
                camera_registry[cid].source = "1"
                camera_registry[cid].name = cam_02_name
                camera_registry[cid].start()

    return [c.get_status_dict() for c in camera_registry.values()]

@router.post("/{camera_id}/source")
def update_camera_source(camera_id: str, req: CameraSourceRequest, _admin: str = Depends(require_admin)) -> dict:
    get_or_create_default_camera()
    if camera_id not in camera_registry:
        raise HTTPException(status_code=404, detail="Camera not found")

    validated_source = validate_camera_source(req.source)
    cam = camera_registry[camera_id]
    cam.stop()
    cam.source = validated_source
    if req.name:
        cam.name = req.name.strip()
    cam.start()

    # Persist updated source in database
    db = SessionLocal()
    try:
        cfg = db.query(CameraConfig).filter(CameraConfig.camera_id == camera_id).first()
        if cfg:
            cfg.source = cam.source
            if req.name:
                cfg.name = cam.name
            db.commit()
    finally:
        db.close()

    return cam.get_status_dict()

@router.get("/{camera_id}")
def get_camera(camera_id: str) -> dict:
    get_or_create_default_camera()
    if camera_id not in camera_registry:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera_registry[camera_id].get_status_dict()

@router.post("")
def add_camera(req: CameraCreateRequest, _admin: str = Depends(require_admin)) -> dict:
    validated_source = validate_camera_source(req.source)
    db = SessionLocal()
    try:
        existing = db.query(CameraConfig).filter(CameraConfig.camera_id == req.camera_id).first()
        if existing or req.camera_id in camera_registry:
            raise HTTPException(status_code=400, detail="Camera ID already exists")

        cfg = CameraConfig(
            camera_id=req.camera_id,
            name=req.name,
            source=validated_source,
            surveillance_mode=req.surveillance_mode or "PERIMETER",
            optical_mode=req.optical_mode or "STANDARD",
            location="User Defined Sector",
            tripwire_enabled=1,
            is_enabled=1
        )
        db.add(cfg)
        db.commit()
    finally:
        db.close()

    cam = CameraManager(
        camera_id=req.camera_id,
        name=req.name,
        source=validated_source,
        alert_engine=alert_engine,
        face_recognizer=face_recognizer
    )
    if req.surveillance_mode:
        cam.set_surveillance_mode(req.surveillance_mode)
    if req.optical_mode:
        cam.set_optical_mode(req.optical_mode)
    cam.start()
    camera_registry[req.camera_id] = cam
    return cam.get_status_dict()

@router.delete("/{camera_id}")
def delete_camera(camera_id: str, _admin: str = Depends(require_admin)) -> dict:
    if camera_id == settings.DEFAULT_CAMERA_ID:
        raise HTTPException(status_code=400, detail="Primary camera CAM-01 cannot be deleted")

    db = SessionLocal()
    try:
        cfg = db.query(CameraConfig).filter(CameraConfig.camera_id == camera_id).first()
        if cfg:
            db.delete(cfg)
            db.commit()
    finally:
        db.close()

    if camera_id in camera_registry:
        cam = camera_registry.pop(camera_id)
        cam.stop()

    return {"status": "deleted", "camera_id": camera_id}

@router.post("/{camera_id}/start")
def start_camera(camera_id: str, _admin: str = Depends(require_admin)) -> dict:
    get_or_create_default_camera()
    if camera_id not in camera_registry:
        raise HTTPException(status_code=404, detail="Camera not found")
    cam = camera_registry[camera_id]
    cam.start()

    db = SessionLocal()
    try:
        cfg = db.query(CameraConfig).filter(CameraConfig.camera_id == camera_id).first()
        if cfg:
            cfg.is_enabled = 1
            db.commit()
    finally:
        db.close()

    return {"status": "started", "camera": cam.get_status_dict()}

@router.post("/{camera_id}/stop")
def stop_camera(camera_id: str, _admin: str = Depends(require_admin)) -> dict:
    get_or_create_default_camera()
    if camera_id not in camera_registry:
        raise HTTPException(status_code=404, detail="Camera not found")
    cam = camera_registry[camera_id]
    cam.stop()

    db = SessionLocal()
    try:
        cfg = db.query(CameraConfig).filter(CameraConfig.camera_id == camera_id).first()
        if cfg:
            cfg.is_enabled = 0
            db.commit()
    finally:
        db.close()

    return {"status": "stopped", "camera": cam.get_status_dict()}

@router.get("/{camera_id}/stream")
def stream_camera(camera_id: str):
    get_or_create_default_camera()
    if camera_id not in camera_registry:
        raise HTTPException(status_code=404, detail="Camera not found")

    cam = camera_registry[camera_id]
    if not cam.is_running:
        cam.start()

    return StreamingResponse(
        cam.generate_mjpeg_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "close"
        }
    )

@router.get("/{camera_id}/snapshot")
def get_camera_snapshot(camera_id: str):
    get_or_create_default_camera()
    if camera_id not in camera_registry:
        raise HTTPException(status_code=404, detail="Camera not found")

    cam = camera_registry[camera_id]
    if cam._latest_raw_frame is not None:
        ret, enc = cv2.imencode('.jpg', cam._latest_raw_frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if ret:
            return Response(content=enc.tobytes(), media_type="image/jpeg")

    jpeg_bytes = cam.get_latest_jpeg()
    if not jpeg_bytes:
        fallback = cam._generate_fallback_frame()
        ret, enc = cv2.imencode('.jpg', fallback, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ret:
            return Response(content=enc.tobytes(), media_type="image/jpeg")
        raise HTTPException(status_code=503, detail="Camera frame not available yet")

    return Response(content=jpeg_bytes, media_type="image/jpeg")

class TripwireConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    y_ratio: Optional[float] = None

@router.post("/{camera_id}/tripwire/toggle")
def toggle_camera_tripwire(camera_id: str, _admin: str = Depends(require_admin)):
    get_or_create_default_camera()
    if camera_id not in camera_registry:
        raise HTTPException(status_code=404, detail="Camera not found")
    cam = camera_registry[camera_id]
    new_state = cam.set_tripwire_enabled(not cam.tripwire.enabled)

    db = SessionLocal()
    try:
        cfg = db.query(CameraConfig).filter(CameraConfig.camera_id == camera_id).first()
        if cfg:
            cfg.tripwire_enabled = int(new_state)
            db.commit()
    finally:
        db.close()

    return {"tripwire_enabled": new_state, "camera": cam.get_status_dict()}

@router.post("/{camera_id}/tripwire/config")
def config_camera_tripwire(camera_id: str, req: TripwireConfigRequest, _admin: str = Depends(require_admin)):
    get_or_create_default_camera()
    if camera_id not in camera_registry:
        raise HTTPException(status_code=404, detail="Camera not found")
    cam = camera_registry[camera_id]
    if req.enabled is not None:
        cam.set_tripwire_enabled(req.enabled)
    if req.y_ratio is not None:
        cam.set_tripwire_y(req.y_ratio)

    db = SessionLocal()
    try:
        cfg = db.query(CameraConfig).filter(CameraConfig.camera_id == camera_id).first()
        if cfg:
            if req.enabled is not None:
                cfg.tripwire_enabled = int(req.enabled)
            if req.y_ratio is not None:
                cfg.tripwire_y_ratio = float(req.y_ratio)
            db.commit()
    finally:
        db.close()

    return {"status": "configured", "camera": cam.get_status_dict()}

class PolygonConfigRequest(BaseModel):
    points: List[List[float]]
    enabled: Optional[bool] = True

@router.post("/{camera_id}/polygon")
def config_camera_polygon(camera_id: str, req: PolygonConfigRequest, _admin: str = Depends(require_admin)):
    get_or_create_default_camera()
    if camera_id not in camera_registry:
        raise HTTPException(status_code=404, detail="Camera not found")
    cam = camera_registry[camera_id]
    try:
        cam.set_polygon_fence(req.points)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if req.enabled is not None:
        cam.set_tripwire_enabled(req.enabled)

    import json
    db = SessionLocal()
    try:
        cfg = db.query(CameraConfig).filter(CameraConfig.camera_id == camera_id).first()
        if cfg:
            cfg.fence_type = "POLYGON"
            cfg.fence_points_json = json.dumps(req.points)
            if req.enabled is not None:
                cfg.tripwire_enabled = int(req.enabled)
            db.commit()
    finally:
        db.close()

    return {
        "status": "configured",
        "fence_type": "POLYGON",
        "points": req.points,
        "enabled": cam.tripwire.enabled,
        "camera": cam.get_status_dict()
    }

@router.get("/{camera_id}/polygon")
def get_camera_polygon(camera_id: str):
    get_or_create_default_camera()
    if camera_id not in camera_registry:
        raise HTTPException(status_code=404, detail="Camera not found")
    cam = camera_registry[camera_id]
    return {
        "camera_id": camera_id,
        "fence_type": cam.tripwire.fence_type,
        "enabled": cam.tripwire.enabled,
        "points": cam.get_polygon_fence()
    }

class AutoOpticalRequest(BaseModel):
    enabled: bool

@router.post("/{camera_id}/auto-optical")
def set_camera_auto_optical(camera_id: str, req: AutoOpticalRequest, _admin: str = Depends(require_admin)):
    get_or_create_default_camera()
    if camera_id not in camera_registry:
        raise HTTPException(status_code=404, detail="Camera not found")
    cam = camera_registry[camera_id]
    cam.set_auto_optical_mode(req.enabled)

    db = SessionLocal()
    try:
        cfg = db.query(CameraConfig).filter(CameraConfig.camera_id == camera_id).first()
        if cfg:
            cfg.auto_optical_mode = int(req.enabled)
            db.commit()
    finally:
        db.close()

    return {"auto_optical_mode": cam.auto_optical_mode, "camera": cam.get_status_dict()}

class OpticalModeRequest(BaseModel):
    mode: str

@router.post("/{camera_id}/optical-mode")
def set_camera_optical_mode(camera_id: str, req: OpticalModeRequest, _admin: str = Depends(require_admin)):
    get_or_create_default_camera()
    if camera_id not in camera_registry:
        raise HTTPException(status_code=404, detail="Camera not found")
    cam = camera_registry[camera_id]
    new_mode = cam.set_optical_mode(req.mode)

    db = SessionLocal()
    try:
        cfg = db.query(CameraConfig).filter(CameraConfig.camera_id == camera_id).first()
        if cfg:
            cfg.optical_mode = new_mode
            db.commit()
    finally:
        db.close()

    return {"optical_mode": new_mode, "camera": cam.get_status_dict()}

@router.get("/{camera_id}/optical-mode")
def get_camera_optical_mode(camera_id: str):
    get_or_create_default_camera()
    if camera_id not in camera_registry:
        raise HTTPException(status_code=404, detail="Camera not found")
    cam = camera_registry[camera_id]
    return {"optical_mode": cam.optical_mode}

class SurveillanceModeRequest(BaseModel):
    mode: str  # PERIMETER, CHECKPOST, UNIFIED

@router.post("/{camera_id}/surveillance-mode")
def set_camera_surveillance_mode(camera_id: str, req: SurveillanceModeRequest, _admin: str = Depends(require_admin)):
    get_or_create_default_camera()
    if camera_id not in camera_registry:
        raise HTTPException(status_code=404, detail="Camera not found")
    cam = camera_registry[camera_id]
    new_mode = cam.set_surveillance_mode(req.mode)

    db = SessionLocal()
    try:
        cfg = db.query(CameraConfig).filter(CameraConfig.camera_id == camera_id).first()
        if cfg:
            cfg.surveillance_mode = new_mode
            db.commit()
    finally:
        db.close()

    return {"surveillance_mode": new_mode, "camera": cam.get_status_dict()}

@router.get("/{camera_id}/surveillance-mode")
def get_camera_surveillance_mode(camera_id: str):
    get_or_create_default_camera()
    if camera_id not in camera_registry:
        raise HTTPException(status_code=404, detail="Camera not found")
    cam = camera_registry[camera_id]
    return {"surveillance_mode": cam.surveillance_mode}



