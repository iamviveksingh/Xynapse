"""
P1-1 & P1-6 Empirical Pipeline Benchmark Script.
Measures 11 individual pipeline stages and multi-camera concurrency (1, 2, 3, 4 cameras).
"""

import sys
import os
import time
import json
import threading
import queue
import psutil
import numpy as np
import cv2

# Ensure path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.detection.person_detector import PersonDetector
from backend.detection.intrusion_detector import VirtualTripwireDetector
from backend.detection.optical_pipeline import OpticalPipeline
from backend.detection.face_detector import FaceDetector
from backend.detection.vehicle_detector import VehicleDetector
from backend.detection.anpr_engine import ANPREngine
from backend.alert.alert_engine import AlertEngine
from backend.evidence.snapshot import save_snapshot, get_evidence_integrity
from backend.database.database import SessionLocal, init_db
from backend.database.models import Alert, SyncOutbox

def generate_surveillance_frame(width=640, height=480, frame_idx=0):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    # Background terrain gradient
    frame[:, :] = (30, 42, 35)
    
    # Person 1 (walking)
    px = int(width * 0.3) + int(40 * np.sin(frame_idx * 0.1))
    py = int(height * 0.35)
    cv2.circle(frame, (px + 20, py + 20), 18, (180, 160, 140), -1)
    cv2.rectangle(frame, (px, py + 38), (px + 40, py + 140), (80, 80, 160), -1)
    
    # Vehicle (in distance)
    vx, vy = int(width * 0.6), int(height * 0.5)
    cv2.rectangle(frame, (vx, vy), (vx + 140, vy + 80), (120, 50, 30), -1)
    cv2.rectangle(frame, (vx + 30, vy + 45), (vx + 110, vy + 68), (255, 255, 255), -1)
    cv2.putText(frame, "ARMY9090", (vx + 34, vy + 62), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    
    return frame

def benchmark_single_stages(num_iterations=30):
    print("=" * 70)
    print("BENCHMARKING 11 INDIVIDUAL PIPELINE STAGES (Single Threaded)")
    print("=" * 70)
    
    init_db()
    person_det = PersonDetector(min_confidence=0.40)
    person_det.initialize()
    
    tripwire = VirtualTripwireDetector(line_y_ratio=0.65, enabled=True)
    tripwire.set_polygon([[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]])
    
    optical = OpticalPipeline()
    face_det = FaceDetector()
    face_det.initialize()
    veh_det = VehicleDetector()
    anpr = ANPREngine()
    alert_engine = AlertEngine(cooldown_seconds=1)
    
    times = {k: [] for k in [
        "acquisition", "yolo_human", "tracking", "geofence",
        "low_light", "face_detection", "anpr_ocr", "alert_generation",
        "evidence_packaging", "db_persistence", "end_to_end_alert"
    ]}
    
    frame = generate_surveillance_frame(640, 480, 0)
    
    for i in range(num_iterations):
        # 1. Frame acquisition
        t0 = time.perf_counter()
        f = generate_surveillance_frame(640, 480, i)
        times["acquisition"].append((time.perf_counter() - t0) * 1000)
        
        # 2. YOLO Human Detection
        t0 = time.perf_counter()
        dets = person_det.detect(f)
        times["yolo_human"].append((time.perf_counter() - t0) * 1000)
        
        # 3. Tracking update
        t0 = time.perf_counter()
        person_det.tracker.update(dets)
        times["tracking"].append((time.perf_counter() - t0) * 1000)
        
        # 4. Geofence / Polygon intrusion
        t0 = time.perf_counter()
        breached, b_dets, _ = tripwire.check_intrusion(f.shape, dets)
        times["geofence"].append((time.perf_counter() - t0) * 1000)
        
        # 5. Low-light processing
        t0 = time.perf_counter()
        is_dark, lum, mode = optical.low_light_detector.update(f)
        proc_f = optical.process_frame(f, mode)
        times["low_light"].append((time.perf_counter() - t0) * 1000)
        
        # 6. Face Detection
        t0 = time.perf_counter()
        faces = face_det.detect(f)
        times["face_detection"].append((time.perf_counter() - t0) * 1000)
        
        # 7. ANPR (crop + OCR)
        veh_crop = f[int(480*0.5):int(480*0.5)+80, int(640*0.6):int(640*0.6)+140].copy()
        t0 = time.perf_counter()
        _ = anpr.extract_plate_from_crop(veh_crop)
        times["anpr_ocr"].append((time.perf_counter() - t0) * 1000)
        
        # 8. Alert Generation
        t0 = time.perf_counter()
        alert_obj = alert_engine.trigger_intrusion_alert(
            camera_id="BENCH-CAM-01",
            frame=f,
            breached_count=1,
            details="Benchmark intrusion"
        )
        times["alert_generation"].append((time.perf_counter() - t0) * 1000)
        
        # 9. Evidence Packaging (Snapshot saving + SHA-256 integrity calculation)
        t0 = time.perf_counter()
        snap_url = save_snapshot(f, "BENCH-CAM-01")
        integrity = get_evidence_integrity(snap_url)
        ev_hash = integrity.get("sha256", "0000")
        times["evidence_packaging"].append((time.perf_counter() - t0) * 1000)
        
        # 10. Database Persistence (Alert + SyncOutbox write + commit)
        t0 = time.perf_counter()
        db = SessionLocal()
        try:
            alert_rec = Alert(
                alert_code=f"XP-BENCH-DB-{i}",
                camera_id="BENCH-CAM-01",
                event_type="BORDER_INTRUSION",
                severity="HIGH",
                status="NEW",
                evidence_hash=ev_hash
            )
            db.add(alert_rec)
            outbox_rec = SyncOutbox(
                event_id=f"XP-BENCH-DB-{i}",
                alert_id=9999 + i,
                camera_id="BENCH-CAM-01",
                event_type="BORDER_INTRUSION",
                severity="HIGH",
                payload_json=json.dumps({"test": True, "evidence_hash": ev_hash}),
                status="PENDING"
            )
            db.add(outbox_rec)
            db.commit()
        finally:
            db.close()
        times["db_persistence"].append((time.perf_counter() - t0) * 1000)
        
        # 11. End-to-end alert latency (Detection -> Alert -> Package -> DB Outbox)
        t0 = time.perf_counter()
        d_e2e = person_det.detect(f)
        b_e2e, _, _ = tripwire.check_intrusion(f.shape, d_e2e)
        al = alert_engine.trigger_intrusion_alert("BENCH-CAM-01", f, 1, "E2E latency test")
        snap_e2e = save_snapshot(f, "BENCH-CAM-01")
        integ_e2e = get_evidence_integrity(snap_e2e)
        db = SessionLocal()
        try:
            o_rec = SyncOutbox(
                event_id=f"XP-E2E-{i}",
                alert_id=8888 + i,
                camera_id="BENCH-CAM-01",
                event_type="BORDER_INTRUSION",
                severity="CRITICAL",
                payload_json=json.dumps(integ_e2e),
                status="PENDING"
            )
            db.add(o_rec)
            db.commit()
        finally:
            db.close()
        times["end_to_end_alert"].append((time.perf_counter() - t0) * 1000)
    
    stage_summary = {}
    print(f"{'Pipeline Stage':<28} | {'Avg (ms)':<10} | {'Median (ms)':<12} | {'p95 (ms)':<10}")
    print("-" * 68)
    for stage, vals in times.items():
        avg_v = float(np.mean(vals))
        med_v = float(np.median(vals))
        p95_v = float(np.percentile(vals, 95))
        stage_summary[stage] = {"avg_ms": round(avg_v, 2), "median_ms": round(med_v, 2), "p95_ms": round(p95_v, 2)}
        print(f"{stage:<28} | {avg_v:<10.2f} | {med_v:<12.2f} | {p95_v:<10.2f}")
    
    return stage_summary

class SimulatedCameraWorker:
    def __init__(self, cam_id, res=(640, 480)):
        self.cam_id = cam_id
        self.width, self.height = res
        self.person_det = PersonDetector(min_confidence=0.40)
        self.person_det.initialize()
        self.tripwire = VirtualTripwireDetector(line_y_ratio=0.65, enabled=True)
        self.tripwire.set_polygon([[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]])
        self.optical = OpticalPipeline()
        self.anpr_engine = ANPREngine()
        self.alert_engine = AlertEngine(cooldown_seconds=1)
        
        self.is_running = False
        self.frames_processed = 0
        self.ai_frames = 0
        self.dropped_frames = 0
        self.yolo_latencies = []
        self.anpr_latencies = []
        self.e2e_latencies = []
        self.thread = None
        self.anpr_queue = queue.Queue(maxsize=2)
        self.anpr_queue_drops = 0
        self.active_tracks = 0
        
    def start(self):
        self.is_running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        
    def stop(self):
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=3.0)
            
    def _run(self):
        idx = 0
        while self.is_running:
            t0 = time.perf_counter()
            frame = generate_surveillance_frame(self.width, self.height, idx)
            idx += 1
            self.frames_processed += 1
            
            # Optical check
            _, _, mode = self.optical.low_light_detector.update(frame)
            disp_frame = self.optical.process_frame(frame, mode)
            
            # AI Inference
            t_yolo_start = time.perf_counter()
            dets = self.person_det.detect(disp_frame)
            t_yolo_end = time.perf_counter()
            self.yolo_latencies.append((t_yolo_end - t_yolo_start) * 1000)
            self.ai_frames += 1
            self.active_tracks = len(dets)
            
            # Geofence check
            breached, b_dets, _ = self.tripwire.check_intrusion(disp_frame.shape, dets)
            
            # Occasional ANPR job
            if idx % 10 == 0:
                crop = frame[100:180, 200:340].copy()
                try:
                    self.anpr_queue.put_nowait(crop)
                except queue.Full:
                    self.anpr_queue_drops += 1
            
            # Drain one ANPR job if present
            if not self.anpr_queue.empty():
                try:
                    job = self.anpr_queue.get_nowait()
                    t_anpr_0 = time.perf_counter()
                    _ = self.anpr_engine.extract_plate_from_crop(job)
                    self.anpr_latencies.append((time.perf_counter() - t_anpr_0) * 1000)
                except queue.Empty:
                    pass
                
            e2e = (time.perf_counter() - t0) * 1000
            self.e2e_latencies.append(e2e)
            time.sleep(0.001)

def benchmark_concurrent_cameras(num_cameras=1, duration_sec=8, resolution=(640, 480)):
    print(f"\n--- BENCHMARKING {num_cameras} CONCURRENT CAMERA(S) FOR {duration_sec}s ({resolution[0]}x{resolution[1]}) ---")
    
    process = psutil.Process()
    cpu_measurements = []
    ram_measurements = []
    
    workers = [SimulatedCameraWorker(f"CAM-0{i+1}", res=resolution) for i in range(num_cameras)]
    
    t_start = time.time()
    for w in workers:
        w.start()
        
    while time.time() - t_start < duration_sec:
        cpu_measurements.append(psutil.cpu_percent(interval=0.5))
        ram_measurements.append(process.memory_info().rss / (1024 * 1024))
        
    for w in workers:
        w.stop()
    actual_duration = time.time() - t_start
    
    total_frames = sum(w.frames_processed for w in workers)
    avg_fps_per_cam = total_frames / (actual_duration * num_cameras)
    total_ai_frames = sum(w.ai_frames for w in workers)
    avg_ai_fps_per_cam = total_ai_frames / (actual_duration * num_cameras)
    
    all_yolo = [lat for w in workers for lat in w.yolo_latencies]
    all_anpr = [lat for w in workers for lat in w.anpr_latencies]
    all_e2e = [lat for w in workers for lat in w.e2e_latencies]
    total_queue_drops = sum(w.anpr_queue_drops for w in workers)
    
    avg_cpu = float(np.mean(cpu_measurements)) if cpu_measurements else 0.0
    max_cpu = float(np.max(cpu_measurements)) if cpu_measurements else 0.0
    avg_ram = float(np.mean(ram_measurements)) if ram_measurements else 0.0
    max_ram = float(np.max(ram_measurements)) if ram_measurements else 0.0
    
    results = {
        "num_cameras": num_cameras,
        "input_resolution": f"{resolution[0]}x{resolution[1]}",
        "duration_sec": round(actual_duration, 1),
        "effective_fps_per_cam": round(avg_fps_per_cam, 1),
        "ai_fps_per_cam": round(avg_ai_fps_per_cam, 1),
        "total_aggregate_fps": round(total_frames / actual_duration, 1),
        "yolo_latency_ms": {
            "avg": round(float(np.mean(all_yolo)), 1) if all_yolo else 0,
            "p95": round(float(np.percentile(all_yolo, 95)), 1) if all_yolo else 0
        },
        "anpr_latency_ms": {
            "avg": round(float(np.mean(all_anpr)), 1) if all_anpr else 0,
            "p95": round(float(np.percentile(all_anpr, 95)), 1) if all_anpr else 0
        },
        "end_to_end_frame_latency_ms": {
            "avg": round(float(np.mean(all_e2e)), 1) if all_e2e else 0,
            "p95": round(float(np.percentile(all_e2e, 95)), 1) if all_e2e else 0
        },
        "cpu_percent": {"avg": round(avg_cpu, 1), "max": round(max_cpu, 1)},
        "ram_mb": {"avg": round(avg_ram, 1), "max": round(max_ram, 1)},
        "dropped_frames": sum(w.dropped_frames for w in workers),
        "anpr_queue_drops": total_queue_drops,
        "reconnect_count": 0,
        "active_tracks_per_cam": round(np.mean([w.active_tracks for w in workers]), 1)
    }
    
    print(f"Results for {num_cameras} Camera(s):")
    print(f"  Effective FPS/cam: {results['effective_fps_per_cam']} FPS (Aggregate: {results['total_aggregate_fps']} FPS)")
    print(f"  YOLO Latency: {results['yolo_latency_ms']['avg']} ms (p95: {results['yolo_latency_ms']['p95']} ms)")
    print(f"  ANPR Latency: {results['anpr_latency_ms']['avg']} ms")
    print(f"  E2E Frame Latency: {results['end_to_end_frame_latency_ms']['avg']} ms")
    print(f"  System CPU: {results['cpu_percent']['avg']}% (Peak: {results['cpu_percent']['max']}%)")
    print(f"  Process RAM: {results['ram_mb']['avg']} MB")
    print(f"  ANPR Queue Drops: {results['anpr_queue_drops']}")
    
    return results

if __name__ == "__main__":
    stage_results = benchmark_single_stages(num_iterations=20)
    
    multi_cam_results = {}
    for c in [1, 2, 3, 4]:
        multi_cam_results[f"{c}_cam"] = benchmark_concurrent_cameras(num_cameras=c, duration_sec=6, resolution=(640, 480))
        
    out = {
        "single_stages": stage_results,
        "multi_cam": multi_cam_results
    }
    with open("tests/p1_pipeline_benchmark_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\nBenchmark results written to tests/p1_pipeline_benchmark_results.json")
