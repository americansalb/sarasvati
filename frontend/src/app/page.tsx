/**
 * SARASVATI Dashboard - Doctor-Friendly Interface
 * ================================================
 * Two-tab design:
 * - MONITOR: Glanceable status for busy doctors
 * - DETAILS: Audit trail and debate logs for review
 */

"use client";

import { useState, useEffect, useRef } from "react";
import { useSarasvatiSimple } from "@/hooks/useSarasvatiSimple";
import {
  Wifi,
  WifiOff,
  Mic,
  MicOff,
  CheckCircle,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  X,
  Settings,
} from "lucide-react";
import { StreamRole, TranscriptSegment, ClinicalError } from "@/types/sarasvati";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

// ===========================================================================
// STATUS INDICATOR - Big glanceable status for doctors
// ===========================================================================
function StatusIndicator({ errorCount }: { errorCount: number }) {
  if (errorCount === 0) {
    return (
      <div className="flex items-center gap-3 px-6 py-4 bg-green-900/50 border-2 border-green-500 rounded-xl">
        <CheckCircle size={32} className="text-green-400" />
        <div>
          <div className="text-2xl font-bold text-green-300">ALL CLEAR</div>
          <div className="text-sm text-green-400/70">No interpretation errors detected</div>
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-3 px-6 py-4 bg-red-900/50 border-2 border-red-500 rounded-xl animate-pulse">
      <XCircle size={32} className="text-red-400" />
      <div>
        <div className="text-2xl font-bold text-red-300">{errorCount} ERROR{errorCount > 1 ? 'S' : ''} DETECTED</div>
        <div className="text-sm text-red-400/70">Review required - see below</div>
      </div>
    </div>
  );
}

// ===========================================================================
// ERROR ALERT - Prominent dismissible error card
// ===========================================================================
function ErrorAlert({
  error,
  onDismiss,
}: {
  error: ClinicalError;
  onDismiss: () => void;
}) {
  const severityColors: Record<string, string> = {
    critical: "border-red-500 bg-red-950",
    high: "border-orange-500 bg-orange-950",
    medium: "border-yellow-500 bg-yellow-950",
    low: "border-blue-500 bg-blue-950",
  };

  const severity = (error.severity || "medium").toLowerCase();
  const colors = severityColors[severity] || severityColors.medium;

  return (
    <div className={`border-2 ${colors} rounded-xl p-4 mb-3`}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <AlertTriangle className="text-red-400" size={20} />
          <span className="font-bold text-lg text-white">
            {(error.error_type || "issue").toUpperCase()}
          </span>
          <span className="text-xs px-2 py-1 rounded bg-gray-700 text-gray-300">
            {severity}
          </span>
        </div>
        <button
          onClick={onDismiss}
          className="text-gray-400 hover:text-white transition-colors"
          title="Dismiss"
        >
          <X size={20} />
        </button>
      </div>

      <div className="space-y-2 text-sm">
        {error.source_quote && (
          <div className="p-2 bg-gray-800/50 rounded">
            <span className="text-gray-400">Source said: </span>
            <span className="text-green-300">"{error.source_quote}"</span>
          </div>
        )}
        {error.interpreter_quote && (
          <div className="p-2 bg-gray-800/50 rounded">
            <span className="text-gray-400">Interpreter said: </span>
            <span className="text-purple-300">"{error.interpreter_quote}"</span>
          </div>
        )}
        {error.description && (
          <div className="p-2 bg-gray-800/50 rounded">
            <span className="text-gray-400">Issue: </span>
            <span className="text-white">{error.description}</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ===========================================================================
// COMPACT TRANSCRIPT - Shows English translations prominently
// ===========================================================================
function CompactTranscript({ transcripts }: { transcripts: TranscriptSegment[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [transcripts]);

  const roleColors: Record<string, string> = {
    provider: "text-blue-400",
    interpreter: "text-purple-400",
    patient: "text-green-400",
  };

  const roleLabels: Record<string, string> = {
    provider: "P",
    interpreter: "I",
    patient: "Pt",
  };

  return (
    <div
      ref={scrollRef}
      className="h-64 overflow-y-auto space-y-1 bg-gray-900/50 rounded-lg p-3"
    >
      {transcripts.length === 0 ? (
        <p className="text-gray-500 italic text-center py-8">
          Waiting for speech...
        </p>
      ) : (
        transcripts.map((t, idx) => (
          <div key={idx} className="flex gap-2 text-sm">
            <span className={`font-bold ${roleColors[t.role] || "text-gray-400"}`}>
              {roleLabels[t.role] || t.role}:
            </span>
            <span className="text-gray-200">
              {/* Show English translation if available, otherwise show raw text */}
              {t.english_translation || t.text}
            </span>
            {t.english_translation && t.english_translation !== t.text && (
              <span className="text-gray-500 text-xs">
                ({t.detected_language || "auto"})
              </span>
            )}
          </div>
        ))
      )}
    </div>
  );
}

// ===========================================================================
// DEBATE PANEL - Collapsible tribunal debate
// ===========================================================================
function DebatePanel({ debateLogs }: { debateLogs: any }) {
  const [expanded, setExpanded] = useState(false);

  if (!debateLogs?.error_evaluation) {
    return (
      <div className="text-gray-500 italic text-center py-4">
        No tribunal debates yet
      </div>
    );
  }

  const debate = debateLogs.error_evaluation;

  return (
    <div className="bg-gray-900/50 rounded-lg border border-gray-700">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-gray-800/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          {expanded ? <ChevronDown size={20} /> : <ChevronRight size={20} />}
          <span className="font-semibold">🏛️ Tribunal Debate</span>
          <span className="text-xs text-gray-400">
            {debate.rounds_taken} round{debate.rounds_taken > 1 ? 's' : ''}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2 py-1 rounded ${
            debate.consensus_reached ? "bg-green-800" : "bg-yellow-800"
          }`}>
            {debate.consensus_reached ? "CONSENSUS" : "NO CONSENSUS"}
          </span>
          <span className={`text-sm font-bold px-3 py-1 rounded ${
            debate.final_consensus === "accurate" ? "bg-green-700" :
            debate.final_consensus === "critical_errors" ? "bg-red-700" :
            "bg-yellow-700"
          }`}>
            {(debate.final_consensus || "").toUpperCase()}
          </span>
        </div>
      </button>

      {expanded && debate.turns && (
        <div className="p-4 border-t border-gray-700 max-h-96 overflow-y-auto">
          {debate.turns.map((turn: any, idx: number) => {
            const isNewRound = idx === 0 || turn.round !== debate.turns[idx - 1]?.round;
            return (
              <div key={idx}>
                {isNewRound && (
                  <div className="flex items-center gap-2 my-3">
                    <div className="flex-1 h-px bg-gray-600" />
                    <span className="text-xs text-gray-400 px-2">Round {turn.round}</span>
                    <div className="flex-1 h-px bg-gray-600" />
                  </div>
                )}
                <div className={`mb-3 p-3 rounded-lg ${turn.changed_mind ? "bg-yellow-900/30 border border-yellow-700" : "bg-gray-800/50"}`}>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="font-medium text-purple-300">{turn.agent}</span>
                    <span className="text-xs text-gray-500">({turn.model})</span>
                    {turn.changed_mind && (
                      <span className="text-xs text-yellow-400">🔄 Changed</span>
                    )}
                    <span className={`ml-auto text-xs px-2 py-0.5 rounded ${
                      turn.position === "accurate" ? "bg-green-800" :
                      turn.position === "critical_errors" ? "bg-red-800" :
                      "bg-yellow-800"
                    }`}>
                      {turn.position}
                    </span>
                  </div>
                  <p className="text-sm text-gray-300">
                    {turn.statement || turn.reasoning || "No statement"}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ===========================================================================
// MAIN DASHBOARD
// ===========================================================================
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

  const [activeTab, setActiveTab] = useState<"monitor" | "details">("monitor");
  const [selectedRole, setSelectedRole] = useState<StreamRole>("provider");
  const [dismissedErrors, setDismissedErrors] = useState<Set<string>>(new Set());
  const [showSettings, setShowSettings] = useState(false);
  const [providerLang, setProviderLang] = useState("en");
  const [patientLang, setPatientLang] = useState("es");

  // Get unique clinical errors
  const clinicalErrors = sessionState.errors.filter((e) => !e.is_system_error);
  const uniqueErrors = Array.from(
    new Map(clinicalErrors.map((e) => [e.error_id, e])).values()
  );
  const activeErrors = uniqueErrors.filter((e) => !dismissedErrors.has(e.error_id));

  const handleDismissError = (errorId: string) => {
    setDismissedErrors((prev) => new Set([...prev, errorId]));
  };

  const handleToggleRecording = () => {
    if (connectionState.isRecording) {
      stopRecording();
    } else {
      const lang = selectedRole === "provider" ? providerLang :
                   selectedRole === "patient" ? patientLang : "auto";
      startRecording(selectedRole, lang, providerLang, patientLang);
    }
  };

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

  return (
    <main className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 text-gray-100">
      {/* Header */}
      <header className="sticky top-0 z-50 bg-gray-900/95 backdrop-blur border-b border-gray-700 px-6 py-4">
        <div className="flex items-center justify-between max-w-7xl mx-auto">
          <div className="flex items-center gap-4">
            <h1 className="text-2xl font-bold text-white">SARASVATI</h1>
            <div className="flex items-center gap-2">
              {connectionState.websocketConnected ? (
                <Wifi className="text-green-500" size={18} />
              ) : (
                <WifiOff className="text-red-500" size={18} />
              )}
              <span className={`text-sm ${connectionState.websocketConnected ? "text-green-400" : "text-red-400"}`}>
                {connectionState.websocketConnected ? "Connected" : "Disconnected"}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Tab Switcher */}
            <div className="flex bg-gray-800 rounded-lg p-1">
              <button
                onClick={() => setActiveTab("monitor")}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                  activeTab === "monitor"
                    ? "bg-blue-600 text-white"
                    : "text-gray-400 hover:text-white"
                }`}
              >
                Monitor
              </button>
              <button
                onClick={() => setActiveTab("details")}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                  activeTab === "details"
                    ? "bg-blue-600 text-white"
                    : "text-gray-400 hover:text-white"
                }`}
              >
                Details
              </button>
            </div>

            <button
              onClick={() => setShowSettings(!showSettings)}
              className="p-2 rounded-lg hover:bg-gray-700 transition-colors"
            >
              <Settings size={20} className="text-gray-400" />
            </button>

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
          </div>
        </div>
      </header>

      {/* Settings Panel */}
      {showSettings && (
        <div className="bg-gray-800 border-b border-gray-700 px-6 py-4">
          <div className="max-w-7xl mx-auto grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Provider Language</label>
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
              <label className="block text-sm text-gray-400 mb-1">Patient Language</label>
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
        </div>
      )}

      {/* Main Content */}
      <div className="max-w-7xl mx-auto p-6">
        {activeTab === "monitor" ? (
          /* ================ MONITOR TAB ================ */
          <div className="space-y-6">
            {/* Status Indicator */}
            <StatusIndicator errorCount={activeErrors.length} />

            {/* Error Alerts */}
            {activeErrors.length > 0 && (
              <div>
                <h3 className="text-lg font-semibold mb-3 text-red-400">Errors Requiring Attention</h3>
                {activeErrors.map((error) => (
                  <ErrorAlert
                    key={error.error_id}
                    error={error}
                    onDismiss={() => handleDismissError(error.error_id)}
                  />
                ))}
              </div>
            )}

            {/* Compact Transcript */}
            <div>
              <h3 className="text-lg font-semibold mb-3">Live Transcript</h3>
              <CompactTranscript transcripts={sessionState.transcripts} />
            </div>
          </div>
        ) : (
          /* ================ DETAILS TAB ================ */
          <div className="space-y-6">
            {/* Full Transcript with translations */}
            <div>
              <h3 className="text-lg font-semibold mb-3">Full Transcript</h3>
              <div className="bg-gray-900/50 rounded-lg p-4 max-h-80 overflow-y-auto space-y-3">
                {sessionState.transcripts.length === 0 ? (
                  <p className="text-gray-500 italic">No transcripts yet</p>
                ) : (
                  sessionState.transcripts.map((t, idx) => (
                    <div key={idx} className="p-3 bg-gray-800/50 rounded-lg">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-xs px-2 py-0.5 rounded capitalize ${
                          t.role === "provider" ? "bg-blue-700" :
                          t.role === "interpreter" ? "bg-purple-700" : "bg-green-700"
                        }`}>
                          {t.role}
                        </span>
                        {t.detected_language && (
                          <span className="text-xs text-gray-500">[{t.detected_language}]</span>
                        )}
                      </div>
                      <p className="text-gray-200">{t.english_translation || t.text}</p>
                      {t.english_translation && t.english_translation !== t.text && (
                        <p className="text-gray-500 text-sm mt-1">
                          Original: {t.text}
                        </p>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Tribunal Debate */}
            <div>
              <h3 className="text-lg font-semibold mb-3">Tribunal Debate</h3>
              <DebatePanel debateLogs={sessionState.debateLogs} />
            </div>

            {/* All Errors */}
            <div>
              <h3 className="text-lg font-semibold mb-3">All Detected Errors ({uniqueErrors.length})</h3>
              <div className="bg-gray-900/50 rounded-lg p-4 max-h-80 overflow-y-auto space-y-3">
                {uniqueErrors.length === 0 ? (
                  <p className="text-gray-500 italic">No errors detected</p>
                ) : (
                  uniqueErrors.map((error) => (
                    <div key={error.error_id} className="p-3 bg-gray-800/50 rounded-lg border-l-4 border-red-600">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium text-red-400">{error.error_type}</span>
                        <span className="text-xs px-2 py-0.5 rounded bg-gray-700">{error.severity}</span>
                      </div>
                      <p className="text-sm text-gray-300">{error.description || "No description"}</p>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Fixed Bottom Input Bar */}
      <div className="fixed bottom-0 left-0 right-0 bg-gray-900/95 backdrop-blur border-t border-gray-700 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center gap-4">
          {/* Role Selector */}
          <div className="flex gap-1 bg-gray-800 rounded-lg p-1">
            {(["provider", "interpreter", "patient"] as StreamRole[]).map((role) => (
              <button
                key={role}
                onClick={() => setSelectedRole(role)}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  selectedRole === role
                    ? role === "provider" ? "bg-blue-600 text-white" :
                      role === "interpreter" ? "bg-purple-600 text-white" :
                      "bg-green-600 text-white"
                    : "text-gray-400 hover:text-white"
                }`}
              >
                {role === "provider" ? "🩺 Provider" :
                 role === "interpreter" ? "🗣️ Interpreter" :
                 "👤 Patient"}
              </button>
            ))}
          </div>

          {/* Record Button */}
          <button
            onClick={handleToggleRecording}
            disabled={!connectionState.websocketConnected}
            className={`flex items-center gap-2 px-6 py-3 rounded-xl font-medium transition-all ${
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
                Record {selectedRole}
              </>
            )}
          </button>

          {/* Recording indicator */}
          {connectionState.isRecording && (
            <span className="text-red-400 text-sm animate-pulse">● Recording...</span>
          )}
        </div>
      </div>

      {/* Spacer for fixed bottom bar */}
      <div className="h-24" />
    </main>
  );
}
