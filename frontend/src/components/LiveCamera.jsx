import React, { useState, useRef, useEffect } from 'react';
import {
  Camera,
  RefreshCw,
  Power,
  Maximize2,
  AlertTriangle,
  UserCheck,
  ShieldAlert,
  Timer,
  Crosshair,
  Truck,
  Eye,
  Radio,
  Video,
  VideoOff
} from 'lucide-react';
import {
  startCamera,
  stopCamera,
  toggleTripwire,
  setOpticalMode,
  setSurveillanceMode,
  ingestCameraFrame,
  getAuthenticatedMediaUrl
} from '../services/api';

export default function LiveCamera({
  camera,
  cameras = [],
  onSelectCamera,
  onCameraUpdated,
  onOpenVehicleDB
}) {
  const [isLoading, setIsLoading] = useState(false);
  const [isTripwireToggling, setIsTripwireToggling] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [authError, setAuthError] = useState(null);
  const containerRef = useRef(null);

  // Optimistic local state for instant mode-switch feedback
  const [localSurveillanceMode, setLocalSurveillanceMode] = useState(null);
  const [localOpticalMode, setLocalOpticalMode] = useState(null);

  // Client WebCam Ingestion states (streams user's laptop/mobile camera to cloud AI)
  const [isWebcamActive, setIsWebcamActive] = useState(false);
  const [webcamError, setWebcamError] = useState(null);
  const localVideoRef = useRef(null);
  const localCanvasRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const ingestTimerRef = useRef(null);

  // Stop client webcam when component unmounts or selected camera changes
  useEffect(() => {
    return () => {
      if (ingestTimerRef.current) {
        clearInterval(ingestTimerRef.current);
        ingestTimerRef.current = null;
      }
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach((t) => t.stop());
        mediaStreamRef.current = null;
      }
    };
  }, [camera?.camera_id]);

  // Attach and play stream when isWebcamActive turns true
  useEffect(() => {
    if (isWebcamActive && localVideoRef.current && mediaStreamRef.current) {
      if (localVideoRef.current.srcObject !== mediaStreamRef.current) {
        localVideoRef.current.srcObject = mediaStreamRef.current;
      }
      localVideoRef.current.play().catch(() => {});
    }
  }, [isWebcamActive]);

  // When camera selection changes, reset mode state and auth error
  useEffect(() => {
    setLocalSurveillanceMode(null);
    setLocalOpticalMode(null);
    setAuthError(null);
  }, [camera?.camera_id]);

  // Reset optimistic state when camera prop updates (server confirmed the change)
  useEffect(() => {
    setLocalSurveillanceMode(null);
    setLocalOpticalMode(null);
  }, [camera?.surveillance_mode, camera?.optical_mode]);

  const cameraId = camera?.camera_id || 'CAM-01';
  const isOnline = camera?.status === 'ONLINE' || camera?.status === 'STANDBY';
  const opticalMode = localOpticalMode || camera?.optical_mode || 'STANDARD';
  const surveillanceMode = localSurveillanceMode || camera?.surveillance_mode || 'PERIMETER';
  const isTampered = camera?.is_tampered === true;
  const isLoitering = camera?.is_loitering === true;
  const isPerimeterBreached = camera?.is_perimeter_breached === true;
  const tripwireEnabled = camera?.tripwire_enabled !== false;
  const dwellSeconds = camera?.dwell_seconds ?? 0.0;
  const fps = camera?.fps ?? 0;
  const detections = camera?.detections || [];
  const vehicles = camera?.vehicles || [];
  const hasSuspect = Boolean(camera?.has_suspect);
  const isAuthorized = Boolean(camera?.is_authorized);
  const hasSuspectVehicle = Boolean(camera?.has_suspect_vehicle);

  const SURVEILLANCE_MODES = [
    { id: 'PERIMETER', label: 'Perimeter Sentry' },
    { id: 'CHECKPOST', label: 'Checkpost' },
    { id: 'UNIFIED', label: 'Unified' },
  ];

  const OPTICAL_MODES = [
    { id: 'STANDARD', label: 'Day RGB' },
    { id: 'LOW_LIGHT_ENHANCE', label: 'Night CLAHE' },
    { id: 'NVG_GREEN', label: 'NVG (Sim)' },
    { id: 'FLIR_THERMAL', label: 'Thermal (Sim)' },
  ];

  const handleSelectSurveillanceMode = async (mode) => {
    if (mode === surveillanceMode) return;
    setLocalSurveillanceMode(mode);
    setAuthError(null);
    try {
      await setSurveillanceMode(cameraId, mode);
      if (onCameraUpdated) onCameraUpdated();
    } catch (err) {
      console.error('[LiveCamera] Mode change error:', err);
      setLocalSurveillanceMode(null);
      setAuthError(err.detail || err.message || 'Administrative privileges required to change surveillance mode.');
    }
  };

  const handleSelectOpticalMode = async (mode) => {
    if (mode === opticalMode) return;
    setLocalOpticalMode(mode);
    setAuthError(null);
    try {
      await setOpticalMode(cameraId, mode);
      if (onCameraUpdated) onCameraUpdated();
    } catch (err) {
      console.error('[LiveCamera] Optical mode change error:', err);
      setLocalOpticalMode(null);
      setAuthError(err.detail || err.message || 'Administrative privileges required to change optical mode.');
    }
  };

  const streamSrc = getAuthenticatedMediaUrl(`/api/cameras/${cameraId}/stream${refreshKey ? `?r=${refreshKey}` : ''}`);

  const formatTime = (sec) => {
    const s = Math.floor(sec || 0);
    const mins = Math.floor(s / 60);
    const rem = s % 60;
    return `${String(mins).padStart(2, '0')}m ${String(rem).padStart(2, '0')}s`;
  };

  const handleToggleCamera = async () => {
    setIsLoading(true);
    setAuthError(null);
    try {
      if (isOnline) {
        await stopCamera(cameraId);
      } else {
        await startCamera(cameraId);
      }
      setRefreshKey((k) => k + 1);
      if (onCameraUpdated) onCameraUpdated();
    } catch (err) {
      console.error('[LiveCamera] Toggle error:', err);
      setAuthError(err.detail || err.message || 'Administrative privileges required to control camera state.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleTurnOnCamera = async () => {
    setIsLoading(true);
    setAuthError(null);
    try {
      await startCamera(cameraId);
      setRefreshKey((k) => k + 1);
      if (onCameraUpdated) onCameraUpdated();
    } catch (err) {
      console.error('[LiveCamera] Turn on error:', err);
      setAuthError(err.detail || err.message || 'Administrative privileges required to start camera.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleToggleTripwire = async () => {
    setIsTripwireToggling(true);
    setAuthError(null);
    try {
      await toggleTripwire(cameraId);
      if (onCameraUpdated) onCameraUpdated();
    } catch (err) {
      console.error('[LiveCamera] Tripwire toggle error:', err);
      setAuthError(err.detail || err.message || 'Administrative privileges required to toggle tripwire.');
    } finally {
      setIsTripwireToggling(false);
    }
  };

  const handleRefresh = () => {
    setRefreshKey((k) => k + 1);
  };

  const handleToggleWebcam = async () => {
    if (isWebcamActive) {
      if (ingestTimerRef.current) {
        clearInterval(ingestTimerRef.current);
        ingestTimerRef.current = null;
      }
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach((t) => t.stop());
        mediaStreamRef.current = null;
      }
      setIsWebcamActive(false);
      setRefreshKey((k) => k + 1);
      return;
    }

    setWebcamError(null);
    try {
      if (!navigator?.mediaDevices?.getUserMedia) {
        throw new Error('WebCam access is not supported by your browser or requires HTTPS.');
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false
      });
      mediaStreamRef.current = stream;
      if (localVideoRef.current) {
        localVideoRef.current.srcObject = stream;
        await localVideoRef.current.play().catch(() => {});
      }
      setIsWebcamActive(true);

      const canvas = localCanvasRef.current || document.createElement('canvas');
      canvas.width = 640;
      canvas.height = 480;
      const ctx = canvas.getContext('2d');

      // Ingest live frames from browser webcam to backend perception engine @ ~8-10 FPS
      let isPosting = false;
      ingestTimerRef.current = setInterval(() => {
        const video = localVideoRef.current;
        if (!video || video.readyState < 2 || isPosting) return;
        const w = video.videoWidth || 640;
        const h = video.videoHeight || 480;
        if (canvas.width !== w || canvas.height !== h) {
          canvas.width = w;
          canvas.height = h;
        }
        ctx.drawImage(video, 0, 0, w, h);
        isPosting = true;
        canvas.toBlob(
          async (blob) => {
            try {
              if (blob) {
                await ingestCameraFrame(cameraId, blob);
              }
            } catch {
              // Ignore transient upload drops
            } finally {
              isPosting = false;
            }
          },
          'image/jpeg',
          0.65
        );
      }, 120);
    } catch (err) {
      console.error('[WebCam] Access error:', err);
      setWebcamError(err.message || 'Unable to access device webcam. Please grant browser camera permission.');
    }
  };

  const handleFullscreen = () => {
    if (containerRef.current) {
      if (!document.fullscreenElement) {
        containerRef.current.requestFullscreen().catch(() => {});
      } else {
        document.exitFullscreen();
      }
    }
  };

  return (
    <div className="relative group">
      {/* Ambient Projection Halo (simulates VisionOS media back-glow) */}
      <div className="absolute -inset-1 bg-gradient-to-r from-sky-400/20 via-indigo-500/15 to-emerald-400/20 rounded-[2.2rem] blur-2xl opacity-60 group-hover:opacity-85 transition-opacity duration-700 pointer-events-none" />

      <div
        ref={containerRef}
        className="neo-glass specular-rim rounded-3xl overflow-hidden flex flex-col transition-all shadow-[0_28px_70px_-15px_rgba(15,23,42,0.12)] border border-white/90 relative z-10"
      >
        {/* Top Header Bar — Neo-Glass Control Surface */}
        <div className="px-6 py-4 border-b border-white/60 flex flex-wrap items-center justify-between gap-4 bg-white/75 backdrop-blur-xl">
          {/* Camera Identity & Feed Switcher */}
          <div className="flex items-center space-x-3.5">
            <div className="flex items-center space-x-2.5">
              <span className="relative flex h-2.5 w-2.5">
                <span
                  className={`relative inline-flex rounded-full h-2.5 w-2.5 ${
                    isOnline
                      ? 'bg-emerald-500 radar-beacon'
                      : 'bg-rose-500'
                  }`}
                />
              </span>
              <span className="font-extrabold text-base text-slate-900 tracking-tight font-display">
                {camera?.name || cameraId}
              </span>
              <span className="text-xs text-slate-400 font-sans font-medium">
                ({camera?.location || 'Sector Zero'})
              </span>
            </div>

            <span className="text-xs font-telemetry font-bold text-slate-700 bg-white/95 px-3 py-1 rounded-full border border-white shadow-2xs">
              {fps} FPS
            </span>

            {/* Tactile Camera Switcher Pills */}
            {cameras.length > 1 && onSelectCamera && (
              <div className="apple-segmented-control ml-1">
                {cameras.map((c) => (
                  <button
                    key={c.camera_id}
                    onClick={() => onSelectCamera(c.camera_id)}
                    className={`apple-segmented-btn text-xs py-1 px-3 font-mono flex items-center space-x-1.5 ${
                      c.camera_id === cameraId ? 'active font-bold text-sky-600' : ''
                    }`}
                    title={`${c.camera_id}: ${c.name}`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        c.status === 'ONLINE' ? 'bg-emerald-500' : 'bg-slate-300'
                      }`}
                    />
                    <span>{c.camera_id}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Center / Right Unified Controls */}
          <div className="flex items-center space-x-2.5 flex-wrap gap-y-2">
            {/* C2 Mission Mode Segmented Control */}
            <div className="apple-segmented-control shadow-xs">
              {SURVEILLANCE_MODES.map((sm) => (
                <button
                  key={sm.id}
                  onClick={() => handleSelectSurveillanceMode(sm.id)}
                  disabled={isLoading}
                  className={`apple-segmented-btn ${
                    surveillanceMode === sm.id ? 'active' : ''
                  }`}
                >
                  {sm.label}
                </button>
              ))}
            </div>

            {/* Optical Filter Segmented Control */}
            <div className="apple-segmented-control hidden sm:inline-flex shadow-xs">
              {OPTICAL_MODES.map((m) => (
                <button
                  key={m.id}
                  onClick={() => handleSelectOpticalMode(m.id)}
                  className={`apple-segmented-btn ${
                    opticalMode === m.id ? 'active' : ''
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>

            {/* Border Tripwire Toggle */}
            <button
              onClick={handleToggleTripwire}
              disabled={isTripwireToggling}
              className={`px-3.5 py-1.5 rounded-full text-xs font-semibold border transition-all flex items-center space-x-1.5 shadow-xs ${
                tripwireEnabled
                  ? 'bg-sky-500/10 text-sky-700 border-sky-300 font-bold'
                  : 'bg-white/80 text-slate-500 border-slate-200 hover:text-slate-900'
              }`}
              title="Toggle Directional Zero-Line Tripwire"
            >
              <Crosshair className="w-3.5 h-3.5 stroke-[2.2]" />
              <span>{tripwireEnabled ? 'Tripwire: ON' : 'Tripwire: OFF'}</span>
            </button>

            {/* Device WebCam Stream Ingestion */}
            <button
              onClick={handleToggleWebcam}
              className={`px-3.5 py-1.5 rounded-full text-xs font-semibold border transition-all flex items-center space-x-1.5 shadow-xs ${
                isWebcamActive
                  ? 'bg-emerald-500 text-white border-emerald-600 font-bold radar-beacon'
                  : 'bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100 hover:border-indigo-300'
              }`}
              title={isWebcamActive ? 'Disconnect Device WebCam' : 'Stream your device/laptop camera directly into this tactical feed'}
            >
              {isWebcamActive ? (
                <>
                  <VideoOff className="w-3.5 h-3.5" />
                  <span>WebCam Active</span>
                </>
              ) : (
                <>
                  <Video className="w-3.5 h-3.5 text-indigo-600" />
                  <span>Use Device WebCam</span>
                </>
              )}
            </button>

            {/* Camera Power Toggle */}
            <button
              onClick={handleToggleCamera}
              disabled={isLoading}
              className={`p-2 rounded-full border text-xs transition-all shadow-xs ${
                isOnline
                  ? 'bg-rose-50 border-rose-200 text-rose-600 hover:bg-rose-100'
                  : 'gel-btn-primary'
              }`}
              title={isOnline ? 'Turn Camera Off' : 'Turn Camera On'}
            >
              <Power className="w-4 h-4" />
            </button>

            {/* Tools */}
            <button
              onClick={handleRefresh}
              className="p-2 text-slate-500 hover:text-slate-900 bg-white/80 hover:bg-white rounded-full transition-colors border border-white shadow-xs"
              title="Refresh Stream"
            >
              <RefreshCw className="w-4 h-4" />
            </button>

            <button
              onClick={handleFullscreen}
              className="p-2 text-slate-500 hover:text-slate-900 bg-white/80 hover:bg-white rounded-full transition-colors border border-white shadow-xs"
              title="Fullscreen"
            >
              <Maximize2 className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Auth Error Banner */}
        {authError && (
          <div className="px-6 py-3 bg-rose-50 border-b border-rose-200 text-rose-700 text-xs font-semibold flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <AlertTriangle className="w-4 h-4 shrink-0 text-rose-600" />
              <span>{authError}</span>
            </div>
            <button
              onClick={() => setAuthError(null)}
              className="text-rose-600 hover:text-rose-800 font-semibold text-xs ml-2"
            >
              ✕
            </button>
          </div>
        )}

        {/* Main Video Viewport — Engineered Obsidian Bezel with Inner Bevel */}
        <div className="relative bg-[#06080F] min-h-[460px] lg:min-h-[520px] flex items-center justify-center overflow-hidden border-t border-b border-slate-900/60 shadow-[inset_0_2px_16px_rgba(0,0,0,0.9)]">
          {/* Subtle Tactical HUD Scanline */}
          <div className="hud-scanline z-10" />

          {/* Tactical Precision Corner Reticles */}
          <div className="absolute top-4 left-4 w-6 h-6 border-t-2 border-l-2 border-sky-400/80 pointer-events-none z-20 shadow-[0_0_10px_rgba(56,189,248,0.4)]" />
          <div className="absolute top-4 right-4 w-6 h-6 border-t-2 border-r-2 border-sky-400/80 pointer-events-none z-20 shadow-[0_0_10px_rgba(56,189,248,0.4)]" />
          <div className="absolute bottom-4 left-4 w-6 h-6 border-b-2 border-l-2 border-sky-400/80 pointer-events-none z-20 shadow-[0_0_10px_rgba(56,189,248,0.4)]" />
          <div className="absolute bottom-4 right-4 w-6 h-6 border-b-2 border-r-2 border-sky-400/80 pointer-events-none z-20 shadow-[0_0_10px_rgba(56,189,248,0.4)]" />

          {/* Floating Top HUD Glass Metadata Badges */}
          <div className="absolute top-5 left-6 z-20 flex items-center space-x-2">
            <div className="px-3.5 py-1.5 rounded-full bg-black/70 backdrop-blur-xl border border-white/20 flex items-center space-x-2.5 text-white shadow-2xl">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 radar-beacon" />
              <span className="font-telemetry text-xs font-bold tracking-wider">{cameraId}</span>
              <span className="text-[10px] text-sky-400 font-telemetry font-bold tracking-widest uppercase">| C2 ACTIVE</span>
            </div>
          </div>

          <div className="absolute top-5 right-6 z-20 hidden sm:flex items-center space-x-2">
            <div className="px-3.5 py-1.5 rounded-full bg-black/70 backdrop-blur-xl border border-white/20 text-white/95 font-telemetry text-xs shadow-2xl flex items-center space-x-2.5">
              <span className="font-bold text-sky-400 uppercase tracking-wider">{opticalMode}</span>
              <span className="text-white/30">•</span>
              <span className="text-emerald-400 font-bold">{fps} FPS</span>
              <span className="text-white/30">•</span>
              <span className="text-slate-300 text-[11px] font-mono">1080p AI</span>
            </div>
          </div>

          {/* Floating Bottom Action Dock inside viewport */}
          <div className="absolute bottom-5 right-6 z-20 hidden md:flex items-center space-x-2">
            <div className="px-2.5 py-1.5 rounded-full bg-black/60 backdrop-blur-xl border border-white/20 text-white flex items-center space-x-1.5 shadow-xl">
              <button
                onClick={handleRefresh}
                className="p-1.5 hover:bg-white/20 rounded-full transition-colors text-white/80 hover:text-white"
                title="Refresh Stream"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={handleFullscreen}
                className="p-1.5 hover:bg-white/20 rounded-full transition-colors text-white/80 hover:text-white"
                title="Fullscreen"
              >
                <Maximize2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

        {/* Offscreen canvas for capturing client webcam frames to send to cloud AI */}
        <canvas ref={localCanvasRef} className="hidden" />

        {/* WebCam Error Notification */}
        {webcamError && (
          <div className="absolute top-16 left-6 right-6 bg-rose-600/90 backdrop-blur-xl text-white px-5 py-3 rounded-2xl flex items-center justify-between text-xs font-semibold shadow-2xl border border-rose-400/40 z-30 animate-fadeIn">
            <div className="flex items-center space-x-2.5">
              <AlertTriangle className="w-4 h-4 text-white" />
              <span>{webcamError}</span>
            </div>
            <button
              onClick={() => setWebcamError(null)}
              className="text-white/80 hover:text-white text-sm font-bold ml-3"
            >
              ✕
            </button>
          </div>
        )}

        {isOnline ? (
          <>
            {isWebcamActive ? (
              <div className="relative w-full h-full flex items-center justify-center bg-slate-950">
                <video
                  ref={(el) => {
                    localVideoRef.current = el;
                    if (el && mediaStreamRef.current && el.srcObject !== mediaStreamRef.current) {
                      el.srcObject = mediaStreamRef.current;
                      el.play().catch(() => {});
                    }
                  }}
                  autoPlay
                  playsInline
                  muted
                  className="w-full h-full object-contain select-none"
                />

                {/* Tactical HUD Overlay for Active Client Camera */}
                <div className="absolute top-4 left-6 z-20 flex items-center space-x-2 bg-emerald-500/90 backdrop-blur-md text-white text-[11px] font-bold px-3.5 py-1 rounded-full border border-emerald-400 shadow-md">
                  <span className="w-2 h-2 rounded-full bg-white animate-ping" />
                  <span>Device WebCam Active • Live Ingestion</span>
                </div>

                {/* Tactical Disconnect Button */}
                <button
                  onClick={handleToggleWebcam}
                  className="absolute bottom-6 left-1/2 -translate-x-1/2 z-20 flex items-center space-x-2 px-5 py-2 rounded-full bg-rose-600/95 hover:bg-rose-500 text-white font-extrabold text-xs shadow-2xl border border-rose-400/50 backdrop-blur-xl transition-all transform hover:scale-105 active:scale-95"
                  title="Disconnect laptop camera and revert to radar surveillance feed"
                >
                  <VideoOff className="w-4 h-4" />
                  <span>Disconnect WebCam</span>
                </button>

                {/* Border Tripwire Overlay on Client Video */}
                {tripwireEnabled && (
                  <div className="absolute inset-0 pointer-events-none z-10 flex flex-col justify-center">
                    <div
                      className="absolute left-0 right-0 border-b-2 border-dashed border-sky-400 shadow-[0_0_12px_rgba(56,189,248,0.9)]"
                      style={{ top: `${(camera?.tripwire_y_ratio || 0.65) * 100}%` }}
                    >
                      <span className="absolute right-4 -top-5 px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-sky-500/90 text-white backdrop-blur-md">
                        BORDER TRIPWIRE ACTIVE
                      </span>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <>
                <img
                  key={`${cameraId}-${refreshKey}`}
                  src={streamSrc}
                  alt="Live Camera Feed"
                  className="w-full h-full object-contain select-none pointer-events-none"
                />
                {/* Quick WebCam Stream Activator Pill when WebCam is idle */}
                <button
                  onClick={handleToggleWebcam}
                  className="absolute bottom-6 left-1/2 -translate-x-1/2 z-20 flex items-center space-x-2.5 px-6 py-2.5 rounded-full bg-emerald-600/95 hover:bg-emerald-500 text-white font-extrabold text-xs shadow-2xl border border-emerald-400/50 backdrop-blur-xl transition-all transform hover:scale-105 active:scale-95 animate-pulse"
                  title="Connect your laptop or mobile camera directly to this tactical feed"
                >
                  <Video className="w-4 h-4" />
                  <span>📷 Connect Laptop / Device WebCam</span>
                </button>
              </>
            )}
          </>
        ) : (
          <div className="flex flex-col items-center justify-center p-10 text-center space-y-4">
            <div className="w-16 h-16 rounded-3xl bg-white/5 border border-white/10 flex items-center justify-center text-white/50 shadow-inner">
              <Camera className="w-8 h-8 stroke-[1.8]" />
            </div>
            <div>
              <h4 className="text-base font-bold text-white tracking-tight">
                Camera Feed Offline
              </h4>
              <p className="text-xs text-white/60 mt-1 max-w-sm">
                Surveillance stream is halted. Click below to initialize DirectShow frame ingestion.
              </p>
            </div>
            <button
              onClick={handleTurnOnCamera}
              disabled={isLoading}
              className="gel-btn-primary px-6 py-2.5 text-xs shadow-lg"
            >
              Start Live Monitoring
            </button>
          </div>
        )}

        {/* Floating Spatial Alert Overlays */}
        {isPerimeterBreached && (
          <div className="absolute top-16 left-6 right-6 bg-rose-600/90 backdrop-blur-xl text-white px-5 py-3 rounded-2xl flex items-center justify-between text-xs font-bold shadow-2xl border border-rose-400/40 z-20 animate-fadeIn">
            <div className="flex items-center space-x-3">
              <ShieldAlert className="w-5 h-5 text-white" />
              <span className="tracking-wide">BORDER TRIPWIRE BREACH DETECTED</span>
            </div>
            <span className="font-mono text-xs bg-white/20 px-2.5 py-1 rounded-full text-white">Inbound Vector</span>
          </div>
        )}

        {isTampered && !isPerimeterBreached && (
          <div className="absolute top-16 left-6 right-6 bg-amber-500/90 backdrop-blur-xl text-white px-5 py-3 rounded-2xl flex items-center justify-between text-xs font-bold shadow-2xl border border-amber-300/40 z-20 animate-fadeIn">
            <div className="flex items-center space-x-3">
              <AlertTriangle className="w-5 h-5 text-white" />
              <span className="tracking-wide">CAMERA LENS OCCLUSION / TAMPERING DETECTED</span>
            </div>
            <span className="font-mono text-xs bg-white/20 px-2.5 py-1 rounded-full text-white">Low Frame Variance</span>
          </div>
        )}

        {isLoitering && !isPerimeterBreached && !isTampered && (
          <div className="absolute top-16 left-6 right-6 bg-indigo-600/90 backdrop-blur-xl text-white px-5 py-3 rounded-2xl flex items-center justify-between text-xs font-bold shadow-2xl border border-indigo-400/40 z-20 animate-fadeIn">
            <div className="flex items-center space-x-3">
              <Timer className="w-5 h-5 text-white" />
              <span className="tracking-wide">SUSTAINED PRESENCE / LOITERING ({formatTime(dwellSeconds)})</span>
            </div>
            <span className="font-mono text-xs bg-white/20 px-2.5 py-1 rounded-full text-white">&gt;25s Dwell Threshold</span>
          </div>
        )}

        {/* Live Vehicle Detection & ANPR Checkpoint Overlay Banner */}
        {vehicles.length > 0 && !isPerimeterBreached && !isTampered && (
          <div
            className={`absolute top-16 left-6 right-6 backdrop-blur-xl px-5 py-3 rounded-2xl flex items-center justify-between text-xs font-bold shadow-2xl transition-all border border-white/30 z-20 animate-fadeIn ${
              hasSuspectVehicle
                ? 'bg-rose-600/95 text-white animate-pulse'
                : vehicles[0]?.plate_number
                ? 'bg-emerald-600/95 text-white'
                : 'bg-blue-600/95 text-white'
            }`}
          >
            <div className="flex items-center space-x-3 min-w-0">
              <Truck className="w-5 h-5 shrink-0 text-white" />
              <span className="truncate">
                {hasSuspectVehicle
                  ? `🚨 SUSPECT VEHICLE INTERCEPT: ${vehicles[0]?.plate_number || 'UNKNOWN'} [RED NOTICE]`
                  : vehicles[0]?.plate_number
                  ? `VEHICLE DETECTED: ${vehicles[0]?.vehicle_type?.toUpperCase()} • PLATE: ${vehicles[0]?.plate_number} [STORED IN DATABASE]`
                  : `VEHICLE DETECTED: ${vehicles[0]?.vehicle_type?.toUpperCase()} • READING NUMBER PLATE...`}
              </span>
            </div>
            <div className="flex items-center space-x-2.5 shrink-0 ml-3">
              <span className="font-mono text-xs bg-black/30 px-3 py-1 rounded-full text-white">
                {vehicles[0]?.plate_number ? 'STORED IN SQLITE' : 'ANPR SCANNING'}
              </span>
              {vehicles[0]?.plate_number && onOpenVehicleDB && (
                <button
                  type="button"
                  onClick={() => onOpenVehicleDB(vehicles[0].plate_number)}
                  className="px-3.5 py-1 rounded-full bg-white/20 hover:bg-white/30 text-white text-xs font-bold transition-all flex items-center space-x-1 cursor-pointer shadow-sm active:scale-95"
                >
                  <span>Search in DB ↗</span>
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Bottom Summary Bar — Neo-Glass Well Operational Status */}
      <div className="bg-white/70 backdrop-blur-md px-6 py-4 border-t border-white/60 flex flex-wrap items-center justify-between text-xs text-gray-500">
        <div className="flex items-center space-x-2.5">
          <span className="font-bold text-gray-800 text-xs sm:text-[13px]">
            {surveillanceMode === 'CHECKPOST'
              ? 'Vehicles in View:'
              : surveillanceMode === 'UNIFIED'
              ? 'Activity in View:'
              : 'Personnel in View:'}
          </span>
          {surveillanceMode === 'CHECKPOST' ? (
            vehicles.length > 0 ? (
              <span className="font-bold text-gray-900 flex items-center space-x-2">
                <span>{vehicles[0]?.vehicle_type}</span>
                {vehicles[0]?.plate_number ? (
                  <button
                    type="button"
                    onClick={() => onOpenVehicleDB && onOpenVehicleDB(vehicles[0].plate_number)}
                    className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-emerald-500/10 text-emerald-700 font-bold border border-emerald-300 hover:bg-emerald-500/20 transition-colors cursor-pointer flex items-center space-x-1"
                    title="Click to search in Vehicle Passage Database"
                  >
                    <span>{vehicles[0].plate_number} (STORED) ↗</span>
                  </button>
                ) : (
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-amber-500/10 text-amber-700 border border-amber-300 font-semibold">
                    Scanning Plate...
                  </span>
                )}
              </span>
            ) : (
              <span className="text-gray-400 font-medium">None</span>
            )
          ) : surveillanceMode === 'UNIFIED' ? (
            <span className="font-bold text-gray-800">
              {detections.length} people • {vehicles.length} {vehicles.length === 1 ? 'vehicle' : 'vehicles'}
              {vehicles[0]?.plate_number ? ` [${vehicles[0].plate_number}] (STORED)` : ''}
            </span>
          ) : detections.length > 0 ? (
            <span className="font-bold text-gray-800">
              {detections.length} {detections.length === 1 ? 'person' : 'people'} (
              {isAuthorized ? 'Authorized Guard' : hasSuspect ? 'Wanted Suspect' : 'Visitor'})
            </span>
          ) : (
            <span className="text-gray-400 font-medium">Area clear</span>
          )}
        </div>

        <div className="flex items-center space-x-4 text-xs text-gray-400 font-mono">
          <span>Mode: <strong className="text-gray-800 font-bold">{surveillanceMode}</strong></span>
          <span>Optics: <strong className="text-gray-800 font-bold">{opticalMode}</strong></span>
          <span>Zero-Line: <strong className="text-gray-800 font-bold">{tripwireEnabled ? 'Armed' : 'Disarmed'}</strong></span>
        </div>
      </div>
    </div>
  </div>
  );
}
