"""
Real-time Manual Runtime Verification Script.
Runs CameraManager with ONE active camera (CAM-01) for 15 seconds.
Measures real FPS, latency, queue depths, CPU, RAM, and monitors for any unexpected alerts.
"""

import sys
import os
import time
import psutil

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from backend.camera.camera_manager import CameraManager
from backend.alert.alert_engine import AlertEngine
from backend.detection.face_recognizer import FaceRecognizer
from backend.database.database import SessionLocal
from backend.database.models import Alert

def main():
    print("=" * 80)
    print("XYNAPSE ONE-CAMERA LIVE RUNTIME VERIFICATION")
    print("=" * 80)
    
    # Check baseline alert count
    db = SessionLocal()
    initial_alert_count = db.query(Alert).count()
    db.close()
    
    engine = AlertEngine(cooldown_seconds=5)
    frs = FaceRecognizer()
    
    cam = CameraManager(
        camera_id="CAM-01",
        name="Sector-01 Thermal & Visual Perimeter",
        source="0",
        alert_engine=engine,
        face_recognizer=frs
    )
    cam.set_surveillance_mode("PERIMETER")
    
    proc = psutil.Process(os.getpid())
    
    print("\nStarting CAM-01 (PERIMETER Mode)...")
    cam.start()
    
    # Run for 15 seconds, sampling every 2 seconds
    samples = []
    t_start = time.time()
    
    try:
        while time.time() - t_start < 15.0:
            time.sleep(2.0)
            elapsed = time.time() - t_start
            
            status = cam.get_status_dict()
            fps = status.get("fps", 0.0)
            humans = status.get("human_count", 0)
            vehs = status.get("vehicle_count", 0)
            has_susp = status.get("has_suspect_vehicle", False)
            q_size = cam._anpr_queue.qsize()
            
            cpu_pct = proc.cpu_percent(interval=None)
            ram_mb = proc.memory_info().rss / (1024 * 1024)
            
            samples.append({
                "elapsed": round(elapsed, 1),
                "fps": fps,
                "humans": humans,
                "vehicles": vehs,
                "susp_veh": has_susp,
                "q_depth": q_size,
                "cpu": cpu_pct,
                "ram": round(ram_mb, 1)
            })
            
            print(f"[{elapsed:4.1f}s] FPS: {fps:4.1f} | Humans: {humans} | Vehicles: {vehs} | SuspVeh: {has_susp} | ANPR Queue: {q_size} | CPU: {cpu_pct:4.1f}% | RAM: {ram_mb:5.1f}MB")
            
    finally:
        print("\nStopping CAM-01...")
        cam.stop()

    # Check ending alert count
    db = SessionLocal()
    final_alert_count = db.query(Alert).count()
    new_alerts = db.query(Alert).filter(Alert.id > initial_alert_count).all()
    db.close()

    print("\n" + "=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)
    avg_fps = sum(s["fps"] for s in samples) / len(samples) if samples else 0.0
    avg_cpu = sum(s["cpu"] for s in samples) / len(samples) if samples else 0.0
    max_q = max(s["q_depth"] for s in samples) if samples else 0
    final_ram = samples[-1]["ram"] if samples else 0.0

    print(f"Average FPS:          {avg_fps:.1f}")
    print(f"ANPR Max Queue Depth: {max_q}")
    print(f"Average CPU%:         {avg_cpu:.1f}%")
    print(f"Memory Footprint:     {final_ram:.1f} MB")
    print(f"Alerts Generated:     {final_alert_count - initial_alert_count}")
    if new_alerts:
        print("New Alerts:")
        for a in new_alerts:
            print(f"  - {a.alert_code}: {a.event_type} ({a.objects_detected})")
    else:
        print("  - Zero false/fabricated alerts produced!")
    print("=" * 80)

if __name__ == "__main__":
    main()
