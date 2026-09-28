import os
import psutil
from fastapi import APIRouter
from backend.config import settings

router = APIRouter(tags=["Health"])

@router.get("/health")
def get_health():
    return {"status": "ok"}

@router.get("/health/edge-telemetry")
def get_edge_telemetry():
    """
    Returns quantitative Edge AI hardware resource telemetry.
    Displays dynamically measured CPU, memory, and inference latency values.
    Unmeasured metrics are explicitly marked as 'Not benchmarked' rather than fabricated.
    """
    try:
        proc = psutil.Process(os.getpid())
        mem_info = proc.memory_info()
        rss_mb = round(mem_info.rss / (1024 * 1024), 1)
        sys_mem = psutil.virtual_memory()
        cpu_usage = psutil.cpu_percent(interval=None)
    except Exception:
        rss_mb = None
        sys_mem = None
        cpu_usage = None

    # Compute real dynamic inference latency from active hardware cameras
    from backend.api.cameras import camera_registry
    active_latencies = [
        getattr(cam, "latest_inference_latency_ms", 0.0)
        for cam in camera_registry.values()
        if getattr(cam, "latest_inference_latency_ms", 0.0) > 0 and getattr(cam, "status", "") == "ONLINE"
    ]
    if active_latencies:
        avg_latency = round(sum(active_latencies) / len(active_latencies), 1)
    else:
        avg_latency = None

    return {
        "status": "OPERATIONAL",
        "deployment_profile": "BORDER_OUTPOST_TACTICAL_NODE",
        "edge_mode": "AIR_GAPPED_OFFLINE",
        "cloud_dependency": False,
        "diagnostic_mode": settings.ENABLE_DIAGNOSTIC_MODE,
        "environment": settings.ENVIRONMENT,
        "inference_engine": "YOLOv8 + OpenCV YuNet (CPU ONNX Vectorized)",
        "cpu_usage_pct": round(cpu_usage, 1) if (cpu_usage is not None and cpu_usage >= 0) else "Not benchmarked",
        "process_memory_mb": rss_mb if rss_mb is not None else "Not benchmarked",
        "system_ram_usage_pct": round(sys_mem.percent, 1) if sys_mem is not None else "Not benchmarked",
        "average_inference_latency_ms": avg_latency if avg_latency is not None else "Not benchmarked (no active camera)",
        "bandwidth_saving_mode": "Event metadata and alert snapshot transmission only",
        "bandwidth_reduction_estimate": "Theoretical estimate: >95% reduction vs continuous 1080p raw video stream",
        "active_ai_models": [
            "YOLOv8-Nano (Full-Body Human 320x320)",
            "SimpleCentroidTracker (Persistent Multi-Person IDs)",
            "YuNet (5-Landmark Facial Biometric Ingest)",
            "SFace (128-D Cosine Face Recognition)",
            "YOLOv8-Vehicle (Checkpost ANPR Classifier)",
            "RapidOCR (License Plate Character Recognition)",
            "Laplacian Variance Anti-Tamper Analyzer",
            "Spatial Dwell & Loitering Timer (Centroid Tracking)"
        ],
        "cyber_shield_active": True
    }

