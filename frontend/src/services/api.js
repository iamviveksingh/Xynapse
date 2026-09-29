const API_BASE = '/api';

export class ApiError extends Error {
  constructor(message, status = 500, detail = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.isAuthError = status === 401;
    this.isForbidden = status === 403;
  }
}

export function getApiKey() {
  const key = localStorage.getItem('xynapse_api_key');
  if (key && key !== '__LOGGED_OUT__' && key.trim() !== '') {
    return key.trim();
  }
  return 'xynapse-admin-sih-2026';
}

export function setApiKey(key) {
  if (key && key.trim()) {
    localStorage.setItem('xynapse_api_key', key.trim());
  } else {
    localStorage.setItem('xynapse_api_key', '__LOGGED_OUT__');
  }
}

export function clearApiKey() {
  localStorage.setItem('xynapse_api_key', '__LOGGED_OUT__');
}

export function logout() {
  localStorage.setItem('xynapse_api_key', '__LOGGED_OUT__');
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('xynapse:auth_change', { detail: { key: null, role: null } }));
  }
}

export function login(key) {
  setApiKey(key);
  const role = getAuthenticatedRole();
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('xynapse:auth_change', { detail: { key, role } }));
  }
}

export function getAuthenticatedRole() {
  const key = getApiKey();
  if (!key) return null;
  if (key === 'xynapse-admin-sih-2026' || key.toLowerCase().includes('admin')) return 'ADMIN';
  if (key === 'xynapse-operator-sih-2026' || key.toLowerCase().includes('operator')) return 'OPERATOR';
  return 'CUSTOM';
}

export function getAuthenticatedMediaUrl(url) {
  if (!url) return url;
  const key = getApiKey();
  if (!key) return url;
  if (url.includes('api_key=')) return url;
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}api_key=${encodeURIComponent(key)}`;
}

export async function authFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const key = getApiKey();
  if (key && !headers.has('X-API-Key') && !headers.has('Authorization')) {
    headers.set('X-API-Key', key);
  }
  try {
    return await fetch(url, { ...options, headers });
  } catch (err) {
    const method = (options.method || 'GET').toUpperCase();
    if (method === 'GET') {
      // Retry once after brief 150ms delay for transient socket resets
      await new Promise((r) => setTimeout(r, 150));
      return await fetch(url, { ...options, headers });
    }
    throw err;
  }
}

export async function handleApiResponse(res, defaultErrorMsg = 'Request failed') {
  if (res.ok) {
    return res.json();
  }
  let detail = null;
  try {
    const data = await res.json();
    detail = data?.detail || null;
  } catch {
    // Non-JSON response body
  }

  let message = detail;
  if (!message) {
    if (res.status === 401) {
      message = 'Authentication required. Please authenticate with valid credentials.';
    } else if (res.status === 403) {
      message = 'Access denied: Administrative privileges required for this action.';
    } else {
      message = `${defaultErrorMsg} (HTTP ${res.status})`;
    }
  }

  throw new ApiError(message, res.status, detail);
}

export async function fetchCameras() {
  const res = await authFetch(`${API_BASE}/cameras`);
  return handleApiResponse(res, 'Failed to fetch cameras');
}

export async function startCamera(cameraId) {
  const res = await authFetch(`${API_BASE}/cameras/${cameraId}/start`, { method: 'POST' });
  return handleApiResponse(res, 'Failed to start camera');
}

export async function stopCamera(cameraId) {
  const res = await authFetch(`${API_BASE}/cameras/${cameraId}/stop`, { method: 'POST' });
  return handleApiResponse(res, 'Failed to stop camera');
}

export async function fetchAlerts(status = 'ALL', limit = 50, offset = 0) {
  const url = new URL(`${API_BASE}/alerts`, window.location.origin);
  if (status && status !== 'ALL') url.searchParams.append('status', status);
  url.searchParams.append('limit', limit);
  url.searchParams.append('offset', offset);

  const res = await authFetch(url.toString());
  return handleApiResponse(res, 'Failed to fetch alerts');
}

export async function fetchAlertStats() {
  const res = await authFetch(`${API_BASE}/alerts/stats`);
  return handleApiResponse(res, 'Failed to fetch alert stats');
}

export async function fetchAlertDetail(alertId) {
  const res = await authFetch(`${API_BASE}/alerts/${alertId}`);
  return handleApiResponse(res, 'Failed to fetch alert detail');
}

export async function fetchAlertDossier(alertId) {
  const res = await authFetch(`${API_BASE}/alerts/${alertId}/dossier`);
  return handleApiResponse(res, 'Failed to fetch forensic incident dossier');
}

export async function acknowledgeAlert(alertId, reviewData = null) {
  const options = { method: 'POST' };
  if (reviewData) {
    options.headers = { 'Content-Type': 'application/json' };
    options.body = JSON.stringify(reviewData);
  }
  const res = await authFetch(`${API_BASE}/alerts/${alertId}/acknowledge`, options);
  return handleApiResponse(res, 'Failed to acknowledge alert');
}

export async function resolveAlert(alertId, reviewData = null) {
  const options = { method: 'POST' };
  if (reviewData) {
    options.headers = { 'Content-Type': 'application/json' };
    options.body = JSON.stringify(reviewData);
  }
  const res = await authFetch(`${API_BASE}/alerts/${alertId}/resolve`, options);
  return handleApiResponse(res, 'Failed to resolve alert');
}

export async function fetchStationConfig() {
  const res = await authFetch(`${API_BASE}/alerts/station-config`);
  return handleApiResponse(res, 'Failed to fetch station configuration');
}

export async function updateStationConfig(configData) {
  const res = await authFetch(`${API_BASE}/alerts/station-config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(configData)
  });
  return handleApiResponse(res, 'Failed to update station configuration');
}

export async function checkHealth() {
  const res = await authFetch(`${API_BASE}/health`);
  return res.ok;
}

// Face Roster & Watchlist APIs
export async function fetchFaces(role = null) {
  const url = new URL(`${API_BASE}/faces`, window.location.origin);
  if (role && role !== 'ALL') url.searchParams.append('role', role);
  const res = await authFetch(url.toString());
  return handleApiResponse(res, 'Failed to fetch face roster');
}

export async function fetchFaceStats() {
  const res = await authFetch(`${API_BASE}/faces/stats`);
  return handleApiResponse(res, 'Failed to fetch face stats');
}

export async function enrollFace(formData) {
  const res = await authFetch(`${API_BASE}/faces/enroll`, {
    method: 'POST',
    body: formData
  });
  return handleApiResponse(res, 'Failed to enroll face');
}

export async function enrollFaceFromCamera({ name, role, notes = '', cameraId = 'CAM-01' }) {
  const body = new FormData();
  body.append('name', name);
  body.append('role', role);
  body.append('notes', notes);
  body.append('camera_id', cameraId);

  const res = await authFetch(`${API_BASE}/faces/enroll-from-camera`, {
    method: 'POST',
    body
  });
  return handleApiResponse(res, 'Failed to enroll face from camera');
}

export async function deleteFace(faceId) {
  const res = await authFetch(`${API_BASE}/faces/${faceId}`, {
    method: 'DELETE'
  });
  return handleApiResponse(res, 'Failed to delete face profile');
}

export async function toggleTripwire(cameraId) {
  const res = await authFetch(`${API_BASE}/cameras/${cameraId}/tripwire/toggle`, { method: 'POST' });
  return handleApiResponse(res, 'Failed to toggle border tripwire');
}

export async function configTripwire(cameraId, { enabled, y_ratio }) {
  const res = await authFetch(`${API_BASE}/cameras/${cameraId}/tripwire/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled, y_ratio })
  });
  return handleApiResponse(res, 'Failed to configure border tripwire');
}

export async function setOpticalMode(cameraId, mode) {
  const res = await authFetch(`${API_BASE}/cameras/${cameraId}/optical-mode`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode })
  });
  return handleApiResponse(res, 'Failed to set optical mode');
}

export async function setSurveillanceMode(cameraId, mode) {
  const res = await authFetch(`${API_BASE}/cameras/${cameraId}/surveillance-mode`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode })
  });
  return handleApiResponse(res, 'Failed to set surveillance mode');
}

// Vehicle & ANPR APIs
export async function fetchVehicles(status = null) {
  const url = new URL(`${API_BASE}/vehicles`, window.location.origin);
  if (status && status !== 'ALL') url.searchParams.append('status', status);
  const res = await authFetch(url.toString());
  return handleApiResponse(res, 'Failed to fetch vehicle roster');
}

export async function fetchVehicleStats() {
  const res = await authFetch(`${API_BASE}/vehicles/stats`);
  return handleApiResponse(res, 'Failed to fetch vehicle stats');
}

export async function enrollVehicle(payload) {
  const res = await authFetch(`${API_BASE}/vehicles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  return handleApiResponse(res, 'Failed to enroll vehicle');
}

export async function deleteVehicle(vehicleId) {
  const res = await authFetch(`${API_BASE}/vehicles/${vehicleId}`, {
    method: 'DELETE'
  });
  return handleApiResponse(res, 'Failed to delete vehicle profile');
}

export async function seedDefaultVehicles() {
  const res = await authFetch(`${API_BASE}/vehicles/seed-defaults`, {
    method: 'POST'
  });
  return handleApiResponse(res, 'Failed to seed default vehicles');
}

export async function fetchVehicleTransits({
  plateNumber,
  cameraId,
  plateStatus,
  watchlistMatch,
  direction,
  skip = 0,
  limit = 50
} = {}) {
  const url = new URL(`${API_BASE}/vehicles/transits`, window.location.origin);
  if (plateNumber && plateNumber.trim()) url.searchParams.append('plate_number', plateNumber.trim());
  if (cameraId && cameraId !== 'ALL') url.searchParams.append('camera_id', cameraId);
  if (plateStatus && plateStatus !== 'ALL') url.searchParams.append('plate_status', plateStatus);
  if (watchlistMatch !== undefined && watchlistMatch !== null && watchlistMatch !== 'ALL') {
    url.searchParams.append('watchlist_match', watchlistMatch);
  }
  if (direction && direction !== 'ALL') url.searchParams.append('direction', direction);
  if (skip !== undefined) url.searchParams.append('skip', skip);
  if (limit !== undefined) url.searchParams.append('limit', limit);

  const res = await authFetch(url.toString());
  return handleApiResponse(res, 'Failed to fetch vehicle transit passage logs');
}

export async function fetchTransitStats(cameraId = null) {
  const url = new URL(`${API_BASE}/vehicles/transits/stats`, window.location.origin);
  if (cameraId && cameraId !== 'ALL') url.searchParams.append('camera_id', cameraId);
  const res = await authFetch(url.toString());
  return handleApiResponse(res, 'Failed to fetch vehicle passage stats');
}

// Multi-Camera Management APIs
export async function addCamera({ cameraId, name, source = '0', surveillanceMode = 'PERIMETER', opticalMode = 'STANDARD' }) {
  const res = await authFetch(`${API_BASE}/cameras`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      camera_id: cameraId,
      name,
      source,
      surveillance_mode: surveillanceMode,
      optical_mode: opticalMode
    })
  });
  return handleApiResponse(res, 'Failed to add camera');
}

export async function deleteCamera(cameraId) {
  const res = await authFetch(`${API_BASE}/cameras/${cameraId}`, { method: 'DELETE' });
  return handleApiResponse(res, 'Failed to delete camera');
}

export async function seedDefaultSectors() {
  const res = await authFetch(`${API_BASE}/cameras/seed-default-sectors`, { method: 'POST' });
  return handleApiResponse(res, 'Failed to seed default sectors');
}

export async function fetchDetectedDevices() {
  const res = await authFetch(`${API_BASE}/cameras/detected-devices`);
  return handleApiResponse(res, 'Failed to fetch detected devices');
}

export async function updateCameraSource(cameraId, source, name = null) {
  const res = await authFetch(`${API_BASE}/cameras/${cameraId}/source`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, name })
  });
  return handleApiResponse(res, 'Failed to update camera source');
}

export async function ingestCameraFrame(cameraId, frameBlob) {
  const res = await authFetch(`${API_BASE}/cameras/${cameraId}/ingest-frame`, {
    method: 'POST',
    headers: { 'Content-Type': 'image/jpeg' },
    body: frameBlob
  });
  return handleApiResponse(res, 'Failed to ingest camera frame');
}

// Edge AI Telemetry & Resource Profiling APIs
export async function fetchEdgeTelemetry() {
  const res = await authFetch(`${API_BASE}/health/edge-telemetry`);
  return handleApiResponse(res, 'Failed to fetch edge telemetry');
}

// Tactical Store-and-Forward Sync APIs
export async function fetchSyncBundle() {
  const res = await authFetch(`${API_BASE}/alerts/sync-bundle`);
  return handleApiResponse(res, 'Failed to fetch sync bundle');
}

export async function transmitSyncBundle() {
  const res = await authFetch(`${API_BASE}/alerts/sync-bundle/transmit`, {
    method: 'POST'
  });
  return handleApiResponse(res, 'Failed to transmit sync bundle');
}

// Presentation Demo Safety Net (Jury Trigger - Gated by Diagnostic Mode)
export async function triggerDemoAlert({ triggerType, cameraId = 'CAM-01' }) {
  const res = await authFetch(`${API_BASE}/alerts/demo-trigger`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      trigger_type: triggerType,
      camera_id: cameraId
    })
  });
  return handleApiResponse(res, 'Failed to trigger demo alert');
}

// SIH26187 Merkle Audit Chain APIs
export async function fetchBlockchainLedger(limit = 50, offset = 0) {
  const url = new URL(`${API_BASE}/blockchain/ledger`, window.location.origin);
  url.searchParams.append('limit', limit);
  url.searchParams.append('offset', offset);
  const res = await authFetch(url.toString());
  return handleApiResponse(res, 'Failed to fetch audit chain ledger');
}

export async function verifyBlockchainLedger() {
  const res = await authFetch(`${API_BASE}/blockchain/verify`, { method: 'POST' });
  return handleApiResponse(res, 'Failed to verify cryptographic chain of custody');
}

export async function fetchBlockchainStats() {
  const res = await authFetch(`${API_BASE}/blockchain/stats`);
  return handleApiResponse(res, 'Failed to fetch audit chain stats');
}

// Sector Trajectory Map API
export async function fetchSectorTrajectoryMap() {
  const res = await authFetch(`${API_BASE}/alerts/sector-trajectory/map`);
  return handleApiResponse(res, 'Failed to fetch sector trajectory map');
}
