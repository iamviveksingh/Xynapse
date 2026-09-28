import React, { useState } from 'react';
import { Eye, CheckCircle, RefreshCw, Download, AlertTriangle, ShieldAlert, Clock, Radio } from 'lucide-react';
import { acknowledgeAlert, resolveAlert, getAuthenticatedMediaUrl } from '../services/api';

export default function AlertHistory({ alerts = [], onRefresh, onViewAlert, onAlertsUpdated }) {
  const [filterStatus, setFilterStatus] = useState('ALL');
  const [searchTerm, setSearchTerm] = useState('');
  const [updatingId, setUpdatingId] = useState(null);
  const [authError, setAuthError] = useState(null);

  const statuses = [
    { id: 'ALL', label: 'All Events' },
    { id: 'NEW', label: 'Needs Review' },
    { id: 'ACKNOWLEDGED', label: 'Under Review' },
    { id: 'RESOLVED', label: 'Resolved' }
  ];

  const filteredAlerts = alerts.filter((a) => {
    if (filterStatus !== 'ALL' && a.status !== filterStatus) return false;
    if (searchTerm) {
      const q = searchTerm.toLowerCase();
      const matchText = `${a.event_type} ${a.camera_id} ${a.objects_detected || ''} ${a.plate_number || ''}`.toLowerCase();
      if (!matchText.includes(q)) return false;
    }
    return true;
  });

  const handleAcknowledge = async (e, id) => {
    e.stopPropagation();
    setUpdatingId(id);
    setAuthError(null);
    try {
      await acknowledgeAlert(id);
      if (onAlertsUpdated) onAlertsUpdated();
    } catch (err) {
      console.error('Acknowledge error:', err);
      setAuthError(err.detail || err.message || 'Action denied: Administrative privileges required to acknowledge alerts.');
    } finally {
      setUpdatingId(null);
    }
  };

  const handleResolve = async (e, id) => {
    e.stopPropagation();
    setUpdatingId(id);
    setAuthError(null);
    try {
      await resolveAlert(id);
      if (onAlertsUpdated) onAlertsUpdated();
    } catch (err) {
      console.error('Resolve error:', err);
      setAuthError(err.detail || err.message || 'Action denied: Administrative privileges required to resolve alerts.');
    } finally {
      setUpdatingId(null);
    }
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case 'NEW':
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-rose-500/10 text-rose-600 border border-rose-300">
            <span className="w-2 h-2 rounded-full bg-rose-500 animate-pulse"></span>
            Needs Review
          </span>
        );
      case 'ACKNOWLEDGED':
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-amber-500/10 text-amber-600 border border-amber-300">
            <span className="w-2 h-2 rounded-full bg-amber-500"></span>
            Under Review
          </span>
        );
      case 'RESOLVED':
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-emerald-500/10 text-emerald-600 border border-emerald-300">
            <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
            Resolved
          </span>
        );
      default:
        return <span className="text-gray-400 text-xs font-mono">{status}</span>;
    }
  };

  const getSeverityBadge = (item) => {
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

    if (isCritical) {
      return (
        <span className="inline-flex items-center gap-1.5 text-xs font-bold text-rose-600 bg-rose-500/10 border border-rose-300 px-3 py-1 rounded-full uppercase tracking-wider">
          <ShieldAlert className="w-3.5 h-3.5 text-rose-600" />
          Critical
        </span>
      );
    }
    if (isWarning) {
      return (
        <span className="inline-flex items-center gap-1.5 text-xs font-bold text-amber-600 bg-amber-500/10 border border-amber-300 px-3 py-1 rounded-full uppercase tracking-wider">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
          Warning
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 text-xs font-semibold text-gray-600 bg-white border border-gray-200 px-3 py-1 rounded-full">
        Info
      </span>
    );
  };

  return (
    <div className="neo-glass rounded-3xl overflow-hidden transition-all border border-white/80 shadow-[0_20px_50px_-15px_rgba(15,23,42,0.06)]">
      {/* Auth Error Banner */}
      {authError && (
        <div className="px-7 py-3 bg-rose-50 border-b border-rose-200 text-rose-700 text-xs font-semibold flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <AlertTriangle className="w-4 h-4 shrink-0 text-rose-600" />
            <span>{authError}</span>
          </div>
          <button
            onClick={() => setAuthError(null)}
            className="text-rose-600 hover:text-rose-800 font-bold text-xs ml-2"
          >
            ✕
          </button>
        </div>
      )}

      {/* Header Controls */}
      <div className="px-7 py-5 border-b border-white/60 flex flex-wrap items-center justify-between gap-4 bg-white/70 backdrop-blur-xl">
        <div className="flex items-center space-x-3.5">
          <div className="w-10 h-10 rounded-2xl bg-blue-500/10 text-blue-600 flex items-center justify-center border border-blue-200/50 shadow-xs">
            <ShieldAlert className="w-5 h-5 stroke-[2.2]" />
          </div>
          <div>
            <div className="flex items-center gap-2.5">
              <h2 className="text-lg sm:text-xl font-extrabold text-gray-900 tracking-tight">
                Events & Threat Intelligence
              </h2>
              <span className="text-xs font-bold text-gray-600 bg-white px-2.5 py-0.5 rounded-full font-mono border border-gray-200 shadow-2xs">
                {filteredAlerts.length}
              </span>
            </div>
            <p className="text-xs sm:text-[13px] text-gray-500 font-medium">
              Real-time audit log of sector intrusions, perimeter breaches, and ANPR flags
            </p>
          </div>
        </div>

        {/* Filter Pills & Search */}
        <div className="flex items-center space-x-3 flex-wrap gap-y-2">
          {/* Search input */}
          <div className="relative">
            <input
              type="text"
              placeholder="Filter events, plates, sensors..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="px-4 py-2 text-xs sm:text-[13px] bg-white/90 border border-white rounded-full text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500/30 w-64 shadow-xs transition-all"
            />
          </div>

          {/* Apple Segmented Filter */}
          <div className="apple-segmented-control shadow-xs">
            {statuses.map((st) => (
              <button
                key={st.id}
                onClick={() => setFilterStatus(st.id)}
                className={`apple-segmented-btn ${filterStatus === st.id ? 'active' : ''}`}
              >
                {st.label}
              </button>
            ))}
          </div>

          {/* Export Actions */}
          <a
            href="/api/alerts/export/csv"
            download
            className="gel-btn-secondary px-4 py-2 text-xs sm:text-[13px] flex items-center space-x-2"
            title="Download CSV Audit Log"
          >
            <Download className="w-4 h-4 text-gray-500" />
            <span>Export CSV</span>
          </a>

          {onRefresh && (
            <button
              onClick={onRefresh}
              className="p-2 text-gray-500 hover:text-gray-900 bg-white/80 hover:bg-white rounded-full transition-colors border border-white shadow-xs"
              title="Refresh Records"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Events Table */}
      <div className="overflow-x-auto bg-white/50 backdrop-blur-md">
        <table className="w-full text-left text-xs sm:text-[13px]">
          <thead>
            <tr className="border-b border-gray-100 text-xs font-bold text-gray-400 bg-white/60 uppercase tracking-wider">
              <th className="py-4 px-7">Timestamp</th>
              <th className="py-4 px-4">Event / Perception</th>
              <th className="py-4 px-4">Sensor Node</th>
              <th className="py-4 px-4">Severity</th>
              <th className="py-4 px-4">Disposition</th>
              <th className="py-4 px-7 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100/70">
            {filteredAlerts.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-24 text-center">
                  <div className="max-w-xs mx-auto space-y-2">
                    <div className="w-12 h-12 rounded-full bg-white/80 flex items-center justify-center mx-auto text-gray-400 shadow-xs border border-white">
                      <ShieldAlert className="w-6 h-6" />
                    </div>
                    <p className="text-base font-bold text-gray-800">No matching threat records</p>
                    <p className="text-xs text-gray-400">All surveillance sectors are currently within baseline parameters.</p>
                  </div>
                </td>
              </tr>
            ) : (
              filteredAlerts.map((item) => {
                const timeStr = item.timestamp
                  ? new Date(item.timestamp).toLocaleString([], {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit',
                      hour12: false
                    })
                  : '—';

                return (
                  <tr
                    key={item.alert_id}
                    onClick={() => onViewAlert && onViewAlert(item)}
                    className="hover:bg-white/80 transition-colors cursor-pointer group"
                  >
                    <td className="py-4 px-7 font-mono text-xs text-gray-500 whitespace-nowrap font-medium">
                      {timeStr}
                    </td>
                    <td className="py-4 px-4 font-bold text-gray-900">
                      <div className="flex items-center space-x-3">
                        {item.snapshot ? (
                          <img
                            src={getAuthenticatedMediaUrl(item.snapshot)}
                            alt=""
                            onError={(e) => { e.target.style.display = 'none'; }}
                            className="w-10 h-10 rounded-xl object-cover border border-white shadow-xs shrink-0"
                          />
                        ) : (
                          <div className="w-10 h-10 rounded-xl bg-white border border-gray-200 flex items-center justify-center shrink-0 text-gray-400 shadow-2xs">
                            <Radio className="w-4 h-4" />
                          </div>
                        )}
                        <span className="truncate max-w-sm">{item.objects_detected || item.event_type}</span>
                      </div>
                    </td>
                    <td className="py-4 px-4 font-mono text-xs font-bold text-gray-600">
                      <span className="bg-white/90 px-2.5 py-1 rounded-full border border-gray-200/80 shadow-2xs">
                        {item.camera_id}
                      </span>
                    </td>
                    <td className="py-4 px-4">
                      {getSeverityBadge(item)}
                    </td>
                    <td className="py-4 px-4">
                      {getStatusBadge(item.status)}
                    </td>
                    <td className="py-4 px-7 text-right whitespace-nowrap">
                      <div
                        className="inline-flex items-center space-x-2"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          onClick={() => onViewAlert && onViewAlert(item)}
                          className="px-3 py-1.5 text-xs font-bold text-blue-600 hover:bg-blue-500/10 rounded-full transition-colors border border-transparent hover:border-blue-200"
                        >
                          View
                        </button>

                        {item.status === 'NEW' && (
                          <button
                            onClick={(e) => handleAcknowledge(e, item.alert_id)}
                            disabled={updatingId === item.alert_id}
                            className="px-3.5 py-1.5 text-xs font-bold text-amber-700 bg-amber-500/10 hover:bg-amber-500/20 rounded-full transition-colors border border-amber-300 shadow-2xs"
                          >
                            Review
                          </button>
                        )}

                        {item.status !== 'RESOLVED' && (
                          <button
                            onClick={(e) => handleResolve(e, item.alert_id)}
                            disabled={updatingId === item.alert_id}
                            className="px-3.5 py-1.5 text-xs font-bold text-emerald-700 bg-emerald-500/10 hover:bg-emerald-500/20 rounded-full transition-colors border border-emerald-300 shadow-2xs"
                          >
                            Resolve
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
