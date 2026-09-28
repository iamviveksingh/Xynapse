import React from 'react';
import { Activity, ShieldAlert, AlertTriangle, User, Radio, ChevronRight } from 'lucide-react';

export default function LiveDetectionLog({ liveDetections = [], onViewAlert, onAcknowledge }) {
  return (
    <div className="neo-glass glass-specular-rim rounded-3xl overflow-hidden flex flex-col h-full border border-white/90 shadow-[0_28px_70px_-15px_rgba(15,23,42,0.08)]">
      {/* Header */}
      <div className="px-6 py-4 border-b border-white/60 flex items-center justify-between bg-white/70 backdrop-blur-xl">
        <div className="flex items-center space-x-2.5">
          <div className="w-8 h-8 rounded-xl bg-sky-500/10 text-sky-600 flex items-center justify-center border border-sky-200/50 shadow-2xs">
            <Activity className="w-4 h-4 stroke-[2.4]" />
          </div>
          <h3 className="font-extrabold text-base text-slate-900 tracking-tight">
            Operational Stream
          </h3>
        </div>
        <div className="flex items-center space-x-2 px-3 py-1 rounded-full bg-white/90 text-slate-700 font-mono text-[11px] font-bold border border-white shadow-2xs">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span>REAL-TIME</span>
        </div>
      </div>

      {/* Events List */}
      <div className="divide-y divide-slate-100/80 overflow-y-auto max-h-[520px] flex-1 bg-white/40 backdrop-blur-md">
        {liveDetections.length === 0 ? (
          <div className="py-24 text-center text-slate-400 text-xs px-4 flex flex-col items-center justify-center space-y-3">
            <div className="w-12 h-12 rounded-2xl bg-white/80 border border-white flex items-center justify-center text-slate-300 shadow-xs">
              <User className="w-6 h-6 stroke-[1.8]" />
            </div>
            <p className="font-bold text-sm text-slate-700">No events logged</p>
            <p className="text-xs text-slate-400 max-w-xs leading-relaxed">
              DirectShow neural inferences and threat alerts will stream here in real time.
            </p>
          </div>
        ) : (
          liveDetections.slice(0, 20).map((item, idx) => {
            const timeStr = item.timestamp
              ? new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
              : 'Just now';

            const isCritical =
              item.event_type === 'SUSPECT_DETECTED' ||
              item.event_type === 'BORDER_INTRUSION' ||
              item.event_type === 'SUSPECT_VEHICLE_INTERCEPT' ||
              item.severity === 'CRITICAL';

            const isWarning =
              item.event_type === 'CAMERA_TAMPERED' ||
              item.event_type === 'CYBER_STREAM_TAMPERED' ||
              item.event_type === 'SUSPICIOUS_LOITERING' ||
              item.severity === 'HIGH';

            return (
              <div
                key={item.alert_id || idx}
                onClick={() => onViewAlert && onViewAlert(item)}
                className={`px-5 py-3.5 hover:bg-white/95 transition-all duration-200 cursor-pointer flex items-center justify-between gap-3 group border-l-4 ${
                  isCritical
                    ? 'border-l-rose-500 hover:bg-rose-50/20'
                    : isWarning
                    ? 'border-l-amber-500 hover:bg-amber-50/20'
                    : 'border-l-transparent hover:border-l-sky-500'
                }`}
              >
                <div className="flex items-center space-x-3 min-w-0">
                  {/* Status Indicator Pip */}
                  <span className="relative flex h-2.5 w-2.5 shrink-0">
                    {isCritical && (
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75" />
                    )}
                    <span
                      className={`relative inline-flex rounded-full h-2.5 w-2.5 ${
                        isCritical
                          ? 'bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.8)]'
                          : isWarning
                          ? 'bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.6)]'
                          : 'bg-emerald-500'
                      }`}
                    />
                  </span>

                  {/* Monospace Timestamp */}
                  <span className="font-mono text-xs text-slate-400 shrink-0 font-bold">
                    {timeStr}
                  </span>

                  {/* Event Label */}
                  <div className="truncate">
                    <span className="text-xs sm:text-[13px] font-semibold text-slate-800 group-hover:text-sky-600 transition-colors block truncate">
                      {item.objects_detected || item.event_type}
                    </span>
                  </div>
                </div>

                {/* Right Camera ID / Action Required Tag */}
                <div className="shrink-0 flex items-center space-x-2">
                  <span className="text-[11px] text-slate-600 font-mono bg-white/90 px-2.5 py-0.5 rounded-full border border-slate-200/60 font-bold shadow-2xs">
                    {item.camera_id || 'CAM-01'}
                  </span>
                  {item.status === 'NEW' && isCritical && (
                    <span className="text-[10px] font-bold text-white bg-rose-500 px-2 py-0.5 rounded-full uppercase tracking-wider font-mono shadow-sm shadow-rose-500/30 animate-pulse">
                      Action
                    </span>
                  )}
                  <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-slate-600 transition-transform group-hover:translate-x-0.5" />
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
