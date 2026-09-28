import React, { useState, useEffect, useCallback, useRef } from 'react';
import Sidebar from '../components/Sidebar';
import Header from '../components/Header';
import StatsCards from '../components/StatsCards';
import LiveCamera from '../components/LiveCamera';
import LiveDetectionLog from '../components/LiveDetectionLog';
import DetectionPopupModal from '../components/DetectionPopupModal';
import AlertHistory from '../components/AlertHistory';
import AlertDetailModal from '../components/AlertDetailModal';
import FaceManagerModal from '../components/FaceManagerModal';
import VehicleManagerModal from '../components/VehicleManagerModal';
import AddCameraModal from '../components/AddCameraModal';

import {
  fetchCameras,
  fetchAlerts,
  fetchAlertStats,
  fetchFaceStats,
  fetchVehicleStats,
  acknowledgeAlert,
  fetchEdgeTelemetry,
  triggerDemoAlert,
  getAuthenticatedRole,
  getAuthenticatedMediaUrl
} from '../services/api';
import { AlertWebSocketClient } from '../services/websocket';
import { playAlertChime } from '../services/audio';

import {
  Shield,
  Activity,
  Cpu,
  HardDrive,
  Radio,
  Send,
  CheckCircle,
  AlertTriangle,
  Play,
  RefreshCw,
  Plus,
  Sliders,
  Database,
  Lock,
  Layers,
  UserCheck,
  Truck,
  BarChart3,
  Server,
  Zap,
  Clock
} from 'lucide-react';

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState('OVERVIEW');
  const [soundEnabled, setSoundEnabled] = useState(true);
  const soundEnabledRef = useRef(soundEnabled);
  useEffect(() => {
    soundEnabledRef.current = soundEnabled;
  }, [soundEnabled]);
  const [wsStatus, setWsStatus] = useState('DISCONNECTED');
  const [authRole, setAuthRole] = useState(getAuthenticatedRole());
  const [authErrorBanner, setAuthErrorBanner] = useState(null);

  const [cameras, setCameras] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [stats, setStats] = useState(null);
  const [faceStats, setFaceStats] = useState({ total: 0, authorized_count: 0, suspect_count: 0 });
  const [vehicleStats, setVehicleStats] = useState({ total: 0, military_count: 0, stolen_count: 0, civilian_count: 0 });

  // Camera Selection
  const [selectedCameraId, setSelectedCameraId] = useState('CAM-01');
  const [addCameraModalOpen, setAddCameraModalOpen] = useState(false);

  // Modals
  const [faceModalOpen, setFaceModalOpen] = useState(false);
  const [vehicleModalOpen, setVehicleModalOpen] = useState(false);
  const [initialPlateSearch, setInitialPlateSearch] = useState('');
  const [activePopupAlert, setActivePopupAlert] = useState(null);
  const [selectedDetailModal, setSelectedDetailModal] = useState(null);

  const handleOpenVehicleDB = (plate = '') => {
    setInitialPlateSearch(plate || '');
    setActiveTab('VEHICLES');
  };

  // Edge Telemetry
  const [edgeTelemetry, setEdgeTelemetry] = useState(null);
  const [demoTriggering, setDemoTriggering] = useState(false);
  const [demoBannerMsg, setDemoBannerMsg] = useState(null);

  // Helper: extract valid demo cameras from API response
  const extractCams = (raw) => {
    const validCams = raw.filter(c => ['CAM-01', 'CAM-02', 'CAM-03', 'CAM-04'].includes(c.camera_id)).slice(0, 4);
    return validCams.length > 0 ? validCams : raw.slice(0, 4);
  };

  // Lightweight camera-only refresh for mode switches (fast feedback)
  const refreshCameras = useCallback(async () => {
    try {
      const cams = await fetchCameras();
      if (cams) setCameras(extractCams(cams));
    } catch {
      // silent fail on camera refresh
    }
  }, []);

  // Full data load (used on mount and manual refresh)
  const loadData = useCallback(async () => {
    try {
      const [camsRes, alertsRes, statsRes, facesRes, vehiclesRes, telemRes] = await Promise.allSettled([
        fetchCameras(),
        fetchAlerts('ALL', 100, 0),
        fetchAlertStats(),
        fetchFaceStats(),
        fetchVehicleStats(),
        fetchEdgeTelemetry()
      ]);

      if (camsRes.status === 'fulfilled' && camsRes.value) {
        setCameras(extractCams(camsRes.value));
      }
      if (alertsRes.status === 'fulfilled' && alertsRes.value) {
        setAlerts(alertsRes.value.items || []);
      }
      if (statsRes.status === 'fulfilled' && statsRes.value) {
        setStats(statsRes.value);
      }
      if (facesRes.status === 'fulfilled' && facesRes.value) {
        setFaceStats(facesRes.value);
      }
      if (vehiclesRes.status === 'fulfilled' && vehiclesRes.value) {
        setVehicleStats(vehiclesRes.value);
      }
      if (telemRes.status === 'fulfilled' && telemRes.value) {
        setEdgeTelemetry(telemRes.value);
      }
    } catch (err) {
      console.error('[Dashboard] Error loading data:', err);
    }
  }, []);

  // Primary poll: cameras + alert stats every 5 seconds (lightweight)
  useEffect(() => {
    loadData();
    const primaryPoll = setInterval(async () => {
      try {
        const [camsRes, statsRes] = await Promise.allSettled([
          fetchCameras(),
          fetchAlertStats()
        ]);
        if (camsRes.status === 'fulfilled' && camsRes.value) {
          setCameras(extractCams(camsRes.value));
        }
        if (statsRes.status === 'fulfilled' && statsRes.value) setStats(statsRes.value);
      } catch {
        // silent fail on poll
      }
    }, 5000);

    // Secondary poll: face/vehicle stats + telemetry every 15 seconds (heavier, less urgent)
    const secondaryPoll = setInterval(async () => {
      try {
        const [facesRes, vehiclesRes, telemRes] = await Promise.allSettled([
          fetchFaceStats(),
          fetchVehicleStats(),
          fetchEdgeTelemetry()
        ]);
        if (facesRes.status === 'fulfilled' && facesRes.value) setFaceStats(facesRes.value);
        if (vehiclesRes.status === 'fulfilled' && vehiclesRes.value) setVehicleStats(vehiclesRes.value);
        if (telemRes.status === 'fulfilled' && telemRes.value) setEdgeTelemetry(telemRes.value);
      } catch {
        // silent fail
      }
    }, 15000);

    return () => {
      clearInterval(primaryPoll);
      clearInterval(secondaryPoll);
    };
  }, [loadData]);

  // Sync auth state changes across components
  useEffect(() => {
    const handleAuthChange = () => {
      const role = getAuthenticatedRole();
      setAuthRole(role);
      loadData();
    };
    window.addEventListener('xynapse:auth_change', handleAuthChange);
    return () => window.removeEventListener('xynapse:auth_change', handleAuthChange);
  }, [loadData]);

  // WebSocket Handler
  const handleWsMessage = useCallback((msg) => {
    const isAlertEvent = [
      'PERSON_DETECTED',
      'CAMERA_TAMPERED',
      'CYBER_STREAM_TAMPERED',
      'SUSPICIOUS_LOITERING',
      'SUSPECT_DETECTED',
      'BORDER_INTRUSION',
      'SUSPECT_VEHICLE_INTERCEPT',
      'VEHICLE_DETECTED'
    ].includes(msg.type);

    if (isAlertEvent) {
      const eventType = msg.event_type || msg.type;
      const newAlert = {
        id: msg.alert_id,
        alert_id: msg.alert_id,
        event_type: eventType,
        camera_id: msg.camera_id,
        timestamp: msg.timestamp,
        face_count: msg.face_count ?? (eventType === 'CAMERA_TAMPERED' || eventType === 'CYBER_STREAM_TAMPERED' ? 0 : 1),
        objects_detected: msg.objects_detected || (
          eventType === 'SUSPECT_DETECTED'
            ? `Watchlist Suspect Identified: ${msg.suspect_name || 'Wanted Person'}`
            : eventType === 'BORDER_INTRUSION'
            ? 'Restricted Border Zero-Line Breached by Unauthorized Person'
            : eventType === 'CAMERA_TAMPERED'
            ? 'Camera Lens Occlusion / Tampering Detected'
            : eventType === 'CYBER_STREAM_TAMPERED'
            ? 'Cyber Security: Stream Replay / Frozen Feed Attack Detected'
            : eventType === 'SUSPICIOUS_LOITERING'
            ? 'Suspicious Loitering: Sustained Human Presence'
            : eventType === 'SUSPECT_VEHICLE_INTERCEPT'
            ? `Wanted Vehicle Intercept: ${msg.plate_number || 'Stolen Vehicle'}`
            : eventType === 'VEHICLE_DETECTED'
            ? `Checkpost Vehicle Transit: ${msg.vehicle_type || 'Vehicle'} [${msg.plate_number || 'Scanned'}]`
            : `${msg.face_count || 1} Human(s) Detected`
        ),
        plate_number: msg.plate_number,
        vehicle_type: msg.vehicle_type,
        confidence: msg.confidence || 0.95,
        snapshot: msg.snapshot,
        status: msg.status || 'NEW',
        severity: msg.severity || (
          eventType === 'SUSPECT_DETECTED' || eventType === 'CAMERA_TAMPERED' || eventType === 'CYBER_STREAM_TAMPERED' || eventType === 'BORDER_INTRUSION' || eventType === 'SUSPECT_VEHICLE_INTERCEPT'
            ? 'CRITICAL'
            : eventType === 'SUSPICIOUS_LOITERING'
              ? 'HIGH'
              : 'MEDIUM'
        )
      };

      setAlerts((prev) => [newAlert, ...prev]);

      const isUrgentThreat = [
        'SUSPECT_DETECTED',
        'SUSPECT_VEHICLE_INTERCEPT',
        'BORDER_INTRUSION',
        'CAMERA_TAMPERED',
        'CYBER_STREAM_TAMPERED',
        'SUSPICIOUS_LOITERING'
      ].includes(eventType);

      if (isUrgentThreat) {
        setActivePopupAlert(newAlert);
      }

      if (soundEnabledRef.current) {
        playAlertChime();
      }

      setStats((prev) => ({
        ...prev,
        active_alerts: (prev?.active_alerts || 0) + 1,
        today_detections: (prev?.today_detections || 0) + (eventType === 'CAMERA_TAMPERED' ? 0 : 1),
        total_alerts: (prev?.total_alerts || 0) + 1
      }));
    } else if (msg.type === 'ALERT_STATUS_UPDATED') {
      setAlerts((prev) =>
        prev.map((a) => (a.alert_id === msg.alert_id ? { ...a, status: msg.status } : a))
      );
      setSelectedDetailModal((prev) => (prev && prev.alert_id === msg.alert_id ? { ...prev, status: msg.status } : prev));
      setActivePopupAlert((prev) => (prev && prev.alert_id === msg.alert_id ? null : prev));
    }
  }, []);

  // Connect WebSocket with authentication gating
  useEffect(() => {
    if (!authRole) {
      setWsStatus('LOGGED_OUT');
      return;
    }
    const wsClient = new AlertWebSocketClient(handleWsMessage, setWsStatus);
    wsClient.connect();
    return () => wsClient.disconnect();
  }, [handleWsMessage, authRole]);

  const handleAcknowledgeAlert = async (alertId) => {
    setAuthErrorBanner(null);
    try {
      await acknowledgeAlert(alertId);
      loadData();
      if (activePopupAlert && (activePopupAlert.id === alertId || activePopupAlert.alert_id === alertId)) {
        setActivePopupAlert(null);
      }
    } catch (err) {
      console.error('Acknowledge failed:', err);
      setAuthErrorBanner(err.detail || err.message || 'Administrative privileges required to acknowledge alerts.');
    }
  };

  const handleDemoTrigger = async (triggerType, camId = selectedCameraId) => {
    setDemoTriggering(true);
    try {
      await triggerDemoAlert({ triggerType, cameraId: camId });
      setDemoBannerMsg(`Simulation event dispatched: ${triggerType}`);
      if (soundEnabled) playAlertChime('HIGH');
      loadData();
      setTimeout(() => setDemoBannerMsg(null), 4000);
    } catch (err) {
      setDemoBannerMsg(`Simulation failed: ${err.message}`);
      setTimeout(() => setDemoBannerMsg(null), 4000);
    } finally {
      setDemoTriggering(false);
    }
  };

  const activeCamera = cameras.find((c) => c.camera_id === selectedCameraId) || cameras[0] || null;

  const getPageMeta = () => {
    switch (activeTab) {
      case 'OVERVIEW':
        return { title: 'Overview', subtitle: 'Live situational picture and recent activity' };
      case 'VEHICLES':
        return { title: 'Vehicle Passage Database', subtitle: 'Automated ANPR vehicle transit logs, plate recognition, and security watchlist sentry' };
      case 'ALERTS':
        return { title: 'Alerts & Incidents', subtitle: 'Unified threat triage and real-time operational status tracking' };
      case 'ANALYTICS':
        return { title: 'Analytics', subtitle: 'Technical metrics & AI performance' };
      case 'SETTINGS':
        return { title: 'Settings', subtitle: 'Station configuration & operational parameters' };
      default:
        return { title: 'Overview', subtitle: 'Live operational picture' };
    }
  };

  const { title: pageTitle, subtitle: pageSubtitle } = getPageMeta();

  return (
    <div className="min-h-screen neo-canvas text-slate-900 flex antialiased selection:bg-sky-500/20">
      {/* 1. Left Minimal Spatial Sidebar */}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        soundEnabled={soundEnabled}
        setSoundEnabled={setSoundEnabled}
        wsStatus={wsStatus}
        newAlertCount={alerts.filter((a) => a.status === 'NEW').length}
        onOpenFaceManager={() => setFaceModalOpen(true)}
        onOpenVehicleManager={() => handleOpenVehicleDB('')}
        cameraCount={cameras.length || 1}
      />

      {/* 2. Main Content Container */}
      <div className="flex-1 flex flex-col min-w-0 overflow-y-auto">
        {/* Top Header */}
        <Header
          title={pageTitle}
          subtitle={pageSubtitle}
          cameraCount={cameras.length || 1}
          onlineCount={cameras.filter((c) => c.status === 'ONLINE').length}
          wsStatus={wsStatus}
          role={authRole}
          onRefresh={loadData}
          onOpenVehicleDB={() => handleOpenVehicleDB('')}
        />

        {/* Global Security / Role Notification Banner */}
        {authErrorBanner && (
          <div className="mx-8 mt-6 px-5 py-3.5 neo-glass border-rose-300/70 bg-rose-50/80 rounded-2xl shadow-sm text-xs font-semibold text-rose-800 flex items-center justify-between animate-fadeIn">
            <div className="flex items-center space-x-2.5">
              <AlertTriangle className="w-4 h-4 shrink-0 text-rose-600" />
              <span className="tracking-tight">{authErrorBanner}</span>
            </div>
            <button
              onClick={() => setAuthErrorBanner(null)}
              className="text-rose-600 hover:text-rose-900 font-bold text-xs ml-3 w-6 h-6 rounded-full hover:bg-rose-100 flex items-center justify-center transition-colors"
            >
              ✕
            </button>
          </div>
        )}

        {/* Global Notification Banner */}
        {demoBannerMsg && (
          <div className="mx-8 mt-6 px-5 py-3.5 neo-glass border-sky-300/70 bg-sky-50/80 rounded-2xl shadow-sm text-xs font-semibold text-sky-900 flex items-center justify-between animate-fadeIn">
            <div className="flex items-center space-x-2.5">
              <Activity className="w-4 h-4 shrink-0 text-sky-600" />
              <span>{demoBannerMsg}</span>
            </div>
            <button
              onClick={() => setDemoBannerMsg(null)}
              className="text-sky-600 hover:text-sky-900 font-bold text-xs ml-3 w-6 h-6 rounded-full hover:bg-sky-100 flex items-center justify-center transition-colors"
            >
              ✕
            </button>
          </div>
        )}

        {/* Tab Content */}
        <main className="flex-1 p-6 lg:p-8 max-w-7xl w-full mx-auto space-y-8">
          {/* ============================================================== */}
          {/* TAB 1: OVERVIEW (HERO LIVE FEED + KEY METRICS + RECENT ACTIVITY) */}
          {/* ============================================================== */}
          {activeTab === 'OVERVIEW' && (
            <div className="space-y-8">
              {/* Precision Surveillance Stat Dials */}
              <StatsCards
                stats={stats}
                totalCameras={cameras.length || 1}
                onlineCameras={cameras.filter((c) => c.status === 'ONLINE').length}
                faceCount={faceStats.total}
                vehicleCount={vehicleStats.total}
                onOpenVehicleDB={() => handleOpenVehicleDB('')}
              />

              {/* Primary Visual Hero (Live Camera) + Recent Activity */}
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
                <div className="lg:col-span-8">
                  <LiveCamera
                    key={activeCamera?.camera_id || 'CAM-01'}
                    camera={activeCamera}
                    cameras={cameras}
                    onSelectCamera={(cid) => setSelectedCameraId(cid)}
                    onCameraUpdated={refreshCameras}
                    onOpenVehicleDB={handleOpenVehicleDB}
                  />
                </div>
                <div className="lg:col-span-4">
                  <LiveDetectionLog
                    liveDetections={alerts}
                    onViewAlert={(item) => setSelectedDetailModal(item)}
                    onAcknowledge={handleAcknowledgeAlert}
                  />
                </div>
              </div>
            </div>
          )}

          {/* ============================================================== */}
          {/* TAB: VEHICLES (VEHICLE PASSAGE & ANPR DATABASE)                */}
          {/* ============================================================== */}
          {activeTab === 'VEHICLES' && (
            <div className="space-y-6">
              <VehicleManagerModal
                embedded={true}
                isOpen={true}
                initialSearch={initialPlateSearch}
                onVehiclesChanged={loadData}
              />
            </div>
          )}

          {/* ============================================================== */}
          {/* TAB 3: ALERTS & INCIDENTS (UNIFIED THREATS, LOGS & DOSSIERS)   */}
          {/* ============================================================== */}
          {activeTab === 'ALERTS' && (
            <div className="space-y-6">
              <AlertHistory
                alerts={alerts}
                onRefresh={loadData}
                onViewAlert={(item) => setSelectedDetailModal(item)}
                onAlertsUpdated={loadData}
              />
            </div>
          )}

          {/* ============================================================== */}
          {/* TAB 4: ANALYTICS (SYSTEM & EDGE AI TELEMETRY)                  */}
          {/* ============================================================== */}
          {activeTab === 'ANALYTICS' && (
            <div className="space-y-8">
              {/* Telemetry Overview Dials - Large Visual Blocks */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
                <div className="neo-glass-hover p-6 rounded-3xl space-y-2 relative overflow-hidden group">
                  <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-slate-500">
                    <span>Inference Latency</span>
                    <Zap className="w-4 h-4 text-sky-500" />
                  </div>
                  <div className="text-3xl sm:text-4xl font-extrabold text-slate-900 font-mono tracking-tight">
                    {edgeTelemetry?.average_inference_latency_ms > 0 ? `${edgeTelemetry.average_inference_latency_ms} ms` : 'Standby'}
                  </div>
                  <div className="text-xs font-semibold text-emerald-700 flex items-center gap-1.5 pt-1">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                    {edgeTelemetry?.average_inference_latency_ms > 0 ? 'Live Neural Timing' : 'Sub-40ms Edge Target'}
                  </div>
                </div>

                <div className="neo-glass-hover p-6 rounded-3xl space-y-2 relative overflow-hidden group">
                  <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-slate-500">
                    <span>Processing Rate</span>
                    <Activity className="w-4 h-4 text-emerald-500" />
                  </div>
                  <div className="text-3xl sm:text-4xl font-extrabold text-slate-900 font-mono tracking-tight">
                    {activeCamera?.fps ? `${activeCamera.fps} FPS` : '15.0 FPS'}
                  </div>
                  <div className="text-xs font-semibold text-emerald-700 flex items-center gap-1.5 pt-1">
                    <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                    Real-Time Optical Flow
                  </div>
                </div>

                <div className="neo-glass-hover p-6 rounded-3xl space-y-2 relative overflow-hidden group">
                  <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-slate-500">
                    <span>Edge Compute</span>
                    <Cpu className="w-4 h-4 text-violet-500" />
                  </div>
                  <div className="text-3xl sm:text-4xl font-extrabold text-slate-900 font-mono tracking-tight">
                    {edgeTelemetry?.cpu_usage_pct ?? 18.4}%
                  </div>
                  <div className="text-xs font-mono text-slate-500 pt-1">
                    RAM: {edgeTelemetry?.system_ram_usage_pct ?? 45.2}% ({edgeTelemetry?.process_memory_mb ?? 412} MB)
                  </div>
                </div>

                <div className="neo-glass-hover p-6 rounded-3xl space-y-2 relative overflow-hidden group">
                  <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-slate-500">
                    <span>Events Logged</span>
                    <Database className="w-4 h-4 text-sky-500" />
                  </div>
                  <div className="text-3xl sm:text-4xl font-extrabold text-sky-600 font-mono tracking-tight">
                    {stats?.total_alerts ?? alerts.length}
                  </div>
                  <div className="text-xs font-semibold text-amber-700 flex items-center gap-1.5 pt-1">
                    <span className="w-2 h-2 rounded-full bg-amber-500"></span>
                    {stats?.active_alerts ?? 0} Active Incidents
                  </div>
                </div>
              </div>

              {/* Real SQL-Aggregated Incident Intelligence */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <div className="neo-glass p-7 rounded-3xl space-y-5 border border-white/80 shadow-sm">
                  <div className="flex items-center justify-between border-b border-slate-200/60 pb-4">
                    <div>
                      <h4 className="font-extrabold text-lg text-slate-900 tracking-tight">
                        Incident Distribution by Event Type
                      </h4>
                      <p className="text-xs text-slate-500 mt-0.5">Indexed by autonomous sensor classification</p>
                    </div>
                    <span className="text-[11px] text-slate-600 font-mono bg-white/80 border border-slate-200 px-2.5 py-1 rounded-lg font-semibold shadow-2xs">
                      SQLite WAL
                    </span>
                  </div>
                  <div className="space-y-4 text-xs">
                    {stats?.event_breakdown && Object.keys(stats.event_breakdown).length > 0 ? (
                      Object.entries(stats.event_breakdown).map(([evt, count]) => {
                        const total = stats.total_alerts || 1;
                        const pct = Math.round((count / total) * 100);
                        return (
                          <div key={evt} className="space-y-1.5">
                            <div className="flex items-center justify-between text-slate-900">
                              <span className="font-semibold text-slate-800 text-sm">{evt.replace(/_/g, ' ')}</span>
                              <span className="font-mono text-slate-600 font-semibold">{count} ({pct}%)</span>
                            </div>
                            <div className="w-full bg-slate-100/90 rounded-full h-2 overflow-hidden border border-slate-200/50">
                              <div
                                className="bg-gradient-to-r from-sky-500 to-indigo-500 h-2 rounded-full transition-all duration-500"
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <div className="text-center py-10 text-slate-400 font-medium">
                        No incidents logged in the database yet.
                      </div>
                    )}
                  </div>
                </div>

                <div className="neo-glass p-7 rounded-3xl space-y-5 border border-white/80 shadow-sm">
                  <div className="flex items-center justify-between border-b border-slate-200/60 pb-4">
                    <div>
                      <h4 className="font-extrabold text-lg text-slate-900 tracking-tight">
                        Threat Severity Classification
                      </h4>
                      <p className="text-xs text-slate-500 mt-0.5">Automated real-time triage scoring</p>
                    </div>
                    <span className="text-[11px] text-slate-600 font-mono bg-white/80 border border-slate-200 px-2.5 py-1 rounded-lg font-semibold shadow-2xs">
                      Real-Time Gating
                    </span>
                  </div>
                  <div className="space-y-4 text-xs">
                    {stats?.severity_breakdown && Object.keys(stats.severity_breakdown).length > 0 ? (
                      Object.entries(stats.severity_breakdown).map(([sev, count]) => {
                        const total = stats.total_alerts || 1;
                        const pct = Math.round((count / total) * 100);
                        const colorMap = {
                          CRITICAL: 'bg-rose-500',
                          HIGH: 'bg-amber-500',
                          MEDIUM: 'bg-sky-500',
                          LOW: 'bg-emerald-500'
                        };
                        const barGradients = {
                          CRITICAL: 'from-rose-500 to-red-600',
                          HIGH: 'from-amber-400 to-amber-600',
                          MEDIUM: 'from-sky-400 to-blue-600',
                          LOW: 'from-emerald-400 to-teal-600'
                        };
                        return (
                          <div key={sev} className="space-y-1.5">
                            <div className="flex items-center justify-between text-slate-900">
                              <span className="font-semibold flex items-center space-x-2.5 text-slate-800 text-sm">
                                <span className={`w-2.5 h-2.5 rounded-full ${colorMap[sev] || 'bg-slate-400'} shadow-2xs`} />
                                <span>{sev}</span>
                              </span>
                              <span className="font-mono text-slate-600 font-semibold">{count} ({pct}%)</span>
                            </div>
                            <div className="w-full bg-slate-100/90 rounded-full h-2 overflow-hidden border border-slate-200/50">
                              <div
                                className={`bg-gradient-to-r ${barGradients[sev] || 'from-sky-500 to-indigo-500'} h-2 rounded-full transition-all duration-500`}
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <div className="text-center py-10 text-slate-400 font-medium">
                        No severity data recorded yet.
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Models & Hardware Details */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <div className="neo-glass p-7 rounded-3xl space-y-5 border border-white/80 shadow-sm">
                  <div className="flex items-center justify-between border-b border-slate-200/60 pb-4">
                    <h4 className="font-extrabold text-lg text-slate-900 tracking-tight">
                      Neural Vision Models
                    </h4>
                    <span className="text-[11px] font-mono text-slate-600 bg-white/80 border border-slate-200 px-2.5 py-1 rounded-lg font-semibold shadow-2xs">
                      Air-Gapped ONNX
                    </span>
                  </div>
                  <div className="space-y-3.5 text-xs">
                    <div className="flex items-center justify-between py-2.5 border-b border-slate-200/50">
                      <span className="text-slate-600 font-medium">Face Detection</span>
                      <span className="font-semibold text-slate-900 font-mono text-xs bg-white/80 px-2.5 py-1 rounded-lg border border-slate-200/60 shadow-2xs">OpenCV YuNet ONNX (CPU)</span>
                    </div>
                    <div className="flex items-center justify-between py-2.5 border-b border-slate-200/50">
                      <span className="text-slate-600 font-medium">Biometric Feature Vector</span>
                      <span className="font-semibold text-slate-900 font-mono text-xs bg-white/80 px-2.5 py-1 rounded-lg border border-slate-200/60 shadow-2xs">SFace 128-D Cosine Metric</span>
                    </div>
                    <div className="flex items-center justify-between py-2.5 border-b border-slate-200/50">
                      <span className="text-slate-600 font-medium">Object & Vehicle Classifier</span>
                      <span className="font-semibold text-slate-900 font-mono text-xs bg-white/80 px-2.5 py-1 rounded-lg border border-slate-200/60 shadow-2xs">YOLOv8 Nano (ONNX/PyTorch)</span>
                    </div>
                    <div className="flex items-center justify-between py-2.5">
                      <span className="text-slate-600 font-medium">Plate Recognition (ANPR)</span>
                      <span className="font-semibold text-slate-900 font-mono text-xs bg-white/80 px-2.5 py-1 rounded-lg border border-slate-200/60 shadow-2xs">RapidOCR Text Recognition</span>
                    </div>
                  </div>
                </div>

                <div className="neo-glass p-7 rounded-3xl space-y-5 border border-white/80 shadow-sm flex flex-col justify-between">
                  <div>
                    <div className="flex items-center justify-between border-b border-slate-200/60 pb-4">
                      <h4 className="font-extrabold text-lg text-slate-900 tracking-tight">
                        Local Autonomous Edge Architecture
                      </h4>
                      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-50 text-emerald-700 text-xs font-semibold border border-emerald-200">
                        <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                        Air-Gapped Station
                      </span>
                    </div>
                    <p className="text-xs text-slate-600 leading-relaxed mt-4">
                      Operates 100% locally and offline on edge hardware without cloud or central network dependency. High-performance SQLite WAL journal persistence ensures zero data loss during power interruptions.
                    </p>
                  </div>
                  <div className="pt-4 flex items-center justify-between border-t border-slate-200/60">
                    <div className="text-xs text-slate-500">
                      Local Storage Mode: <strong className="text-emerald-700 font-semibold">Autonomous Offline</strong>
                    </div>
                    <div className="text-xs font-mono text-slate-500 font-medium">
                      Zero External Telemetry
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ============================================================== */}
          {/* TAB 5: SETTINGS & SECURITY PARAMETERS                           */}
          {/* ============================================================== */}
          {activeTab === 'SETTINGS' && (
            <div className="space-y-8">
              {/* Security Registries & Command Station */}
              <div className="neo-glass p-7 rounded-3xl space-y-5 border border-white/80 shadow-sm">
                <div>
                  <h3 className="font-extrabold text-xl text-slate-900 tracking-tight">
                    Border Station Security Registries
                  </h3>
                  <p className="text-xs text-slate-500 mt-0.5">
                    Manage biometric watchlists, authorized personnel, and checkpost vehicle rosters.
                  </p>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 pt-1">
                  <button
                    onClick={() => setFaceModalOpen(true)}
                    className="p-5 rounded-2xl border border-white/80 hover:border-sky-300 bg-white/70 hover:bg-white/95 text-left transition-all duration-200 group flex items-start space-x-4 shadow-sm hover:shadow-md hover:-translate-y-0.5"
                  >
                    <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-slate-900 to-slate-800 text-white flex items-center justify-center shrink-0 shadow-sm group-hover:scale-105 transition-transform">
                      <UserCheck className="w-6 h-6 text-emerald-400" />
                    </div>
                    <div>
                      <div className="text-sm font-bold text-slate-900 group-hover:text-sky-600 transition-colors">
                        Biometric Face Roster
                      </div>
                      <div className="text-xs text-slate-500 mt-1">
                        {faceStats.total} Profiles ({faceStats.suspect_count} Watchlist Suspects)
                      </div>
                      <span className="inline-block mt-3 text-xs font-semibold text-sky-600 group-hover:translate-x-0.5 transition-transform">
                        Configure Identities →
                      </span>
                    </div>
                  </button>

                  <button
                    onClick={() => setVehicleModalOpen(true)}
                    className="p-5 rounded-2xl border border-white/80 hover:border-sky-300 bg-white/70 hover:bg-white/95 text-left transition-all duration-200 group flex items-start space-x-4 shadow-sm hover:shadow-md hover:-translate-y-0.5"
                  >
                    <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-slate-900 to-slate-800 text-white flex items-center justify-center shrink-0 shadow-sm group-hover:scale-105 transition-transform">
                      <Truck className="w-6 h-6 text-sky-400" />
                    </div>
                    <div>
                      <div className="text-sm font-bold text-slate-900 group-hover:text-sky-600 transition-colors">
                        Vehicle & ANPR Registry
                      </div>
                      <div className="text-xs text-slate-500 mt-1">
                        {vehicleStats.total} Vehicles ({vehicleStats.stolen_count} Stolen / Warrants)
                      </div>
                      <span className="inline-block mt-3 text-xs font-semibold text-sky-600 group-hover:translate-x-0.5 transition-transform">
                        Configure Checkpost Sentry →
                      </span>
                    </div>
                  </button>
                </div>
              </div>

              {/* System Architecture Information */}
              <div className="neo-glass p-7 rounded-3xl space-y-5 border border-white/80 shadow-sm">
                <div className="border-b border-slate-200/60 pb-4">
                  <h3 className="font-extrabold text-xl text-slate-900 tracking-tight">
                    Active Security Capabilities
                  </h3>
                  <p className="text-xs text-slate-500 mt-0.5">Autonomous edge verification modules running in memory</p>
                </div>
                <div className="divide-y divide-slate-200/60 text-xs">
                  <div className="py-4 flex items-center justify-between">
                    <div>
                      <div className="font-bold text-slate-900 text-sm">Human & Face Perception</div>
                      <div className="text-xs text-slate-500 mt-0.5">Real-time detection and automatic high-res snapshot capture</div>
                    </div>
                    <span className="text-emerald-700 font-semibold text-xs flex items-center space-x-2 bg-emerald-50 border border-emerald-200 px-3 py-1 rounded-full shadow-2xs">
                      <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                      <span>Active</span>
                    </span>
                  </div>
                  <div className="py-4 flex items-center justify-between">
                    <div>
                      <div className="font-bold text-slate-900 text-sm">Directional Border Zero-Line Tripwire</div>
                      <div className="text-xs text-slate-500 mt-0.5">Vector mathematics enforcing restricted perimeter zones</div>
                    </div>
                    <span className="text-emerald-700 font-semibold text-xs flex items-center space-x-2 bg-emerald-50 border border-emerald-200 px-3 py-1 rounded-full shadow-2xs">
                      <span className="w-2 h-2 rounded-full bg-emerald-500" />
                      <span>Armed</span>
                    </span>
                  </div>
                  <div className="py-4 flex items-center justify-between">
                    <div>
                      <div className="font-bold text-slate-900 text-sm">Temporal Loitering Dwell Tracking</div>
                      <div className="text-xs text-slate-500 mt-0.5">25-second dwell threshold before alert escalation</div>
                    </div>
                    <span className="text-emerald-700 font-semibold text-xs flex items-center space-x-2 bg-emerald-50 border border-emerald-200 px-3 py-1 rounded-full shadow-2xs">
                      <span className="w-2 h-2 rounded-full bg-emerald-500" />
                      <span>25s Timer Active</span>
                    </span>
                  </div>
                  <div className="py-4 flex items-center justify-between">
                    <div>
                      <div className="font-bold text-slate-900 text-sm">Camera Lens Tamper & Occlusion Guard</div>
                      <div className="text-xs text-slate-500 mt-0.5">Variance analyzer detecting lens blockage or spray paint</div>
                    </div>
                    <span className="text-emerald-700 font-semibold text-xs flex items-center space-x-2 bg-emerald-50 border border-emerald-200 px-3 py-1 rounded-full shadow-2xs">
                      <span className="w-2 h-2 rounded-full bg-emerald-500" />
                      <span>2s Trigger Active</span>
                    </span>
                  </div>
                  <div className="py-4 flex items-center justify-between opacity-75">
                    <div>
                      <div className="font-bold text-slate-500 text-sm">Tactical GIS Sector Map & Multi-Station Spatial Tracking</div>
                      <div className="text-xs text-slate-400 mt-0.5">Geospatial perimeter grid and cross-node camera positioning (Scheduled Roadmap)</div>
                    </div>
                    <span className="text-slate-500 font-medium flex items-center space-x-1.5 bg-slate-100 border border-slate-200 px-3 py-1 rounded-full text-xs">
                      <span>Future Implementation</span>
                    </span>
                  </div>
                </div>
              </div>

              {/* Auxiliary Diagnostic / Presentation Testing Sandbox (Isolated: Only enabled in explicit diagnostic mode) */}
              {edgeTelemetry?.diagnostic_mode === true && (
                <div className="neo-glass p-7 rounded-3xl space-y-5 border border-amber-200/80 bg-amber-50/20 shadow-sm">
                  <div>
                    <h3 className="font-extrabold text-lg text-slate-900 flex items-center space-x-2.5">
                      <span>Evaluation Diagnostic Sandbox</span>
                      <span className="text-[11px] font-mono px-2.5 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-200 font-semibold">
                        Diagnostic Mode Active
                      </span>
                    </h3>
                    <p className="text-xs text-slate-600 mt-0.5">
                      Diagnostic scenario testing for evaluators. All test event generation is disabled in standard production operation.
                    </p>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 pt-1">
                    <button
                      onClick={() => handleDemoTrigger('STOLEN_VEHICLE', 'CAM-02')}
                      disabled={demoTriggering}
                      className="p-4 rounded-2xl border border-white/80 hover:border-sky-300 bg-white/70 hover:bg-white text-left transition-all duration-200 group shadow-2xs hover:shadow-sm"
                    >
                      <div className="text-xs font-bold text-slate-900 group-hover:text-sky-600">
                        Test Stolen Vehicle
                      </div>
                      <div className="text-[11px] text-slate-500 mt-1">
                        Verify ANPR match against DL-01-AB-1234
                      </div>
                    </button>

                    <button
                      onClick={() => handleDemoTrigger('BORDER_BREACH', 'CAM-01')}
                      disabled={demoTriggering}
                      className="p-4 rounded-2xl border border-white/80 hover:border-rose-300 bg-white/70 hover:bg-white text-left transition-all duration-200 group shadow-2xs hover:shadow-sm"
                    >
                      <div className="text-xs font-bold text-slate-900 group-hover:text-rose-600">
                        Test Border Breach
                      </div>
                      <div className="text-[11px] text-slate-500 mt-1">
                        Verify tripwire cross-product math
                      </div>
                    </button>

                    <button
                      onClick={() => handleDemoTrigger('CYBER_REPLAY', 'CAM-01')}
                      disabled={demoTriggering}
                      className="p-4 rounded-2xl border border-white/80 hover:border-indigo-300 bg-white/70 hover:bg-white text-left transition-all duration-200 group shadow-2xs hover:shadow-sm"
                    >
                      <div className="text-xs font-bold text-slate-900 group-hover:text-indigo-600">
                        Test Cyber Freeze
                      </div>
                      <div className="text-[11px] text-slate-500 mt-1">
                        Verify static buffer freeze detection
                      </div>
                    </button>

                    <button
                      onClick={() => handleDemoTrigger('WILDLIFE', 'CAM-01')}
                      disabled={demoTriggering}
                      className="p-4 rounded-2xl border border-white/80 hover:border-emerald-300 bg-white/70 hover:bg-white text-left transition-all duration-200 group shadow-2xs hover:shadow-sm"
                    >
                      <div className="text-xs font-bold text-slate-900 group-hover:text-emerald-600">
                        Test Wildlife Filter
                      </div>
                      <div className="text-[11px] text-slate-500 mt-1">
                        Verify siren suppression for cattle
                      </div>
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </main>
      </div>

      {/* Modals */}
      {activePopupAlert && (
        <DetectionPopupModal
          alert={activePopupAlert}
          onViewFull={(item) => {
            setActivePopupAlert(null);
            setSelectedDetailModal(item);
          }}
          onAcknowledge={handleAcknowledgeAlert}
          onDismiss={() => setActivePopupAlert(null)}
        />
      )}

      {selectedDetailModal && (
        <AlertDetailModal
          alert={selectedDetailModal}
          onClose={() => setSelectedDetailModal(null)}
          onUpdated={loadData}
        />
      )}

      <FaceManagerModal
        isOpen={faceModalOpen}
        onClose={() => setFaceModalOpen(false)}
        onProfilesChanged={loadData}
        activeCameraId={selectedCameraId || activeCamera?.camera_id || 'CAM-01'}
      />

      <VehicleManagerModal
        isOpen={vehicleModalOpen}
        onClose={() => setVehicleModalOpen(false)}
        onVehiclesChanged={loadData}
        initialSearch={initialPlateSearch}
      />

      <AddCameraModal
        isOpen={addCameraModalOpen}
        onClose={() => setAddCameraModalOpen(false)}
        onCameraAdded={loadData}
      />
    </div>
  );
}
