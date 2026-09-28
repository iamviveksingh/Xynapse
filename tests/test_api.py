import os
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.main import app
from backend.config import settings
from backend.database.database import init_db
from backend.api.cameras import camera_registry

@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app, headers={"X-API-Key": settings.ADMIN_API_KEY}) as c:
        yield c
    for cam in camera_registry.values():
        cam.stop()

def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_list_cameras(client):
    response = client.get("/api/cameras")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["camera_id"] == "CAM-01"

def test_alerts_lifecycle(client):
    # 1. Fetch stats
    stats_res = client.get("/api/alerts/stats")
    assert stats_res.status_code == 200
    stats = stats_res.json()
    assert "total_alerts" in stats
    assert "active_alerts" in stats

    # 2. Fetch alerts list
    list_res = client.get("/api/alerts")
    assert list_res.status_code == 200
    data = list_res.json()
    assert "items" in data
    assert "total" in data

    if data["total"] > 0:
        first_alert = data["items"][0]
        alert_id = first_alert["id"]

        # Acknowledge
        ack_res = client.post(f"/api/alerts/{alert_id}/acknowledge")
        assert ack_res.status_code == 200
        assert ack_res.json()["status"] == "ACKNOWLEDGED"

        # Resolve
        res_res = client.post(f"/api/alerts/{alert_id}/resolve")
        assert res_res.status_code == 200
        assert res_res.json()["status"] == "RESOLVED"

def test_forensic_dossier_and_csv_export(client):
    # 1. Test CSV export with SHA-256 header and compliance
    csv_res = client.get("/api/alerts/export/csv")
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers.get("content-type", "")
    assert "SHA-256" in csv_res.text

    # 2. Test Dossier endpoint
    list_res = client.get("/api/alerts?limit=1")
    assert list_res.status_code == 200
    items = list_res.json().get("items", [])
    if items:
        aid = items[0]["id"]
        dos_res = client.get(f"/api/alerts/{aid}/dossier")
        assert dos_res.status_code == 200
        dossier = dos_res.json()
        assert "dossier_id" in dossier
        assert "incident" in dossier
        assert "sector" in dossier
        assert "evidence" in dossier
        assert "sha256" in dossier["evidence"]
        assert len(dossier["evidence"]["sha256"]) == 64
        assert "legal_certification" in dossier
        assert "audit_trail" in dossier

