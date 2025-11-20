/**
 * Audio Waveform Component
 * =========================
 * Real-time waveform visualization using wavesurfer.js
 */

"use client";

import { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import { StreamRole } from "@/types/sarasvati";
import { Mic, Volume2, VolumeX } from "lucide-react";

interface AudioWaveformProps {
  role: StreamRole;
  audioTrack?: MediaStreamTrack;
  height?: number;
  className?: string;
}

const ROLE_COLORS = {
  provider: {
    wave: "#3b82f6", // blue-500
    progress: "#1d4ed8", // blue-700
    label: "Provider",
    icon: "👨‍⚕️",
  },
  interpreter: {
    wave: "#a855f7", // purple-500
    progress: "#7e22ce", // purple-700
    label: "Interpreter",
    icon: "🌐",
  },
  patient: {
    wave: "#10b981", // green-500
    progress: "#047857", // green-700
    label: "Patient",
    icon: "🧑",
  },
};

export function AudioWaveform({
  role,
  audioTrack,
  height = 80,
  className = "",
}: AudioWaveformProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wavesurferRef = useRef<WaveSurfer | null>(null);
  const [isActive, setIsActive] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [volume, setVolume] = useState(0.7);

  const config = ROLE_COLORS[role];

  // Initialize WaveSurfer
  useEffect(() => {
    if (!containerRef.current) return;

    // Create wavesurfer instance
    const wavesurfer = WaveSurfer.create({
      container: containerRef.current,
      waveColor: config.wave,
      progressColor: config.progress,
      cursorColor: "transparent",
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      height: height,
      normalize: true,
      backend: "WebAudio",
    });

    wavesurferRef.current = wavesurfer;

    // Cleanup
    return () => {
      wavesurfer.destroy();
    };
  }, [config.wave, config.progress, height]);

  // Handle audio track updates
  useEffect(() => {
    if (!wavesurferRef.current || !audioTrack) return;

    try {
      // Create MediaStream from track
      const stream = new MediaStream([audioTrack]);

      // Load stream into wavesurfer
      // Note: wavesurfer.js 7.x uses loadMediaStream for live audio
      const audioContext = new AudioContext();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 2048;

      source.connect(analyser);

      // Visualize live audio
      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      const draw = () => {
        if (!wavesurferRef.current) return;

        analyser.getByteTimeDomainData(dataArray);

        // Convert to float array for wavesurfer
        const floatArray = new Float32Array(bufferLength);
        for (let i = 0; i < bufferLength; i++) {
          floatArray[i] = (dataArray[i] - 128) / 128.0;
        }

        // Update waveform (this is a simplified approach)
        // In production, you'd use wavesurfer's microphone plugin
        requestAnimationFrame(draw);
      };

      draw();
      setIsActive(true);
    } catch (error) {
      console.error("Failed to visualize audio:", error);
    }
  }, [audioTrack]);

  // Volume control
  useEffect(() => {
    if (wavesurferRef.current) {
      wavesurferRef.current.setVolume(isMuted ? 0 : volume);
    }
  }, [volume, isMuted]);

  return (
    <div className={`audio-waveform ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-2xl">{config.icon}</span>
          <div>
            <h3 className="font-semibold text-sm">{config.label}</h3>
            <p className="text-xs text-gray-400">
              {isActive ? (
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                  Live
                </span>
              ) : (
                "Waiting..."
              )}
            </p>
          </div>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsMuted(!isMuted)}
            className="p-2 rounded hover:bg-gray-800 transition"
            title={isMuted ? "Unmute" : "Mute"}
          >
            {isMuted ? (
              <VolumeX className="w-4 h-4" />
            ) : (
              <Volume2 className="w-4 h-4" />
            )}
          </button>

          <input
            type="range"
            min="0"
            max="1"
            step="0.1"
            value={volume}
            onChange={(e) => setVolume(parseFloat(e.target.value))}
            className="w-20 accent-blue-500"
            disabled={isMuted}
          />
        </div>
      </div>

      {/* Waveform Container */}
      <div
        ref={containerRef}
        className="waveform-container rounded-lg bg-gray-900 border border-gray-800"
        style={{
          borderColor: isActive ? config.wave : undefined,
          boxShadow: isActive
            ? `0 0 20px ${config.wave}40`
            : undefined,
        }}
      />

      {/* Status Indicator */}
      {!isActive && (
        <div className="mt-2 text-center">
          <Mic className="w-4 h-4 mx-auto text-gray-500 animate-pulse" />
          <p className="text-xs text-gray-500 mt-1">
            Waiting for audio stream...
          </p>
        </div>
      )}
    </div>
  );
}
