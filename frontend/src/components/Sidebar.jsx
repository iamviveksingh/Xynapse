import React from 'react';
import {
  LayoutDashboard,
  Bell,
  BarChart3,
  Settings,
  Shield,
  UserCheck,
  Truck,
  Volume2,
  VolumeX,
  Radio,
  Sparkles
} from 'lucide-react';
import { enableAudio } from '../services/audio';

export default function Sidebar({
  activeTab,
  setActiveTab,
  soundEnabled,
  setSoundEnabled,
  wsStatus,
  newAlertCount = 0,
  onOpenFaceManager,
  onOpenVehicleManager,
  cameraCount = 1
}) {
  const handleToggleSound = () => {
    enableAudio();
    setSoundEnabled(!soundEnabled);
  };

  const navItems = [
    { id: 'OVERVIEW', label: 'Overview', icon: LayoutDashboard },
    { id: 'VEHICLES', label: 'Vehicle Passage', icon: Truck, badge: 'ANPR' },
    { id: 'ALERTS', label: 'Alerts & Incidents', icon: Bell, badgeCount: newAlertCount },
    { id: 'ANALYTICS', label: 'Analytics', icon: BarChart3 },
    { id: 'SETTINGS', label: 'Settings', icon: Settings },
  ];

  return (
    <aside className="w-72 bg-white/75 backdrop-blur-2xl border-r border-white/70 flex flex-col shrink-0 select-none z-30 min-h-screen shadow-[4px_0_35px_rgba(15,23,42,0.03)] transition-all">
      {/* Brand Header — Neo-Apple Glass Emblem */}
      <div className="h-20 px-6 border-b border-white/60 flex items-center justify-between specular-rim">
        <div className="flex items-center space-x-3.5">
          {/* Custom Iridescent 3D Emblem */}
          <div className="w-11 h-11 rounded-2xl bg-gradient-to-tr from-blue-600 via-indigo-600 to-violet-500 text-white flex items-center justify-center shadow-lg shadow-blue-500/25 border border-white/40 relative overflow-hidden group">
            <div className="absolute inset-0 bg-white/20 opacity-0 group-hover:opacity-100 transition-opacity" />
            <Shield className="w-5 h-5 text-white stroke-[2.4] drop-shadow-sm" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="font-black text-base tracking-tight text-gray-900 font-display">
                XYNAPSE
              </span>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-telemetry font-bold bg-gradient-to-r from-blue-500/10 to-indigo-500/10 text-blue-700 border border-blue-200/50">
                v1.9
              </span>
            </div>
            <span className="text-xs text-gray-400 font-medium block tracking-tight font-sans">
              Tactical Perimeter C2
            </span>
          </div>
        </div>
      </div>

      {/* Main Navigation */}
      <div className="flex-1 py-6 px-4 space-y-1.5 overflow-y-auto">
        <div className="px-3 pb-2 text-xs font-bold text-gray-400 uppercase tracking-wider font-mono">
          Command Rail
        </div>
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center justify-between px-4 py-3 rounded-2xl text-[14px] font-semibold transition-all group ${
                isActive
                  ? 'bg-gradient-to-r from-[#0071E3] to-[#389BFF] text-white shadow-lg shadow-blue-500/25 border border-white/30'
                  : 'text-gray-600 hover:text-gray-900 hover:bg-white/80 border border-transparent'
              }`}
            >
              <div className="flex items-center space-x-3">
                <Icon
                  className={`w-5 h-5 transition-transform group-hover:scale-105 ${
                    isActive ? 'text-white' : 'text-gray-400 group-hover:text-gray-700'
                  }`}
                />
                <span>{item.label}</span>
              </div>
              {item.badgeCount > 0 ? (
                <span
                  className={`px-2.5 py-0.5 rounded-full text-xs font-mono font-bold ${
                    isActive
                      ? 'bg-white text-blue-600 shadow-sm'
                      : 'bg-rose-500 text-white shadow-md shadow-rose-500/30'
                  }`}
                >
                  {item.badgeCount}
                </span>
              ) : item.badge ? (
                <span
                  className={`text-[11px] font-mono px-2 py-0.5 rounded-full font-bold ${
                    isActive
                      ? 'bg-white/20 text-white'
                      : 'bg-gray-100 text-gray-500 border border-gray-200/60'
                  }`}
                >
                  {item.badge}
                </span>
              ) : null}
            </button>
          );
        })}

        <div className="pt-8 px-3 pb-2 text-xs font-bold text-gray-400 uppercase tracking-wider font-mono">
          Security Registries
        </div>
        <button
          onClick={onOpenFaceManager}
          className="w-full flex items-center space-x-3 px-4 py-3 rounded-2xl text-[14px] font-semibold text-gray-600 hover:text-gray-900 hover:bg-white/80 transition-all border border-transparent"
        >
          <UserCheck className="w-5 h-5 text-gray-400" />
          <span>Face Biometric Roster</span>
        </button>
        <button
          onClick={() => {
            setActiveTab('VEHICLES');
            if (onOpenVehicleManager) onOpenVehicleManager();
          }}
          className={`w-full flex items-center space-x-3 px-4 py-3 rounded-2xl text-[14px] font-semibold transition-all ${
            activeTab === 'VEHICLES'
              ? 'bg-gradient-to-r from-[#0071E3] to-[#389BFF] text-white shadow-lg shadow-blue-500/25 border border-white/30'
              : 'text-gray-600 hover:text-gray-900 hover:bg-white/80 border border-transparent'
          }`}
        >
          <Truck className={`w-5 h-5 ${activeTab === 'VEHICLES' ? 'text-white' : 'text-gray-400'}`} />
          <span>Vehicle Passage DB</span>
        </button>
      </div>

      {/* Footer Status & Audio Controls — Neo-Glass Well */}
      <div className="p-4 border-t border-white/60 bg-white/40 space-y-3">
        <div className="p-3 rounded-2xl bg-white/80 backdrop-blur-md border border-white/80 shadow-xs flex items-center justify-between">
          <div className="flex items-center space-x-2.5 min-w-0">
            <span
              className={`w-2.5 h-2.5 rounded-full shrink-0 ${
                wsStatus === 'CONNECTED'
                  ? 'bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.7)] animate-pulse'
                  : 'bg-amber-500 animate-pulse'
              }`}
            />
            <div className="truncate">
              <span className="text-xs font-bold text-gray-800 block truncate">
                {wsStatus === 'CONNECTED' ? 'Live Telemetry Active' : 'Connecting Node...'}
              </span>
            </div>
          </div>

          <button
            onClick={handleToggleSound}
            className={`px-2.5 py-1.5 rounded-xl border transition-all flex items-center space-x-1.5 ${
              soundEnabled
                ? 'bg-white border-sky-300 text-sky-600 shadow-sm hover:border-sky-400'
                : 'bg-slate-100 border-slate-200 text-slate-400 hover:text-slate-600'
            }`}
            title={soundEnabled ? 'Mute Radar Audio Chime' : 'Enable Radar Audio Chime'}
          >
            {soundEnabled ? (
              <>
                <Volume2 className="w-4 h-4 text-sky-600 shrink-0" />
                <div className="flex items-end space-x-0.5 h-3.5 px-0.5">
                  <span className="w-0.5 bg-sky-500 rounded-full animate-eq-1" />
                  <span className="w-0.5 bg-sky-500 rounded-full animate-eq-2" />
                  <span className="w-0.5 bg-sky-500 rounded-full animate-eq-3" />
                </div>
              </>
            ) : (
              <VolumeX className="w-4 h-4" />
            )}
          </button>
        </div>

        <div className="px-2 text-[11px] text-gray-400 flex items-center justify-between font-mono">
          <span className="flex items-center space-x-1.5">
            <Radio className="w-3 h-3 text-gray-400" />
            <span>AIR-GAPPED NODE</span>
          </span>
          <span className="text-emerald-600 font-bold bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200/60">
            OFFLINE
          </span>
        </div>
      </div>
    </aside>
  );
}
