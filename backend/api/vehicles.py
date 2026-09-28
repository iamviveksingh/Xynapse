import re
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime

from backend.database.database import get_db, SessionLocal
from backend.database.models import VehicleProfile, VehicleTransitLog
from backend.security.auth import require_operator, require_admin

router = APIRouter(prefix="/vehicles", tags=["Vehicles & ANPR"], dependencies=[Depends(require_operator)])


class VehicleCreateSchema(BaseModel):
    plate_number: str
    vehicle_type: str = "Car"
    owner_name: Optional[str] = "Unknown"
    status: str = "CIVILIAN"  # AUTHORIZED_MILITARY, SUSPECT_STOLEN, CIVILIAN
    notes: Optional[str] = ""


@router.get("")
def list_vehicles(
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Lists enrolled vehicle profiles with optional status filtering."""
    query = db.query(VehicleProfile)
    if status:
        query = query.filter(VehicleProfile.status == status.upper())
    records = query.order_by(VehicleProfile.created_at.desc()).all()
    return [r.to_dict() for r in records]


@router.get("/stats")
def get_vehicle_stats(db: Session = Depends(get_db)):
    """Returns total count, military convoy count, and suspect stolen vehicle count."""
    total = db.query(VehicleProfile).count()
    military = db.query(VehicleProfile).filter(VehicleProfile.status == "AUTHORIZED_MILITARY").count()
    stolen = db.query(VehicleProfile).filter(VehicleProfile.status == "SUSPECT_STOLEN").count()
    civilian = db.query(VehicleProfile).filter(VehicleProfile.status == "CIVILIAN").count()
    return {
        "total": total,
        "military_count": military,
        "stolen_count": stolen,
        "civilian_count": civilian
    }


def sync_camera_anpr():
    """Reloads in-memory ANPR watchlists across all active camera managers."""
    try:
        from backend.api.cameras import camera_registry
        for cam in camera_registry.values():
            if hasattr(cam, "anpr_engine") and cam.anpr_engine:
                cam.anpr_engine.reload_profiles()
    except Exception as e:
        print(f"[VehiclesAPI] Failed to sync ANPR engines: {e}")


@router.post("")
def enroll_vehicle(payload: VehicleCreateSchema, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    """Enrolls a vehicle into the Border Check Post ANPR database."""
    clean_plate = re.sub(r"[^A-Z0-9]", "", payload.plate_number.strip().upper())
    if len(clean_plate) < 4:
        raise HTTPException(status_code=400, detail="Invalid license plate format.")

    # Check for existing
    existing = db.query(VehicleProfile).filter(VehicleProfile.plate_number == clean_plate).first()
    if existing:
        existing.vehicle_type = payload.vehicle_type
        existing.owner_name = payload.owner_name
        existing.status = payload.status.upper()
        existing.notes = payload.notes
        db.commit()
        db.refresh(existing)
        sync_camera_anpr()
        return existing.to_dict()

    profile = VehicleProfile(
        plate_number=clean_plate,
        vehicle_type=payload.vehicle_type,
        owner_name=payload.owner_name,
        status=payload.status.upper(),
        notes=payload.notes or "",
        created_at=datetime.utcnow()
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    sync_camera_anpr()
    return profile.to_dict()


@router.delete("/{profile_id}")
def delete_vehicle(profile_id: int, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    """Deletes a vehicle record from the check post roster."""
    rec = db.query(VehicleProfile).filter(VehicleProfile.id == profile_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Vehicle profile not found.")
    db.delete(rec)
    db.commit()
    sync_camera_anpr()
    return {"status": "success", "message": f"Deleted vehicle profile {profile_id}"}


from backend.config import settings

@router.post("/seed-defaults")
def seed_default_vehicles(db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    """Seeds default sample military and watchlist vehicles for testing in diagnostic mode."""
    if not settings.ENABLE_DIAGNOSTIC_MODE:
        raise HTTPException(
            status_code=403,
            detail="Vehicle roster seeding is disabled in production mode. Set ENABLE_DIAGNOSTIC_MODE=true to enable."
        )
    defaults = [
        {
            "plate_number": "ARMY01X9988",
            "vehicle_type": "Military Convoy",
            "owner_name": "Border Patrol Unit Alpha",
            "status": "AUTHORIZED_MILITARY",
            "notes": "BSF Quick Reaction Team (QRT)"
        },
        {
            "plate_number": "DL01AB1234",
            "vehicle_type": "Heavy Truck",
            "owner_name": "Wanted Cargo Smuggling",
            "status": "SUSPECT_STOLEN",
            "notes": "Red Notice: Stolen Commercial Transport"
        }
    ]

    added = 0
    for d in defaults:
        existing = db.query(VehicleProfile).filter(VehicleProfile.plate_number == d["plate_number"]).first()
        if not existing:
            p = VehicleProfile(
                plate_number=d["plate_number"],
                vehicle_type=d["vehicle_type"],
                owner_name=d["owner_name"],
                status=d["status"],
                notes=d["notes"],
                created_at=datetime.utcnow()
            )
            db.add(p)
            added += 1
    db.commit()
    return {"status": "success", "seeded": added}


# ==============================================================================
# VEHICLE TRANSIT REGISTRY & ANPR CHECKPOST LOG ENDPOINTS (P1.5 Architecture)
# ==============================================================================

@router.get("/transits")
def list_vehicle_transits(
    plate_number: Optional[str] = None,
    camera_id: Optional[str] = None,
    plate_status: Optional[str] = None,
    watchlist_match: Optional[bool] = None,
    watchlist_category: Optional[str] = None,
    direction: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """
    Retrieves paginated vehicle transit logs with multi-parameter filtering:
    - plate_number (partial substring search or exact)
    - camera_id
    - plate_status (RECOGNIZED, UNREADABLE, PENDING, LOW_CONFIDENCE, OBSCURED)
    - watchlist_match (True / False)
    - watchlist_category (SUSPECT_STOLEN, AUTHORIZED_MILITARY, CIVILIAN, etc.)
    - direction (INBOUND, OUTBOUND, UNKNOWN)
    - start_time & end_time (ISO timestamps)
    """
    query = db.query(VehicleTransitLog)

    if plate_number:
        clean = re.sub(r"[^A-Z0-9]", "", plate_number.upper())
        query = query.filter(VehicleTransitLog.plate_number.like(f"%{clean}%"))

    if camera_id:
        query = query.filter(VehicleTransitLog.camera_id == camera_id)

    if plate_status:
        query = query.filter(VehicleTransitLog.plate_status == plate_status.upper())

    if watchlist_match is not None:
        query = query.filter(VehicleTransitLog.watchlist_match == (1 if watchlist_match else 0))

    if watchlist_category:
        query = query.filter(VehicleTransitLog.watchlist_category == watchlist_category.upper())

    if direction:
        query = query.filter(VehicleTransitLog.direction == direction.upper())

    if start_time:
        query = query.filter(VehicleTransitLog.created_at >= start_time)

    if end_time:
        query = query.filter(VehicleTransitLog.created_at <= end_time)

    total = query.count()
    records = query.order_by(VehicleTransitLog.id.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "transits": [r.to_dict() for r in records]
    }


@router.get("/transits/recent")
def get_recent_transits(
    limit: int = Query(20, ge=1, le=100),
    camera_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Returns the most recent vehicle transits in chronological order."""
    query = db.query(VehicleTransitLog)
    if camera_id:
        query = query.filter(VehicleTransitLog.camera_id == camera_id)
    records = query.order_by(VehicleTransitLog.id.desc()).limit(limit).all()
    return [r.to_dict() for r in records]


@router.get("/transits/stats")
def get_transit_stats(
    camera_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Returns aggregate vehicle checkpost transit statistics."""
    base_query = db.query(VehicleTransitLog)
    if camera_id:
        base_query = base_query.filter(VehicleTransitLog.camera_id == camera_id)

    total = base_query.count()
    recognized = base_query.filter(VehicleTransitLog.plate_status == "RECOGNIZED").count()
    unreadable = base_query.filter(VehicleTransitLog.plate_status == "UNREADABLE").count()
    pending = base_query.filter(VehicleTransitLog.plate_status == "PENDING").count()
    watchlist_matches = base_query.filter(VehicleTransitLog.watchlist_match == 1).count()
    stolen_intercepts = base_query.filter(VehicleTransitLog.watchlist_category == "SUSPECT_STOLEN").count()

    return {
        "total_transits": total,
        "recognized_count": recognized,
        "unreadable_count": unreadable,
        "pending_count": pending,
        "watchlist_matches": watchlist_matches,
        "stolen_intercepts": stolen_intercepts,
        "recognition_rate_pct": round((recognized / total * 100), 1) if total > 0 else 0.0
    }


@router.get("/transits/{transit_id}")
def get_transit_by_id(
    transit_id: str,
    db: Session = Depends(get_db)
):
    """Retrieves a specific vehicle transit log by primary key ID or unique event_id."""
    rec = None
    if transit_id.isdigit():
        rec = db.query(VehicleTransitLog).filter(VehicleTransitLog.id == int(transit_id)).first()
    if not rec:
        rec = db.query(VehicleTransitLog).filter(VehicleTransitLog.event_id == transit_id).first()

    if not rec:
        raise HTTPException(status_code=404, detail="Vehicle transit record not found.")

    return rec.to_dict()
