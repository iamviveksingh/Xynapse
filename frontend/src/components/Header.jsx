import React from 'react';
import { Maximize2, Shield, RefreshCw, Search } from 'lucide-react';

export default function Header({
  title,
  subtitle,
  cameraCount = 1,
  onlineCount = 1,
  wsStatus = 'CONNECTED',
  role = 'ADMIN',
  onRefresh,
  onOpenVehicleDB
}) {
  const handleFullscreen = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen();
    }
  };

  return (
    <header className="h-20 px-8 border-b border-white/70 bg-white/80 backdrop-blur-2xl flex items-center justify-between shrink-0 sticky top-0 z-20 shadow-[0_4px_30px_rgba(15,23,42,0.03)] specular-rim transition-all">
      <div>
        <h1 className="text-xl sm:text-2xl font-extrabold tracking-tight text-slate-900 font-display flex items-center gap-2.5">
          <span>{title}</span>
          <span className="text-[10px] font-mono uppercase tracking-widest px-2 py-0.5 rounded-full bg-sky-500/10 text-sky-600 border border-sky-500/20 font-bold hidden sm:inline-block">v1.9</span>
        </h1>
        {subtitle && (
          <p className="text-xs sm:text-[13px] text-slate-500 font-medium mt-0.5 font-sans">
            {subtitle}
          </p>
        )}
      </div>

      <div className="flex items-center space-x-3">
        {/* Search Plate Database Quick Action — Tactile Glass Search */}
        {onOpenVehicleDB && (
          <button
            onClick={() => onOpenVehicleDB()}
            className="flex items-center space-x-2 px-4 py-2 rounded-full bg-white/90 hover:bg-white text-sky-600 border border-sky-200/80 text-xs sm:text-[13px] font-semibold transition-all duration-200 shadow-sm hover:shadow-md hover:shadow-sky-500/10 active:scale-95 group font-display"
            title="Search Vehicle Passage Database & ANPR Logs"
          >
            <Search className="w-4 h-4 stroke-[2.2] text-sky-500 group-hover:scale-110 transition-transform" />
            <span>Search Plate DB</span>
            <kbd className="hidden sm:inline-block text-[10px] font-telemetry bg-sky-50 text-sky-600 px-1.5 py-0.5 rounded border border-sky-200/60 font-bold ml-1">⌘K</kbd>
          </button>
        )}

        {/* Station Operational Status Indicator */}
        <div
          className="flex items-center space-x-2 px-3.5 py-1.5 rounded-full bg-emerald-500/10 text-emerald-700 border border-emerald-500/25 text-xs font-bold select-none shadow-xs font-display"
          title="Operational Surveillance Station Active"
        >
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 radar-beacon" />
          <span>Station Active</span>
        </div>

        {/* Feeds Status Pill */}
        <div className="flex items-center space-x-2 px-3.5 py-1.5 rounded-full bg-white/80 border border-white text-xs shadow-xs">
          <span
            className={`w-2 h-2 rounded-full ${
              wsStatus === 'CONNECTED'
                ? 'bg-emerald-500'
                : wsStatus === 'AUTH_FAILED' || wsStatus === 'LOGGED_OUT'
                ? 'bg-rose-500'
                : 'bg-amber-500'
            }`}
          />
          <span className="font-bold text-gray-700 font-mono text-xs">
            {onlineCount}/{cameraCount} Cams
          </span>
        </div>

        {onRefresh && (
          <button
            onClick={onRefresh}
            className="p-2 text-gray-500 hover:text-gray-900 bg-white/80 hover:bg-white rounded-full transition-all border border-white hover:border-gray-200 shadow-xs active:scale-95"
            title="Refresh Data"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        )}

        <button
          onClick={handleFullscreen}
          className="p-2 text-gray-500 hover:text-gray-900 bg-white/80 hover:bg-white rounded-full transition-all border border-white hover:border-gray-200 shadow-xs active:scale-95"
          title="Toggle Fullscreen"
        >
          <Maximize2 className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
}
