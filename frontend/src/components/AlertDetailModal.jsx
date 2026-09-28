import React, { useState } from 'react';
import { X, CheckCircle, ShieldCheck, Camera, AlertTriangle, ShieldAlert, Timer, Truck, User } from 'lucide-react';
import { acknowledgeAlert, resolveAlert, getAuthenticatedMediaUrl } from '../services/api';

export default function AlertDetailModal({ alert, onClose, onUpdated }) {
  const [isUpdating, setIsUpdating] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);
  const [imgFailed, setImgFailed] = useState(false);

  if (!alert) return null;

  const alertCode = alert.alert_id || `XP-${String(alert.id).padStart(6, '0')}`;
  const dateObj = alert.timestamp ? new Date(alert.timestamp) : new Date();
  const formattedDate = dateObj.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  });
  const formattedTime = dateObj.toLocaleTimeString([], { hour12: false });
  const isSuspect = alert.event_type === 'SUSPECT_DETECTED';
  const isIntrusion = alert.event_type === 'BORDER_INTRUSION';
  const isStolenVehicle = alert.event_type === 'SUSPECT_VEHICLE_INTERCEPT';
  const isVehicle = alert.event_type === 'VEHICLE_DETECTED';
  const isTampered = alert.event_type === 'CAMERA_TAMPERED';
  const isLoitering = alert.event_type === 'SUSPICIOUS_LOITERING';

  const handleAcknowledge = async () => {
    setIsUpdating(true);
    setErrorMessage(null);
    try {
      await acknowledgeAlert(alert.id || alertCode);
      if (onUpdated) onUpdated();
    } catch (err) {
      console.error('[Modal] Acknowledge failed:', err);
      setErrorMessage(err.detail || err.message || 'Administrative privileges required to acknowledge alerts.');
    } finally {
      setIsUpdating(false);
    }
  };

  const handleResolve = async () => {
    setIsUpdating(true);
    setErrorMessage(null);
    try {
      await resolveAlert(alert.id || alertCode);
      if (onUpdated) onUpdated();
    } catch (err) {
      console.error('[Modal] Resolve failed:', err);
      setErrorMessage(err.detail || err.message || 'Administrative privileges required to resolve alerts.');
    } finally {
      setIsUpdating(false);
    }
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case 'NEW':
        return (
          <span className="px-3 py-1 rounded-full bg-rose-500/10 text-rose-600 border border-rose-300 text-xs font-bold font-mono">
            Needs Review
          </span>
        );
      case 'ACKNOWLEDGED':
        return (
          <span className="px-3 py-1 rounded-full bg-amber-500/10 text-amber-600 border border-amber-300 text-xs font-bold font-mono">
            Under Review
          </span>
        );
      case 'RESOLVED':
        return (
          <span className="px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-600 border border-emerald-300 text-xs font-bold font-mono">
            Resolved / Safe
          </span>
        );
      default:
        return <span className="text-gray-400 text-xs font-mono">{status}</span>;
    }
  };

  const friendlyTitle = isSuspect
    ? 'Wanted Suspect Identified'
    : isIntrusion
    ? 'Restricted Border Line Breached'
    : isStolenVehicle
    ? 'Wanted Vehicle Intercept Warrant'
    : isVehicle
    ? 'Border Checkpost Vehicle Transit'
    : isTampered
    ? 'Camera Covered or Blocked'
    : isLoitering
    ? 'Sustained Presence (Loitering)'
    : 'Person Detected';

  const friendlyExplanation = isSuspect
    ? (alert.objects_detected || 'A person on the security watchlist was recognized by the biometric facial recognition system. Immediate armed interdiction ordered.')
    : isIntrusion
    ? (alert.objects_detected || 'An unauthorized person crossed the virtual border zero-line into the restricted buffer zone.')
    : isStolenVehicle
    ? (alert.objects_detected || 'Automatic Number Plate Recognition (ANPR) matched this vehicle with a red-notice intercept warrant at the border checkpost.')
    : isVehicle
    ? (alert.objects_detected || 'A vehicle passed through the automated checkpost camera feed and its license plate was logged.')
    : isTampered
    ? 'The camera view is blocked or obscured. Someone may have placed an object over the camera lens or sprayed paint.'
    : isLoitering
    ? 'A person was standing or lingering in this camera view for more than 25 seconds.'
    : 'A person was detected by the camera. The system captured photo evidence automatically.';

  return (
    <div className="spatial-modal-backdrop animate-fadeIn">
      <div className="neo-glass-elevated w-full max-w-2xl overflow-hidden shadow-2xl flex flex-col max-h-[90vh] relative border border-white/80">
        {/* Top Iridescent Reflection */}
        <div className="absolute top-0 inset-x-0 h-1.5 bg-gradient-to-r from-blue-500 via-indigo-500 to-pink-500 opacity-70" />

        {/* Header */}
        <div className="px-7 py-5 bg-white/70 border-b border-gray-100 flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <div className={`w-11 h-11 rounded-2xl flex items-center justify-center shadow-xs ${
              isSuspect || isIntrusion || isStolenVehicle
                ? 'bg-rose-500/15 text-rose-600'
                : isTampered
                ? 'bg-amber-500/15 text-amber-600'
                : isLoitering
                ? 'bg-indigo-500/15 text-indigo-600'
                : 'bg-blue-500/15 text-blue-600'
            }`}>
              {isSuspect || isIntrusion ? (
                <ShieldAlert className="w-5 h-5 stroke-[2.2]" />
              ) : isStolenVehicle || isVehicle ? (
                <Truck className="w-5 h-5 stroke-[2.2]" />
              ) : isTampered ? (
                <AlertTriangle className="w-5 h-5 stroke-[2.2]" />
              ) : isLoitering ? (
                <Timer className="w-5 h-5 stroke-[2.2]" />
              ) : (
                <User className="w-5 h-5 stroke-[2.2]" />
              )}
            </div>
            <div>
              <div className="flex items-center space-x-2.5">
                <h3 className="font-extrabold text-lg text-gray-900 tracking-tight">{friendlyTitle}</h3>
                <span className="text-xs font-mono font-bold text-gray-500 px-2.5 py-0.5 rounded-full bg-white/90 border border-gray-200">
                  {alertCode}
                </span>
              </div>
              <p className="text-xs text-gray-400 mt-0.5 font-medium">
                Incident Details & Photographic Evidence
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-full text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Error Banner */}
        {errorMessage && (
          <div className="mx-7 mt-4 p-3.5 rounded-2xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-semibold flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <AlertTriangle className="w-4 h-4 shrink-0 text-rose-600" />
              <span>{errorMessage}</span>
            </div>
            <button
              onClick={() => setErrorMessage(null)}
              className="text-rose-600 hover:text-rose-800 font-bold text-xs ml-2"
            >
              ✕
            </button>
          </div>
        )}

        {/* Content */}
        <div className="p-7 overflow-y-auto space-y-5">
          {/* Explanation Card */}
          <div className="bg-white/80 p-4.5 rounded-2xl border border-white text-gray-700 leading-relaxed font-medium shadow-xs">
            <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-gray-400 block mb-1">
              Operational Assessment:
            </span>
            <p className="text-xs sm:text-[13px] text-gray-800 leading-relaxed">
              {friendlyExplanation}
            </p>
          </div>

          {/* Quick Info Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div className="bg-white/80 p-3.5 rounded-2xl border border-white shadow-2xs">
              <span className="text-gray-400 block text-[10px] font-mono uppercase font-bold">Camera</span>
              <span className="font-extrabold text-gray-900 mt-1 block font-mono text-sm">{alert.camera_id}</span>
            </div>
            <div className="bg-white/80 p-3.5 rounded-2xl border border-white shadow-2xs">
              <span className="text-gray-400 block text-[10px] font-mono uppercase font-bold">Time</span>
              <span className="font-bold text-gray-900 mt-1 block font-mono text-xs">{formattedTime}</span>
            </div>
            <div className="bg-white/80 p-3.5 rounded-2xl border border-white shadow-2xs">
              <span className="text-gray-400 block text-[10px] font-mono uppercase font-bold">Date</span>
              <span className="font-bold text-gray-900 mt-1 block font-mono text-xs">{formattedDate}</span>
            </div>
            <div className="bg-white/80 p-3.5 rounded-2xl border border-white shadow-2xs">
              <span className="text-gray-400 block text-[10px] font-mono uppercase font-bold">Status</span>
              <div className="mt-1">{getStatusBadge(alert.status)}</div>
            </div>
            {(alert.plate_number || isStolenVehicle || isVehicle) && (
              <>
                <div className="bg-white/80 p-3.5 rounded-2xl border border-white shadow-2xs">
                  <span className="text-gray-400 block text-[10px] font-mono uppercase font-bold">License Plate</span>
                  <span className="font-mono font-extrabold text-gray-900 mt-1 block">{alert.plate_number || 'Detected'}</span>
                </div>
                <div className="bg-white/80 p-3.5 rounded-2xl border border-white shadow-2xs">
                  <span className="text-gray-400 block text-[10px] font-mono uppercase font-bold">Vehicle Type</span>
                  <span className="font-bold text-gray-900 mt-1 block">{alert.vehicle_type || 'Vehicle'}</span>
                </div>
              </>
            )}
          </div>

          {/* Snapshot Evidence */}
          <div>
            <div className="flex items-center justify-between mb-2.5">
              <span className="text-xs font-bold text-gray-800 flex items-center space-x-2">
                <Camera className="w-4 h-4 text-blue-600" />
                <span>Captured Snapshot Evidence</span>
              </span>
            </div>
            <div className="relative bg-[#06080F] rounded-2xl overflow-hidden border border-slate-800 flex items-center justify-center max-h-[350px] shadow-inner">
              {alert.snapshot && !imgFailed ? (
                <img
                  src={getAuthenticatedMediaUrl(alert.snapshot)}
                  alt={`Photo for ${alertCode}`}
                  onError={() => setImgFailed(true)}
                  className="w-full h-auto object-contain max-h-[350px]"
                />
              ) : (
                <div className="p-14 text-center text-gray-400 text-xs font-mono">
                  {imgFailed ? 'Snapshot image not found or access restricted' : 'No snapshot image saved'}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="px-7 py-4.5 bg-white/70 border-t border-gray-100 flex flex-wrap items-center justify-end gap-3">
          {alert.status === 'NEW' && (
            <button
              onClick={handleAcknowledge}
              disabled={isUpdating}
              className="flex items-center space-x-2 px-5 py-2.5 rounded-full bg-gradient-to-r from-amber-500 to-amber-400 text-white text-xs font-bold shadow-md shadow-amber-500/30 transition-all active:scale-95"
            >
              <CheckCircle className="w-4 h-4 stroke-[2]" />
              <span>Mark Reviewed</span>
            </button>
          )}

          {alert.status !== 'RESOLVED' && (
            <button
              onClick={handleResolve}
              disabled={isUpdating}
              className="gel-btn-success flex items-center space-x-2 px-5 py-2.5 text-xs shadow-md"
            >
              <ShieldCheck className="w-4 h-4 stroke-[2]" />
              <span>Resolve Alert</span>
            </button>
          )}

          <button
            onClick={onClose}
            className="gel-btn-secondary px-5 py-2.5 text-xs"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
