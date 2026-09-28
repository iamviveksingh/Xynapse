import React from 'react';
import { Eye, CheckCircle, X, ShieldAlert, Timer, User, Truck, AlertTriangle } from 'lucide-react';
import { getAuthenticatedMediaUrl } from '../services/api';

export default function DetectionPopupModal({ alert, onViewFull, onAcknowledge, onDismiss }) {
  if (!alert) return null;

  const confPercent = Math.round((alert.confidence || 0) * 100);
  const timeStr = alert.timestamp
    ? new Date(alert.timestamp).toLocaleTimeString([], { hour12: false })
    : 'Just now';

  const isSuspect = alert.event_type === 'SUSPECT_DETECTED';
  const isIntrusion = alert.event_type === 'BORDER_INTRUSION';
  const isLoitering = alert.event_type === 'SUSPICIOUS_LOITERING';
  const isTampered = alert.event_type === 'CAMERA_TAMPERED';
  const isStolenVehicle = alert.event_type === 'SUSPECT_VEHICLE_INTERCEPT';
  const isVehicle = alert.event_type === 'VEHICLE_DETECTED';

  const config = isSuspect
    ? {
        badge: 'CRITICAL',
        badgeClass: 'bg-rose-500/10 text-rose-600 border border-rose-300',
        title: 'Wanted Suspect Identified',
        description: 'Biometric facial recognition matched an enrolled high-priority target.',
        icon: ShieldAlert,
        iconBg: 'bg-rose-500/15 text-rose-600'
      }
    : isIntrusion
    ? {
        badge: 'CRITICAL',
        badgeClass: 'bg-rose-500/10 text-rose-600 border border-rose-300',
        title: 'Border Zero-Line Breached',
        description: 'Directional tripwire vector indicates an unauthorized inbound boundary crossing.',
        icon: ShieldAlert,
        iconBg: 'bg-rose-500/15 text-rose-600'
      }
    : isTampered
    ? {
        badge: 'WARNING',
        badgeClass: 'bg-amber-500/10 text-amber-600 border border-amber-300',
        title: 'Camera Lens Occlusion',
        description: 'Sudden loss of frame variance. The camera lens may be covered or obstructed.',
        icon: AlertTriangle,
        iconBg: 'bg-amber-500/15 text-amber-600'
      }
    : isLoitering
    ? {
        badge: 'WARNING',
        badgeClass: 'bg-indigo-500/10 text-indigo-600 border border-indigo-300',
        title: 'Sustained Presence (Loitering)',
        description: 'A person has remained in the monitored zone for longer than the 25-second dwell threshold.',
        icon: Timer,
        iconBg: 'bg-indigo-500/15 text-indigo-600'
      }
    : isStolenVehicle
    ? {
        badge: 'CRITICAL',
        badgeClass: 'bg-rose-500/10 text-rose-600 border border-rose-300',
        title: 'Wanted Vehicle Intercept',
        description: 'ANPR plate scanner matched an active red-notice vehicle at the checkpost.',
        icon: Truck,
        iconBg: 'bg-rose-500/15 text-rose-600'
      }
    : isVehicle
    ? {
        badge: 'INFORMATIONAL',
        badgeClass: 'bg-blue-500/10 text-blue-600 border border-blue-300',
        title: 'Checkpost Vehicle Logged',
        description: 'Vehicle transit detected and license plate recorded in the checkpost ledger.',
        icon: Truck,
        iconBg: 'bg-blue-500/15 text-blue-600'
      }
    : {
        badge: 'INFORMATIONAL',
        badgeClass: 'bg-blue-500/10 text-blue-600 border border-blue-300',
        title: 'Human Detection Logged',
        description: 'Human presence detected. High-resolution evidence snapshot archived.',
        icon: User,
        iconBg: 'bg-blue-500/15 text-blue-600'
      };

  const Icon = config.icon;

  return (
    <div className="spatial-modal-backdrop animate-fadeIn">
      <div className="neo-glass-elevated w-full max-w-lg overflow-hidden shadow-2xl flex flex-col relative border border-white/80">
        {/* Top Iridescent Reflection */}
        <div className="absolute top-0 inset-x-0 h-1.5 bg-gradient-to-r from-blue-500 via-indigo-500 to-pink-500 opacity-70" />

        {/* Header */}
        <div className="px-7 py-5 border-b border-gray-100 flex items-center justify-between bg-white/70">
          <div className="flex items-center space-x-4">
            <div className={`w-11 h-11 rounded-2xl flex items-center justify-center shadow-xs ${config.iconBg}`}>
              <Icon className="w-5 h-5 stroke-[2.2]" />
            </div>
            <div>
              <div className="flex items-center space-x-2.5">
                <h3 className="font-extrabold text-base text-gray-900 tracking-tight">
                  {config.title}
                </h3>
                <span className={`text-[10px] font-mono font-bold px-2.5 py-0.5 rounded-full uppercase tracking-wider ${config.badgeClass}`}>
                  {config.badge}
                </span>
              </div>
              <p className="text-xs text-gray-400 mt-0.5 truncate max-w-xs font-mono font-medium">
                {alert.objects_detected || alert.camera_id}
              </p>
            </div>
          </div>
          <button
            onClick={onDismiss}
            className="p-2 rounded-full text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-7 space-y-5 text-xs">
          <div className="bg-white/80 p-4 rounded-2xl border border-white text-gray-600 leading-relaxed font-medium shadow-xs">
            {config.description}
          </div>

          {/* Snapshot Preview */}
          {alert.snapshot && (
            <div className="relative rounded-2xl overflow-hidden border border-slate-900/40 bg-[#06080F] max-h-[240px] flex items-center justify-center shadow-inner">
              <img
                src={getAuthenticatedMediaUrl(alert.snapshot)}
                alt="Alert snapshot"
                onError={(e) => { e.target.style.display = 'none'; }}
                className="w-full h-full object-contain max-h-[240px]"
              />
            </div>
          )}

          {/* Quick Metrics */}
          <div className="grid grid-cols-3 gap-3">
            <div className="bg-white/80 p-3 rounded-2xl border border-white shadow-2xs">
              <span className="text-gray-400 block text-[10px] font-mono uppercase font-bold">Camera</span>
              <span className="font-bold text-gray-800 mt-0.5 block font-mono text-xs">{alert.camera_id}</span>
            </div>
            <div className="bg-white/80 p-3 rounded-2xl border border-white shadow-2xs">
              <span className="text-gray-400 block text-[10px] font-mono uppercase font-bold">Time</span>
              <span className="font-bold text-gray-800 mt-0.5 block font-mono text-xs">{timeStr}</span>
            </div>
            <div className="bg-white/80 p-3 rounded-2xl border border-white shadow-2xs">
              <span className="text-gray-400 block text-[10px] font-mono uppercase font-bold">Confidence</span>
              <span className="font-extrabold text-emerald-600 mt-0.5 block font-mono text-xs">{confPercent}%</span>
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="px-7 py-4.5 bg-white/70 border-t border-gray-100 flex items-center justify-between gap-3">
          <button
            onClick={() => onAcknowledge(alert.id || alert.alert_id)}
            className="gel-btn-primary flex items-center space-x-2 px-5 py-2.5 text-xs shadow-md"
          >
            <CheckCircle className="w-4 h-4 stroke-[2]" />
            <span>Acknowledge</span>
          </button>

          <div className="flex items-center space-x-2.5">
            <button
              onClick={() => onViewFull(alert)}
              className="gel-btn-secondary px-4 py-2.5 text-xs"
            >
              Full Details
            </button>
            <button
              onClick={onDismiss}
              className="px-4 py-2.5 rounded-full text-gray-500 hover:text-gray-900 text-xs font-semibold transition-colors"
            >
              Dismiss
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
