import pytest
import numpy as np
from sqlalchemy import text
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import settings
from backend.database.database import engine, SessionLocal
from backend.database.models import Alert, AuditLog, SyncOutbox
from backend.alert.alert_engine import AlertEngine


@pytest.fixture
def client():
    return TestClient(app, headers={"X-API-Key": settings.ADMIN_API_KEY})


@pytest.fixture(autouse=True)
def clean_test_data():
    db = SessionLocal()
    try:
        opt_alerts = db.query(Alert).filter(Alert.camera_id.like("CAM-OPT-%")).all()
        opt_codes = [a.alert_code for a in opt_alerts if a.alert_code]
        opt_ids = [a.id for a in opt_alerts]
        if opt_codes:
            db.query(AuditLog).filter(AuditLog.alert_code.in_(opt_codes)).delete(synchronize_session=False)
            db.query(SyncOutbox).filter(SyncOutbox.event_id.in_(opt_codes)).delete(synchronize_session=False)
        if opt_ids:
            db.query(AuditLog).filter(AuditLog.alert_id.in_(opt_ids)).delete(synchronize_session=False)
        db.query(Alert).filter(Alert.camera_id.like("CAM-OPT-%")).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield


def test_sqlite_wal_and_busy_timeout():
    """
    P0.5-1 Requirement:
    Verify SQLite WAL mode, NORMAL synchronous, and busy_timeout=5000ms.
    """
    with engine.connect() as conn:
        journal_mode = conn.execute(text("PRAGMA journal_mode;")).scalar()
        busy_timeout = conn.execute(text("PRAGMA busy_timeout;")).scalar()
        synchronous = conn.execute(text("PRAGMA synchronous;")).scalar()

    # WAL mode is active
    assert str(journal_mode).lower() == "wal"
    # busy_timeout is configured to 5000ms
    assert int(busy_timeout) == 5000
    # synchronous is 1 (NORMAL) for WAL efficiency
    assert int(synchronous) == 1


def test_dynamic_optical_mode_propagation_person_detected():
    """
    P0.5-2 Requirement:
    Verify dynamic optical mode propagates into PERSON_DETECTED alerts and ws_payload.
    """
    engine_inst = AlertEngine(cooldown_seconds=0)
    dispatched = []
    engine_inst.register_listener(lambda payload: dispatched.append(payload))

    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    detections = [{"label": "Person", "confidence": 0.88, "box": [10, 10, 50, 50]}]

    alert_dict = engine_inst.process_detections(
        camera_id="CAM-OPT-01",
        frame=frame,
        detections=detections,
        optical_mode="NIGHT_CLAHE"
    )

    assert alert_dict is not None
    assert alert_dict["optical_mode"] == "NIGHT_CLAHE"
    assert len(dispatched) == 1
    assert dispatched[0]["optical_mode"] == "NIGHT_CLAHE"

    # Verify persisted in database
    db = SessionLocal()
    try:
        saved_alert = db.query(Alert).filter(Alert.camera_id == "CAM-OPT-01").order_by(Alert.id.desc()).first()
        assert saved_alert is not None
        assert saved_alert.optical_mode == "NIGHT_CLAHE"

        # Verify audit log recorded optical mode in OPTICAL_ACQUISITION stage
        audit = db.query(AuditLog).filter(
            AuditLog.alert_code == saved_alert.alert_code,
            AuditLog.stage == "OPTICAL_ACQUISITION"
        ).order_by(AuditLog.id.desc()).first()
        assert audit is not None
        assert "NIGHT_CLAHE optical mode" in audit.description

        # Verify outbox payload contains optical_mode
        ev_code = saved_alert.alert_code
        outbox = db.query(SyncOutbox).filter(SyncOutbox.event_id == ev_code).first()
        if outbox:
            import json
            payload = json.loads(outbox.payload_json)
            assert payload.get("optical_mode") == "NIGHT_CLAHE"
    finally:
        db.close()


def test_dynamic_optical_mode_propagation_tampering_and_cyber():
    """
    P0.5-2 Requirement:
    Verify dynamic optical mode propagates into CAMERA_TAMPERED and CYBER_STREAM_TAMPERED.
    """
    engine_inst = AlertEngine(cooldown_seconds=0)
    frame = np.zeros((240, 320, 3), dtype=np.uint8)

    # 1. Tampering alert with FLIR_THERMAL
    tamper_alert = engine_inst.trigger_tampering_alert(
        camera_id="CAM-OPT-02",
        frame=frame,
        reason="Lens Occluded",
        optical_mode="FLIR_THERMAL"
    )
    assert tamper_alert is not None
    assert tamper_alert["optical_mode"] == "FLIR_THERMAL"

    # 2. Cyber replay alert with NVG_GREEN
    cyber_alert = engine_inst.trigger_cyber_tamper_alert(
        camera_id="CAM-OPT-03",
        frame=frame,
        reason="Frozen video replay",
        optical_mode="NVG_GREEN"
    )
    assert cyber_alert is not None
    assert cyber_alert["optical_mode"] == "NVG_GREEN"


def test_dynamic_optical_mode_propagation_perimeter_and_loitering():
    """
    P0.5-2 Requirement:
    Verify optical mode propagates into loitering, intrusion, and wildlife alerts.
    """
    engine_inst = AlertEngine(cooldown_seconds=0)
    frame = np.zeros((240, 320, 3), dtype=np.uint8)

    # 1. Loitering
    loiter_alert = engine_inst.check_loitering(
        camera_id="CAM-OPT-04",
        frame=frame,
        dwell_seconds=30.0,
        optical_mode="NVG_GREEN"
    )
    assert loiter_alert is not None
    assert loiter_alert["optical_mode"] == "NVG_GREEN"

    # 2. Border intrusion
    intrusion_alert = engine_inst.trigger_intrusion_alert(
        camera_id="CAM-OPT-05",
        frame=frame,
        breached_count=2,
        details="Restricted boundary breached",
        confidence=0.96,
        optical_mode="NIGHT_CLAHE"
    )
    assert intrusion_alert is not None
    assert intrusion_alert["optical_mode"] == "NIGHT_CLAHE"

    # 3. Wildlife transit
    wildlife_alert = engine_inst.trigger_wildlife_alert(
        camera_id="CAM-OPT-06",
        frame=frame,
        animal_type="Deer",
        count=1,
        confidence=0.89,
        optical_mode="DAY_RGB"
    )
    assert wildlife_alert is not None
    assert wildlife_alert["optical_mode"] == "DAY_RGB"


def test_dynamic_optical_mode_propagation_vehicle_alerts():
    """
    P0.5-2 Requirement:
    Verify optical mode propagates into vehicle passage and stolen vehicle intercept alerts.
    """
    engine_inst = AlertEngine(cooldown_seconds=0)
    frame = np.zeros((240, 320, 3), dtype=np.uint8)

    # 1. Stolen vehicle intercept
    stolen_alert = engine_inst.trigger_stolen_vehicle_alert(
        camera_id="CAM-OPT-07",
        frame=frame,
        plate_number="DL01AB1234",
        vehicle_type="SUV",
        optical_mode="FLIR_THERMAL"
    )
    assert stolen_alert is not None
    assert stolen_alert["optical_mode"] == "FLIR_THERMAL"

    # 2. Standard vehicle transit
    transit_alert = engine_inst.trigger_vehicle_alert(
        camera_id="CAM-OPT-08",
        frame=frame,
        vehicle_type="Truck",
        plate_number="HR26DK8888",
        optical_mode="NVG_GREEN"
    )
    assert transit_alert is not None
    assert transit_alert["optical_mode"] == "NVG_GREEN"


def test_truthful_ai_telemetry_and_legal_terminology(client):
    """
    P0.5-3 Requirement:
    Verify removal of misleading 'Deep Behavioral AI' terminology and check
    accurate reporting of vision stack and Section 63 BSA 2023 legal framework.
    """
    resp = client.get("/api/health/edge-telemetry")
    assert resp.status_code == 200
    data = resp.json()

    models = data.get("active_ai_models", [])
    # Verify no misleading deep behavioral claims
    assert not any("Deep Behavioral AI" in m for m in models)
    # Verify truthful models are listed
    assert any("Laplacian Variance Anti-Tamper" in m for m in models)
    assert any("RapidOCR" in m for m in models)
    assert any("Spatial Dwell & Loitering Timer" in m for m in models)

    # Verify blockchain ledger API cites Section 63 BSA 2023 and FIPS 180-4
    ledger_resp = client.get("/api/blockchain/ledger")
    assert ledger_resp.status_code == 200
    ledger_data = ledger_resp.json()
    assert "Section 63, Bharatiya Sakshya Adhiniyam" in ledger_data.get("legal_framework", "")
    assert "FIPS 180-4 SHA-256" in ledger_data.get("cryptographic_standard", "")


def test_production_safe_hiding_and_disabling_diagnostic(client):
    """
    P0.5-4 Requirement:
    Verify diagnostic mode endpoints are disabled by default in production (HTTP 403).
    """
    # Enforce production mode
    settings.ENABLE_DIAGNOSTIC_MODE = False

    resp = client.post("/api/alerts/demo-trigger", json={
        "trigger_type": "BORDER_BREACH",
        "camera_id": "CAM-01"
    })
    assert resp.status_code == 403
    assert "disabled in production mode" in resp.json()["detail"]

    # Verify edge telemetry reports diagnostic_mode as False
    telemetry_resp = client.get("/api/health/edge-telemetry")
    assert telemetry_resp.status_code == 200
    assert telemetry_resp.json()["diagnostic_mode"] is False
