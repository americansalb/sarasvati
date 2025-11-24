/**
 * SARASVATI Dashboard - Main Page
 * ================================
 * Simple interface: Browser audio + Groq Whisper + Backend tribunal
 * No LiveKit dependency.
 */

"use client";

import { useState, useEffect } from "react";
import { useSarasvatiSimple } from "@/hooks/useSarasvatiSimple";
import { Wifi, WifiOff, Mic, MicOff, Send, AlertTriangle, Settings } from "lucide-react";
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
  const [providerLang, setProviderLang] = useState("en");
  const [patientLang, setPatientLang] = useState("es"); // Default Spanish for testing (change to "gu" for Gujarati, etc.)
  const [asrBackend, setAsrBackend] = useState<"groq" | "openai">("openai");
  const [asrBackendLoading, setAsrBackendLoading] = useState(false);

  const LANGUAGES = [
    { code: "en", name: "English" },
    { code: "es", name: "Spanish" },
    { code: "gu", name: "Gujarati" },
    { code: "hi", name: "Hindi" },
    { code: "pt", name: "Portuguese" },
    { code: "zh", name: "Chinese" },
    { code: "ar", name: "Arabic" },
    { code: "fr", name: "French" },
    { code: "de", name: "German" },
    { code: "auto", name: "Auto-detect" },
  ];

  // Fetch current ASR backend configuration
  useEffect(() => {
    const fetchAsrConfig = async () => {
      try {
        const httpUrl = BACKEND_URL.replace("ws://", "http://").replace("wss://", "https://");
        const response = await fetch(`${httpUrl}/admin/asr-config`);
        if (response.ok) {
          const data = await response.json();
          const defaultBackend = data.current_config?.default || "openai-gpt4o-transcribe";
          setAsrBackend(defaultBackend.startsWith("openai") ? "openai" : "groq");
        }
      } catch (error) {
        console.error("Failed to fetch ASR config:", error);
      }
    };
    fetchAsrConfig();
  }, []);

  // Switch ASR backend
  const handleSwitchAsrBackend = async (backend: "groq" | "openai") => {
    setAsrBackendLoading(true);
    try {
      const httpUrl = BACKEND_URL.replace("ws://", "http://").replace("wss://", "https://");
      const response = await fetch(`${httpUrl}/admin/asr-config/switch-default`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ backend }),
      });
      if (response.ok) {
        setAsrBackend(backend);
        console.log(`Switched ASR backend to ${backend}`);
      } else {
        console.error("Failed to switch ASR backend:", await response.text());
      }
    } catch (error) {
      console.error("Error switching ASR backend:", error);
    } finally {
      setAsrBackendLoading(false);
    }
  };

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
      // Use appropriate language based on role
      // For interpreter: pass both languages so backend can try both
      const lang = selectedRole === "provider" ? providerLang :
                   selectedRole === "patient" ? patientLang : "auto";
      startRecording(selectedRole, lang, providerLang, patientLang);
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

      {(connectionState.lastInterpreterLanguage || connectionState.interpreterDetectionWarning) && (
        <div className="mb-6 p-4 bg-purple-900/30 border border-purple-700 rounded-lg text-sm text-purple-100">
          <div className="font-semibold text-purple-200 mb-1">Interpreter language detection</div>
          {connectionState.lastInterpreterLanguage && (
            <p className="text-purple-100">
              Last detected language: <span className="font-mono">{connectionState.lastInterpreterLanguage}</span>
            </p>
          )}
          {connectionState.interpreterDetectionWarning && (
            <p className="text-yellow-200 mt-1">⚠️ {connectionState.interpreterDetectionWarning}</p>
          )}
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

          {/* Language Settings */}
          <div className="mb-4 grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-2">Provider Language</label>
              <select
                value={providerLang}
                onChange={(e) => setProviderLang(e.target.value)}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg"
              >
                {LANGUAGES.map((lang) => (
                  <option key={lang.code} value={lang.code}>{lang.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-2">Patient Language</label>
              <select
                value={patientLang}
                onChange={(e) => setPatientLang(e.target.value)}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg"
              >
                {LANGUAGES.map((lang) => (
                  <option key={lang.code} value={lang.code}>{lang.name}</option>
                ))}
              </select>
            </div>
          </div>
          <p className="text-xs text-yellow-500 mb-4">
            ⚠️ Keep language settings consistent during a session. Changing mid-session may cause incorrect transcriptions.
          </p>

          {/* ASR Backend Selector */}
          <div className="mb-4">
            <label className="block text-sm text-gray-400 mb-2 flex items-center gap-2">
              <Settings size={16} />
              ASR Backend (Speech Recognition Engine)
            </label>
            <div className="flex gap-2">
              <button
                onClick={() => handleSwitchAsrBackend("groq")}
                disabled={asrBackendLoading || asrBackend === "groq"}
                className={`flex-1 px-4 py-2 rounded-lg font-medium transition-colors ${
                  asrBackend === "groq"
                    ? "bg-emerald-600 text-white ring-2 ring-emerald-400"
                    : "bg-gray-700 text-gray-300 hover:bg-gray-600"
                } disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                {asrBackend === "groq" && "✓ "}Groq Whisper Large V3
              </button>
              <button
                onClick={() => handleSwitchAsrBackend("openai")}
                disabled={asrBackendLoading || asrBackend === "openai"}
                className={`flex-1 px-4 py-2 rounded-lg font-medium transition-colors ${
                  asrBackend === "openai"
                    ? "bg-blue-600 text-white ring-2 ring-blue-400"
                    : "bg-gray-700 text-gray-300 hover:bg-gray-600"
                } disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                {asrBackend === "openai" && "✓ "}OpenAI Whisper-1
              </button>
            </div>
            {asrBackendLoading && (
              <p className="text-xs text-gray-500 mt-1 animate-pulse">Switching backend...</p>
            )}
            <p className="text-xs text-gray-500 mt-2">
              Current: <span className="font-semibold text-gray-300">
                {asrBackend === "groq" ? "Groq Whisper Large V3" : "OpenAI Whisper-1 (with medical context)"}
              </span>
            </p>
          </div>

          {/* Microphone Recording */}
          <div className="mb-6">
            <label className="block text-sm text-gray-400 mb-2">
              Voice Input ({asrBackend === "groq" ? "Groq Whisper" : "OpenAI Whisper"})
            </label>
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
            Clinical Errors ({
              // Count unique clinical errors only (de-duplicated by error_id)
              new Set(
                sessionState.errors
                  .filter(e => !e.is_system_error)
                  .map(e => e.error_id)
              ).size
            })
          </h2>

          <div className="space-y-3 max-h-96 overflow-y-auto">
            {sessionState.errors.filter(e => !e.is_system_error).length === 0 ? (
              <p className="text-gray-500 italic">No clinical errors detected yet</p>
            ) : (
              // De-duplicate errors by error_id (some errors are broadcast multiple times during processing)
              Array.from(
                new Map(
                  sessionState.errors
                    .filter(e => !e.is_system_error)
                    .map(error => [error.error_id, error])
                ).values()
              ).map((error) => (
                <div
                  key={error.error_id}
                  className={`p-4 rounded-lg border ${
                    error.severity === "critical"
                      ? "bg-red-900/50 border-red-700"
                      : error.severity === "high"
                      ? "bg-orange-900/50 border-orange-700"
                      : "bg-yellow-900/50 border-yellow-700"
                  }`}
                >
                  <div className="flex justify-between items-start mb-2">
                    <div className="flex flex-col gap-1">
                      <span className="font-semibold text-white">
                        {error.error_type}
                        {error.case_type && (
                          <span className="text-xs text-gray-400 ml-2">({error.case_type})</span>
                        )}
                      </span>
                      {typeof error.confidence === "number" && !Number.isNaN(error.confidence) && (
                        <span className="text-xs text-gray-400">
                          Confidence: {(error.confidence * 100).toFixed(0)}%
                        </span>
                      )}
                    </div>
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
                  <p className="text-sm text-gray-300 mb-2">{error.description}</p>
                  {error.arbiter_reasoning && (
                    <p className="text-xs text-blue-300 mb-2 italic">
                      Arbiter: {error.arbiter_reasoning}
                    </p>
                  )}
                  {error.source_quote && (
                    <p className="text-xs text-green-400 mb-1">
                      {error.source_role === "provider" ? "Provider" : "Patient"}: "{error.source_quote}"
                    </p>
                  )}
                  {error.interpreter_quote && (
                    <p className="text-xs text-purple-400 mb-1">
                      Interpreter said: "{error.interpreter_quote}"
                    </p>
                  )}
                  {error.ideal_interpretation && (
                    <p className="text-xs text-cyan-400 mb-1">
                      Should have said: "{error.ideal_interpretation}"
                    </p>
                  )}
                  {error.provider_entity && (
                    <p className="text-xs text-gray-500">Provider entity: "{error.provider_entity.text}"</p>
                  )}
                  {error.interpreter_entity && (
                    <p className="text-xs text-gray-500">Interpreter entity: "{error.interpreter_entity.text}"</p>
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
              <div key={idx} className="flex gap-3 py-2">
                <span
                  className={`text-xs px-2 py-1 rounded capitalize self-start ${
                    t.role === "provider"
                      ? "bg-blue-700"
                      : t.role === "interpreter"
                      ? "bg-purple-700"
                      : "bg-green-700"
                  }`}
                >
                  {t.role}
                </span>
                <div className="flex flex-col gap-1">
                  <span className="text-gray-300">{t.text}</span>
                  {t.transliteration && t.transliteration !== t.text && (
                    <span className="text-gray-500 text-sm italic">
                      Transliteration: {t.transliteration}
                    </span>
                  )}
                  {t.english_translation && (
                    <span className="text-cyan-400 text-sm">
                      🌐 English: {t.english_translation}
                    </span>
                  )}
                  {t.detected_language && t.detected_language !== "en" && t.detected_language !== "unknown" && (
                    <span className="text-gray-600 text-xs">
                      [{t.detected_language}]
                    </span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </main>
  );
}
