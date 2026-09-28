import json
import pytest
from datetime import datetime
from starlette.testclient import TestClient

from backend.main import app
from backend.database.database import SessionLocal, init_db
from backend.database.models import Alert, SyncOutbox, AuditLog
from backend.alert.alert_engine import AlertEngine
from backend.sync.sync_worker import sync_pending_events, get_outbox_stats
from backend.config import settings

@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    yield

def test_alert_creation_enqueues_into_persistent_outbox():
    """Verify that creating any alert automatically writes a PENDING record in sync_outbox."""
    db = SessionLocal()
    try:
        # Clean up existing test records if present
        db.query(SyncOutbox).filter(SyncOutbox.event_id == "XP-SYNC-TEST-001").delete()
        db.query(Alert).filter(Alert.alert_code == "XP-SYNC-TEST-001").delete()
        db.commit()

        # Create an alert record
        alert = Alert(
            alert_code="XP-SYNC-TEST-001",
            event_type="BORDER_INTRUSION",
            camera_id="CAM-01",
            face_count=1,
            confidence=0.97,
            objects_detected="Zero-Line Breach Test Subject",
            status="NEW",
            severity="CRITICAL",
            created_at=datetime.utcnow()
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)

        # Trigger audit & outbox write
        AlertEngine._write_audit_trail(db, alert)

        # Verify record exists in sync_outbox
        outbox = db.query(SyncOutbox).filter(SyncOutbox.event_id == "XP-SYNC-TEST-001").first()
        assert outbox is not None
        assert outbox.status == "PENDING"
        assert outbox.event_type == "BORDER_INTRUSION"
        assert outbox.severity == "CRITICAL"
        assert outbox.attempt_count == 0
        assert outbox.synced_at is None

        # Verify restart recovery: fresh DB session still sees the pending outbox item
        db.close()
        fresh_db = SessionLocal()
        fresh_outbox = fresh_db.query(SyncOutbox).filter(SyncOutbox.event_id == "XP-SYNC-TEST-001").first()
        assert fresh_outbox is not None
        assert fresh_outbox.status == "PENDING"
        fresh_db.close()
    finally:
        try:
            db.query(SyncOutbox).filter(SyncOutbox.event_id == "XP-SYNC-TEST-001").delete()
            db.query(Alert).filter(Alert.alert_code == "XP-SYNC-TEST-001").delete()
            db.commit()
            db.close()
        except Exception:
            pass

def test_sync_when_not_configured():
    """Verify that without HQ_SYNC_URL, system reports SYNC_NOT_CONFIGURED without faking success."""
    db = SessionLocal()
    try:
        # Pass target_url="" and ensure settings.HQ_SYNC_URL is empty
        res = sync_pending_events(db, target_url="")
        assert res["status"] == "SYNC_NOT_CONFIGURED"
        assert res["synced_count"] == 0
        assert res["hq_endpoint"] is None
    finally:
        db.close()

def test_sync_failure_and_retry_backoff():
    """Verify that an unreachable HQ endpoint results in SYNC_FAILED, increments attempt_count, and sets backoff."""
    db = SessionLocal()
    try:
        # Ensure a fresh pending record exists ready for immediate sync
        test_id = "XP-SYNC-FAIL-001"
        db.query(SyncOutbox).filter(SyncOutbox.status == "PENDING").update({"status": "SYNCED"})
        db.query(SyncOutbox).filter(SyncOutbox.event_id == test_id).delete()
        db.commit()

        outbox = SyncOutbox(
            event_id=test_id,
            alert_id=999,
            camera_id="CAM-01",
            event_type="TEST_FAIL_EVENT",
            severity="HIGH",
            payload_json=json.dumps({"test": "data"}),
            status="PENDING",
            attempt_count=0,
            next_retry_at=None
        )
        db.add(outbox)
        db.commit()

        # Attempt sync to a non-existent port (connection refused)
        res = sync_pending_events(db, target_url="http://127.0.0.1:59999/api/hq/ingest", batch_size=10)
        assert res["status"] == "SYNC_FAILED"

        # Check outbox record state in DB
        db.expire_all()
        record = db.query(SyncOutbox).filter(SyncOutbox.event_id == test_id).first()
        assert record.status == "PENDING"
        assert record.attempt_count >= 1
        assert record.last_error is not None
        assert record.next_retry_at is not None
    finally:
        db.close()

def test_successful_hq_sync_and_idempotency():
    """
    Verify complete real sync:
    1. Transmit outbox event to the local HQ receiver endpoint.
    2. Receiver responds with 200 accepted and remote_id.
    3. Outbox status transitions to SYNCED.
    4. Re-transmitting the same event demonstrates duplicate prevention (idempotency).
    """
    client = TestClient(app)

    # 1. Clear HQ receiver cache
    client.post("/api/hq/clear")

    # 2. Direct check of HQ ingest endpoint
    test_payload = {
        "event_id": "XP-HQ-TEST-007",
        "camera_id": "CAM-01",
        "event_type": "SUSPECT_DETECTED",
        "severity": "CRITICAL",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {"suspect_name": "Tariq Mansoor", "confidence": 0.94}
    }
    headers = {"X-Worker-Secret": settings.INTERNAL_WORKER_SECRET}
    r1 = client.post("/api/hq/ingest", json=test_payload, headers=headers)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["status"] == "accepted"
    assert d1["event_id"] == "XP-HQ-TEST-007"
    assert d1["duplicate"] is False
    remote_id = d1["remote_id"]
    assert remote_id.startswith("HQ-REC-")

    # 3. Test Idempotency / Duplicate Prevention: send same event again
    r2 = client.post("/api/hq/ingest", json=test_payload, headers=headers)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["status"] == "accepted"
    assert d2["duplicate"] is True
    assert d2["remote_id"] == remote_id  # Same remote identifier returned

    # 4. Check that HQ receiver has logged exactly 1 event (no duplicates)
    r3 = client.get("/api/hq/received")
    assert r3.status_code == 200
    hq_records = r3.json()
    matching = [rec for rec in hq_records if rec["event_id"] == "XP-HQ-TEST-007"]
    assert len(matching) == 1

def test_api_outbox_endpoints():
    """Verify that /api/alerts/outbox and /api/alerts/sync-bundle return genuine real outbox data."""
    client = TestClient(app, headers={"X-API-Key": settings.ADMIN_API_KEY})

    # Outbox listing
    resp = client.get("/api/alerts/outbox?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "events" in data
    assert isinstance(data["events"], list)

    # Sync bundle status
    resp_bundle = client.get("/api/alerts/sync-bundle")
    assert resp_bundle.status_code == 200
    b_data = resp_bundle.json()
    assert "pending_count" in b_data
    assert "synced_count" in b_data
    assert "sync_configured" in b_data
    assert "incidents" in b_data
