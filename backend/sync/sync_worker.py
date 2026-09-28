import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.models import SyncOutbox, AuditLog

logger = logging.getLogger("xynapse.sync")

def sync_pending_events(
    db: Session,
    target_url: Optional[str] = None,
    batch_size: int = 25
) -> Dict[str, Any]:
    """
    Genuine Store-and-Forward synchronization worker.
    Selects pending outbox records from SQLite, transmits them over HTTP POST to the
    configured Central HQ endpoint, checks response validity, updates outbox state
    to SYNCED upon true confirmation, and schedules exponential retry on network failure.
    """
    endpoint = (target_url or settings.HQ_SYNC_URL or "").strip()

    if endpoint and not endpoint.lower().startswith(("http://", "https://")):
        logger.warning(f"[SyncWorker] Invalid HQ synchronization scheme: {endpoint}")
        total_pending = db.query(SyncOutbox).filter(SyncOutbox.status == "PENDING").count()
        return {
            "status": "INVALID_HQ_ENDPOINT",
            "message": f"HQ endpoint must use http:// or https:// scheme: {endpoint}",
            "pending_count": total_pending,
            "synced_count": 0,
            "failed_count": 0,
            "hq_endpoint": endpoint
        }

    now = datetime.utcnow()
    # Select ready pending records (not in active retry delay)
    pending_records = db.query(SyncOutbox).filter(
        SyncOutbox.status == "PENDING",
        or_(SyncOutbox.next_retry_at == None, SyncOutbox.next_retry_at <= now)
    ).order_by(SyncOutbox.id.asc()).limit(batch_size).all()

    if not endpoint:
        total_pending = db.query(SyncOutbox).filter(SyncOutbox.status == "PENDING").count()
        return {
            "status": "SYNC_NOT_CONFIGURED",
            "message": "No Central HQ synchronization endpoint configured. Events remain queued in local persistent outbox.",
            "pending_count": total_pending,
            "synced_count": 0,
            "failed_count": 0,
            "hq_endpoint": None
        }

    now = datetime.utcnow()
    synced_count = 0
    failed_count = 0

    with httpx.Client(timeout=6.0) as client:
        for outbox in pending_records:
            # Respect retry delay if set
            if outbox.next_retry_at and outbox.next_retry_at > now:
                continue

            outbox.attempt_count += 1
            outbox.last_attempt_at = now

            # Prepare real structured event payload
            try:
                inner_data = json.loads(outbox.payload_json) if outbox.payload_json else {}
            except Exception:
                inner_data = {}

            payload = {
                "event_id": outbox.event_id,
                "alert_id": outbox.alert_id,
                "camera_id": outbox.camera_id,
                "event_type": outbox.event_type,
                "severity": outbox.severity,
                "timestamp": outbox.timestamp.isoformat() if outbox.timestamp else now.isoformat(),
                "data": inner_data
            }

            try:
                headers = {"X-Worker-Secret": settings.INTERNAL_WORKER_SECRET}
                resp = client.post(endpoint, json=payload, headers=headers)
                if resp.status_code in (200, 201, 202):
                    resp_json = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    remote_id = str(resp_json.get("remote_id") or resp_json.get("id") or f"HQ-{outbox.event_id}")

                    # Mark event as confirmed and synced
                    outbox.status = "SYNCED"
                    outbox.synced_at = datetime.utcnow()
                    outbox.remote_id = remote_id
                    outbox.last_error = None
                    outbox.next_retry_at = None

                    # Insert persistent audit record
                    audit = AuditLog(
                        alert_id=outbox.alert_id,
                        alert_code=outbox.event_id,
                        stage="CENTRAL_HQ_SYNCED",
                        timestamp=datetime.utcnow(),
                        operator="STORE_AND_FORWARD_SYNC_WORKER",
                        description=f"Event {outbox.event_id} verified and synchronized with Central HQ [{remote_id}] over HTTP."
                    )
                    db.add(audit)
                    synced_count += 1
                else:
                    err_msg = f"HTTP {resp.status_code}: {resp.text[:250]}"
                    outbox.last_error = err_msg
                    # Exponential backoff: 5s, 10s, 20s, 40s... max 300s
                    delay_sec = min(300, 2 ** min(outbox.attempt_count, 6) * 5)
                    outbox.next_retry_at = datetime.utcnow() + timedelta(seconds=delay_sec)
                    failed_count += 1
            except Exception as ex:
                err_msg = f"Connection error: {str(ex)[:250]}"
                outbox.last_error = err_msg
                delay_sec = min(300, 2 ** min(outbox.attempt_count, 6) * 5)
                outbox.next_retry_at = datetime.utcnow() + timedelta(seconds=delay_sec)
                failed_count += 1

    db.commit()

    remaining_pending = db.query(SyncOutbox).filter(SyncOutbox.status == "PENDING").count()

    overall_status = "IDLE"
    if synced_count > 0:
        overall_status = "SYNC_COMPLETED"
    elif failed_count > 0:
        overall_status = "SYNC_FAILED"

    return {
        "status": overall_status,
        "synced_count": synced_count,
        "failed_count": failed_count,
        "pending_count": remaining_pending,
        "hq_endpoint": endpoint
    }


def get_outbox_stats(db: Session) -> Dict[str, Any]:
    """Returns real metrics on outbox queue states."""
    total_pending = db.query(SyncOutbox).filter(SyncOutbox.status == "PENDING").count()
    total_synced = db.query(SyncOutbox).filter(SyncOutbox.status == "SYNCED").count()
    total_failed = db.query(SyncOutbox).filter(SyncOutbox.status == "FAILED").count()
    total_all = db.query(SyncOutbox).count()

    return {
        "total_pending": total_pending,
        "total_synced": total_synced,
        "total_failed": total_failed,
        "total_events": total_all,
        "hq_endpoint": settings.HQ_SYNC_URL or None,
        "sync_configured": bool(settings.HQ_SYNC_URL)
    }
