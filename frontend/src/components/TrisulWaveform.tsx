/**
 * Trisul Waveform Component
 * ==========================
 * Unified 3-track waveform visualization for Provider, Interpreter, Patient.
 * Uses wavesurfer.js with synchronized tracks and error region overlay.
 */

"use client";

import { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin from "wavesurfer.js/dist/plugins/regions.esm.js";
import { Play, Square, AlertTriangle } from "lucide-react";

interface Track {
  role: "provider" | "interpreter" | "patient";
  label: string;
  color: string;
  icon: string;
  wavesurfer: WaveSurfer | null;
  regions: RegionsPlugin | null;
}

export function TrisulWaveform() {
  const providerRef = useRef<HTMLDivElement>(null);
  const interpreterRef = useRef<HTMLDivElement>(null);
  const patientRef = useRef<HTMLDivElement>(null);

  const [tracks, setTracks] = useState<Track[]>([
    {
      role: "provider",
      label: "Provider (Doctor)",
      color: "#3b82f6", // blue-500
      icon: "👨‍⚕️",
      wavesurfer: null,
      regions: null,
    },
    {
      role: "interpreter",
      label: "Interpreter",
      color: "#a855f7", // purple-500
      icon: "🌐",
      wavesurfer: null,
      regions: null,
    },
    {
      role: "patient",
      label: "Patient",
      color: "#10b981", // green-500
      icon: "🧑",
      wavesurfer: null,
      regions: null,
    },
  ]);

  const [isSimulating, setIsSimulating] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);

  // Initialize WaveSurfer instances
  useEffect(() => {
    if (!providerRef.current || !interpreterRef.current || !patientRef.current)
      return;

    const refs = [providerRef.current, interpreterRef.current, patientRef.current];

    const newTracks = tracks.map((track, index) => {
      // Create regions plugin for interpreter track
      const regions =
        track.role === "interpreter" ? RegionsPlugin.create() : null;

      const wavesurfer = WaveSurfer.create({
        container: refs[index],
        waveColor: track.color,
        progressColor: track.color + "cc", // slightly transparent
        cursorColor: "#ffffff",
        barWidth: 2,
        barGap: 1,
        barRadius: 2,
        height: 80,
        normalize: true,
        plugins: regions ? [regions] : [],
      });

      return {
        ...track,
        wavesurfer,
        regions,
      };
    });

    setTracks(newTracks);

    // Cleanup
    return () => {
      newTracks.forEach((track) => {
        track.wavesurfer?.destroy();
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Generate dummy audio buffer for simulation
  const generateDummyAudio = (
    duration: number,
    frequency: number,
    sampleRate: number = 44100
  ): AudioBuffer => {
    const audioContext = new AudioContext();
    const buffer = audioContext.createBuffer(1, duration * sampleRate, sampleRate);
    const data = buffer.getChannelData(0);

    // Generate sine wave with some randomness for visual interest
    for (let i = 0; i < buffer.length; i++) {
      const t = i / sampleRate;
      // Mix of sine wave and noise
      const sine = Math.sin(2 * Math.PI * frequency * t);
      const noise = (Math.random() - 0.5) * 0.3;
      const envelope = Math.sin((Math.PI * i) / buffer.length); // fade in/out
      data[i] = (sine * 0.7 + noise) * envelope * 0.5;
    }

    return buffer;
  };

  // Start simulation mode
  const startSimulation = () => {
    if (tracks.some((t) => !t.wavesurfer)) return;

    setIsSimulating(true);

    // Generate different dummy waveforms for each track
    const providerBuffer = generateDummyAudio(10, 200); // Lower frequency
    const interpreterBuffer = generateDummyAudio(10, 300); // Mid frequency
    const patientBuffer = generateDummyAudio(10, 250); // Mid-low frequency

    // Load buffers into wavesurfer instances
    tracks[0].wavesurfer?.loadBlob(
      new Blob([audioBufferToWav(providerBuffer)], { type: "audio/wav" })
    );
    tracks[1].wavesurfer?.loadBlob(
      new Blob([audioBufferToWav(interpreterBuffer)], { type: "audio/wav" })
    );
    tracks[2].wavesurfer?.loadBlob(
      new Blob([audioBufferToWav(patientBuffer)], { type: "audio/wav" })
    );

    // Add red error region to interpreter track after loading
    setTimeout(() => {
      if (tracks[1].regions && tracks[1].wavesurfer) {
        const duration = tracks[1].wavesurfer.getDuration();

        tracks[1].regions.addRegion({
          start: duration * 0.3, // 30% into the track
          end: duration * 0.5, // 50% into the track
          color: "rgba(239, 68, 68, 0.3)", // red-500 with transparency
          drag: false,
          resize: false,
        });
      }
    }, 500);
  };

  // Simple AudioBuffer to WAV converter
  const audioBufferToWav = (buffer: AudioBuffer): ArrayBuffer => {
    const numberOfChannels = buffer.numberOfChannels;
    const sampleRate = buffer.sampleRate;
    const format = 1; // PCM
    const bitDepth = 16;

    const bytesPerSample = bitDepth / 8;
    const blockAlign = numberOfChannels * bytesPerSample;

    const data = buffer.getChannelData(0);
    const dataLength = data.length * bytesPerSample;
    const headerLength = 44;
    const totalLength = headerLength + dataLength;

    const arrayBuffer = new ArrayBuffer(totalLength);
    const view = new DataView(arrayBuffer);

    // Write WAV header
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
    offset += 4; // fmt chunk size
    view.setUint16(offset, format, true);
    offset += 2;
    view.setUint16(offset, numberOfChannels, true);
    offset += 2;
    view.setUint32(offset, sampleRate, true);
    offset += 4;
    view.setUint32(offset, sampleRate * blockAlign, true);
    offset += 4; // byte rate
    view.setUint16(offset, blockAlign, true);
    offset += 2;
    view.setUint16(offset, bitDepth, true);
    offset += 2;
    writeString("data");
    view.setUint32(offset, dataLength, true);
    offset += 4;

    // Write PCM samples
    for (let i = 0; i < data.length; i++) {
      const sample = Math.max(-1, Math.min(1, data[i]));
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
      offset += 2;
    }

    return arrayBuffer;
  };

  // Play/pause all tracks synchronously
  const togglePlayback = () => {
    if (!isSimulating) return;

    if (isPlaying) {
      tracks.forEach((track) => track.wavesurfer?.pause());
      setIsPlaying(false);
    } else {
      tracks.forEach((track) => track.wavesurfer?.play());
      setIsPlaying(true);
    }
  };

  // Stop simulation
  const stopSimulation = () => {
    tracks.forEach((track) => {
      track.wavesurfer?.stop();
      track.regions?.clearRegions();
    });
    setIsSimulating(false);
    setIsPlaying(false);
  };

  return (
    <div className="trisul-waveform bg-gray-950 border border-gray-800 rounded-lg p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <span className="text-2xl">🔱</span>
            Trisul Protocol — Live Audio Streams
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            Real-time waveform visualization of Provider, Interpreter, and Patient
          </p>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-3">
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
                Stop Simulation
              </button>
            </>
          )}
        </div>
      </div>

      {/* Tracks */}
      <div className="space-y-4">
        {tracks.map((track, index) => (
          <div
            key={track.role}
            className="track bg-gray-900 border border-gray-800 rounded-lg p-4"
          >
            {/* Track Header */}
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="text-2xl">{track.icon}</span>
                <div>
                  <h3 className="font-semibold text-sm text-white">
                    {track.label}
                  </h3>
                  <p className="text-xs text-gray-400">
                    {isSimulating ? (
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

              {/* Error indicator for interpreter track */}
              {track.role === "interpreter" && isSimulating && (
                <div className="flex items-center gap-2 px-3 py-1 bg-red-950 border border-red-800 rounded text-red-400 text-xs">
                  <AlertTriangle className="w-3 h-3" />
                  Error Region Detected
                </div>
              )}
            </div>

            {/* Waveform Container */}
            <div
              ref={
                index === 0
                  ? providerRef
                  : index === 1
                    ? interpreterRef
                    : patientRef
              }
              className="waveform-container rounded bg-gray-950"
              style={{
                borderLeft: `3px solid ${track.color}`,
                paddingLeft: "8px",
              }}
            />
          </div>
        ))}
      </div>

      {/* Legend */}
      {isSimulating && (
        <div className="mt-6 p-4 bg-gray-900 border border-gray-800 rounded-lg">
          <h4 className="text-sm font-semibold text-white mb-2">
            Simulation Legend
          </h4>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-blue-500" />
              <span className="text-gray-300">Provider waveform (200 Hz)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-purple-500" />
              <span className="text-gray-300">Interpreter waveform (300 Hz)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-green-500" />
              <span className="text-gray-300">Patient waveform (250 Hz)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 bg-red-500 opacity-30" />
              <span className="text-gray-300">
                Error region (simulated misinterpretation)
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
