/**
 * SARASVATI Dashboard - Main Page
 * ================================
 * Simple interface: Browser audio + Groq Whisper + Backend tribunal
 * No LiveKit dependency.
 */

"use client";

import { useState } from "react";
import { useSarasvatiSimple } from "@/hooks/useSarasvatiSimple";
import { Wifi, WifiOff, Mic, MicOff, Send, AlertTriangle } from "lucide-react";
import { StreamRole } from "@/types/sarasvati";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export default function DashboardPage() {
  const {
    connectionState,
    sessionState,
    connect,
    disconnect,
    startRecording,
    stopRecording,
    sendTranscript,
  } = useSarasvatiSimple({ backendUrl: BACKEND_URL });

  const [selectedRole, setSelectedRole] = useState<StreamRole>("provider");
  const [manualText, setManualText] = useState("");

  const handleSendManual = () => {
    if (manualText.trim()) {
      sendTranscript(selectedRole, manualText.trim());
      setManualText("");
    }
  };

  const handleToggleRecording = () => {
    if (connectionState.isRecording) {
      stopRecording();
    } else {
      startRecording(selectedRole);
    }
  };

  return (
    <main className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 text-gray-100 p-6">
      {/* Header */}
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">SARASVATI</h1>
        <p className="text-gray-400">Medical Interpreter Monitoring System</p>
      </header>

      {/* Connection Status */}
      <div className="mb-6 flex items-center gap-4">
        <div className="flex items-center gap-2">
          {connectionState.websocketConnected ? (
            <Wifi className="text-green-500" size={20} />
          ) : (
            <WifiOff className="text-red-500" size={20} />
          )}
          <span className={connectionState.websocketConnected ? "text-green-400" : "text-red-400"}>
            {connectionState.websocketConnected ? "Connected" : "Disconnected"}
          </span>
        </div>

        {!connectionState.websocketConnected ? (
          <button
            onClick={connect}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium"
          >
            Connect
          </button>
        ) : (
          <button
            onClick={disconnect}
            className="px-4 py-2 bg-gray-600 hover:bg-gray-700 rounded-lg font-medium"
          >
            Disconnect
          </button>
        )}

        {sessionState.sessionId && (
          <span className="text-gray-500 text-sm">Session: {sessionState.sessionId}</span>
        )}
      </div>

      {connectionState.error && (
        <div className="mb-6 p-4 bg-red-900/50 border border-red-700 rounded-lg">
          <p className="text-red-300">{connectionState.error}</p>
        </div>
      )}

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Input Panel */}
        <div className="bg-gray-800/50 rounded-xl p-6 border border-gray-700">
          <h2 className="text-xl font-semibold mb-4">Input</h2>

          {/* Role Selector */}
          <div className="mb-4">
            <label className="block text-sm text-gray-400 mb-2">Speaker Role</label>
            <div className="flex gap-2">
              {(["provider", "interpreter", "patient"] as StreamRole[]).map((role) => (
                <button
                  key={role}
                  onClick={() => setSelectedRole(role)}
                  className={`px-4 py-2 rounded-lg capitalize ${
                    selectedRole === role
                      ? "bg-blue-600 text-white"
                      : "bg-gray-700 text-gray-300 hover:bg-gray-600"
                  }`}
                >
                  {role}
                </button>
              ))}
            </div>
          </div>

          {/* Microphone Recording */}
          <div className="mb-6">
            <label className="block text-sm text-gray-400 mb-2">Voice Input (Groq Whisper)</label>
            <button
              onClick={handleToggleRecording}
              disabled={!connectionState.websocketConnected}
              className={`flex items-center gap-2 px-6 py-3 rounded-lg font-medium ${
                connectionState.isRecording
                  ? "bg-red-600 hover:bg-red-700 animate-pulse"
                  : "bg-green-600 hover:bg-green-700"
              } disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {connectionState.isRecording ? (
                <>
                  <MicOff size={20} />
                  Stop Recording
                </>
              ) : (
                <>
                  <Mic size={20} />
                  Start Recording ({selectedRole})
                </>
              )}
            </button>
          </div>

          {/* Manual Text Input */}
          <div>
            <label className="block text-sm text-gray-400 mb-2">Manual Text Input (for testing)</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={manualText}
                onChange={(e) => setManualText(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSendManual()}
                placeholder={`Type what the ${selectedRole} says...`}
                className="flex-1 px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                disabled={!connectionState.websocketConnected}
              />
              <button
                onClick={handleSendManual}
                disabled={!connectionState.websocketConnected || !manualText.trim()}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg disabled:opacity-50"
              >
                <Send size={20} />
              </button>
            </div>
          </div>
        </div>

        {/* Errors Panel */}
        <div className="bg-gray-800/50 rounded-xl p-6 border border-gray-700">
          <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <AlertTriangle className="text-yellow-500" size={20} />
            Detected Errors ({sessionState.errors.length})
          </h2>

          <div className="space-y-3 max-h-96 overflow-y-auto">
            {sessionState.errors.length === 0 ? (
              <p className="text-gray-500 italic">No errors detected yet</p>
            ) : (
              sessionState.errors.map((error, idx) => (
                <div
                  key={idx}
                  className={`p-4 rounded-lg border ${
                    error.severity === "critical"
                      ? "bg-red-900/50 border-red-700"
                      : error.severity === "high"
                      ? "bg-orange-900/50 border-orange-700"
                      : "bg-yellow-900/50 border-yellow-700"
                  }`}
                >
                  <div className="flex justify-between items-start mb-2">
                    <span className="font-semibold text-white">{error.error_type}</span>
                    <span
                      className={`text-xs px-2 py-1 rounded ${
                        error.severity === "critical"
                          ? "bg-red-700"
                          : error.severity === "high"
                          ? "bg-orange-700"
                          : "bg-yellow-700"
                      }`}
                    >
                      {error.severity}
                    </span>
                  </div>
                  <p className="text-sm text-gray-300">{error.description}</p>
                  {error.original_text && (
                    <p className="text-xs text-gray-500 mt-2">Original: "{error.original_text}"</p>
                  )}
                  {error.translated_text && (
                    <p className="text-xs text-gray-500">Translated: "{error.translated_text}"</p>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Transcripts */}
      <div className="mt-6 bg-gray-800/50 rounded-xl p-6 border border-gray-700">
        <h2 className="text-xl font-semibold mb-4">Transcripts</h2>
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {sessionState.transcripts.length === 0 ? (
            <p className="text-gray-500 italic">No transcripts yet. Connect and start speaking or typing.</p>
          ) : (
            sessionState.transcripts.map((t, idx) => (
              <div key={idx} className="flex gap-3">
                <span
                  className={`text-xs px-2 py-1 rounded capitalize ${
                    t.role === "provider"
                      ? "bg-blue-700"
                      : t.role === "interpreter"
                      ? "bg-purple-700"
                      : "bg-green-700"
                  }`}
                >
                  {t.role}
                </span>
                <span className="text-gray-300">{t.text}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </main>
  );
}
