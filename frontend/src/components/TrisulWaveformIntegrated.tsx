/**
 * Trisul Waveform Component (Integrated with Backend)
 * ====================================================
 * Phase 4: Jiva (Integration) - Connected to SARASVATI backend
 *
 * Uses useSarasvatiBackend hook to receive detected_error events
 * and draw red regions on the Interpreter track in real-time.
 */

"use client";

import { useEffect, useRef, useState } from "react";
import Multitrack from "wavesurfer-multitrack";
import type { MultitrackTracks } from "wavesurfer-multitrack";
import RegionsPlugin from "wavesurfer.js/dist/plugins/regions.esm.js";
import { Play, Square, AlertTriangle, Wifi, WifiOff } from "lucide-react";
import {
  useSarasvatiBackend,
  type ErrorRegion,
} from "@/hooks/useSarasvatiBackend";

interface TrackMetadata {
  id: string;
  role: "provider" | "interpreter" | "patient";
  label: string;
  color: string;
  icon: string;
}

const TRACK_METADATA: TrackMetadata[] = [
  {
    id: "provider",
    role: "provider",
    label: "Provider (Doctor)",
    color: "#3b82f6", // blue-500
    icon: "👨‍⚕️",
  },
  {
    id: "interpreter",
    role: "interpreter",
    label: "Interpreter",
    color: "#a855f7", // purple-500
    icon: "🌐",
  },
  {
    id: "patient",
    role: "patient",
    label: "Patient",
    color: "#10b981", // green-500
    icon: "🧑",
  },
];

interface TrisulWaveformIntegratedProps {
  backendUrl?: string;
  autoConnect?: boolean;
}

export function TrisulWaveformIntegrated({
  backendUrl = "ws://localhost:8000/ws",
  autoConnect = false,
}: TrisulWaveformIntegratedProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const multitrackRef = useRef<Multitrack | null>(null);
  const interpreterRegionsRef = useRef<RegionsPlugin | null>(null);
  const audioUrlsRef = useRef<string[]>([]);

  const [isSimulating, setIsSimulating] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [trackStatuses, setTrackStatuses] = useState<Record<string, "waiting" | "ready">>({
    provider: "waiting",
    interpreter: "waiting",
    patient: "waiting",
  });

  // Connect to backend
  const {
    isConnected,
    connectionError,
    state,
    connect,
    disconnect,
    startSession,
    clearErrors,
  } = useSarasvatiBackend({
    url: backendUrl,
    autoConnect,
    onError: (error) => {
      console.log("🔴 Error detected:", error);
      // Will be drawn as red region via useEffect
    },
  });

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      multitrackRef.current?.destroy();
      audioUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);

  // Draw red regions when errors are detected
  useEffect(() => {
    if (!interpreterRegionsRef.current || !multitrackRef.current) return;

    // Clear existing regions
    interpreterRegionsRef.current.clearRegions();

    // Draw red region for each error (using derived ErrorRegion)
    state.errorRegions.forEach((region) => {
      if (interpreterRegionsRef.current) {
        interpreterRegionsRef.current.addRegion({
          start: region.start,
          end: region.end,
          color: region.severity === "critical"
            ? "rgba(239, 68, 68, 0.4)" // red-500, more opaque for critical
            : "rgba(239, 68, 68, 0.2)", // red-500, less opaque for others
          drag: false,
          resize: false,
          content: region.description,
        });
      }
    });
  }, [state.errorRegions]);

  // Generate dummy audio buffer for simulation
  const generateDummyAudio = (
    duration: number,
    frequency: number,
    sampleRate: number = 44100
  ): AudioBuffer => {
    const audioContext = new AudioContext();
    const buffer = audioContext.createBuffer(1, duration * sampleRate, sampleRate);
    const data = buffer.getChannelData(0);

    for (let i = 0; i < buffer.length; i++) {
      const t = i / sampleRate;
      const sine = Math.sin(2 * Math.PI * frequency * t);
      const noise = (Math.random() - 0.5) * 0.3;
      const envelope = Math.sin((Math.PI * i) / buffer.length);
      data[i] = (sine * 0.7 + noise) * envelope * 0.5;
    }

    return buffer;
  };

  // AudioBuffer to WAV converter
  const audioBufferToWav = (buffer: AudioBuffer): ArrayBuffer => {
    const numberOfChannels = buffer.numberOfChannels;
    const sampleRate = buffer.sampleRate;
    const format = 1;
    const bitDepth = 16;
    const bytesPerSample = bitDepth / 8;
    const blockAlign = numberOfChannels * bytesPerSample;
    const data = buffer.getChannelData(0);
    const dataLength = data.length * bytesPerSample;
    const headerLength = 44;
    const totalLength = headerLength + dataLength;
    const arrayBuffer = new ArrayBuffer(totalLength);
    const view = new DataView(arrayBuffer);
    let offset = 0;

    const writeString = (str: string) => {
      for (let i = 0; i < str.length; i++) {
        view.setUint8(offset++, str.charCodeAt(i));
      }
    };

    writeString("RIFF");
    view.setUint32(offset, totalLength - 8, true);
    offset += 4;
    writeString("WAVE");
    writeString("fmt ");
    view.setUint32(offset, 16, true);
    offset += 4;
    view.setUint16(offset, format, true);
    offset += 2;
    view.setUint16(offset, numberOfChannels, true);
    offset += 2;
    view.setUint32(offset, sampleRate, true);
    offset += 4;
    view.setUint32(offset, sampleRate * blockAlign, true);
    offset += 4;
    view.setUint16(offset, blockAlign, true);
    offset += 2;
    view.setUint16(offset, bitDepth, true);
    offset += 2;
    writeString("data");
    view.setUint32(offset, dataLength, true);
    offset += 4;

    for (let i = 0; i < data.length; i++) {
      const sample = Math.max(-1, Math.min(1, data[i]));
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
      offset += 2;
    }

    return arrayBuffer;
  };

  // Start simulation mode
  const startSimulation = () => {
    if (!containerRef.current) return;

    setIsSimulating(true);

    const providerBuffer = generateDummyAudio(10, 200);
    const interpreterBuffer = generateDummyAudio(10, 300);
    const patientBuffer = generateDummyAudio(10, 250);

    const providerBlob = new Blob([audioBufferToWav(providerBuffer)], { type: "audio/wav" });
    const interpreterBlob = new Blob([audioBufferToWav(interpreterBuffer)], { type: "audio/wav" });
    const patientBlob = new Blob([audioBufferToWav(patientBuffer)], { type: "audio/wav" });

    const providerUrl = URL.createObjectURL(providerBlob);
    const interpreterUrl = URL.createObjectURL(interpreterBlob);
    const patientUrl = URL.createObjectURL(patientBlob);

    audioUrlsRef.current = [providerUrl, interpreterUrl, patientUrl];

    const interpreterRegions = RegionsPlugin.create();
    interpreterRegionsRef.current = interpreterRegions;

    const tracks: MultitrackTracks = [
      {
        id: "provider",
        url: providerUrl,
        startPosition: 0,
        options: {
          waveColor: TRACK_METADATA[0].color,
          progressColor: TRACK_METADATA[0].color + "cc",
          height: 80,
          normalize: true,
          barWidth: 2,
          barGap: 1,
          barRadius: 2,
        },
      },
      {
        id: "interpreter",
        url: interpreterUrl,
        startPosition: 0,
        options: {
          waveColor: TRACK_METADATA[1].color,
          progressColor: TRACK_METADATA[1].color + "cc",
          height: 80,
          normalize: true,
          barWidth: 2,
          barGap: 1,
          barRadius: 2,
          plugins: [interpreterRegions],
        },
      },
      {
        id: "patient",
        url: patientUrl,
        startPosition: 0,
        options: {
          waveColor: TRACK_METADATA[2].color,
          progressColor: TRACK_METADATA[2].color + "cc",
          height: 80,
          normalize: true,
          barWidth: 2,
          barGap: 1,
          barRadius: 2,
        },
      },
    ];

    const multitrack = Multitrack.create(tracks, {
      container: containerRef.current,
      cursorColor: "#ffffff",
      cursorWidth: 2,
      trackBackground: "#1f2937",
      trackBorderColor: "#374151",
      rightButtonDrag: false,
    });

    multitrackRef.current = multitrack;

    setTrackStatuses({
      provider: "ready",
      interpreter: "ready",
      patient: "ready",
    });

    // Start backend session if connected
    if (isConnected) {
      startSession();
    }
  };

  const togglePlayback = () => {
    if (!isSimulating || !multitrackRef.current) return;

    if (isPlaying) {
      multitrackRef.current.pause();
      setIsPlaying(false);
    } else {
      multitrackRef.current.play();
      setIsPlaying(true);
    }
  };

  const stopSimulation = () => {
    if (multitrackRef.current) {
      multitrackRef.current.pause();
      multitrackRef.current.destroy();
      multitrackRef.current = null;
    }

    interpreterRegionsRef.current?.clearRegions();
    interpreterRegionsRef.current = null;

    audioUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    audioUrlsRef.current = [];

    setIsSimulating(false);
    setIsPlaying(false);
    setTrackStatuses({
      provider: "waiting",
      interpreter: "waiting",
      patient: "waiting",
    });

    clearErrors();
  };

  return (
    <div className="trisul-waveform bg-gray-950 border border-gray-800 rounded-lg p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <span className="text-2xl">🔱</span>
            Trisul Protocol — Live Monitoring
          </h2>
          <p className="text-sm text-gray-400 mt-1 flex items-center gap-2">
            {isConnected ? (
              <>
                <Wifi className="w-3 h-3 text-green-500" />
                <span className="text-green-500">Connected to backend</span>
              </>
            ) : (
              <>
                <WifiOff className="w-3 h-3 text-red-500" />
                <span className="text-red-500">
                  {connectionError || "Disconnected"}
                </span>
              </>
            )}
          </p>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-3">
          {!isConnected && (
            <button
              onClick={connect}
              className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg font-medium transition flex items-center gap-2"
            >
              <Wifi className="w-4 h-4" />
              Connect Backend
            </button>
          )}

          {!isSimulating ? (
            <button
              onClick={startSimulation}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition flex items-center gap-2"
            >
              <Play className="w-4 h-4" />
              Start Simulation
            </button>
          ) : (
            <>
              <button
                onClick={togglePlayback}
                className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg font-medium transition flex items-center gap-2"
              >
                {isPlaying ? (
                  <>
                    <Square className="w-4 h-4" />
                    Pause
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4" />
                    Play
                  </>
                )}
              </button>
              <button
                onClick={stopSimulation}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg font-medium transition flex items-center gap-2"
              >
                <Square className="w-4 h-4" />
                Stop
              </button>
            </>
          )}
        </div>
      </div>

      {/* Track Headers */}
      <div className="space-y-3 mb-4">
        {TRACK_METADATA.map((track) => (
          <div
            key={track.id}
            className="flex items-center justify-between px-4 py-2 bg-gray-900 border border-gray-800 rounded-lg"
          >
            <div className="flex items-center gap-2">
              <span className="text-2xl">{track.icon}</span>
              <div>
                <h3 className="font-semibold text-sm text-white">{track.label}</h3>
                <p className="text-xs text-gray-400">
                  {trackStatuses[track.id] === "ready" ? (
                    <span className="flex items-center gap-1">
                      <span
                        className="w-2 h-2 rounded-full animate-pulse"
                        style={{ backgroundColor: track.color }}
                      />
                      {isPlaying ? "Playing" : "Ready"}
                    </span>
                  ) : (
                    "Waiting..."
                  )}
                </p>
              </div>
            </div>

            {/* Error count for interpreter track */}
            {track.role === "interpreter" && state.errorRegions.length > 0 && (
              <div className="flex items-center gap-2 px-3 py-1 bg-red-950 border border-red-800 rounded text-red-400 text-xs">
                <AlertTriangle className="w-3 h-3" />
                {state.errorRegions.length} Error{state.errorRegions.length > 1 ? "s" : ""} Detected
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Multitrack Container */}
      <div
        ref={containerRef}
        className="multitrack-container rounded-lg bg-gray-900 border border-gray-800 p-4"
        style={{ minHeight: "300px" }}
      />

      {/* Backend Stats */}
      {isConnected && state.isActive && (
        <div className="mt-6 p-4 bg-gray-900 border border-gray-800 rounded-lg">
          <h4 className="text-sm font-semibold text-white mb-2">
            Backend Stats
          </h4>
          <div className="grid grid-cols-3 gap-3 text-xs">
            <div>
              <div className="text-gray-400">Total Segments</div>
              <div className="text-white text-lg font-bold">
                {state.stats.totalSegments}
              </div>
            </div>
            <div>
              <div className="text-gray-400">Total Errors</div>
              <div className="text-white text-lg font-bold">
                {state.stats.totalErrors}
              </div>
            </div>
            <div>
              <div className="text-gray-400">Critical Errors</div>
              <div className="text-red-400 text-lg font-bold">
                {state.stats.criticalErrors}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Error List */}
      {state.errorRegions.length > 0 && (
        <div className="mt-6 p-4 bg-gray-900 border border-gray-800 rounded-lg">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-sm font-semibold text-white">
              Detected Errors ({state.errorRegions.length})
            </h4>
            <button
              onClick={clearErrors}
              className="text-xs text-gray-400 hover:text-white transition"
            >
              Clear
            </button>
          </div>
          <div className="space-y-2 max-h-40 overflow-y-auto">
            {state.errorRegions.map((region) => (
              <div
                key={region.id}
                className={`p-2 rounded text-xs ${
                  region.severity === "critical"
                    ? "bg-red-950 border border-red-800 text-red-300"
                    : "bg-orange-950 border border-orange-800 text-orange-300"
                }`}
              >
                <div className="font-semibold">{region.description}</div>
                <div className="text-gray-400 mt-1">
                  Time: {region.start.toFixed(1)}s | Confidence: {region.confidence.toFixed(2)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
