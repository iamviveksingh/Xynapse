import React, { useState, useEffect, useCallback } from 'react';
import {
  X,
  Truck,
  Car,
  ShieldCheck,
  ShieldAlert,
  Plus,
  Trash2,
  RefreshCw,
  Search,
  CheckCircle,
  AlertTriangle,
  Sparkles,
  Eye,
  Camera,
  ArrowDownLeft,
  ArrowUpRight,
  Clock,
  ExternalLink,
  ChevronRight,
  Maximize2,
  Radio
} from 'lucide-react';
import {
  fetchVehicles,
  fetchVehicleStats,
  enrollVehicle,
  deleteVehicle,
  seedDefaultVehicles,
  fetchVehicleTransits,
  fetchTransitStats,
  getAuthenticatedMediaUrl
} from '../services/api';

export default function VehicleManagerModal({
  isOpen = true,
  onClose,
  onVehiclesChanged,
  initialSearch = '',
  embedded = false
}) {
  // Navigation Tabs: 'PASSAGE_DB' or 'WATCHLIST'
  const [activeTab, setActiveTab] = useState('PASSAGE_DB');

  // --- PASSAGE DATABASE STATE ---
  const [transits, setTransits] = useState([]);
  const [transitStats, setTransitStats] = useState({
    total_transits: 0,
    recognized_count: 0,
    unreadable_count: 0,
    pending_count: 0,
    watchlist_matches: 0,
    stolen_intercepts: 0,
    recognition_rate_pct: 0
  });
  const [transitLoading, setTransitLoading] = useState(false);
  const [transitSearch, setTransitSearch] = useState('');
  const [debouncedTransitSearch, setDebouncedTransitSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL'); // ALL, RECOGNIZED, UNREADABLE
  const [cameraFilter, setCameraFilter] = useState('ALL');
  const [directionFilter, setDirectionFilter] = useState('ALL');
  const [watchlistOnlyFilter, setWatchlistOnlyFilter] = useState(false);
  const [selectedTransit, setSelectedTransit] = useState(null);

  // Debounce search input by 250ms for smooth instantaneous typing
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedTransitSearch(transitSearch);
    }, 250);
    return () => clearTimeout(handler);
  }, [transitSearch]);

  // --- WATCHLIST ROSTER STATE ---
  const [vehicles, setVehicles] = useState([]);
  const [rosterStats, setRosterStats] = useState({ total: 0, military_count: 0, stolen_count: 0, civilian_count: 0 });
  const [rosterLoading, setRosterLoading] = useState(false);
  const [rosterFilter, setRosterFilter] = useState('ALL');
  const [rosterSearch, setRosterSearch] = useState('');

  // Enroll Form State
  const [showEnrollForm, setShowEnrollForm] = useState(false);
  const [plateNumber, setPlateNumber] = useState('');
  const [vehicleType, setVehicleType] = useState('Car');
  const [ownerName, setOwnerName] = useState('');
  const [status, setStatus] = useState('AUTHORIZED_MILITARY');
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [statusMessage, setStatusMessage] = useState(null);

  // Load Transit Data
  const loadTransitData = useCallback(async () => {
    setTransitLoading(true);
    try {
      const [tData, sData] = await Promise.all([
        fetchVehicleTransits({
          plateNumber: debouncedTransitSearch,
          cameraId: cameraFilter,
          plateStatus: statusFilter,
          direction: directionFilter,
          watchlistMatch: watchlistOnlyFilter ? true : null,
          limit: 100
        }),
        fetchTransitStats(cameraFilter !== 'ALL' ? cameraFilter : null)
      ]);
      setTransits(tData.transits || []);
      setTransitStats(sData);
    } catch (e) {
      console.error('Error loading transit passage data:', e);
    } finally {
      setTransitLoading(false);
    }
  }, [debouncedTransitSearch, cameraFilter, statusFilter, directionFilter, watchlistOnlyFilter]);

  // Load Watchlist Roster Data
  const loadRosterData = useCallback(async () => {
    setRosterLoading(true);
    try {
      const [vData, sData] = await Promise.all([
        fetchVehicles(),
        fetchVehicleStats()
      ]);
      setVehicles(vData);
      setRosterStats(sData);
    } catch (e) {
      console.error('Error loading watchlist roster data:', e);
    } finally {
      setRosterLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      if (initialSearch) {
        setTransitSearch(initialSearch);
        setActiveTab('PASSAGE_DB');
      }
      if (activeTab === 'PASSAGE_DB') {
        loadTransitData();
      } else {
        loadRosterData();
      }
      setStatusMessage(null);
    }
  }, [isOpen, initialSearch, activeTab, loadTransitData, loadRosterData]);

  if (!isOpen) return null;

  // Watchlist Actions
  const handleEnroll = async (e) => {
    e.preventDefault();
    if (!plateNumber.trim()) {
      setStatusMessage({ type: 'error', text: 'License plate number is required.' });
      return;
    }

    setSubmitting(true);
    setStatusMessage(null);

    try {
      await enrollVehicle({
        plate_number: plateNumber.trim().toUpperCase(),
        vehicle_type: vehicleType,
        owner_name: ownerName.trim() || 'Unknown',
        status: status,
        notes: notes.trim()
      });

      setStatusMessage({ type: 'success', text: `Vehicle [${plateNumber.toUpperCase()}] enrolled successfully.` });
      setPlateNumber('');
      setOwnerName('');
      setNotes('');
      setShowEnrollForm(false);
      await loadRosterData();
      if (onVehiclesChanged) onVehiclesChanged();
    } catch (err) {
      setStatusMessage({ type: 'error', text: err.detail || err.message || 'Failed to enroll vehicle.' });
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id, plate) => {
    if (!window.confirm(`Remove vehicle [${plate}] from roster?`)) return;
    try {
      await deleteVehicle(id);
      await loadRosterData();
      if (onVehiclesChanged) onVehiclesChanged();
    } catch (err) {
      console.error('Delete error:', err);
      setStatusMessage({ type: 'error', text: err.detail || err.message || 'Administrative privileges required to remove vehicle from watchlist.' });
    }
  };

  const handleSeedDefaults = async () => {
    setRosterLoading(true);
    try {
      await seedDefaultVehicles();
      await loadRosterData();
      if (onVehiclesChanged) onVehiclesChanged();
      setStatusMessage({ type: 'success', text: 'Demo vehicles added to watchlist.' });
    } catch (err) {
      setStatusMessage({ type: 'error', text: err.detail || err.message || 'Failed to seed vehicles.' });
    } finally {
      setRosterLoading(false);
    }
  };

  const filteredRosterVehicles = vehicles.filter((v) => {
    if (rosterFilter !== 'ALL' && v.status !== rosterFilter) return false;
    if (rosterSearch.trim()) {
      const q = rosterSearch.toLowerCase();
      return (
        v.plate_number?.toLowerCase().includes(q) ||
        v.owner_name?.toLowerCase().includes(q) ||
        v.vehicle_type?.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const formatTimestamp = (isoString) => {
    if (!isoString) return '—';
    try {
      const d = new Date(isoString);
      return d.toLocaleString('en-IN', {
        dateStyle: 'medium',
        timeStyle: 'medium'
      });
    } catch {
      return isoString;
    }
  };

  if (!isOpen && !embedded) return null;

  const content = (
    <div className={`flex flex-col bg-white/80 backdrop-blur-2xl border border-white/80 rounded-3xl overflow-hidden text-gray-900 ${
      embedded ? 'w-full shadow-lg shadow-gray-200/50' : 'relative w-full max-w-6xl max-h-[92vh] shadow-2xl'
    }`}>
      {/* Header */}
      <div className="flex items-center justify-between px-7 py-5 border-b border-white/60 bg-white/70 backdrop-blur-xl">
        <div className="flex items-center space-x-4">
          <div className="w-11 h-11 rounded-2xl bg-blue-500/10 text-blue-600 flex items-center justify-center border border-blue-200/50 shadow-xs">
            <Truck className="w-5 h-5 stroke-[2.2]" />
          </div>
          <div>
            <div className="flex items-center space-x-3">
              <h2 className="text-lg sm:text-xl font-extrabold text-gray-900 tracking-tight">
                Vehicle Passage Database & ANPR Sentry
              </h2>
              <span className="inline-flex items-center gap-1.5 text-xs font-mono px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-700 border border-emerald-300 font-bold">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                Active Checkpoint
              </span>
            </div>
            <p className="text-xs sm:text-[13px] text-gray-500 font-medium">
              Persistent passage records, OCR isolation, and BOLO watchlist intercept alerts
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-3">
          {/* Top Primary Segmented Tabs */}
          <div className="apple-segmented-control shadow-xs">
            <button
              onClick={() => setActiveTab('PASSAGE_DB')}
              className={`apple-segmented-btn ${activeTab === 'PASSAGE_DB' ? 'active' : ''}`}
            >
              Passage Database ({transitStats.total_transits})
            </button>
            <button
              onClick={() => setActiveTab('WATCHLIST')}
              className={`apple-segmented-btn ${activeTab === 'WATCHLIST' ? 'active' : ''}`}
            >
              Watchlist & BOLO ({rosterStats.total})
            </button>
          </div>

          {!embedded && onClose && (
            <button
              onClick={onClose}
              className="p-2 rounded-full text-gray-400 hover:text-gray-900 hover:bg-white transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>
      </div>

      {/* Status Message */}
      {statusMessage && (
        <div className={`mx-7 mt-4 p-3.5 rounded-2xl flex items-center space-x-2 text-xs font-semibold border ${
          statusMessage.type === 'error'
            ? 'bg-rose-50 border-rose-200 text-rose-700'
            : 'bg-emerald-50 border-emerald-200 text-emerald-700'
        }`}>
          {statusMessage.type === 'error' ? <AlertTriangle className="w-4 h-4 shrink-0 text-rose-600" /> : <CheckCircle className="w-4 h-4 shrink-0 text-emerald-600" />}
          <span>{statusMessage.text}</span>
        </div>
      )}

      {/* TAB 1: PASSAGE DATABASE */}
      {activeTab === 'PASSAGE_DB' && (
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          {/* Stats Strip — Floating Glass Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 px-7 py-4.5 border-b border-white/60 bg-white/50 backdrop-blur-md">
            <div className="p-4 rounded-2xl bg-white/80 border border-white flex items-center justify-between shadow-xs">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-wider text-gray-400 font-mono">Total Monitored</div>
                <div className="text-2xl sm:text-3xl font-extrabold font-mono text-gray-900 mt-1">{transitStats.total_transits}</div>
              </div>
              <div className="w-9 h-9 rounded-xl bg-gray-100 flex items-center justify-center text-gray-500">
                <Car className="w-5 h-5" />
              </div>
            </div>

            <div className="p-4 rounded-2xl bg-white/80 border border-white flex items-center justify-between shadow-xs">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-wider text-emerald-600 font-mono">Recognized Plates</div>
                <div className="flex items-baseline space-x-1.5 mt-1">
                  <span className="text-2xl sm:text-3xl font-extrabold font-mono text-emerald-600">{transitStats.recognized_count}</span>
                  <span className="text-xs font-mono text-gray-400 font-bold">({transitStats.recognition_rate_pct}%)</span>
                </div>
              </div>
              <div className="w-9 h-9 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center border border-emerald-200">
                <CheckCircle className="w-5 h-5" />
              </div>
            </div>

            <div className="p-4 rounded-2xl bg-white/80 border border-white flex items-center justify-between shadow-xs">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-wider text-amber-600 font-mono">Unreadable / Obscured</div>
                <div className="text-2xl sm:text-3xl font-extrabold font-mono text-amber-600 mt-1">{transitStats.unreadable_count}</div>
              </div>
              <div className="w-9 h-9 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center border border-amber-200">
                <AlertTriangle className="w-5 h-5" />
              </div>
            </div>

            <div className="p-4 rounded-2xl bg-white/80 border border-white flex items-center justify-between shadow-xs">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-wider text-rose-600 font-mono">Watchlist Intercepts</div>
                <div className="text-2xl sm:text-3xl font-extrabold font-mono text-rose-600 mt-1">{transitStats.stolen_intercepts || transitStats.watchlist_matches}</div>
              </div>
              <div className="w-9 h-9 rounded-xl bg-rose-50 text-rose-600 flex items-center justify-center border border-rose-200">
                <ShieldAlert className="w-5 h-5" />
              </div>
            </div>
          </div>

          {/* Filter Toolbar */}
          <div className="flex flex-wrap items-center justify-between gap-3 px-7 py-3.5 border-b border-white/60 bg-white/60">
            <div className="flex items-center space-x-2 flex-1 max-w-md">
              <div className="relative flex-1">
                <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search plate (e.g. TN09BY9726, DL01, UP32)..."
                  value={transitSearch}
                  onChange={(e) => setTransitSearch(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 text-xs sm:text-[13px] rounded-full bg-white/90 border border-white text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500/30 shadow-xs transition-all"
                />
                {transitSearch && (
                  <button
                    onClick={() => setTransitSearch('')}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>

            <div className="flex items-center space-x-2">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="px-3 py-1.5 text-xs rounded-full bg-white/90 border border-white text-gray-800 focus:outline-none shadow-2xs font-medium"
              >
                <option value="ALL">All Statuses</option>
                <option value="RECOGNIZED">Recognized Only</option>
                <option value="UNREADABLE">Unreadable Only</option>
              </select>

              <select
                value={cameraFilter}
                onChange={(e) => setCameraFilter(e.target.value)}
                className="px-3 py-1.5 text-xs rounded-full bg-white/90 border border-white text-gray-800 focus:outline-none shadow-2xs font-medium"
              >
                <option value="ALL">All Cameras</option>
                <option value="CAM-01">CAM-01 (Checkpost)</option>
                <option value="CAM-02">CAM-02</option>
                <option value="CAM-TEST-V">CAM-TEST-V</option>
              </select>

              <select
                value={directionFilter}
                onChange={(e) => setDirectionFilter(e.target.value)}
                className="px-3 py-1.5 text-xs rounded-full bg-white/90 border border-white text-gray-800 focus:outline-none shadow-2xs font-medium"
              >
                <option value="ALL">All Directions</option>
                <option value="INBOUND">Inbound</option>
                <option value="OUTBOUND">Outbound</option>
              </select>

              {/* Watchlist toggle */}
              <button
                onClick={() => setWatchlistOnlyFilter(!watchlistOnlyFilter)}
                className={`px-3.5 py-1.5 rounded-full text-xs font-bold border transition-all flex items-center space-x-1.5 shadow-2xs ${
                  watchlistOnlyFilter
                    ? 'bg-rose-500/10 border-rose-300 text-rose-600'
                    : 'bg-white/80 border-white text-gray-600 hover:text-gray-900'
                }`}
              >
                <ShieldAlert className="w-3.5 h-3.5 text-rose-600" />
                <span>Alerts Only</span>
              </button>

              {/* Refresh */}
              <button
                onClick={loadTransitData}
                disabled={transitLoading}
                className="p-2 rounded-full bg-white/80 hover:bg-white text-gray-600 border border-white transition-colors shadow-2xs"
                title="Refresh Database"
              >
                <RefreshCw className={`w-4 h-4 ${transitLoading ? 'animate-spin text-blue-600' : ''}`} />
              </button>
            </div>
          </div>

          {/* Passage Table */}
          <div className="flex-1 overflow-y-auto p-7 bg-white/30 backdrop-blur-md">
            {transitLoading && transits.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-24 text-gray-400">
                <RefreshCw className="w-7 h-7 animate-spin text-blue-600 mb-2" />
                <p className="text-xs font-semibold">Querying Checkpoint Passage Database...</p>
              </div>
            ) : transits.length === 0 ? (
              <div className="text-center py-24 text-gray-400">
                <div className="w-14 h-14 rounded-2xl bg-white/80 border border-white flex items-center justify-center mx-auto mb-3 text-gray-300 shadow-xs">
                  <Car className="w-7 h-7" />
                </div>
                <p className="text-base font-bold text-gray-800">No vehicle passages found</p>
                <p className="text-xs text-gray-400 mt-1 max-w-sm mx-auto">
                  {transitSearch
                    ? `No vehicle match for "${transitSearch}". Try clearing the search.`
                    : 'Vehicles detected in CHECKPOST mode will automatically be recorded here in SQLite.'}
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {transits.map((item) => {
                  const isRecognized = item.plate_status === 'RECOGNIZED';
                  const isWatchlist = item.watchlist_match;
                  const isStolen = item.watchlist_category === 'SUSPECT_STOLEN';
                  const isMilitary = item.watchlist_category === 'AUTHORIZED_MILITARY';

                  return (
                    <div
                      key={item.id || item.event_id}
                      onClick={() => setSelectedTransit(item)}
                      className="group flex items-center justify-between p-4 rounded-2xl bg-white/80 hover:bg-white border border-white hover:border-blue-300 shadow-xs hover:shadow-md transition-all cursor-pointer"
                    >
                      {/* Left: Plate Badge & Classification */}
                      <div className="flex items-center space-x-5">
                        {/* Authentic Indian Plate Visual */}
                        {isRecognized && item.plate_number ? (
                          <div className="flex items-center border-2 border-black rounded-lg overflow-hidden bg-white shadow-xs font-mono font-black text-sm tracking-wider select-all">
                            <div className="bg-[#002B7F] text-white text-[9px] font-sans px-2 py-1.5 flex flex-col items-center justify-center leading-tight">
                              <span className="text-[8px] font-bold">🇮🇳</span>
                              <span className="font-bold">IND</span>
                            </div>
                            <div className="px-3 py-1 text-black font-extrabold tracking-widest text-sm sm:text-base">
                              {item.plate_number}
                            </div>
                          </div>
                        ) : (
                          <div className="flex items-center px-3.5 py-2 rounded-xl bg-amber-500/10 text-amber-800 border border-amber-300 font-mono text-xs font-bold">
                            <AlertTriangle className="w-4 h-4 mr-1.5 text-amber-600 shrink-0" />
                            <span>UNREADABLE / OBSCURED</span>
                          </div>
                        )}

                        {/* Details */}
                        <div>
                          <div className="flex items-center space-x-2.5">
                            <span className="text-sm font-bold text-gray-900">
                              {item.vehicle_type || 'Vehicle'}
                            </span>

                            {/* Watchlist Badge */}
                            {isWatchlist ? (
                              <span className={`text-[10px] font-bold px-2.5 py-0.5 rounded-full uppercase tracking-wider ${
                                isStolen
                                  ? 'bg-rose-500/10 text-rose-700 border border-rose-300 animate-pulse'
                                  : isMilitary
                                  ? 'bg-emerald-500/10 text-emerald-700 border border-emerald-300'
                                  : 'bg-blue-500/10 text-blue-700 border border-blue-300'
                              }`}>
                                {isStolen ? '🚨 SUSPECT STOLEN' : isMilitary ? '🛡️ MILITARY CONVOY' : 'WATCHLIST MATCH'}
                              </span>
                            ) : (
                              <span className="text-[10px] font-semibold px-2.5 py-0.5 rounded-full bg-white text-gray-500 border border-gray-200">
                                Civilian Passage
                              </span>
                            )}

                            {/* OCR Confidence */}
                            {isRecognized && item.plate_confidence !== null && (
                              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-700 border border-emerald-300 font-bold">
                                {Math.round(item.plate_confidence * 100)}% Conf
                              </span>
                            )}
                          </div>

                          <div className="flex items-center space-x-3 text-xs text-gray-400 mt-1 font-mono">
                            <span className="flex items-center space-x-1">
                              <Clock className="w-3.5 h-3.5 text-gray-400" />
                              <span>{formatTimestamp(item.first_seen_at || item.created_at)}</span>
                            </span>
                            <span>•</span>
                            <span className="flex items-center space-x-1">
                              <Camera className="w-3.5 h-3.5 text-gray-400" />
                              <span>{item.camera_id}</span>
                            </span>
                            <span>•</span>
                            <span className="flex items-center space-x-0.5 font-bold">
                              {item.direction === 'INBOUND' ? (
                                <ArrowDownLeft className="w-3.5 h-3.5 text-blue-600" />
                              ) : (
                                <ArrowUpRight className="w-3.5 h-3.5 text-emerald-600" />
                              )}
                              <span>{item.direction || 'UNKNOWN'}</span>
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Right: Evidence Snapshot Preview */}
                      <div className="flex items-center space-x-4">
                        {item.plate_crop_path || item.vehicle_snapshot_path ? (
                          <div className="relative group/thumb w-20 h-12 rounded-xl overflow-hidden bg-slate-900 border border-white/60 flex items-center justify-center shadow-xs">
                            <img
                              src={getAuthenticatedMediaUrl(item.plate_crop_path || item.vehicle_snapshot_path)}
                              alt="Evidence Crop"
                              className="w-full h-full object-cover group-hover/thumb:scale-105 transition-transform"
                              onError={(e) => {
                                e.target.style.display = 'none';
                              }}
                            />
                            <div className="absolute inset-0 bg-black/25 opacity-0 group-hover/thumb:opacity-100 flex items-center justify-center transition-opacity">
                              <Eye className="w-4 h-4 text-white" />
                            </div>
                          </div>
                        ) : (
                          <div className="w-20 h-12 rounded-xl bg-white border border-gray-200 flex items-center justify-center text-[10px] text-gray-400 font-mono">
                            No Pic
                          </div>
                        )}

                        <div className="text-right">
                          <span className="font-mono text-xs text-gray-400 block truncate max-w-[120px]">
                            {item.event_id}
                          </span>
                          <span className="text-xs text-blue-600 font-bold flex items-center justify-end space-x-0.5 group-hover:underline">
                            <span>Inspect</span>
                            <ChevronRight className="w-3.5 h-3.5" />
                          </span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Selected Transit Evidence Lightbox */}
          {selectedTransit && (
            <div className="spatial-modal-backdrop">
              <div className="neo-glass-elevated relative w-full max-w-3xl overflow-hidden p-7 space-y-5 border border-white/80">
                <div className="flex items-center justify-between border-b border-gray-100 pb-4">
                  <div className="flex items-center space-x-3">
                    <div className="w-10 h-10 rounded-2xl bg-blue-500/10 text-blue-600 flex items-center justify-center border border-blue-200/50 shadow-xs">
                      <Truck className="w-5 h-5 stroke-[2.2]" />
                    </div>
                    <div>
                      <h3 className="text-base font-extrabold text-gray-900 tracking-tight">
                        Transit Passage Audit Record
                      </h3>
                      <p className="text-xs font-mono text-gray-400">
                        Event ID: {selectedTransit.event_id}
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={() => setSelectedTransit(null)}
                    className="p-2 rounded-full text-gray-400 hover:text-gray-900 hover:bg-gray-100 transition-colors"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>

                {/* Dual Evidence Snapshot Viewer */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Vehicle Snapshot */}
                  <div className="space-y-2">
                    <div className="text-xs font-bold text-gray-600 flex items-center justify-between uppercase tracking-wider">
                      <span>Vehicle Full Frame Crop</span>
                      <span className="font-mono text-xs text-gray-400 font-medium">{selectedTransit.vehicle_type}</span>
                    </div>
                    <div className="w-full h-52 rounded-2xl overflow-hidden bg-slate-950 border border-slate-800 flex items-center justify-center shadow-inner">
                      {selectedTransit.vehicle_snapshot_path ? (
                        <img
                          src={getAuthenticatedMediaUrl(selectedTransit.vehicle_snapshot_path)}
                          alt="Vehicle Frame"
                          className="w-full h-full object-cover"
                          onError={(e) => {
                            e.target.parentNode.innerHTML = '<span class="text-xs text-slate-400">Snapshot not available</span>';
                          }}
                        />
                      ) : (
                        <span className="text-xs text-slate-400 font-mono">Snapshot not captured</span>
                      )}
                    </div>
                  </div>

                  {/* Plate Crop */}
                  <div className="space-y-2">
                    <div className="text-xs font-bold text-gray-600 flex items-center justify-between uppercase tracking-wider">
                      <span>ANPR Optical Plate Isolation</span>
                      {selectedTransit.plate_confidence && (
                        <span className="font-mono text-xs text-emerald-600 font-bold">
                          {Math.round(selectedTransit.plate_confidence * 100)}% Confidence
                        </span>
                      )}
                    </div>
                    <div className="w-full h-52 rounded-2xl overflow-hidden bg-slate-950 border border-slate-800 flex items-center justify-center p-3 shadow-inner">
                      {selectedTransit.plate_crop_path ? (
                        <img
                          src={getAuthenticatedMediaUrl(selectedTransit.plate_crop_path)}
                          alt="License Plate Crop"
                          className="max-h-full max-w-full object-contain rounded-xl border border-white/20 shadow-md"
                          onError={(e) => {
                            e.target.parentNode.innerHTML = '<span class="text-xs text-slate-400">Plate crop not available</span>';
                          }}
                        />
                      ) : (
                        <span className="text-xs text-slate-400 font-mono">Plate crop not available</span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Metadata Matrix */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 p-4 rounded-2xl bg-white/80 border border-white text-xs shadow-xs">
                  <div>
                    <div className="text-[10px] text-gray-400 uppercase font-bold tracking-wider">Recognized Plate</div>
                    <div className="font-mono font-extrabold text-sm text-gray-900 mt-1">
                      {selectedTransit.plate_number || 'UNREADABLE'}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-gray-400 uppercase font-bold tracking-wider">Camera & Direction</div>
                    <div className="font-bold text-gray-800 mt-1">
                      {selectedTransit.camera_id} • {selectedTransit.direction}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-gray-400 uppercase font-bold tracking-wider">Passage Time</div>
                    <div className="font-mono text-xs text-gray-800 mt-1 font-medium">
                      {formatTimestamp(selectedTransit.first_seen_at || selectedTransit.created_at)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-gray-400 uppercase font-bold tracking-wider">OCR Latency</div>
                    <div className="font-mono text-xs text-blue-600 font-extrabold mt-1">
                      {selectedTransit.ocr_latency_ms ? `${selectedTransit.ocr_latency_ms} ms` : 'N/A'}
                    </div>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-2">
                  <span className="text-xs text-gray-400 font-mono">
                    Air-gapped SQLite (`vehicle_transit_logs`)
                  </span>
                  <button
                    onClick={() => setSelectedTransit(null)}
                    className="gel-btn-primary px-5 py-2 text-xs"
                  >
                    Done
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 2: WATCHLIST & BOLO REGISTRY */}
      {activeTab === 'WATCHLIST' && (
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          {/* Stats Strip */}
          <div className="grid grid-cols-3 gap-4 px-7 py-4.5 border-b border-white/60 bg-white/50 backdrop-blur-md">
            <div className="p-4 rounded-2xl bg-white/80 border border-white flex items-center justify-between shadow-xs">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-wider text-gray-400 font-mono">Enrolled Targets</div>
                <div className="text-2xl sm:text-3xl font-extrabold font-mono text-gray-900 mt-1">{rosterStats.total}</div>
              </div>
              <Car className="w-5 h-5 text-gray-400" />
            </div>

            <div className="p-4 rounded-2xl bg-white/80 border border-white flex items-center justify-between shadow-xs">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-wider text-emerald-600 font-mono">Military Convoys</div>
                <div className="text-2xl sm:text-3xl font-extrabold font-mono text-emerald-600 mt-1">{rosterStats.military_count}</div>
              </div>
              <ShieldCheck className="w-5 h-5 text-emerald-600" />
            </div>

            <div className="p-4 rounded-2xl bg-white/80 border border-white flex items-center justify-between shadow-xs">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-wider text-rose-600 font-mono">Stolen / Intercept BOLO</div>
                <div className="text-2xl sm:text-3xl font-extrabold font-mono text-rose-600 mt-1">{rosterStats.stolen_count}</div>
              </div>
              <ShieldAlert className="w-5 h-5 text-rose-600" />
            </div>
          </div>

          {/* Toolbar */}
          <div className="flex flex-wrap items-center justify-between gap-3 px-7 py-3.5 border-b border-white/60 bg-white/60">
            <div className="apple-segmented-control shadow-xs">
              <button
                onClick={() => setRosterFilter('ALL')}
                className={`apple-segmented-btn ${rosterFilter === 'ALL' ? 'active' : ''}`}
              >
                All ({rosterStats.total})
              </button>
              <button
                onClick={() => setRosterFilter('AUTHORIZED_MILITARY')}
                className={`apple-segmented-btn ${rosterFilter === 'AUTHORIZED_MILITARY' ? 'active' : ''}`}
              >
                Convoys ({rosterStats.military_count})
              </button>
              <button
                onClick={() => setRosterFilter('SUSPECT_STOLEN')}
                className={`apple-segmented-btn ${rosterFilter === 'SUSPECT_STOLEN' ? 'active' : ''}`}
              >
                Stolen ({rosterStats.stolen_count})
              </button>
            </div>

            <div className="flex items-center space-x-2.5">
              <div className="relative">
                <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search plate or unit..."
                  value={rosterSearch}
                  onChange={(e) => setRosterSearch(e.target.value)}
                  className="pl-10 pr-3 py-2 text-xs rounded-full bg-white/90 border border-white text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500/30 w-52 shadow-2xs"
                />
              </div>

              <button
                onClick={handleSeedDefaults}
                className="gel-btn-secondary flex items-center space-x-1.5 px-4 py-2 text-xs font-semibold"
              >
                <Sparkles className="w-4 h-4 text-amber-500" />
                <span>Seed Demo</span>
              </button>

              <button
                onClick={() => setShowEnrollForm(!showEnrollForm)}
                className="gel-btn-primary flex items-center space-x-1.5 px-4.5 py-2 text-xs font-semibold"
              >
                <Plus className="w-4 h-4" />
                <span>Enroll Target</span>
              </button>
            </div>
          </div>

          {/* Enroll Form (Collapsible) */}
          {showEnrollForm && (
            <form onSubmit={handleEnroll} className="p-7 border-b border-white/60 bg-white/70 space-y-4">
              <div className="text-sm font-bold text-gray-900 flex items-center space-x-2 tracking-tight">
                <Truck className="w-4 h-4 text-blue-600" />
                <span>Enroll Vehicle Target into Watchlist</span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div>
                  <label className="block text-xs font-bold text-gray-500 mb-1">Plate Number *</label>
                  <input
                    type="text"
                    placeholder="e.g. ARMY01X9988 or DL01AB1234"
                    value={plateNumber}
                    onChange={(e) => setPlateNumber(e.target.value.toUpperCase())}
                    required
                    className="w-full px-3.5 py-2 rounded-xl bg-white border border-gray-200 text-gray-900 font-mono uppercase focus:outline-none focus:ring-2 focus:ring-blue-500/30 text-xs shadow-2xs"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-gray-500 mb-1">Vehicle Classification</label>
                  <select
                    value={vehicleType}
                    onChange={(e) => setVehicleType(e.target.value)}
                    className="w-full px-3.5 py-2 rounded-xl bg-white border border-gray-200 text-gray-900 focus:outline-none text-xs shadow-2xs font-medium"
                  >
                    <option value="Car">Car / SUV</option>
                    <option value="Heavy Truck">Heavy Truck / Cargo</option>
                    <option value="Military Convoy">Military Convoy</option>
                    <option value="Bus">Bus / Transport</option>
                    <option value="Motorcycle">Motorcycle</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-bold text-gray-500 mb-1">Watchlist Status</label>
                  <select
                    value={status}
                    onChange={(e) => setStatus(e.target.value)}
                    className="w-full px-3.5 py-2 rounded-xl bg-white border border-gray-200 text-gray-900 focus:outline-none text-xs shadow-2xs font-medium"
                  >
                    <option value="AUTHORIZED_MILITARY">Military Convoy (Authorized Pass)</option>
                    <option value="SUSPECT_STOLEN">Stolen / Suspect (Red Intercept)</option>
                    <option value="CIVILIAN">Civilian Border Transit</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-bold text-gray-500 mb-1">Owner / Unit Name</label>
                  <input
                    type="text"
                    placeholder="e.g. 5th BSF Battalion"
                    value={ownerName}
                    onChange={(e) => setOwnerName(e.target.value)}
                    className="w-full px-3.5 py-2 rounded-xl bg-white border border-gray-200 text-gray-900 focus:outline-none text-xs shadow-2xs"
                  />
                </div>
              </div>

              <div className="flex items-center justify-between gap-3 pt-2">
                <input
                  type="text"
                  placeholder="Operational notes (e.g. Stolen vehicle red alert, Wanted cargo)..."
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  className="flex-1 px-3.5 py-2 rounded-xl bg-white border border-gray-200 text-gray-900 focus:outline-none text-xs shadow-2xs"
                />
                <div className="flex items-center space-x-2">
                  <button
                    type="button"
                    onClick={() => setShowEnrollForm(false)}
                    className="gel-btn-secondary px-4 py-2 text-xs font-semibold text-gray-500 hover:text-gray-900"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={submitting}
                    className="gel-btn-primary px-5 py-2 text-xs font-bold disabled:opacity-50"
                  >
                    {submitting ? 'Saving...' : 'Add to Watchlist'}
                  </button>
                </div>
              </div>
            </form>
          )}

          {/* Watchlist Vehicles List */}
          <div className="flex-1 overflow-y-auto p-7 space-y-3 bg-white/30 backdrop-blur-md">
            {rosterLoading ? (
              <div className="flex flex-col items-center justify-center py-20 text-gray-400">
                <RefreshCw className="w-6 h-6 animate-spin text-blue-600 mb-2" />
                <p className="text-xs font-semibold">Loading ANPR Watchlist...</p>
              </div>
            ) : filteredRosterVehicles.length === 0 ? (
              <div className="text-center py-20 text-gray-400">
                <div className="w-12 h-12 rounded-2xl bg-white/80 border border-white flex items-center justify-center mx-auto mb-2 text-gray-300 shadow-xs">
                  <Car className="w-6 h-6" />
                </div>
                <p className="text-base font-bold text-gray-800">No vehicles match this filter</p>
                <p className="text-xs text-gray-400 mt-1">Enroll a vehicle target above or seed demo vehicles</p>
              </div>
            ) : (
              filteredRosterVehicles.map((v) => {
                const isMilitary = v.status === 'AUTHORIZED_MILITARY';
                const isStolen = v.status === 'SUSPECT_STOLEN';

                return (
                  <div
                    key={v.id}
                    className="flex items-center justify-between p-4.5 rounded-2xl bg-white/80 hover:bg-white border border-white hover:border-blue-300 shadow-xs transition-all"
                  >
                    <div className="flex items-center space-x-4">
                      <div className={`w-10 h-10 rounded-2xl flex items-center justify-center border shadow-xs ${
                        isMilitary
                          ? 'bg-emerald-500/10 text-emerald-700 border-emerald-300'
                          : isStolen
                          ? 'bg-rose-500/10 text-rose-700 border-rose-300'
                          : 'bg-blue-500/10 text-blue-700 border-blue-300'
                      }`}>
                        <Truck className="w-5 h-5 stroke-[2.2]" />
                      </div>

                      <div>
                        <div className="flex items-center space-x-2.5">
                          <span className="font-mono font-black text-sm sm:text-base text-gray-900">
                            {v.plate_number}
                          </span>
                          <span className={`text-[10px] font-bold px-2.5 py-0.5 rounded-full uppercase tracking-wider ${
                            isMilitary
                              ? 'bg-emerald-500/10 text-emerald-700 border border-emerald-300'
                              : isStolen
                              ? 'bg-rose-500/10 text-rose-700 border border-rose-300'
                              : 'bg-white text-gray-500 border border-gray-200'
                          }`}>
                            {isMilitary ? 'MILITARY CONVOY' : isStolen ? 'INTERCEPT RED NOTICE' : 'CIVILIAN'}
                          </span>
                          <span className="text-xs text-gray-400 font-medium">• {v.vehicle_type}</span>
                        </div>

                        <div className="flex items-center space-x-3 text-xs text-gray-500 mt-1">
                          <span>Unit: <strong className="text-gray-900 font-bold">{v.owner_name}</strong></span>
                          {v.notes && <span>| {v.notes}</span>}
                        </div>
                      </div>
                    </div>

                    <button
                      onClick={() => handleDelete(v.id, v.plate_number)}
                      title="Remove from roster"
                      className="p-2.5 rounded-full text-gray-400 hover:text-rose-600 hover:bg-rose-50 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="px-7 py-4 border-t border-white/60 bg-white/70 flex items-center justify-between text-xs text-gray-500">
        <div className="flex items-center space-x-2">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="font-mono text-xs text-gray-600 font-medium">
            ANPR Engine: RapidOCR ONNX • Checkpoint Passage Persistence Active
          </span>
        </div>
        {!embedded && onClose && (
          <button
            onClick={onClose}
            className="gel-btn-secondary px-5 py-2 text-xs font-semibold"
          >
            Close
          </button>
        )}
      </div>

    </div>
  );

  if (embedded) {
    return (
      <div className="w-full">
        {content}
      </div>
    );
  }

  return (
    <div className="spatial-modal-backdrop">
      {content}
    </div>
  );
}
