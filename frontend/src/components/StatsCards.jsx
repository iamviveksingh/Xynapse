import React from 'react';
import { UserCheck, Truck, ShieldAlert, Video, ArrowUpRight } from 'lucide-react';

export default function StatsCards({
  stats,
  totalCameras = 1,
  onlineCameras = 1,
  faceCount = 0,
  vehicleCount = 0,
  onOpenVehicleDB
}) {
  const activeAlerts = stats?.active_alerts ?? 0;
  const todayDetections = stats?.today_detections ?? 0;

  const instruments = [
    {
      id: 'people',
      label: 'PEOPLE DETECTED',
      value: todayDetections > 0 ? String(todayDetections).padStart(2, '0') : '00',
      unit: 'LIVE PERCEPTION',
      sub: todayDetections > 0 ? 'Active Ingestion' : 'Zero Breaches',
      icon: UserCheck,
      pipColor: 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.7)]',
      highlight: false,
      accentGlow: 'from-blue-500/10 to-emerald-500/10'
    },
    {
      id: 'vehicles',
      label: 'VEHICLES MONITORED',
      value: vehicleCount > 0 ? String(vehicleCount).padStart(2, '0') : '00',
      unit: 'ANPR CHECKPOST',
      sub: 'Passage DB & Watchlist',
      icon: Truck,
      pipColor: 'bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.7)]',
      highlight: false,
      onClick: onOpenVehicleDB,
      actionable: true,
      accentGlow: 'from-blue-500/10 to-indigo-500/10'
    },
    {
      id: 'alerts',
      label: 'ACTIVE EVENTS',
      value: activeAlerts > 0 ? String(activeAlerts).padStart(2, '0') : '00',
      unit: activeAlerts > 0 ? 'CRITICAL TRIAGE' : 'ALL CLEAR',
      sub: activeAlerts > 0 ? `${activeAlerts} unreviewed` : 'Standby Sentry',
      icon: ShieldAlert,
      pipColor: activeAlerts > 0 ? 'bg-rose-500 shadow-[0_0_10px_rgba(244,63,94,0.8)] animate-pulse' : 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.7)]',
      highlight: activeAlerts > 0,
      accentGlow: activeAlerts > 0 ? 'from-rose-500/15 to-amber-500/15' : 'from-emerald-500/10 to-teal-500/10'
    },
    {
      id: 'feeds',
      label: 'SURVEILLANCE FEEDS',
      value: `${onlineCameras}/${totalCameras}`,
      unit: 'DIRECTSHOW / RTSP',
      sub: onlineCameras === totalCameras ? '100% Operational' : `${totalCameras - onlineCameras} Offline`,
      icon: Video,
      pipColor: onlineCameras === totalCameras ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.7)]' : 'bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.7)]',
      highlight: false,
      accentGlow: 'from-sky-500/10 to-violet-500/10',
      feedCount: totalCameras,
      onlineCount: onlineCameras
    }
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-5 py-2">
      {instruments.map((inst) => {
        const Icon = inst.icon;
        return (
          <div
            key={inst.id}
            onClick={inst.onClick ? () => inst.onClick() : undefined}
            className={`neo-glass neo-glass-hover specular-rim p-6 rounded-3xl flex flex-col justify-between relative group overflow-hidden transition-all duration-300 ${
              inst.onClick ? 'cursor-pointer hover:border-blue-300' : ''
            }`}
          >
            {/* Ambient Corner Reflection */}
            <div className={`absolute -right-8 -top-8 w-32 h-32 rounded-full bg-gradient-to-br ${inst.accentGlow} blur-2xl pointer-events-none transition-all duration-500 group-hover:scale-135 group-hover:opacity-100 opacity-70`} />

            {/* Top Row: Label & Indicator Pip */}
            <div className="flex items-center justify-between z-10">
              <div className="flex items-center space-x-2.5">
                <span className="relative flex h-2.5 w-2.5">
                  {inst.highlight && (
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75" />
                  )}
                  <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${inst.pipColor}`} />
                </span>
                <span className="text-[11px] sm:text-xs font-display font-bold tracking-wider text-slate-500 uppercase">
                  {inst.label}
                </span>
              </div>
              {inst.actionable ? (
                <div className="w-8 h-8 rounded-full bg-white/95 text-blue-600 flex items-center justify-center transition-all duration-300 group-hover:scale-110 shadow-sm border border-white group-hover:bg-blue-600 group-hover:text-white">
                  <ArrowUpRight className="w-4 h-4 stroke-[2.4]" />
                </div>
              ) : (
                <div className="w-8 h-8 rounded-full bg-white/70 text-slate-400 flex items-center justify-center shadow-2xs border border-white group-hover:text-slate-700 transition-colors">
                  <Icon className="w-4 h-4 stroke-[2]" />
                </div>
              )}
            </div>

            {/* Middle Row: Massive Readable Metric Number + Micro Sparkline Bar */}
            <div className="my-4 z-10 flex items-baseline justify-between">
              <div
                className={`text-4xl sm:text-5xl font-black font-display tracking-tight leading-none ${
                  inst.highlight ? 'text-rose-600' : 'text-slate-900'
                }`}
              >
                {inst.value}
              </div>

              {/* Tactical Micro-Visual Indicators */}
              {inst.id === 'feeds' ? (
                <div className="flex items-center space-x-1.5 bg-slate-100/80 px-2 py-1 rounded-lg border border-slate-200/50">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <span
                      key={i}
                      className={`w-1.5 h-3 rounded-full transition-all ${
                        i < (inst.onlineCount || 1)
                          ? 'bg-emerald-500 shadow-[0_0_4px_rgba(16,185,129,0.8)]'
                          : 'bg-slate-300'
                      }`}
                    />
                  ))}
                </div>
              ) : inst.id === 'people' ? (
                <div className="flex items-end space-x-1 h-6">
                  <span className="w-1 bg-emerald-400/50 h-2 rounded-full" />
                  <span className="w-1 bg-emerald-400/70 h-3.5 rounded-full" />
                  <span className="w-1 bg-emerald-500 h-5 rounded-full animate-pulse" />
                  <span className="w-1 bg-emerald-400/70 h-3 rounded-full" />
                </div>
              ) : inst.id === 'vehicles' ? (
                <div className="flex items-end space-x-1 h-6">
                  <span className="w-1 bg-sky-400/50 h-2.5 rounded-full" />
                  <span className="w-1 bg-sky-400/80 h-4 rounded-full" />
                  <span className="w-1 bg-sky-500 h-3 rounded-full" />
                  <span className="w-1 bg-sky-500 h-5 rounded-full" />
                </div>
              ) : (
                <div className="flex items-end space-x-1 h-6">
                  <span className="w-1 bg-amber-400/50 h-2 rounded-full" />
                  <span className="w-1 bg-amber-400/70 h-3 rounded-full" />
                  <span className={`w-1 rounded-full ${inst.highlight ? 'bg-rose-500 h-5 animate-pulse' : 'bg-slate-300 h-1.5'}`} />
                </div>
              )}
            </div>

            {/* Bottom Row: Metadata & State */}
            <div className="pt-3 border-t border-slate-100/90 flex items-center justify-between text-xs z-10">
              <span className="font-mono text-slate-400 font-bold tracking-wider uppercase text-[11px]">
                {inst.unit}
              </span>
              <span className={`font-semibold truncate text-[12px] ${inst.highlight ? 'text-rose-600 font-bold' : 'text-slate-600'}`}>
                {inst.sub}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
