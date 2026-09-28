import asyncio
import time
from datetime import datetime
from typing import List, Dict, Any, Callable, Optional
from collections import defaultdict, deque
import numpy as np

from backend.config import settings
from backend.alert.cooldown import CooldownTracker
from backend.evidence.snapshot import save_snapshot, get_evidence_integrity
from backend.database.database import SessionLocal
from backend.database.models import Alert, AuditLog

class AlertEngine:
    """
    Processes vision perception events, evaluates cooldown rules,
    creates evidence snapshots, persists incident records to SQLite,
    and dispatches real-time alert events.
    """

    def __init__(self, cooldown_seconds: int = settings.ALERT_COOLDOWN_SECONDS):
        self.cooldown_tracker = CooldownTracker(cooldown_seconds)
        self._listeners: List[Callable[[Dict[str, Any]], Any]] = []
        # Loitering detection: per-camera detection timestamps
        self._detection_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=20))
        self.LOITER_WINDOW_SECONDS = 120  # 2 minutes
        self.LOITER_THRESHOLD = 3  # 3 detections in window = loitering

    @staticmethod
    def _write_audit_trail(db, alert):
        try:
            ts = alert.timestamp or datetime.utcnow()
            ev_hash = getattr(alert, "evidence_hash", None) or ""
            hash_display = f"[{ev_hash[:16]}...{ev_hash[-8:]}]" if len(ev_hash) >= 24 else (ev_hash or "CALCULATING")
            logs = [
                AuditLog(
                    alert_id=alert.id,
                    alert_code=alert.alert_code,
                    stage="OPTICAL_ACQUISITION",
                    timestamp=ts,
                    operator="AUTONOMOUS_SENSOR_NODE",
                    description=f"Hardware optical frame acquired from sensor node {alert.camera_id} in {getattr(alert, 'optical_mode', 'DAY_RGB') or 'DAY_RGB'} optical mode."
                ),
                AuditLog(
                    alert_id=alert.id,
                    alert_code=alert.alert_code,
                    stage="NEURAL_INFERENCE",
                    timestamp=ts,
                    operator="AUTONOMOUS_VISION_PIPELINE",
                    description=f"Neural perception classified: {alert.event_type} at {int((alert.confidence or 0)*100)}% confidence ({alert.objects_detected})."
                ),
                AuditLog(
                    alert_id=alert.id,
                    alert_code=alert.alert_code,
                    stage="SHA256_HASHING",
                    timestamp=ts,
                    operator="EVIDENTIARY_HASH_ENGINE",
                    evidence_hash=ev_hash,
                    description=f"Cryptographic SHA-256 evidence fingerprint calculated: {hash_display}."
                ),
                AuditLog(
                    alert_id=alert.id,
                    alert_code=alert.alert_code,
                    stage="TACTICAL_DISPATCH",
                    timestamp=ts,
                    operator="DISPATCH_WEBSOCKET_BROADCASTER",
                    description=f"Tactical intercept alert dispatched to Command Center Terminals (Severity: {alert.severity})."
                )
            ]
            db.add_all(logs)
            db.commit()

            # Cryptographically link incident into tamper-evident audit chain
            try:
                from backend.security.blockchain_ledger import seal_alert_in_blockchain
                seal_alert_in_blockchain(db, alert)
            except Exception as b_ex:
                print(f"[AlertEngine] Cryptographic audit chain seal note: {b_ex}")

            # Enqueue incident into persistent store-and-forward outbox
            try:
                import json
                from backend.database.models import SyncOutbox
                ev_code = alert.alert_code or f"XP-{alert.id:06d}"
                existing_outbox = db.query(SyncOutbox).filter(SyncOutbox.event_id == ev_code).first()
                if not existing_outbox:
                    outbox_payload = {
                        "event_id": ev_code,
                        "alert_code": ev_code,
                        "event_type": alert.event_type,
                        "camera_id": alert.camera_id,
                        "timestamp": alert.timestamp.isoformat() if alert.timestamp else datetime.utcnow().isoformat(),
                        "confidence": float(alert.confidence or 0.0),
                        "objects_detected": alert.objects_detected,
                        "severity": alert.severity or "MEDIUM",
                        "optical_mode": getattr(alert, "optical_mode", "DAY_RGB") or "DAY_RGB",
                        "evidence_hash": getattr(alert, "evidence_hash", None),
                        "snapshot_path": getattr(alert, "snapshot_path", None)
                    }
                    outbox_entry = SyncOutbox(
                        event_id=ev_code,
                        alert_id=alert.id,
                        camera_id=alert.camera_id,
                        event_type=alert.event_type,
                        severity=alert.severity or "MEDIUM",
                        timestamp=alert.timestamp or datetime.utcnow(),
                        payload_json=json.dumps(outbox_payload),
                        status="PENDING"
                    )
                    db.add(outbox_entry)
                    db.commit()
            except Exception as outbox_err:
                print(f"[AlertEngine] Outbox enqueue note: {outbox_err}")
        except Exception as ex:
            print(f"[AlertEngine] Audit log write failed: {ex}")

    @staticmethod
    def _compute_severity(event_type: str, face_count: int = 0, confidence: float = 0.0) -> str:
        """Classifies alert severity based on event type, face count, and confidence."""
        if event_type in ("CAMERA_TAMPERED", "SUSPECT_DETECTED"):
            return "CRITICAL"
        if event_type == "SUSPICIOUS_LOITERING":
            return "HIGH"
        if face_count >= 3:
            return "HIGH"
        if face_count >= 2 or confidence >= 0.90:
            return "HIGH"
        if face_count == 1 and confidence >= 0.70:
            return "MEDIUM"
        return "LOW"

    def register_listener(self, listener: Callable[[Dict[str, Any]], Any]) -> None:
        """Register an async or sync callback for when new alerts trigger."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def _dispatch_to_listeners(self, ws_payload: Dict[str, Any]) -> None:
        """Dispatch alert payload to all registered listeners (WebSocket, etc.)."""
        for listener in self._listeners:
            try:
                from backend.websocket.alert_socket import ws_manager
                if listener == ws_manager.broadcast or (hasattr(listener, "__self__") and listener.__self__ is ws_manager):
                    ws_manager.broadcast_threadsafe(ws_payload)
                    continue

                res = listener(ws_payload)
                if asyncio.iscoroutine(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        if ws_manager._loop and ws_manager._loop.is_running():
                            asyncio.run_coroutine_threadsafe(res, ws_manager._loop)
                        else:
                            try:
                                asyncio.run(res)
                            except Exception:
                                pass
            except Exception as ex:
                print(f"[AlertEngine] Listener error: {ex}")

    def process_detections(
        self,
        camera_id: str,
        frame: np.ndarray,
        detections: List[Dict[str, Any]],
        annotated_frame: Optional[np.ndarray] = None,
        optical_mode: str = "DAY_RGB"
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates detected faces. If at least 1 face is found and camera is cooled down,
        creates a new PERSON_DETECTED alert.
        """
        face_count = len(detections)
        if face_count == 0:
            return None

        # Check debouncing window
        if not self.cooldown_tracker.is_cooled_down(camera_id):
            return None

        # Cooldown passed — mark trigger timestamp
        self.cooldown_tracker.trigger(camera_id)

        # Compute highest detection confidence among visible faces
        max_conf = max(d["confidence"] for d in detections)
        obj_names = ", ".join([f"{d['label']} ({int(d['confidence']*100)}%)" for d in detections])

        # Snapshot preference: capture annotated frame with detection box if available, or clean frame
        snap_source = annotated_frame if annotated_frame is not None else frame
        snapshot_url = save_snapshot(snap_source, camera_id)
        integrity = get_evidence_integrity(snapshot_url)
        evidence_hash = integrity.get("sha256")

        # Compute severity
        severity = self._compute_severity("PERSON_DETECTED", face_count, max_conf)

        # Persist alert record to SQLite
        db = SessionLocal()
        try:
            alert = Alert(
                event_type="PERSON_DETECTED",
                camera_id=camera_id,
                timestamp=datetime.now(),
                face_count=face_count,
                confidence=float(max_conf),
                objects_detected=obj_names,
                snapshot_path=snapshot_url,
                evidence_hash=evidence_hash,
                optical_mode=optical_mode,
                status="NEW",
                severity=severity,
                created_at=datetime.now()
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)

            # Assign human-readable alert code: XP-000001
            alert.alert_code = f"XP-{alert.id:06d}"
            db.commit()
            db.refresh(alert)
            alert_dict = alert.to_dict()

            # Format and DISPATCH WebSocket payload immediately for zero-delay UI alert
            ws_payload = {
                "type": "PERSON_DETECTED",
                "alert_id": alert_dict["alert_id"],
                "camera_id": alert_dict["camera_id"],
                "timestamp": alert_dict["timestamp"],
                "face_count": alert_dict["face_count"],
                "objects_detected": alert_dict.get("objects_detected", f"{alert_dict['face_count']} Face(s)"),
                "confidence": alert_dict["confidence"],
                "snapshot": alert_dict["snapshot"],
                "evidence_hash": alert_dict.get("evidence_hash"),
                "optical_mode": alert_dict.get("optical_mode", optical_mode),
                "status": alert_dict["status"],
                "severity": alert_dict.get("severity", severity)
            }
            self._dispatch_to_listeners(ws_payload)

            # Persist blockchain audit ledger asynchronously / right after
            self._write_audit_trail(db, alert)
        except Exception as e:
            db.rollback()
            print(f"[AlertEngine] DB error creating alert: {e}")
            alert_dict = {
                "id": 0,
                "alert_id": "XP-ALERT",
                "event_type": "PERSON_DETECTED",
                "camera_id": camera_id,
                "timestamp": datetime.utcnow().isoformat(),
                "face_count": face_count,
                "confidence": round(float(max_conf), 2),
                "snapshot": snapshot_url,
                "evidence_hash": evidence_hash,
                "optical_mode": optical_mode,
                "status": "NEW",
                "severity": severity
            }
            ws_payload = {
                "type": "PERSON_DETECTED",
                "alert_id": alert_dict["alert_id"],
                "camera_id": alert_dict["camera_id"],
                "timestamp": alert_dict["timestamp"],
                "face_count": alert_dict["face_count"],
                "objects_detected": alert_dict.get("objects_detected", f"{alert_dict['face_count']} Face(s)"),
                "confidence": alert_dict["confidence"],
                "snapshot": alert_dict["snapshot"],
                "evidence_hash": alert_dict.get("evidence_hash"),
                "optical_mode": alert_dict.get("optical_mode", optical_mode),
                "status": alert_dict["status"],
                "severity": alert_dict.get("severity", severity)
            }
            self._dispatch_to_listeners(ws_payload)
        finally:
            db.close()

        return alert_dict

    def check_loitering(
        self,
        camera_id: str,
        frame: np.ndarray,
        dwell_seconds: Optional[float] = None,
        optical_mode: str = "DAY_RGB"
    ) -> Optional[Dict[str, Any]]:
        """
        Checks if repeated detections or sustained presence on the same camera indicate loitering.
        Triggers if dwell time exceeds threshold (>= 25s) or 3+ detections occur within window.
        """
        now = time.time()
        self._detection_history[camera_id].append(now)

        # Count detections within the loitering window
        recent = [t for t in self._detection_history[camera_id]
                  if now - t <= self.LOITER_WINDOW_SECONDS]

        is_loitering = len(recent) >= self.LOITER_THRESHOLD or (dwell_seconds is not None and dwell_seconds >= 25.0)

        if is_loitering:
            count = len(recent) if len(recent) >= self.LOITER_THRESHOLD else max(len(recent), 1)
            return self._trigger_loitering_alert(camera_id, frame, count, dwell_seconds=dwell_seconds, optical_mode=optical_mode)
        return None

    def _trigger_loitering_alert(
        self,
        camera_id: str,
        frame: np.ndarray,
        detection_count: int,
        dwell_seconds: Optional[float] = None,
        optical_mode: str = "DAY_RGB"
    ) -> Optional[Dict[str, Any]]:
        """
        Creates a SUSPICIOUS_LOITERING alert when sustained human presence
        is detected on a camera within the loitering time window or dwell threshold.
        """
        cooldown_key = f"{camera_id}_LOITER"
        if not self.cooldown_tracker.is_cooled_down(cooldown_key):
            return None

        self.cooldown_tracker.trigger(cooldown_key)
        snapshot_url = save_snapshot(frame, camera_id)
        integrity = get_evidence_integrity(snapshot_url)
        evidence_hash = integrity.get("sha256")
        severity = "HIGH"
        if dwell_seconds is not None and dwell_seconds >= 25.0:
            reason = f"Suspicious loitering: Subject dwelling in restricted perimeter for {int(dwell_seconds)}s"
        else:
            reason = f"Sustained human presence detected ({detection_count} detections in {self.LOITER_WINDOW_SECONDS}s)"

        db = SessionLocal()
        try:
            alert = Alert(
                event_type="SUSPICIOUS_LOITERING",
                camera_id=camera_id,
                timestamp=datetime.now(),
                face_count=detection_count,
                confidence=0.95,
                objects_detected=reason,
                snapshot_path=snapshot_url,
                evidence_hash=evidence_hash,
                optical_mode=optical_mode,
                status="NEW",
                severity=severity,
                created_at=datetime.now()
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)
            alert.alert_code = f"XP-{alert.id:06d}"
            db.commit()
            db.refresh(alert)
            self._write_audit_trail(db, alert)
            alert_dict = alert.to_dict()
        except Exception as e:
            db.rollback()
            print(f"[AlertEngine] DB error creating loitering alert: {e}")
            alert_dict = {
                "id": 0,
                "alert_id": "XP-LOITER",
                "event_type": "SUSPICIOUS_LOITERING",
                "camera_id": camera_id,
                "timestamp": datetime.utcnow().isoformat(),
                "face_count": detection_count,
                "confidence": 0.95,
                "objects_detected": reason,
                "snapshot": snapshot_url,
                "evidence_hash": evidence_hash,
                "optical_mode": optical_mode,
                "status": "NEW",
                "severity": severity
            }
        finally:
            db.close()

        ws_payload = {
            "type": "SUSPICIOUS_LOITERING",
            "alert_id": alert_dict["alert_id"],
            "camera_id": alert_dict["camera_id"],
            "event_type": "SUSPICIOUS_LOITERING",
            "timestamp": alert_dict["timestamp"],
            "face_count": detection_count,
            "objects_detected": reason,
            "confidence": 0.95,
            "snapshot": alert_dict["snapshot"],
            "evidence_hash": alert_dict.get("evidence_hash"),
            "optical_mode": alert_dict.get("optical_mode", optical_mode),
            "status": alert_dict["status"],
            "severity": severity
        }

        self._dispatch_to_listeners(ws_payload)
        return alert_dict

    def trigger_tampering_alert(
        self,
        camera_id: str,
        frame: np.ndarray,
        reason: str = "Camera Lens Occlusion / Tampering Detected",
        optical_mode: str = "DAY_RGB"
    ) -> Optional[Dict[str, Any]]:
        """
        Triggered when camera lens is occluded, covered, or tampered with.
        Debounces via isolated cooldown tracker key to avoid event flooding.
        """
        cooldown_key = f"{camera_id}_TAMPER"
        if not self.cooldown_tracker.is_cooled_down(cooldown_key):
            return None

        self.cooldown_tracker.trigger(cooldown_key)
        snapshot_url = save_snapshot(frame, camera_id)
        integrity = get_evidence_integrity(snapshot_url)
        evidence_hash = integrity.get("sha256")
        severity = "CRITICAL"

        db = SessionLocal()
        try:
            alert = Alert(
                event_type="CAMERA_TAMPERED",
                camera_id=camera_id,
                timestamp=datetime.now(),
                face_count=0,
                confidence=0.99,
                objects_detected=reason,
                snapshot_path=snapshot_url,
                evidence_hash=evidence_hash,
                optical_mode=optical_mode,
                status="NEW",
                severity=severity,
                created_at=datetime.now()
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)
            alert.alert_code = f"XP-{alert.id:06d}"
            db.commit()
            db.refresh(alert)
            self._write_audit_trail(db, alert)
            alert_dict = alert.to_dict()
        except Exception as e:
            db.rollback()
            print(f"[AlertEngine] DB error creating tampering alert: {e}")
            alert_dict = {
                "id": 0,
                "alert_id": "XP-TAMPER",
                "event_type": "CAMERA_TAMPERED",
                "camera_id": camera_id,
                "timestamp": datetime.utcnow().isoformat(),
                "face_count": 0,
                "confidence": 0.99,
                "objects_detected": reason,
                "snapshot": snapshot_url,
                "evidence_hash": evidence_hash,
                "optical_mode": optical_mode,
                "status": "NEW",
                "severity": severity
            }
        finally:
            db.close()

        ws_payload = {
            "type": "CAMERA_TAMPERED",
            "alert_id": alert_dict["alert_id"],
            "camera_id": alert_dict["camera_id"],
            "event_type": "CAMERA_TAMPERED",
            "timestamp": alert_dict["timestamp"],
            "face_count": 0,
            "objects_detected": reason,
            "confidence": 0.99,
            "snapshot": alert_dict["snapshot"],
            "evidence_hash": alert_dict.get("evidence_hash"),
            "optical_mode": alert_dict.get("optical_mode", optical_mode),
            "status": alert_dict["status"],
            "severity": severity
        }

        self._dispatch_to_listeners(ws_payload)
        return alert_dict

    def trigger_cyber_tamper_alert(
        self,
        camera_id: str,
        frame: np.ndarray,
        reason: str = "Cyber Security Alert: Video Replay / Frozen Stream Attack Detected",
        optical_mode: str = "DAY_RGB"
    ) -> Optional[Dict[str, Any]]:
        """
        Triggered when consecutive physical camera frames exhibit zero natural sensor noise,
        indicating a synthetic freeze, static frame injection, or video replay loop.
        Debounced via CYBER_TAMPER key. Dispatches CRITICAL severity alert.
        """
        cooldown_key = f"{camera_id}_CYBER_TAMPER"
        if not self.cooldown_tracker.is_cooled_down(cooldown_key):
            return None

        self.cooldown_tracker.trigger(cooldown_key)
        snapshot_url = save_snapshot(frame, camera_id)
        integrity = get_evidence_integrity(snapshot_url)
        evidence_hash = integrity.get("sha256")
        severity = "CRITICAL"

        db = SessionLocal()
        try:
            alert = Alert(
                event_type="CYBER_STREAM_TAMPERED",
                camera_id=camera_id,
                timestamp=datetime.now(),
                face_count=0,
                confidence=0.99,
                objects_detected=reason,
                snapshot_path=snapshot_url,
                evidence_hash=evidence_hash,
                optical_mode=optical_mode,
                status="NEW",
                severity=severity,
                created_at=datetime.now()
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)
            alert.alert_code = f"XP-{alert.id:06d}"
            db.commit()
            db.refresh(alert)
            self._write_audit_trail(db, alert)
            alert_dict = alert.to_dict()
        except Exception as e:
            db.rollback()
            print(f"[AlertEngine] DB error creating cyber tamper alert: {e}")
            alert_dict = {
                "id": 0,
                "alert_id": "XP-CYBER",
                "event_type": "CYBER_STREAM_TAMPERED",
                "camera_id": camera_id,
                "timestamp": datetime.utcnow().isoformat(),
                "face_count": 0,
                "confidence": 0.99,
                "objects_detected": reason,
                "snapshot": snapshot_url,
                "evidence_hash": evidence_hash,
                "optical_mode": optical_mode,
                "status": "NEW",
                "severity": severity
            }
        finally:
            db.close()

        ws_payload = {
            "type": "CYBER_STREAM_TAMPERED",
            "alert_id": alert_dict["alert_id"],
            "camera_id": alert_dict["camera_id"],
            "event_type": "CYBER_STREAM_TAMPERED",
            "timestamp": alert_dict["timestamp"],
            "face_count": 0,
            "objects_detected": reason,
            "confidence": 0.99,
            "snapshot": alert_dict["snapshot"],
            "evidence_hash": alert_dict.get("evidence_hash"),
            "optical_mode": alert_dict.get("optical_mode", optical_mode),
            "status": alert_dict["status"],
            "severity": severity
        }

        self._dispatch_to_listeners(ws_payload)
        return alert_dict

    def trigger_suspect_alert(
        self,
        camera_id: str,
        frame: np.ndarray,
        suspect_name: str,
        confidence: float = 0.95,
        notes: str = "",
        optical_mode: str = "DAY_RGB"
    ) -> Optional[Dict[str, Any]]:
        """
        Triggered when an individual on the SUSPECT_WATCHLIST is identified.
        Dispatches an immediate CRITICAL severity alert and saves visual evidence snapshot.
        """
        cooldown_key = f"{camera_id}_SUSPECT_{suspect_name}"
        if not self.cooldown_tracker.is_cooled_down(cooldown_key):
            return None

        self.cooldown_tracker.trigger(cooldown_key)
        snapshot_url = save_snapshot(frame, camera_id)
        integrity = get_evidence_integrity(snapshot_url)
        evidence_hash = integrity.get("sha256")
        severity = "CRITICAL"
        reason = f"WATCHLIST SUSPECT IDENTIFIED: {suspect_name}"
        if notes:
            reason += f" ({notes})"

        db = SessionLocal()
        try:
            alert = Alert(
                event_type="SUSPECT_DETECTED",
                camera_id=camera_id,
                timestamp=datetime.now(),
                face_count=1,
                confidence=float(confidence),
                objects_detected=reason,
                snapshot_path=snapshot_url,
                evidence_hash=evidence_hash,
                optical_mode=optical_mode,
                status="NEW",
                severity=severity,
                created_at=datetime.now()
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)
            alert.alert_code = f"XP-{alert.id:06d}"
            db.commit()
            db.refresh(alert)
            alert_dict = alert.to_dict()

            # Format and DISPATCH WebSocket payload immediately for zero-delay UI alert
            ws_payload = {
                "type": "SUSPECT_DETECTED",
                "alert_id": alert_dict["alert_id"],
                "camera_id": alert_dict["camera_id"],
                "event_type": "SUSPECT_DETECTED",
                "timestamp": alert_dict["timestamp"],
                "face_count": 1,
                "suspect_name": suspect_name,
                "objects_detected": reason,
                "confidence": round(float(confidence), 2),
                "snapshot": alert_dict["snapshot"],
                "evidence_hash": alert_dict.get("evidence_hash"),
                "optical_mode": alert_dict.get("optical_mode", optical_mode),
                "status": alert_dict["status"],
                "severity": severity
            }
            self._dispatch_to_listeners(ws_payload)

            # Persist blockchain audit ledger asynchronously / right after
            self._write_audit_trail(db, alert)
        except Exception as e:
            db.rollback()
            print(f"[AlertEngine] DB error creating suspect alert: {e}")
            alert_dict = {
                "id": 0,
                "alert_id": "XP-SUSPECT",
                "event_type": "SUSPECT_DETECTED",
                "camera_id": camera_id,
                "timestamp": datetime.utcnow().isoformat(),
                "face_count": 1,
                "confidence": round(float(confidence), 2),
                "objects_detected": reason,
                "snapshot": snapshot_url,
                "evidence_hash": evidence_hash,
                "optical_mode": optical_mode,
                "status": "NEW",
                "severity": severity
            }
            ws_payload = {
                "type": "SUSPECT_DETECTED",
                "alert_id": alert_dict["alert_id"],
                "camera_id": alert_dict["camera_id"],
                "event_type": "SUSPECT_DETECTED",
                "timestamp": alert_dict["timestamp"],
                "face_count": 1,
                "suspect_name": suspect_name,
                "objects_detected": reason,
                "confidence": round(float(confidence), 2),
                "snapshot": alert_dict["snapshot"],
                "evidence_hash": alert_dict.get("evidence_hash"),
                "optical_mode": alert_dict.get("optical_mode", optical_mode),
                "status": alert_dict["status"],
                "severity": severity
            }
            self._dispatch_to_listeners(ws_payload)
        finally:
            db.close()

        return alert_dict

    def trigger_intrusion_alert(
        self,
        camera_id: str,
        frame: np.ndarray,
        breached_count: int = 1,
        details: str = "Restricted Border Zero-Line Breached by Unauthorized Person",
        confidence: float = 0.95,
        optical_mode: str = "DAY_RGB"
    ) -> Optional[Dict[str, Any]]:
        """
        Triggered when an unauthorized subject crosses the virtual border fence line.
        Dispatches CRITICAL perimeter breach alert and captures snapshot evidence.
        """
        cooldown_key = f"{camera_id}_INTRUSION"
        if not self.cooldown_tracker.is_cooled_down(cooldown_key):
            return None

        self.cooldown_tracker.trigger(cooldown_key)
        snapshot_url = save_snapshot(frame, camera_id)
        integrity = get_evidence_integrity(snapshot_url)
        evidence_hash = integrity.get("sha256")
        severity = "CRITICAL"

        db = SessionLocal()
        try:
            alert = Alert(
                event_type="BORDER_INTRUSION",
                camera_id=camera_id,
                timestamp=datetime.now(),
                face_count=breached_count,
                confidence=float(confidence),
                objects_detected=details,
                snapshot_path=snapshot_url,
                evidence_hash=evidence_hash,
                optical_mode=optical_mode,
                status="NEW",
                severity=severity,
                created_at=datetime.now()
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)
            alert.alert_code = f"XP-{alert.id:06d}"
            db.commit()
            db.refresh(alert)
            self._write_audit_trail(db, alert)
            alert_dict = alert.to_dict()
        except Exception as e:
            db.rollback()
            print(f"[AlertEngine] DB error creating border intrusion alert: {e}")
            alert_dict = {
                "id": 0,
                "alert_id": "XP-INTRUSION",
                "event_type": "BORDER_INTRUSION",
                "camera_id": camera_id,
                "timestamp": datetime.utcnow().isoformat(),
                "face_count": breached_count,
                "confidence": round(float(confidence), 2),
                "objects_detected": details,
                "snapshot": snapshot_url,
                "evidence_hash": evidence_hash,
                "optical_mode": optical_mode,
                "status": "NEW",
                "severity": severity
            }
        finally:
            db.close()

        ws_payload = {
            "type": "BORDER_INTRUSION",
            "alert_id": alert_dict["alert_id"],
            "camera_id": alert_dict["camera_id"],
            "event_type": "BORDER_INTRUSION",
            "timestamp": alert_dict["timestamp"],
            "face_count": breached_count,
            "objects_detected": details,
            "confidence": round(float(confidence), 2),
            "snapshot": alert_dict["snapshot"],
            "evidence_hash": alert_dict.get("evidence_hash"),
            "optical_mode": alert_dict.get("optical_mode", optical_mode),
            "status": alert_dict["status"],
            "severity": severity
        }

        self._dispatch_to_listeners(ws_payload)
        return alert_dict

    def trigger_wildlife_alert(
        self,
        camera_id: str,
        frame: np.ndarray,
        animal_type: str = "Cattle",
        count: int = 1,
        confidence: float = 0.85,
        optical_mode: str = "DAY_RGB"
    ) -> Optional[Dict[str, Any]]:
        """
        Triggered when non-threat border fauna/livestock crosses the zero-line.
        SSB Operational Requirement: Logs transit quietly with LOW severity to prevent
        armed alarm fatigue, completely suppressing critical sirens and popups.
        """
        cooldown_key = f"{camera_id}_WILDLIFE_{animal_type}"
        if not self.cooldown_tracker.is_cooled_down(cooldown_key):
            return None

        self.cooldown_tracker.trigger(cooldown_key)
        snapshot_url = save_snapshot(frame, camera_id)
        integrity = get_evidence_integrity(snapshot_url)
        evidence_hash = integrity.get("sha256")
        severity = "LOW"
        details = f"Fauna Filter: {count}x {animal_type} transit detected (Armed Siren Suppressed)"

        db = SessionLocal()
        try:
            alert = Alert(
                event_type="WILDLIFE_TRANSIT",
                camera_id=camera_id,
                timestamp=datetime.now(),
                face_count=count,
                confidence=float(confidence),
                objects_detected=details,
                snapshot_path=snapshot_url,
                evidence_hash=evidence_hash,
                optical_mode=optical_mode,
                status="NEW",
                severity=severity,
                created_at=datetime.now()
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)
            alert.alert_code = f"XP-{alert.id:06d}"
            db.commit()
            db.refresh(alert)
            self._write_audit_trail(db, alert)
            alert_dict = alert.to_dict()
        except Exception as e:
            db.rollback()
            print(f"[AlertEngine] DB error creating wildlife transit alert: {e}")
            alert_dict = {
                "id": 0,
                "alert_id": "XP-WILDLIFE",
                "event_type": "WILDLIFE_TRANSIT",
                "camera_id": camera_id,
                "timestamp": datetime.utcnow().isoformat(),
                "face_count": count,
                "confidence": round(float(confidence), 2),
                "objects_detected": details,
                "snapshot": snapshot_url,
                "evidence_hash": evidence_hash,
                "optical_mode": optical_mode,
                "status": "NEW",
                "severity": severity
            }
        finally:
            db.close()

        ws_payload = {
            "type": "WILDLIFE_TRANSIT",
            "alert_id": alert_dict["alert_id"],
            "camera_id": alert_dict["camera_id"],
            "event_type": "WILDLIFE_TRANSIT",
            "timestamp": alert_dict["timestamp"],
            "face_count": count,
            "objects_detected": details,
            "confidence": round(float(confidence), 2),
            "snapshot": alert_dict["snapshot"],
            "evidence_hash": alert_dict.get("evidence_hash"),
            "optical_mode": alert_dict.get("optical_mode", optical_mode),
            "status": alert_dict["status"],
            "severity": severity
        }

        self._dispatch_to_listeners(ws_payload)
        return alert_dict

    def trigger_stolen_vehicle_alert(
        self,
        camera_id: str,
        frame: np.ndarray,
        plate_number: str,
        vehicle_type: str = "Vehicle",
        owner_name: str = "",
        notes: str = "",
        confidence: float = 0.95,
        optical_mode: str = "DAY_RGB"
    ) -> Optional[Dict[str, Any]]:
        """
        Triggers CRITICAL Red Alert when a vehicle on the Stolen / Intercept Watchlist
        is detected approaching the Border Check Post (BOP).
        """
        cooldown_key = f"{camera_id}_STOLEN_{plate_number}"
        if not self.cooldown_tracker.is_cooled_down(cooldown_key):
            return None

        self.cooldown_tracker.trigger(cooldown_key)
        snapshot_url = save_snapshot(frame, camera_id)
        integrity = get_evidence_integrity(snapshot_url)
        evidence_hash = integrity.get("sha256")
        details = f"🚨 INTERCEPT: Wanted Vehicle {plate_number} ({vehicle_type}) | Flag: {notes or 'Stolen/Smuggling Alert'}"

        db = SessionLocal()
        try:
            alert = Alert(
                event_type="SUSPECT_VEHICLE_INTERCEPT",
                camera_id=camera_id,
                timestamp=datetime.now(),
                face_count=1,
                confidence=confidence,
                objects_detected=details,
                snapshot_path=snapshot_url,
                evidence_hash=evidence_hash,
                optical_mode=optical_mode,
                status="NEW",
                severity="CRITICAL",
                created_at=datetime.now()
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)
            alert.alert_code = f"XP-{alert.id:06d}"
            db.commit()
            db.refresh(alert)
            self._write_audit_trail(db, alert)
            alert_dict = alert.to_dict()
        except Exception as e:
            db.rollback()
            print(f"[AlertEngine] DB error creating stolen vehicle alert: {e}")
            alert_dict = {
                "id": 0,
                "alert_id": "XP-STOLEN-VEHICLE",
                "event_type": "SUSPECT_VEHICLE_INTERCEPT",
                "camera_id": camera_id,
                "timestamp": datetime.utcnow().isoformat(),
                "face_count": 1,
                "confidence": confidence,
                "objects_detected": details,
                "snapshot": snapshot_url,
                "evidence_hash": evidence_hash,
                "optical_mode": optical_mode,
                "status": "NEW",
                "severity": "CRITICAL"
            }
        finally:
            db.close()

        ws_payload = {
            "type": "SUSPECT_VEHICLE_INTERCEPT",
            "alert_id": alert_dict["alert_id"],
            "camera_id": alert_dict["camera_id"],
            "event_type": "SUSPECT_VEHICLE_INTERCEPT",
            "timestamp": alert_dict["timestamp"],
            "face_count": 1,
            "objects_detected": details,
            "confidence": round(float(confidence), 2),
            "snapshot": alert_dict["snapshot"],
            "evidence_hash": alert_dict.get("evidence_hash"),
            "optical_mode": alert_dict.get("optical_mode", optical_mode),
            "status": alert_dict["status"],
            "severity": "CRITICAL",
            "plate_number": plate_number,
            "vehicle_type": vehicle_type
        }
        self._dispatch_to_listeners(ws_payload)
        return alert_dict

    def trigger_vehicle_alert(
        self,
        camera_id: str,
        frame: np.ndarray,
        vehicle_type: str = "Vehicle",
        plate_number: Optional[str] = None,
        confidence: float = 0.85,
        optical_mode: str = "DAY_RGB"
    ) -> Optional[Dict[str, Any]]:
        """
        Logs a standard vehicle transit at the Border Check Post.
        """
        cooldown_key = f"{camera_id}_VEHICLE_{plate_number or vehicle_type}"
        if not self.cooldown_tracker.is_cooled_down(cooldown_key):
            return None

        self.cooldown_tracker.trigger(cooldown_key)
        snapshot_url = save_snapshot(frame, camera_id)
        integrity = get_evidence_integrity(snapshot_url)
        evidence_hash = integrity.get("sha256")
        plate_str = f" [Plate: {plate_number}]" if plate_number else ""
        details = f"Border Checkpost Transit: {vehicle_type}{plate_str}"

        db = SessionLocal()
        try:
            alert = Alert(
                event_type="VEHICLE_DETECTED",
                camera_id=camera_id,
                timestamp=datetime.now(),
                face_count=1,
                confidence=confidence,
                objects_detected=details,
                snapshot_path=snapshot_url,
                evidence_hash=evidence_hash,
                optical_mode=optical_mode,
                status="NEW",
                severity="LOW",
                created_at=datetime.now()
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)
            alert.alert_code = f"XP-{alert.id:06d}"
            db.commit()
            db.refresh(alert)
            self._write_audit_trail(db, alert)
            alert_dict = alert.to_dict()
        except Exception as e:
            db.rollback()
            print(f"[AlertEngine] DB error creating vehicle transit alert: {e}")
            alert_dict = {
                "id": 0,
                "alert_id": "XP-VEHICLE",
                "event_type": "VEHICLE_DETECTED",
                "camera_id": camera_id,
                "timestamp": datetime.utcnow().isoformat(),
                "face_count": 1,
                "confidence": confidence,
                "objects_detected": details,
                "snapshot": snapshot_url,
                "evidence_hash": evidence_hash,
                "optical_mode": optical_mode,
                "status": "NEW",
                "severity": "LOW"
            }
        finally:
            db.close()

        ws_payload = {
            "type": "VEHICLE_DETECTED",
            "alert_id": alert_dict["alert_id"],
            "camera_id": alert_dict["camera_id"],
            "event_type": "VEHICLE_DETECTED",
            "timestamp": alert_dict["timestamp"],
            "face_count": 1,
            "objects_detected": details,
            "confidence": round(float(confidence), 2),
            "snapshot": alert_dict["snapshot"],
            "evidence_hash": alert_dict.get("evidence_hash"),
            "optical_mode": alert_dict.get("optical_mode", optical_mode),
            "status": alert_dict["status"],
            "severity": "LOW",
            "plate_number": plate_number,
            "vehicle_type": vehicle_type
        }
        self._dispatch_to_listeners(ws_payload)
        return alert_dict


