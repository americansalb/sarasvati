/**
 * SARASVATI Dashboard - Main Page
 * ================================
 * The "Drishya" (Vision) Interface for the Trisul Protocol
 */

"use client";

import { useState, useEffect } from "react";
import { useSarasvati } from "@/hooks/useSarasvati";
import { AudioWaveform } from "@/components/AudioWaveform";
import { TranscriptStream } from "@/components/TranscriptStream";
import { ArbiterLog } from "@/components/ArbiterLog";
import {
  Wifi,
  WifiOff,
  Play,
  Square,
  Settings,
  AlertCircle,
} from "lucide-react";
import { clsx } from "clsx";

const LIVEKIT_URL = process.env.NEXT_PUBLIC_LIVEKIT_URL || "ws://localhost:7880";
const BACKEND_WS_URL = process.env.NEXT_PUBLIC_BACKEND_WS_URL || "http://localhost:3001";
const ROOM_NAME = process.env.NEXT_PUBLIC_ROOM_NAME || "sarasvati-session";

export default function DashboardPage() {
  const [simulationMode, setSimulationMode] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const {
    connectionState,
    sessionState,
    connect,
    disconnect,
    startSimulation,
    clearErrors,
    room,
  } = useSarasvati({
    livekitUrl: LIVEKIT_URL,
    backendWsUrl: BACKEND_WS_URL,
    roomName: ROOM_NAME,
    autoConnect: false,
  });

  // Handle critical error flash
  useEffect(() => {
    const criticalErrors = sessionState.errors.filter(
      (e) => e.severity === "critical"
    );

    if (criticalErrors.length > 0) {
      // Trigger flash effect
      document.body.classList.add("critical-flash");
      setTimeout(() => {
        document.body.classList.remove("critical-flash");
      }, 1000);
    }
  }, [sessionState.errors]);

  const handleConnect = async () => {
    try {
      await connect();
    } catch (error) {
      console.error("Connection failed:", error);
    }
  };

  const handleDisconnect = async () => {
    try {
      await disconnect();
      setSimulationMode(false);
    } catch (error) {
      console.error("Disconnect failed:", error);
    }
  };

  const handleStartSimulation = async () => {
    try {
      await startSimulation({
        enabled: true,
        providerAudioUrl: "/audio/provider.mp3",
        interpreterAudioUrl: "/audio/interpreter.mp3",
        patientAudioUrl: "/audio/patient.mp3",
        autoPlay: true,
      });
      setSimulationMode(true);
    } catch (error) {
      console.error("Simulation failed:", error);
    }
  };

  const isConnected =
    connectionState.livekitConnected && connectionState.websocketConnected;

  return (
    <main className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 text-gray-100">
      {/* Header */}
      <header className="border-b border-gray-800 bg-gray-900/50 backdrop-blur">
        <div className="container mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            {/* Logo */}
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
                <span className="text-2xl font-bold">🔱</span>
              </div>
              <div>
                <h1 className="text-2xl font-bold bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent">
                  SARASVATI
                </h1>
                <p className="text-xs text-gray-400">
                  Trisul Protocol • Real-time Medical Monitoring
                </p>
              </div>
            </div>

            {/* Connection Status */}
            <div className="flex items-center gap-4">
              {/* Status Indicators */}
              <div className="flex items-center gap-3">
                <div
                  className={clsx(
                    "flex items-center gap-2 px-3 py-1.5 rounded-full text-sm",
                    connectionState.livekitConnected
                      ? "bg-green-500/20 text-green-400"
                      : "bg-gray-800 text-gray-500"
                  )}
                >
                  {connectionState.livekitConnected ? (
                    <Wifi className="w-4 h-4" />
                  ) : (
                    <WifiOff className="w-4 h-4" />
                  )}
                  LiveKit
                </div>

                <div
                  className={clsx(
                    "flex items-center gap-2 px-3 py-1.5 rounded-full text-sm",
                    connectionState.websocketConnected
                      ? "bg-green-500/20 text-green-400"
                      : "bg-gray-800 text-gray-500"
                  )}
                >
                  {connectionState.websocketConnected ? (
                    <Wifi className="w-4 h-4" />
                  ) : (
                    <WifiOff className="w-4 h-4" />
                  )}
                  Backend
                </div>
              </div>

              {/* Control Buttons */}
              <div className="flex items-center gap-2">
                {!isConnected ? (
                  <button
                    onClick={handleConnect}
                    className="px-4 py-2 rounded-lg bg-blue-500 hover:bg-blue-600 text-white font-medium flex items-center gap-2 transition"
                  >
                    <Play className="w-4 h-4" />
                    Connect
                  </button>
                ) : (
                  <>
                    {!simulationMode && (
                      <button
                        onClick={handleStartSimulation}
                        className="px-4 py-2 rounded-lg bg-purple-500 hover:bg-purple-600 text-white font-medium flex items-center gap-2 transition"
                      >
                        <Play className="w-4 h-4" />
                        Start Simulation
                      </button>
                    )}

                    <button
                      onClick={handleDisconnect}
                      className="px-4 py-2 rounded-lg bg-red-500 hover:bg-red-600 text-white font-medium flex items-center gap-2 transition"
                    >
                      <Square className="w-4 h-4" />
                      Disconnect
                    </button>
                  </>
                )}

                <button
                  onClick={() => setShowSettings(!showSettings)}
                  className="p-2 rounded-lg bg-gray-800 hover:bg-gray-700 transition"
                >
                  <Settings className="w-5 h-5" />
                </button>
              </div>
            </div>
          </div>

          {/* Session Info */}
          {sessionState.isActive && (
            <div className="mt-4 flex items-center gap-4 text-sm text-gray-400">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                Session Active
              </div>
              {sessionState.sessionId && (
                <div>ID: {sessionState.sessionId}</div>
              )}
              {sessionState.startTime && (
                <div>
                  Started{" "}
                  {new Date(sessionState.startTime).toLocaleTimeString()}
                </div>
              )}
              <div>Errors: {sessionState.errors.length}</div>
              <div>Transcripts: {sessionState.transcripts.length}</div>
            </div>
          )}

          {/* Error Banner */}
          {connectionState.error && (
            <div className="mt-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 flex items-center gap-2">
              <AlertCircle className="w-5 h-5 text-red-400" />
              <p className="text-sm text-red-400">{connectionState.error}</p>
            </div>
          )}
        </div>
      </header>

      {/* Main Content */}
      <div className="container mx-auto px-6 py-6 space-y-6">
        {/* Top Row: 3 Waveforms */}
        <section className="grid grid-cols-3 gap-6">
          <AudioWaveform role="provider" />
          <AudioWaveform role="interpreter" />
          <AudioWaveform role="patient" />
        </section>

        {/* Middle Row: Live Transcript */}
        <section className="bg-gray-900/50 rounded-xl p-6 border border-gray-800">
          <TranscriptStream
            transcripts={sessionState.transcripts}
            maxHeight={400}
          />
        </section>

        {/* Bottom Row: Arbiter's Log */}
        <section className="bg-gray-900/50 rounded-xl p-6 border border-gray-800">
          <ArbiterLog
            errors={sessionState.errors}
            onClearErrors={clearErrors}
          />
        </section>

        {/* Debug Panel (optional) */}
        {process.env.NODE_ENV === "development" && sessionState.debugInfo && (
          <section className="bg-gray-900/50 rounded-xl p-6 border border-gray-800">
            <h3 className="text-lg font-bold mb-3">🔧 Debug Info</h3>
            <pre className="text-xs bg-gray-950 p-4 rounded overflow-x-auto">
              {JSON.stringify(sessionState.debugInfo, null, 2)}
            </pre>
          </section>
        )}
      </div>

      {/* Settings Modal */}
      {showSettings && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
          onClick={() => setShowSettings(false)}
        >
          <div
            className="bg-gray-900 rounded-xl p-6 max-w-md w-full border border-gray-800"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-xl font-bold mb-4">⚙️ Settings</h3>

            <div className="space-y-4">
              <div>
                <label className="text-sm text-gray-400 mb-1 block">
                  LiveKit URL
                </label>
                <input
                  type="text"
                  value={LIVEKIT_URL}
                  readOnly
                  className="w-full px-3 py-2 bg-gray-800 rounded border border-gray-700 text-sm"
                />
              </div>

              <div>
                <label className="text-sm text-gray-400 mb-1 block">
                  Backend WebSocket URL
                </label>
                <input
                  type="text"
                  value={BACKEND_WS_URL}
                  readOnly
                  className="w-full px-3 py-2 bg-gray-800 rounded border border-gray-700 text-sm"
                />
              </div>

              <div>
                <label className="text-sm text-gray-400 mb-1 block">
                  Room Name
                </label>
                <input
                  type="text"
                  value={ROOM_NAME}
                  readOnly
                  className="w-full px-3 py-2 bg-gray-800 rounded border border-gray-700 text-sm"
                />
              </div>
            </div>

            <button
              onClick={() => setShowSettings(false)}
              className="mt-6 w-full px-4 py-2 rounded-lg bg-blue-500 hover:bg-blue-600 transition"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
