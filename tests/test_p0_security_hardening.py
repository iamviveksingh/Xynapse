import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings

@pytest.fixture
def client():
    return TestClient(app, headers={"X-API-Key": settings.ADMIN_API_KEY})

def test_production_mode_blocks_demo_trigger(client):
    """
    P0-1 & P0-7 requirement:
    Verify that in default production mode (ENABLE_DIAGNOSTIC_MODE=False),
    calling the demo trigger endpoint is strictly forbidden (HTTP 403).
    """
    # Ensure diagnostic mode is False
    settings.ENABLE_DIAGNOSTIC_MODE = False

    payload = {
        "trigger_type": "BORDER_BREACH",
        "camera_id": "CAM-01"
    }
    resp = client.post("/api/alerts/demo-trigger", json=payload)
    assert resp.status_code == 403
    assert "disabled in production mode" in resp.json()["detail"]

def test_production_mode_blocks_vehicle_seed(client):
    """
    P0-1 requirement:
    Verify that seeding mock/fake vehicle data is strictly blocked in production.
    """
    settings.ENABLE_DIAGNOSTIC_MODE = False
    resp = client.post("/api/vehicles/seed-defaults")
    assert resp.status_code == 403
    assert "disabled in production mode" in resp.json()["detail"]

def test_invalid_rtsp_ssrf_rejection(client):
    """
    P0-5 requirement:
    Verify SSRF and protocol protection on camera source configuration.
    """
    # 1. Reject cloud metadata IP SSRF
    resp1 = client.post("/api/cameras", json={
        "camera_id": "CAM-SSRF-1",
        "name": "SSRF Probe",
        "source": "rtsp://169.254.169.254:554/live"
    })
    assert resp1.status_code == 400
    assert "SSRF protection" in resp1.json()["detail"]

    # 2. Reject file:// scheme
    resp2 = client.post("/api/cameras", json={
        "camera_id": "CAM-SSRF-2",
        "name": "File Scheme Probe",
        "source": "file:///etc/passwd"
    })
    assert resp2.status_code == 400
    assert "Unsupported camera protocol" in resp2.json()["detail"]

    # 3. Reject http:// intranet probe
    resp3 = client.post("/api/cameras", json={
        "camera_id": "CAM-SSRF-3",
        "name": "HTTP Probe",
        "source": "http://192.168.1.1/admin"
    })
    assert resp3.status_code == 400

    # 4. Reject 0.0.0.0 broadcast
    resp4 = client.post("/api/cameras", json={
        "camera_id": "CAM-SSRF-4",
        "name": "Zero Broadcast Probe",
        "source": "rtsp://0.0.0.0:554/feed"
    })
    assert resp4.status_code == 400

def test_internal_worker_secret_auth(client):
    """
    P0-5 requirement:
    Verify that an unauthorized worker secret is rejected with 401 Unauthorized.
    """
    payload = {
        "event_id": "XP-SEC-TEST",
        "camera_id": "CAM-01",
        "event_type": "BORDER_INTRUSION"
    }
    # 1. Missing secret header
    resp_missing = client.post("/api/hq/ingest", json=payload)
    assert resp_missing.status_code == 401
    assert "Unauthorized internal worker secret" in resp_missing.json()["detail"]

    # 2. Empty secret header
    resp_empty = client.post("/api/hq/ingest", json=payload, headers={"X-Worker-Secret": ""})
    assert resp_empty.status_code == 401
    assert "Unauthorized internal worker secret" in resp_empty.json()["detail"]

    resp_whitespace = client.post("/api/hq/ingest", json=payload, headers={"X-Worker-Secret": "   "})
    assert resp_whitespace.status_code == 401

    # 3. Bad/incorrect secret
    resp_bad = client.post(
        "/api/hq/ingest",
        json=payload,
        headers={"X-Worker-Secret": "invalid-malicious-token"}
    )
    assert resp_bad.status_code == 401
    assert "Unauthorized internal worker secret" in resp_bad.json()["detail"]

    # 4. Valid secret
    resp_good = client.post(
        "/api/hq/ingest",
        json=payload,
        headers={"X-Worker-Secret": settings.INTERNAL_WORKER_SECRET}
    )
    assert resp_good.status_code == 200
    assert resp_good.json()["status"] == "accepted"

def test_dossier_and_chain_bsa_2023_statute(client):
    """
    P0-3 requirement:
    Verify that the legal certification references Section 63 BSA 2023
    and does NOT claim guaranteed court admissibility or Section 65B.
    """
    # 1. Fetch dossier for latest alert
    resp = client.get("/api/alerts?limit=1")
    items = resp.json().get("items", [])
    if items:
        aid = items[0]["id"]
        dossier_res = client.get(f"/api/alerts/{aid}/dossier")
        assert dossier_res.status_code == 200
        dossier = dossier_res.json()
        legal = dossier["legal_certification"]
        assert "Section 63, Bharatiya Sakshya Adhiniyam (BSA), 2023" in legal["act"]
        assert "65B" not in legal["act"]
        assert "cryptographically integrity-protected electronic evidence package" in legal["statement"].lower()
        assert "section 63 of the bharatiya sakshya adhiniyam, 2023" in legal["statement"].lower()
        assert dossier["signoff"]["verification_status"] == "INTEGRITY_VERIFIED"

    # 2. Cryptographic Audit Chain verification
    verify_res = client.post("/api/blockchain/verify")
    assert verify_res.status_code == 200
    chain_ver = verify_res.json()
    assert "Section 63, Bharatiya Sakshya Adhiniyam (BSA), 2023" in chain_ver["legal_statute"]
    assert "65B" not in chain_ver["legal_statute"]
    assert chain_ver["verification_status"] == "VERIFIED_AUTHENTIC"
    assert chain_ver["tamper_detected"] is False

def test_health_edge_telemetry_no_fabricated_numbers(client):
    """
    P0-4 requirement:
    Verify that health edge telemetry does NOT return hardcoded 99.4% or fabricated fallbacks.
    """
    res = client.get("/api/health/edge-telemetry")
    assert res.status_code == 200
    data = res.json()
    assert "bandwidth_saved_vs_raw_video_pct" not in data
    assert "bandwidth_reduction_estimate" in data
    assert "Theoretical estimate" in data["bandwidth_reduction_estimate"]
    assert "diagnostic_mode" in data
    assert data["diagnostic_mode"] is False
