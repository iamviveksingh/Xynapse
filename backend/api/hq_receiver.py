import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from backend.config import settings

router = APIRouter(prefix="/hq", tags=["Central HQ Ingest Receiver"])
logger = logging.getLogger("xynapse.hq_receiver")

# In-memory store for test HQ receiver to demonstrate idempotency and receipt verification
_received_hq_events: Dict[str, Dict[str, Any]] = {}

class HQIngestPayload(BaseModel):
    event_id: Optional[str] = None
    alert_code: Optional[str] = None
    alert_id: Optional[int] = None
    camera_id: Optional[str] = "CAM-01"
    event_type: Optional[str] = "BORDER_INTRUSION"
    severity: Optional[str] = "MEDIUM"
    timestamp: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

@router.post("/ingest")
def ingest_hq_event(
    payload: HQIngestPayload,
    x_worker_secret: Optional[str] = Header(None, alias="X-Worker-Secret")
):
    """
    Central Command HQ Ingest Endpoint.
    Receives synchronized events transmitted from remote border edge nodes.
    Validates internal worker authentication secret if provided or in strict mode.
    Demonstrates true duplicate prevention / idempotency: if the event_id has already
    been received, returns HTTP 200 with the existing remote_id without creating duplicate records.
    """
    if not x_worker_secret or not x_worker_secret.strip() or x_worker_secret != settings.INTERNAL_WORKER_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized internal worker secret.")

    now_str = datetime.utcnow().isoformat()
    ev_id = payload.event_id or payload.alert_code or f"EV-{int(datetime.utcnow().timestamp() * 1000)}"

    if ev_id in _received_hq_events:
        existing = _received_hq_events[ev_id]
        return {
            "status": "accepted",
            "event_id": ev_id,
            "remote_id": existing["remote_id"],
            "received_at": existing["received_at"],
            "duplicate": True,
            "message": "Event previously synchronized (idempotent response)"
        }

    remote_id = f"HQ-REC-{ev_id}"
    record = {
        "remote_id": remote_id,
        "event_id": ev_id,
        "alert_id": payload.alert_id,
        "camera_id": payload.camera_id,
        "event_type": payload.event_type,
        "severity": payload.severity,
        "timestamp": payload.timestamp,
        "received_at": now_str,
        "data": payload.data
    }
    _received_hq_events[ev_id] = record

    return {
        "status": "accepted",
        "event_id": ev_id,
        "remote_id": remote_id,
        "received_at": now_str,
        "duplicate": False,
        "message": "Event successfully accepted by Central Command HQ receiver"
    }

@router.get("/received")
def list_received_hq_events() -> List[Dict[str, Any]]:
    """Lists all events confirmed and received at the Central HQ receiver."""
    return list(_received_hq_events.values())

@router.post("/clear")
def clear_received_hq_events():
    """Clears test receiver cache for testing purposes."""
    _received_hq_events.clear()
    return {"status": "cleared", "total_received": 0}
