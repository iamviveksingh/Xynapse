import os
import time
from typing import List, Optional
import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.database.models import FaceProfile
from backend.api.cameras import face_recognizer, camera_registry, get_or_create_default_camera
from backend.config import settings
from backend.security.auth import require_operator, require_admin

router = APIRouter(prefix="/faces", tags=["Face Recognition"], dependencies=[Depends(require_operator)])

@router.get("")
def list_faces(
    role: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Returns list of registered face profiles (Authorized Whitelist & Suspect Watchlist)."""
    query = db.query(FaceProfile)
    if role and role.upper() != "ALL":
        query = query.filter(FaceProfile.role == role.upper())

    records = query.order_by(FaceProfile.id.desc()).all()
    return [r.to_dict() for r in records]

@router.get("/stats")
def get_face_stats(db: Session = Depends(get_db)):
    """Summary counts of authorized vs suspect watchlist persons."""
    total = db.query(FaceProfile).count()
    authorized = db.query(FaceProfile).filter(FaceProfile.role == "AUTHORIZED_GUARD").count()
    suspects = db.query(FaceProfile).filter(FaceProfile.role == "SUSPECT_WATCHLIST").count()

    return {
        "total": total,
        "authorized_count": authorized,
        "suspect_count": suspects
    }

@router.post("/enroll")
async def enroll_face(
    name: str = Form(...),
    role: str = Form("AUTHORIZED_GUARD"),
    notes: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin)
):
    """
    Enrolls a new person into the face database.
    Uploads an image, detects the face, extracts a 128-D neural embedding,
    and classifies as either AUTHORIZED_GUARD (whitelist) or SUSPECT_WATCHLIST (blacklist).
    """
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Person name is required.")

    valid_roles = ["AUTHORIZED_GUARD", "SUSPECT_WATCHLIST"]
    clean_role = role.strip().upper()
    if clean_role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")

    # Read image bytes and handle orientation/channels
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    image = None
    try:
        import io
        from PIL import Image, ImageOps
        pil_img = Image.open(io.BytesIO(contents))
        pil_img = ImageOps.exif_transpose(pil_img)
        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")
        image = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception:
        np_arr = np.frombuffer(contents, np.uint8)
        image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if image is None or image.size == 0:
        raise HTTPException(status_code=400, detail="Invalid image file format.")

    # Photo destination in evidence directory
    faces_dir = os.path.join(os.path.dirname(settings.EVIDENCE_DIR), "faces")
    os.makedirs(faces_dir, exist_ok=True)
    filename = f"face_{int(time.time())}_{name.strip().replace(' ', '_')}.jpg"
    photo_path = os.path.join(faces_dir, filename)

    try:
        profile_dict = face_recognizer.enroll_from_image(
            image=image,
            name=name.strip(),
            role=clean_role,
            notes=notes.strip() if notes else "",
            save_photo_path=photo_path
        )
        # Web accessible photo path
        profile_dict["photo_path"] = f"/evidence/faces/{filename}"
        return {
            "success": True,
            "message": f"Successfully enrolled {name} as {clean_role}",
            "profile": profile_dict
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Face enrollment failed: {e}")

@router.post("/enroll-from-camera")
def enroll_from_camera(
    name: str = Form(...),
    role: str = Form("AUTHORIZED_GUARD"),
    notes: str = Form(""),
    camera_id: str = Form("CAM-01"),
    _admin: str = Depends(require_admin)
):
    """
    Convenience method: Takes the current live webcam frame and enrolls the person directly.
    """
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Person name is required.")

    get_or_create_default_camera()
    cam = camera_registry.get(camera_id)
    if not cam:
        raise HTTPException(status_code=400, detail="Camera not found.")

    # Retrieve current frame with short retry if camera is starting
    frame = None
    for _ in range(10):
        frame = cam.get_current_raw_frame()
        if frame is not None and frame.size > 0:
            break
        time.sleep(0.1)

    if frame is None:
        raise HTTPException(status_code=400, detail="Camera is currently offline or loading. Please ensure the camera is turned ON.")
    faces_dir = os.path.join(os.path.dirname(settings.EVIDENCE_DIR), "faces")
    os.makedirs(faces_dir, exist_ok=True)
    filename = f"face_{int(time.time())}_{name.strip().replace(' ', '_')}.jpg"
    photo_path = os.path.join(faces_dir, filename)

    clean_role = role.strip().upper()
    try:
        profile_dict = face_recognizer.enroll_from_image(
            image=frame,
            name=name.strip(),
            role=clean_role,
            notes=notes.strip() if notes else "",
            save_photo_path=photo_path
        )
        profile_dict["photo_path"] = f"/evidence/faces/{filename}"
        return {
            "success": True,
            "message": f"Successfully enrolled {name} from camera as {clean_role}",
            "profile": profile_dict
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Camera face enrollment failed: {e}")

@router.delete("/{face_id}")
def delete_face(face_id: int, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    """Deletes a face profile and reloads the active recognition cache."""
    profile = db.query(FaceProfile).filter(FaceProfile.id == face_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Face profile not found.")

    name = profile.name
    # Remove photo file if exists
    if profile.photo_path:
        photo_disk_path = profile.photo_path
        if photo_disk_path.startswith("/evidence/faces/"):
            faces_dir = os.path.join(os.path.dirname(settings.EVIDENCE_DIR), "faces")
            photo_disk_path = os.path.join(faces_dir, os.path.basename(photo_disk_path))
        if os.path.exists(photo_disk_path):
            try:
                os.remove(photo_disk_path)
            except Exception:
                pass

    db.delete(profile)
    db.commit()

    # Reload in-memory profiles
    face_recognizer.reload_profiles()

    return {
        "success": True,
        "message": f"Successfully deleted profile for {name}.",
        "deleted_id": face_id
    }
