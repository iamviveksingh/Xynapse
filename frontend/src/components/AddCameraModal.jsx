import React, { useState, useEffect } from 'react';
import { Camera, X, Plus, ShieldCheck, Truck, Eye, Smartphone, CheckCircle, RefreshCw, Sparkles } from 'lucide-react';
import { addCamera, seedDefaultSectors, fetchDetectedDevices } from '../services/api';

export default function AddCameraModal({ isOpen, onClose, onCameraAdded, existingCameraCount = 1 }) {
  const [cameraId, setCameraId] = useState(`CAM-0${existingCameraCount + 1}`);
  const [name, setName] = useState('');
  const [sourceType, setSourceType] = useState('DEVICE'); // 'DEVICE', 'IP_WEBCAM', 'RTSP', 'SIMULATED'
  const [selectedDeviceIndex, setSelectedDeviceIndex] = useState('0');
  const [customSource, setCustomSource] = useState('');
  const [surveillanceMode, setSurveillanceMode] = useState('CHECKPOST');
  const [opticalMode, setOpticalMode] = useState('STANDARD');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [detectedDevices, setDetectedDevices] = useState([]);
  const [isLoadingDevices, setIsLoadingDevices] = useState(false);

  const loadDevices = async () => {
    setIsLoadingDevices(true);
    try {
      const devs = await fetchDetectedDevices();
      setDetectedDevices(devs || []);
      const hasDevice1 = devs.some((d) => d.source === '1');
      if (hasDevice1 && !selectedDeviceIndex) {
        setSelectedDeviceIndex('1');
      }
    } catch {
      setDetectedDevices([]);
    } finally {
      setIsLoadingDevices(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      loadDevices();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErrorMsg('');

    let source = '0';
    if (sourceType === 'DEVICE') source = selectedDeviceIndex;
    else if (sourceType === 'IP_WEBCAM') source = customSource.trim() || 'http://192.168.1.100:8080/video';
    else if (sourceType === 'RTSP') source = customSource.trim() || 'rtsp://127.0.0.1:554/live';
    else source = `sim_${cameraId.toLowerCase()}`;

    const sectorName = name.trim() || (
      source === '1'
        ? `Sector Bravo • Phone ANPR Checkpost`
        : `${cameraId} • Tactical Border Sector`
    );

    setIsSubmitting(true);
    try {
      await addCamera({
        cameraId: cameraId.trim().toUpperCase(),
        name: sectorName,
        source,
        surveillanceMode,
        opticalMode
      });
      if (onCameraAdded) onCameraAdded();
      onClose();
    } catch (err) {
      setErrorMsg(err.message || 'Failed to add camera');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSeedDefaults = async () => {
    setIsSubmitting(true);
    setErrorMsg('');
    try {
      await seedDefaultSectors();
      if (onCameraAdded) onCameraAdded();
      onClose();
    } catch (err) {
      setErrorMsg(err.message || 'Failed to seed default sectors');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-fadeIn">
      <div className="bg-white border border-[#E5E5E7] rounded-3xl w-full max-w-xl overflow-hidden shadow-2xl flex flex-col text-[#1D1D1F]">
        {/* Header */}
        <div className="px-6 py-4 bg-white border-b border-[#E5E5E7] flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-2xl bg-[#0071E3]/10 text-[#0071E3] flex items-center justify-center">
              <Camera className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-semibold text-base text-[#1D1D1F]">Add Surveillance Camera</h3>
              <p className="text-xs text-[#86868B]">Deploy a physical webcam, phone camera, or RTSP feed</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-[#86868B] hover:text-[#1D1D1F] hover:bg-[#F5F5F7] transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {errorMsg && (
            <div className="p-3 rounded-xl bg-[#FF3B30]/10 border border-[#FF3B30]/20 text-[#FF3B30] text-xs">
              {errorMsg}
            </div>
          )}

          {/* Quick Phone Detection Banner */}
          {detectedDevices.some((d) => d.source === '1') && (
            <div className="bg-[#34C759]/10 border border-[#34C759]/20 p-3.5 rounded-2xl flex items-center justify-between gap-3">
              <div className="flex items-center space-x-2.5">
                <div className="p-2 bg-white text-[#34C759] rounded-xl shadow-sm">
                  <Smartphone className="w-4 h-4" />
                </div>
                <div>
                  <span className="text-xs font-semibold text-[#1D1D1F] block">Phone Camera Detected (Device #1)</span>
                  <span className="text-[11px] text-[#6E6E73]">Connected phone webcam is ready for live streaming.</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  setSourceType('DEVICE');
                  setSelectedDeviceIndex('1');
                  setName((prev) => prev || 'Checkpost Bravo • Phone ANPR Gate');
                  setSurveillanceMode('CHECKPOST');
                }}
                className="px-3 py-1.5 rounded-xl bg-[#34C759] hover:bg-[#34C759]/90 text-white font-medium text-xs transition-colors shrink-0 shadow-sm"
              >
                Use Phone Cam
              </button>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-[#1D1D1F] mb-1">Camera ID</label>
              <input
                type="text"
                required
                value={cameraId}
                onChange={(e) => setCameraId(e.target.value)}
                placeholder="CAM-02"
                className="w-full bg-[#FAFBFD] border border-[#E5E5E7] rounded-xl px-3 py-2 text-xs text-[#1D1D1F] font-mono uppercase focus:outline-none focus:border-[#0071E3] transition-colors"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#1D1D1F] mb-1">Sector Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Checkpost Bravo"
                className="w-full bg-[#FAFBFD] border border-[#E5E5E7] rounded-xl px-3 py-2 text-xs text-[#1D1D1F] focus:outline-none focus:border-[#0071E3] transition-colors"
              />
            </div>
          </div>

          {/* Video Feed Source Tabs */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs font-medium text-[#1D1D1F]">Video Input Source</label>
              <button
                type="button"
                onClick={loadDevices}
                className="text-[11px] text-[#0071E3] hover:underline flex items-center space-x-1"
                title="Rescan connected cameras"
              >
                <RefreshCw className={`w-3 h-3 ${isLoadingDevices ? 'animate-spin' : ''}`} />
                <span>Rescan</span>
              </button>
            </div>

            <div className="apple-segmented-control w-full flex text-xs mb-2.5">
              <button
                type="button"
                onClick={() => setSourceType('DEVICE')}
                className={`apple-segmented-btn flex-1 ${sourceType === 'DEVICE' ? 'active' : ''}`}
              >
                Connected Webcam
              </button>
              <button
                type="button"
                onClick={() => setSourceType('IP_WEBCAM')}
                className={`apple-segmented-btn flex-1 ${sourceType === 'IP_WEBCAM' ? 'active' : ''}`}
              >
                Phone Wi-Fi
              </button>
              <button
                type="button"
                onClick={() => setSourceType('RTSP')}
                className={`apple-segmented-btn flex-1 ${sourceType === 'RTSP' ? 'active' : ''}`}
              >
                RTSP Stream
              </button>
              <button
                type="button"
                onClick={() => setSourceType('SIMULATED')}
                className={`apple-segmented-btn flex-1 ${sourceType === 'SIMULATED' ? 'active' : ''}`}
              >
                Standby Loop
              </button>
            </div>

            {sourceType === 'DEVICE' && (
              <div className="space-y-2 bg-[#FAFBFD] border border-[#E5E5E7] p-3 rounded-2xl">
                <span className="text-[11px] text-[#86868B] block">
                  Select device index:
                </span>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedDeviceIndex('0');
                      setName((prev) => prev || 'Sector Alpha • PC Webcam');
                    }}
                    className={`p-2.5 rounded-xl border text-left flex items-center justify-between transition-all ${
                      selectedDeviceIndex === '0'
                        ? 'bg-white text-[#1D1D1F] border-[#0071E3] shadow-sm font-semibold'
                        : 'bg-white text-[#6E6E73] border-[#E5E5E7] hover:border-[#D2D2D7]'
                    }`}
                  >
                    <div>
                      <span className="block text-xs">Device #0 (Primary)</span>
                      <span className="text-[10px] text-[#86868B]">Integrated PC Camera</span>
                    </div>
                    {selectedDeviceIndex === '0' && <CheckCircle className="w-4 h-4 text-[#0071E3]" />}
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setSelectedDeviceIndex('1');
                      setName((prev) => prev || 'Checkpost Bravo • Phone ANPR');
                      setSurveillanceMode('CHECKPOST');
                    }}
                    className={`p-2.5 rounded-xl border text-left flex items-center justify-between transition-all ${
                      selectedDeviceIndex === '1'
                        ? 'bg-white text-[#1D1D1F] border-[#0071E3] shadow-sm font-semibold'
                        : 'bg-white text-[#6E6E73] border-[#E5E5E7] hover:border-[#D2D2D7]'
                    }`}
                  >
                    <div>
                      <div className="flex items-center space-x-1.5">
                        <Smartphone className="w-3.5 h-3.5 text-[#34C759]" />
                        <span className="block text-xs">Device #1 (Phone)</span>
                      </div>
                      <span className="text-[10px] text-[#86868B]">DroidCam / Camo</span>
                    </div>
                    {selectedDeviceIndex === '1' && <CheckCircle className="w-4 h-4 text-[#0071E3]" />}
                  </button>
                </div>
              </div>
            )}

            {sourceType === 'IP_WEBCAM' && (
              <div className="space-y-1">
                <input
                  type="text"
                  value={customSource}
                  onChange={(e) => setCustomSource(e.target.value)}
                  placeholder="http://192.168.1.15:8080/video"
                  className="w-full bg-[#FAFBFD] border border-[#E5E5E7] rounded-xl px-3 py-2 text-xs text-[#1D1D1F] font-mono focus:outline-none focus:border-[#0071E3]"
                />
                <p className="text-[11px] text-[#86868B]">
                  Enter local IP Webcam URL from your smartphone.
                </p>
              </div>
            )}

            {sourceType === 'RTSP' && (
              <input
                type="text"
                value={customSource}
                onChange={(e) => setCustomSource(e.target.value)}
                placeholder="rtsp://admin:pass@192.168.1.100:554/live"
                className="w-full bg-[#FAFBFD] border border-[#E5E5E7] rounded-xl px-3 py-2 text-xs text-[#1D1D1F] font-mono focus:outline-none focus:border-[#0071E3]"
              />
            )}
          </div>

          {/* Operational Surveillance Mode */}
          <div>
            <label className="block text-xs font-medium text-[#1D1D1F] mb-1.5">Operational Mission Mode</label>
            <div className="apple-segmented-control w-full flex">
              <button
                type="button"
                onClick={() => setSurveillanceMode('PERIMETER')}
                className={`apple-segmented-btn flex-1 ${surveillanceMode === 'PERIMETER' ? 'active' : ''}`}
              >
                Perimeter (FRS)
              </button>
              <button
                type="button"
                onClick={() => setSurveillanceMode('CHECKPOST')}
                className={`apple-segmented-btn flex-1 ${surveillanceMode === 'CHECKPOST' ? 'active' : ''}`}
              >
                Checkpost (ANPR)
              </button>
              <button
                type="button"
                onClick={() => setSurveillanceMode('UNIFIED')}
                className={`apple-segmented-btn flex-1 ${surveillanceMode === 'UNIFIED' ? 'active' : ''}`}
              >
                Unified Defense
              </button>
            </div>
          </div>

          {/* Optical Mode */}
          <div>
            <label className="block text-xs font-medium text-[#1D1D1F] mb-1.5">Optical Sensor Pipeline</label>
            <div className="apple-segmented-control w-full flex">
              <button
                type="button"
                onClick={() => setOpticalMode('STANDARD')}
                className={`apple-segmented-btn flex-1 ${opticalMode === 'STANDARD' ? 'active' : ''}`}
              >
                Day RGB
              </button>
              <button
                type="button"
                onClick={() => setOpticalMode('LOW_LIGHT_ENHANCE')}
                className={`apple-segmented-btn flex-1 ${opticalMode === 'LOW_LIGHT_ENHANCE' ? 'active' : ''}`}
              >
                Night CLAHE
              </button>
              <button
                type="button"
                onClick={() => setOpticalMode('NVG_GREEN')}
                className={`apple-segmented-btn flex-1 ${opticalMode === 'NVG_GREEN' ? 'active' : ''}`}
              >
                NVG (Sim)
              </button>
              <button
                type="button"
                onClick={() => setOpticalMode('FLIR_THERMAL')}
                className={`apple-segmented-btn flex-1 ${opticalMode === 'FLIR_THERMAL' ? 'active' : ''}`}
              >
                Thermal (Sim)
              </button>
            </div>
          </div>

          {/* Actions */}
          <div className="pt-4 border-t border-[#E5E5E7] flex flex-wrap items-center justify-between gap-3">
            <button
              type="button"
              onClick={handleSeedDefaults}
              disabled={isSubmitting}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-[#F5F5F7] hover:bg-[#EBEBED] text-[#1D1D1F] border border-[#E5E5E7] transition-colors"
            >
              <Sparkles className="w-3.5 h-3.5 text-[#FF9500]" />
              <span>Deploy 4 Preset Sectors</span>
            </button>

            <div className="flex items-center space-x-2">
              <button
                type="button"
                onClick={onClose}
                className="px-3.5 py-1.5 rounded-xl text-xs text-[#86868B] hover:text-[#1D1D1F] transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting}
                className="flex items-center space-x-1.5 px-4 py-1.5 rounded-xl text-xs font-medium text-white bg-[#0071E3] hover:bg-[#0077ED] transition-colors shadow-sm"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Deploy Camera</span>
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
