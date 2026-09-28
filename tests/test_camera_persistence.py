import pytest
from backend.database.database import SessionLocal, init_db
from backend.database.models import CameraConfig
from backend.api.cameras import (
    camera_registry,
    init_camera_system,
    get_or_create_default_camera,
    add_camera,
    delete_camera,
    update_camera_source,
    start_camera,
    stop_camera,
    CameraCreateRequest,
    CameraSourceRequest
)

@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    yield

def test_camera_persistence_lifecycle():
    # Clear in-memory registry to simulate cold boot
    for c in list(camera_registry.values()):
        c.stop()
    camera_registry.clear()

    # 1. Initialize system - should seed default cameras into SQLite
    init_camera_system()
    assert "CAM-01" in camera_registry
    assert camera_registry["CAM-01"].is_running is True

    # Verify SQLite record exists
    db = SessionLocal()
    try:
        cfg = db.query(CameraConfig).filter(CameraConfig.camera_id == "CAM-01").first()
        assert cfg is not None
        assert cfg.surveillance_mode in ("PERIMETER", "CHECKPOST", "UNIFIED")
    finally:
        db.close()

    # 2. Add a new custom camera via API
    custom_id = "CAM-TEST-99"
    # Ensure it's clean
    if custom_id in camera_registry:
        camera_registry[custom_id].stop()
        camera_registry.pop(custom_id, None)
    db = SessionLocal()
    try:
        existing = db.query(CameraConfig).filter(CameraConfig.camera_id == custom_id).first()
        if existing:
            db.delete(existing)
            db.commit()
    finally:
        db.close()

    req = CameraCreateRequest(
        camera_id=custom_id,
        name="Sector-99 High-Altitude Sentry",
        source="outpost_zulu_03",
        surveillance_mode="CHECKPOST",
        optical_mode="NVG_GREEN"
    )
    res = add_camera(req)
    assert res["camera_id"] == custom_id
    assert res["surveillance_mode"] == "CHECKPOST"
    assert res["optical_mode"] == "NVG_GREEN"

    # 3. Simulate backend server restart
    # Clear in-memory registry completely
    for c in list(camera_registry.values()):
        c.stop()
    camera_registry.clear()
    assert len(camera_registry) == 0

    # Reboot: init_camera_system should reload persisted cameras from SQLite
    init_camera_system()
    assert custom_id in camera_registry
    reloaded_cam = camera_registry[custom_id]
    assert reloaded_cam.name == "Sector-99 High-Altitude Sentry"
    assert reloaded_cam.source == "outpost_zulu_03"
    assert reloaded_cam.surveillance_mode == "CHECKPOST"
    assert reloaded_cam.optical_mode == "NVG_GREEN"

    # 4. Modify camera source and verify persistence
    src_req = CameraSourceRequest(source="sector_delta_04", name="Renamed Sentry 99")
    update_camera_source(custom_id, src_req)

    # Simulate reboot again
    for c in list(camera_registry.values()):
        c.stop()
    camera_registry.clear()
    init_camera_system()
    assert camera_registry[custom_id].source == "sector_delta_04"
    assert camera_registry[custom_id].name == "Renamed Sentry 99"

    # 5. Clean up custom camera
    del_res = delete_camera(custom_id)
    assert del_res["status"] == "deleted"

    db = SessionLocal()
    try:
        deleted_cfg = db.query(CameraConfig).filter(CameraConfig.camera_id == custom_id).first()
        assert deleted_cfg is None
    finally:
        db.close()
        for c in list(camera_registry.values()):
            c.stop()
        camera_registry.clear()
