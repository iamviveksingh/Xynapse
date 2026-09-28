import React, { useState, useEffect, useRef } from 'react';
import {
  X,
  UserCheck,
  ShieldAlert,
  UserPlus,
  Trash2,
  Camera,
  Upload,
  RefreshCw,
  Search,
  CheckCircle,
  AlertTriangle,
  RotateCcw,
  Sparkles,
  User,
  Fingerprint
} from 'lucide-react';
import {
  fetchFaces,
  fetchFaceStats,
  enrollFace,
  enrollFaceFromCamera,
  deleteFace,
  authFetch,
  getAuthenticatedMediaUrl
} from '../services/api';

export default function FaceManagerModal({ isOpen, onClose, onProfilesChanged, activeCameraId = 'CAM-01' }) {
  const [faces, setFaces] = useState([]);
  const [stats, setStats] = useState({ total: 0, authorized_count: 0, suspect_count: 0 });
  const [loading, setLoading] = useState(false);
  const [activeFilter, setActiveFilter] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');

  // Enroll Form State
  const [showEnrollForm, setShowEnrollForm] = useState(false);
  const [enrollName, setEnrollName] = useState('');
  const [enrollRole, setEnrollRole] = useState('AUTHORIZED_GUARD');
  const [enrollNotes, setEnrollNotes] = useState('');

  // Mode: 'UPLOAD' or 'CAMERA'
  const [captureMode, setCaptureMode] = useState('UPLOAD');
  const [selectedFile, setSelectedFile] = useState(null);
  const [capturedBlob, setCapturedBlob] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [isSnapping, setIsSnapping] = useState(false);
  const [streamKey, setStreamKey] = useState(Date.now());

  const [enrollSubmitting, setEnrollSubmitting] = useState(false);
  const [statusMessage, setStatusMessage] = useState(null);

  const fileInputRef = useRef(null);

  const loadFaces = async () => {
    setLoading(true);
    try {
      const [facesData, statsData] = await Promise.all([
        fetchFaces(),
        fetchFaceStats()
      ]);
      setFaces(facesData);
      setStats(statsData);
      if (onProfilesChanged) onProfilesChanged();
    } catch (err) {
      console.error('[FaceManager] Failed to load roster:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      loadFaces();
      setStatusMessage(null);
      setShowEnrollForm(false);
      resetPhotoState();
    }
  }, [isOpen]);

  const resetPhotoState = () => {
    setSelectedFile(null);
    setCapturedBlob(null);
    setPreviewUrl(null);
    setStreamKey(Date.now());
  };

  if (!isOpen) return null;

  const handleFileSelect = (file) => {
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      setStatusMessage({ type: 'error', text: 'Please select an image file (JPG, PNG, or WEBP).' });
      return;
    }
    setSelectedFile(file);
    setCapturedBlob(null);
    setStatusMessage(null);

    const reader = new FileReader();
    reader.onloadend = () => {
      setPreviewUrl(reader.result);
    };
    reader.readAsDataURL(file);
  };

  const handleFileInputChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      handleFileSelect(e.target.files[0]);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleSnapPhoto = async () => {
    setIsSnapping(true);
    setStatusMessage(null);
    try {
      const camId = activeCameraId || 'CAM-01';
      const res = await authFetch(`/api/cameras/${camId}/snapshot?t=${Date.now()}`);
      if (!res.ok) {
        throw new Error('Camera snapshot is not ready. Please ensure the camera is active.');
      }
      const blob = await res.blob();
      setCapturedBlob(blob);
      setSelectedFile(null);
      const url = URL.createObjectURL(blob);
      setPreviewUrl(url);
    } catch (err) {
      setStatusMessage({
        type: 'error',
        text: err.detail || err.message || 'Failed to capture snapshot from camera.'
      });
    } finally {
      setIsSnapping(false);
    }
  };

  const handleRetakePhoto = () => {
    setCapturedBlob(null);
    setPreviewUrl(null);
    setStreamKey(Date.now());
  };

  const handleEnrollSubmit = async (e) => {
    e.preventDefault();
    if (!enrollName.trim()) {
      setStatusMessage({ type: 'error', text: 'Please provide a person name.' });
      return;
    }

    setEnrollSubmitting(true);
    setStatusMessage(null);

    try {
      let fileToUpload = null;

      if (captureMode === 'CAMERA' && capturedBlob) {
        fileToUpload = new File([capturedBlob], `${enrollName.replace(/\s+/g, '_')}_snap.jpg`, { type: 'image/jpeg' });
      } else if (captureMode === 'UPLOAD' && selectedFile) {
        fileToUpload = selectedFile;
      }

      if (!fileToUpload) {
        setStatusMessage({ type: 'error', text: 'Please select a photo or snap one from the camera.' });
        setEnrollSubmitting(false);
        return;
      }

      const formData = new FormData();
      formData.append('name', enrollName.trim());
      formData.append('role', enrollRole);
      formData.append('notes', enrollNotes.trim());
      formData.append('file', fileToUpload);

      const result = await enrollFace(formData);
      const personName = result?.profile?.name || result?.name || enrollName.trim();

      setStatusMessage({
        type: 'success',
        text: `Enrolled "${personName}" successfully as ${enrollRole === 'AUTHORIZED_GUARD' ? 'Authorized Guard' : 'Suspect Watchlist'}.`
      });

      setEnrollName('');
      setEnrollNotes('');
      resetPhotoState();
      setShowEnrollForm(false);
      await loadFaces();
      if (onProfilesChanged) {
        onProfilesChanged();
      }
    } catch (err) {
      console.error('Enroll error:', err);
      setStatusMessage({
        type: 'error',
        text: err.message || 'Failed to enroll face profile.'
      });
    } finally {
      setEnrollSubmitting(false);
    }
  };

  const handleDelete = async (faceId, name) => {
    if (!window.confirm(`Are you sure you want to remove "${name}" from the face roster?`)) return;
    try {
      await deleteFace(faceId);
      setStatusMessage({ type: 'success', text: `Removed "${name}" from roster.` });
      await loadFaces();
    } catch (err) {
      setStatusMessage({ type: 'error', text: err.detail || err.message || 'Failed to remove face profile.' });
    }
  };

  const filteredFaces = faces.filter((p) => {
    if (activeFilter !== 'ALL' && p.role !== activeFilter) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return p.name.toLowerCase().includes(q) || (p.notes && p.notes.toLowerCase().includes(q));
    }
    return true;
  });

  return (
    <div className="spatial-modal-backdrop">
      <div className="neo-glass-elevated relative w-full max-w-4xl max-h-[92vh] flex flex-col overflow-hidden text-gray-900 border border-white/80">
        {/* Header */}
        <div className="px-7 py-5 border-b border-white/60 bg-white/70 backdrop-blur-xl flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <div className="w-11 h-11 rounded-2xl bg-blue-500/10 text-blue-600 flex items-center justify-center border border-blue-200/50 shadow-xs">
              <Fingerprint className="w-5 h-5 text-emerald-500 stroke-[2.2]" />
            </div>
            <div>
              <div className="flex items-center space-x-2.5">
                <h2 className="text-lg sm:text-xl font-extrabold text-gray-900 tracking-tight">
                  Biometric Face Roster
                </h2>
                <span className="text-xs font-mono text-gray-600 bg-white px-2.5 py-0.5 rounded-full border border-gray-200 font-bold shadow-2xs">
                  SFace 128-D
                </span>
              </div>
              <p className="text-xs sm:text-[13px] text-gray-500 font-medium">
                Manage authorized patrol personnel and watchlist targets for automated cosine matching
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 rounded-full text-gray-400 hover:text-gray-900 hover:bg-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Status Message */}
        {statusMessage && (
          <div
            className={`mx-7 mt-4 p-3.5 rounded-2xl border flex items-center justify-between text-xs font-bold ${
              statusMessage.type === 'success'
                ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                : 'bg-rose-50 border-rose-200 text-rose-700'
            }`}
          >
            <div className="flex items-center space-x-2">
              {statusMessage.type === 'success' ? (
                <CheckCircle className="w-4 h-4 shrink-0 text-emerald-600" />
              ) : (
                <AlertTriangle className="w-4 h-4 shrink-0 text-rose-600" />
              )}
              <span>{statusMessage.text}</span>
            </div>
            <button onClick={() => setStatusMessage(null)} className="text-gray-400 hover:text-gray-700">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Toolbar */}
        <div className="px-7 py-3.5 border-b border-white/60 flex flex-wrap items-center justify-between gap-3 bg-white/60">
          <div className="apple-segmented-control shadow-xs">
            <button
              onClick={() => setActiveFilter('ALL')}
              className={`apple-segmented-btn ${activeFilter === 'ALL' ? 'active' : ''}`}
            >
              All ({stats.total})
            </button>
            <button
              onClick={() => setActiveFilter('AUTHORIZED_GUARD')}
              className={`apple-segmented-btn ${activeFilter === 'AUTHORIZED_GUARD' ? 'active' : ''}`}
            >
              Guards ({stats.authorized_count})
            </button>
            <button
              onClick={() => setActiveFilter('SUSPECT_WATCHLIST')}
              className={`apple-segmented-btn ${activeFilter === 'SUSPECT_WATCHLIST' ? 'active' : ''}`}
            >
              Watchlist ({stats.suspect_count})
            </button>
          </div>

          <div className="flex items-center space-x-2.5">
            <div className="relative">
              <Search className="w-4 h-4 text-gray-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search name or notes..."
                className="pl-10 pr-3 py-2 rounded-full bg-white/90 border border-white text-xs text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500/30 w-52 shadow-2xs"
              />
            </div>

            <button
              onClick={() => {
                setShowEnrollForm(!showEnrollForm);
                if (!showEnrollForm) resetPhotoState();
              }}
              className="gel-btn-primary flex items-center space-x-1.5 px-4.5 py-2 text-xs font-bold"
            >
              <UserPlus className="w-4 h-4" />
              <span>{showEnrollForm ? 'Cancel' : 'Enroll Person'}</span>
            </button>
          </div>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto p-7 space-y-6 bg-white/30 backdrop-blur-md">
          {/* Enrollment Form */}
          {showEnrollForm && (
            <div className="bg-white/80 border border-white rounded-3xl p-6 space-y-4 shadow-sm">
              <div className="flex items-center justify-between border-b border-gray-100 pb-3">
                <div className="flex items-center space-x-2">
                  <UserPlus className="w-4 h-4 text-blue-600" />
                  <h3 className="text-xs font-bold text-gray-900 uppercase tracking-wider">Enroll Face Biometric Profile</h3>
                </div>
                <span className="text-[11px] text-gray-400 font-mono">
                  SFace 128-D Embedding
                </span>
              </div>

              <form onSubmit={handleEnrollSubmit} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                  <div className="space-y-3.5">
                    <div>
                      <label className="block text-xs font-bold text-gray-600 mb-1">
                        Full Name *
                      </label>
                      <input
                        type="text"
                        required
                        value={enrollName}
                        onChange={(e) => setEnrollName(e.target.value)}
                        placeholder="e.g. Officer Sharma"
                        className="w-full px-3.5 py-2 rounded-xl bg-white border border-gray-200 text-xs text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500/30 shadow-2xs"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-gray-600 mb-1.5">
                        Access Role *
                      </label>
                      <div className="grid grid-cols-2 gap-2.5">
                        <div
                          onClick={() => setEnrollRole('AUTHORIZED_GUARD')}
                          className={`p-3.5 rounded-2xl border cursor-pointer transition-all ${
                            enrollRole === 'AUTHORIZED_GUARD'
                              ? 'bg-emerald-500/10 border-emerald-300 shadow-xs'
                              : 'bg-white border-gray-200 hover:border-gray-300'
                          }`}
                        >
                          <div className="flex items-center space-x-2 text-emerald-700 font-bold text-xs">
                            <UserCheck className="w-4 h-4" />
                            <span>Authorized Guard</span>
                          </div>
                          <p className="text-[11px] text-gray-500 mt-1">
                            Silences alarms automatically.
                          </p>
                        </div>

                        <div
                          onClick={() => setEnrollRole('SUSPECT_WATCHLIST')}
                          className={`p-3.5 rounded-2xl border cursor-pointer transition-all ${
                            enrollRole === 'SUSPECT_WATCHLIST'
                              ? 'bg-rose-500/10 border-rose-300 shadow-xs'
                              : 'bg-white border-gray-200 hover:border-gray-300'
                          }`}
                        >
                          <div className="flex items-center space-x-2 text-rose-700 font-bold text-xs">
                            <ShieldAlert className="w-4 h-4" />
                            <span>Watchlist Target</span>
                          </div>
                          <p className="text-[11px] text-gray-500 mt-1">
                            Triggers critical security alerts.
                          </p>
                        </div>
                      </div>
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-gray-600 mb-1">
                        Operational Notes
                      </label>
                      <input
                        type="text"
                        value={enrollNotes}
                        onChange={(e) => setEnrollNotes(e.target.value)}
                        placeholder="e.g. Sector 4 Patrol Lead"
                        className="w-full px-3.5 py-2 rounded-xl bg-white border border-gray-200 text-xs text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500/30 shadow-2xs"
                      />
                    </div>
                  </div>

                  {/* Photo Selection */}
                  <div className="space-y-3">
                    <label className="block text-xs font-bold text-gray-600">
                      Photo Evidence Source *
                    </label>

                    <div className="apple-segmented-control w-full flex shadow-xs">
                      <button
                        type="button"
                        onClick={() => {
                          setCaptureMode('UPLOAD');
                          resetPhotoState();
                        }}
                        className={`apple-segmented-btn flex-1 ${captureMode === 'UPLOAD' ? 'active' : ''}`}
                      >
                        Upload Photo File
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setCaptureMode('CAMERA');
                          resetPhotoState();
                        }}
                        className={`apple-segmented-btn flex-1 ${captureMode === 'CAMERA' ? 'active' : ''}`}
                      >
                        Live Camera Snap
                      </button>
                    </div>

                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/jpeg,image/png,image/webp,image/jpg"
                      onChange={handleFileInputChange}
                      className="hidden"
                    />

                    {captureMode === 'UPLOAD' && (
                      <div className="space-y-2">
                        {previewUrl ? (
                          <div className="h-44 rounded-2xl border border-white bg-white p-3 flex flex-col items-center justify-between shadow-xs">
                            <img
                              src={previewUrl}
                              alt="Preview"
                              className="max-h-28 object-contain rounded-xl"
                            />
                            <div className="w-full flex items-center justify-between text-xs pt-2 border-t border-gray-100">
                              <span className="text-gray-400 truncate max-w-[180px] font-mono text-[11px]">
                                {selectedFile?.name || 'Selected Photo'}
                              </span>
                              <button
                                type="button"
                                onClick={resetPhotoState}
                                className="text-rose-600 hover:underline font-bold"
                              >
                                Remove
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div
                            onDragOver={(e) => e.preventDefault()}
                            onDrop={handleDrop}
                            onClick={() => fileInputRef.current && fileInputRef.current.click()}
                            className="h-44 border-2 border-dashed border-gray-200 hover:border-blue-500 rounded-2xl flex flex-col items-center justify-center p-6 text-center bg-white cursor-pointer transition-colors shadow-2xs"
                          >
                            <Upload className="w-7 h-7 text-gray-400 mb-2" />
                            <span className="text-xs font-bold text-blue-600">Browse Photo File</span>
                            <span className="text-[11px] text-gray-400 mt-1">or drag and drop here</span>
                          </div>
                        )}
                      </div>
                    )}

                    {captureMode === 'CAMERA' && (
                      <div className="space-y-2">
                        {capturedBlob ? (
                          <div className="h-44 rounded-2xl border border-emerald-300 bg-white p-3 flex flex-col items-center justify-between shadow-xs">
                            <img
                              src={previewUrl}
                              alt="Captured"
                              className="max-h-28 object-contain rounded-xl"
                            />
                            <div className="w-full flex items-center justify-between text-xs pt-2 border-t border-gray-100">
                              <span className="text-emerald-700 font-bold text-[11px] flex items-center gap-1">
                                <CheckCircle className="w-4 h-4 text-emerald-600" />
                                Snapshot Ready
                              </span>
                              <button
                                type="button"
                                onClick={handleRetakePhoto}
                                className="text-blue-600 hover:underline flex items-center space-x-1 font-bold"
                              >
                                <RotateCcw className="w-3.5 h-3.5" />
                                <span>Retake</span>
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="space-y-2">
                            <div className="h-36 rounded-2xl border border-slate-800 bg-black relative overflow-hidden flex items-center justify-center shadow-inner">
                              <img
                                src={getAuthenticatedMediaUrl(`/api/cameras/${activeCameraId || 'CAM-01'}/stream?t=${streamKey}`)}
                                alt="Camera Stream"
                                className="w-full h-full object-cover"
                              />
                            </div>
                            <button
                              type="button"
                              onClick={handleSnapPhoto}
                              disabled={isSnapping}
                              className="gel-btn-secondary w-full py-2.5 text-xs font-bold flex items-center justify-center space-x-2"
                            >
                              <Camera className="w-4 h-4 text-gray-600" />
                              <span>{isSnapping ? 'Snapping...' : 'Capture Snapshot'}</span>
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex items-center justify-end space-x-2.5 pt-3 border-t border-gray-100">
                  <button
                    type="button"
                    onClick={() => {
                      setShowEnrollForm(false);
                      resetPhotoState();
                    }}
                    className="gel-btn-secondary px-4 py-2 text-xs font-semibold text-gray-500 hover:text-gray-900"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={enrollSubmitting}
                    className="gel-btn-primary px-5 py-2 text-xs font-bold disabled:opacity-50"
                  >
                    {enrollSubmitting ? 'Enrolling...' : 'Save Profile'}
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* Roster Grid */}
          <div>
            <div className="flex items-center justify-between mb-3.5">
              <h3 className="text-xs font-bold text-gray-900 uppercase tracking-wider">
                Enrolled Profiles ({filteredFaces.length})
              </h3>
              <button
                onClick={loadFaces}
                className="text-xs text-blue-600 hover:underline flex items-center space-x-1 font-bold"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                <span>Refresh</span>
              </button>
            </div>

            {filteredFaces.length === 0 ? (
              <div className="border border-white bg-white/80 rounded-3xl p-12 text-center space-y-2.5 shadow-xs">
                <User className="w-10 h-10 text-gray-300 mx-auto" />
                <h4 className="text-sm font-bold text-gray-800">No Profiles Found</h4>
                <p className="text-xs text-gray-400 max-w-sm mx-auto">
                  Add authorized team members or watchlist suspects to activate facial recognition alerts.
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {filteredFaces.map((person) => {
                  const isAuth = person.role === 'AUTHORIZED_GUARD';
                  return (
                    <div
                      key={person.id}
                      className="p-4 rounded-2xl bg-white/80 hover:bg-white border border-white hover:border-blue-300 shadow-xs flex items-start space-x-3.5 transition-all"
                    >
                      <div className="w-14 h-14 rounded-2xl bg-gray-100 border border-white overflow-hidden shrink-0 flex items-center justify-center relative shadow-xs ring-1 ring-slate-200/60">
                        {person.photo_path ? (
                          <img
                            src={getAuthenticatedMediaUrl(person.photo_path)}
                            alt={person.name}
                            className="w-full h-full object-cover"
                            onError={(e) => {
                              e.currentTarget.style.display = 'none';
                              const fb = e.currentTarget.parentElement.querySelector('.avatar-fallback');
                              if (fb) fb.style.display = 'flex';
                            }}
                          />
                        ) : null}
                        <div
                          className="avatar-fallback w-full h-full items-center justify-center font-extrabold text-base text-gray-500 bg-slate-100"
                          style={{ display: person.photo_path ? 'none' : 'flex' }}
                        >
                          {person.name.charAt(0).toUpperCase()}
                        </div>
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <h4 className="text-xs sm:text-[13px] font-extrabold text-gray-900 truncate">
                            {person.name}
                          </h4>
                          <button
                            onClick={() => handleDelete(person.id, person.name)}
                            className="text-gray-400 hover:text-rose-600 p-1.5 rounded-full hover:bg-rose-50 transition-colors"
                            title="Remove person"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>

                        <div className="mt-1">
                          <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                            isAuth
                              ? 'bg-emerald-500/10 text-emerald-700 border border-emerald-300'
                              : 'bg-rose-500/10 text-rose-700 border border-rose-300'
                          }`}>
                            {isAuth ? 'Authorized Guard' : 'Watchlist Target'}
                          </span>
                        </div>

                        {person.notes && (
                          <p className="text-xs text-gray-400 mt-1 truncate">
                            {person.notes}
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-7 py-4 border-t border-white/60 bg-white/70 flex items-center justify-between text-xs text-gray-500">
          <div className="flex items-center space-x-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="font-mono text-xs text-gray-600 font-medium">Real-Time Facial Cosine Verification Active</span>
          </div>
          <button
            onClick={onClose}
            className="gel-btn-secondary px-5 py-2 text-xs font-semibold"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
