/**
 * SARASVATI Dashboard - Doctor-Friendly Monitoring UI
 * ====================================================
 * Two-tab design:
 * - MONITOR: Glanceable status, compact transcript, prominent errors
 * - DETAILS: Full debate logs, audit trail (for debugging)
 */

"use client";

import { useState, useEffect, useRef } from "react";
import { useSarasvatiSimple } from "@/hooks/useSarasvatiSimple";
import {
  Wifi,
  WifiOff,
  Mic,
  MicOff,
  Settings,
  CheckCircle,
  XCircle,
  AlertTriangle,
  X,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import {
  StreamRole,
  TranscriptSegment,
  ClinicalError,
  DebateLogEntry,
} from "@/types/sarasvati";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

// ============================================================================
// STATUS INDICATOR - Big glanceable status
// ============================================================================

function StatusIndicator({
  hasErrors,
  errorCount,
}: {
  hasErrors: boolean;
  errorCount: number;
}) {
  if (hasErrors) {
    return (
      <div className="flex items-center gap-2 px-4 py-2 bg-red-600 rounded-full">
        <XCircle size={20} className="text-white" />
        <span className="font-bold text-white">
          {errorCount} ERROR{errorCount > 1 ? "S" : ""}
        </span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 px-4 py-2 bg-green-600 rounded-full">
      <CheckCircle size={20} className="text-white" />
      <span className="font-bold text-white">ALL CLEAR</span>
    </div>
  );
}

// ============================================================================
// ERROR ALERT - Prominent error display for doctor
// ============================================================================

function ErrorAlert({
  error,
  sourceText,
  interpreterText,
  onDismiss,
  onViewDetails,
}: {
  error: ClinicalError;
  sourceText?: string;
  interpreterText?: string;
  onDismiss: () => void;
  onViewDetails: () => void;
}) {
  // Normalize severity - handle both enum string and plain string
  const normalizedSeverity = (error.severity || "medium").toLowerCase().replace("errorseverity.", "");

  const severityColors: Record<string, string> = {
    critical: "border-red-500 bg-red-950",
    high: "border-orange-500 bg-orange-950",
    medium: "border-yellow-500 bg-yellow-950",
    low: "border-blue-500 bg-blue-950",
  };
  const colors = severityColors[normalizedSeverity] || severityColors.medium;

  // Format error type for display
  const errorType = (error.error_type || "issue").toUpperCase().replace(/_/g, " ");

  // Get description with fallback
  const description = error.description || "Potential interpretation issue detected. Check details for more information.";

  // Use source/interpreter quotes from error if available, fallback to props
  const displaySourceText = error.source_quote || sourceText;
  const displayInterpreterText = error.interpreter_quote || interpreterText;

  return (
    <div className={`border-2 ${colors} rounded-lg p-4 mb-4`}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <AlertTriangle className="text-red-400" size={24} />
          <span className="font-bold text-lg text-red-300">
            {errorType}
          </span>
          <span className={`text-xs px-2 py-1 rounded ${
            normalizedSeverity === "critical" ? "bg-red-700" :
            normalizedSeverity === "high" ? "bg-orange-700" :
            normalizedSeverity === "medium" ? "bg-yellow-700" : "bg-blue-700"
          }`}>
            {normalizedSeverity}
          </span>
        </div>
        <button
          onClick={onDismiss}
          className="text-gray-400 hover:text-white transition-colors"
        >
          <X size={20} />
        </button>
      </div>

      {displaySourceText && (
        <div className="mb-3">
          <p className="text-xs text-gray-500 mb-1">SOURCE SAID:</p>
          <p className="text-gray-200 bg-gray-800 rounded p-2">"{displaySourceText}"</p>
        </div>
      )}

      {displayInterpreterText && (
        <div className="mb-3">
          <p className="text-xs text-gray-500 mb-1">INTERPRETER SAID:</p>
          <p className="text-gray-200 bg-gray-800 rounded p-2">"{displayInterpreterText}"</p>
        </div>
      )}

      <div className="mb-4">
        <p className="text-xs text-gray-500 mb-1">ISSUE:</p>
        <p className="text-yellow-300">{description}</p>
      </div>

      <div className="flex gap-2">
        <button
          onClick={onDismiss}
          className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm"
        >
          Dismiss
        </button>
        <button
          onClick={onViewDetails}
          className="px-4 py-2 bg-purple-700 hover:bg-purple-600 rounded text-sm"
        >
          View Details
        </button>
      </div>
    </div>
  );
}

// ============================================================================
// COMPACT TRANSCRIPT - Shows ENGLISH meaning, not raw text
// ============================================================================

function CompactTranscript({
  transcripts,
  errors,
}: {
  transcripts: TranscriptSegment[];
  errors: ClinicalError[];
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [transcripts]);

  const roleConfig: Record<StreamRole, { icon: string; color: string; label: string }> = {
    provider: { icon: "🩺", color: "text-blue-400", label: "Dr" },
    interpreter: { icon: "🗣️", color: "text-purple-400", label: "Int" },
    patient: { icon: "👤", color: "text-green-400", label: "Pt" },
  };

  const hasRecentError = errors.length > 0;

  return (
    <div
      ref={scrollRef}
      className="bg-gray-900 rounded-lg border border-gray-700 p-3 h-64 overflow-y-auto"
    >
      {transcripts.length === 0 ? (
        <p className="text-gray-500 text-center py-8">
          Waiting for conversation...
        </p>
      ) : (
        <div className="space-y-2">
          {transcripts.map((t, idx) => {
            const config = roleConfig[t.role];
            // Show error indicator on recent interpreter lines if there are errors
            const showError = t.role === "interpreter" && hasRecentError &&
              idx >= transcripts.length - 2;

            // Get the ENGLISH meaning to display (not raw text)
            const displayText = t.english_translation || t.text;

            return (
              <div key={idx} className="flex items-start gap-2 text-sm">
                <span className={`${config.color} font-bold shrink-0 w-8`}>
                  {config.label}:
                </span>
                <span className="text-gray-300 flex-1">{displayText}</span>
                {t.role === "interpreter" && !showError && (
                  <CheckCircle size={14} className="text-green-500 shrink-0" />
                )}
                {showError && (
                  <AlertTriangle size={14} className="text-yellow-500 shrink-0" />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// DETAILS TAB - Full debate logs for auditing
// ============================================================================

function DetailsTab({
  transcripts,
  debateLogs,
  errors,
  latestVerdict,
}: {
  transcripts: TranscriptSegment[];
  debateLogs: DebateLogEntry[] | null;
  errors: ClinicalError[];
  latestVerdict?: { arbiter_decision?: string; verdict_is_accurate?: boolean } | null;
}) {
  const [expandedRounds, setExpandedRounds] = useState<Set<number>>(new Set([1, 2]));

  const toggleRound = (round: number) => {
    const newSet = new Set(expandedRounds);
    if (newSet.has(round)) {
      newSet.delete(round);
    } else {
      newSet.add(round);
    }
    setExpandedRounds(newSet);
  };

  // Group debate entries by round
  const roundsMap = new Map<number, DebateLogEntry[]>();
  debateLogs?.forEach((entry) => {
    const roundEntries = roundsMap.get(entry.round) || [];
    roundEntries.push(entry);
    roundsMap.set(entry.round, roundEntries);
  });
  const rounds = Array.from(roundsMap.entries()).sort((a, b) => a[0] - b[0]);

  const getPhaseLabel = (roundNum: number): string => {
    if (roundNum === 1) return "INDEPENDENT ANALYSIS";
    return "PEER REVIEW";
  };

  const verdictColor = (verdict?: string) =>
    verdict === "accurate" ? "text-green-400" :
    verdict === "minor_issues" ? "text-yellow-400" :
    verdict === "significant_errors" ? "text-orange-400" :
    verdict === "critical_errors" ? "text-red-400" : "text-gray-400";

  return (
    <div className="space-y-6">
      {/* Full Transcript with English */}
      <div>
        <h3 className="text-sm font-bold text-gray-400 mb-2">FULL TRANSCRIPT (English)</h3>
        <div className="bg-gray-900 rounded-lg border border-gray-700 p-3 max-h-48 overflow-y-auto">
          {transcripts.map((t, idx) => (
            <div key={idx} className="py-1 border-b border-gray-800 last:border-0">
              <span className={`text-xs font-bold ${
                t.role === "provider" ? "text-blue-400" :
                t.role === "interpreter" ? "text-purple-400" : "text-green-400"
              }`}>
                {t.role.toUpperCase()}:
              </span>
              <span className="text-gray-300 ml-2">
                {/* Show English translation prominently */}
                {t.english_translation || t.text}
              </span>
              {/* Show original text in smaller font if different */}
              {t.english_translation && t.detected_language !== "en" && (
                <span className="text-gray-500 text-xs ml-2">
                  (Original: {t.text})
                </span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Debate Log */}
      {debateLogs && debateLogs.length > 0 && (
        <div>
          <h3 className="text-sm font-bold text-gray-400 mb-2">
            TRIBUNAL DEBATE ({rounds.length} round{rounds.length > 1 ? "s" : ""})
          </h3>
          <div className="bg-gray-900 rounded-lg border border-gray-700 overflow-hidden">
            {rounds.map(([roundNum, entries]) => (
              <div key={roundNum} className="border-b border-gray-700 last:border-0">
                <button
                  onClick={() => toggleRound(roundNum)}
                  className="w-full flex items-center gap-2 p-3 hover:bg-gray-800 transition-colors text-left"
                >
                  {expandedRounds.has(roundNum) ? (
                    <ChevronDown size={16} />
                  ) : (
                    <ChevronRight size={16} />
                  )}
                  <span className="text-sm font-medium">Round {roundNum}</span>
                  <span className="text-xs text-gray-500">{getPhaseLabel(roundNum)}</span>
                  <span className="text-xs text-gray-600 ml-auto">{entries.length} agents</span>
                </button>
                {expandedRounds.has(roundNum) && (
                  <div className="px-4 pb-3 space-y-3">
                    {entries.map((entry, idx) => {
                      const opinion = entry.opinion || {};
                      return (
                        <div key={idx} className="pl-4 border-l-2 border-purple-700 py-2 bg-gray-800/50 rounded-r">
                          <div className="flex items-center gap-2 flex-wrap text-sm mb-2">
                            <span className="font-medium text-purple-300">{entry.agent}</span>
                            <span className={`font-medium px-2 py-0.5 rounded text-xs ${verdictColor(opinion.verdict)}`}>
                              {opinion.verdict || "analyzing"}
                            </span>
                            {opinion.changed_mind && (
                              <span className="text-xs bg-yellow-800 text-yellow-200 px-1.5 py-0.5 rounded">
                                CHANGED MIND
                              </span>
                            )}
                          </div>
                          {opinion.reasoning && (
                            <p className="text-gray-400 text-sm mb-2">
                              {opinion.reasoning.slice(0, 300)}{opinion.reasoning.length > 300 ? "..." : ""}
                            </p>
                          )}
                          {opinion.errors && opinion.errors.length > 0 && (
                            <div className="text-xs text-red-400 mt-1">
                              Found {opinion.errors.length} error(s): {opinion.errors.map(e => e.type).join(", ")}
                            </div>
                          )}
                          {(opinion.agrees_with?.length || opinion.disagrees_with?.length) && (
                            <div className="flex gap-2 mt-2 text-xs">
                              {opinion.agrees_with?.length > 0 && (
                                <span className="text-green-400">Agrees: {opinion.agrees_with.join(", ")}</span>
                              )}
                              {opinion.disagrees_with?.length > 0 && (
                                <span className="text-red-400">Disagrees: {opinion.disagrees_with.join(", ")}</span>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}
            {/* Final verdict from arbiter */}
            {latestVerdict && (
              <div className="p-3 bg-gray-800">
                <div className="flex items-center gap-2">
                  {latestVerdict.verdict_is_accurate ? (
                    <CheckCircle size={16} className="text-green-500" />
                  ) : (
                    <AlertTriangle size={16} className="text-yellow-500" />
                  )}
                  <span className="text-sm font-medium">Final Verdict:</span>
                  <span className={`font-bold ${latestVerdict.verdict_is_accurate ? "text-green-400" : "text-yellow-400"}`}>
                    {latestVerdict.verdict_is_accurate ? "ACCURATE" : "ERRORS FOUND"}
                  </span>
                </div>
                {latestVerdict.arbiter_decision && (
                  <p className="text-gray-500 text-xs mt-2">
                    {latestVerdict.arbiter_decision.slice(0, 200)}...
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Errors List */}
      {errors.length > 0 && (
        <div>
          <h3 className="text-sm font-bold text-gray-400 mb-2">DETECTED ERRORS ({errors.length})</h3>
          <div className="space-y-2">
            {errors.map((error, idx) => (
              <div
                key={error.error_id || idx}
                className={`p-3 rounded border ${
                  error.severity === "critical" ? "border-red-600 bg-red-950/50" :
                  error.severity === "high" ? "border-orange-600 bg-orange-950/50" :
                  "border-yellow-600 bg-yellow-950/50"
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-gray-200">{error.error_type}</span>
                  <span className="text-xs px-1.5 py-0.5 rounded bg-gray-700">
                    {error.severity}
                  </span>
                </div>
                <p className="text-gray-400 text-sm">{error.description}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {(!debateLogs || debateLogs.length === 0) && errors.length === 0 && (
        <p className="text-gray-500 text-center py-8">
          No tribunal data yet. Record a provider-interpreter exchange to see the debate.
        </p>
      )}
    </div>
  );
}

// ============================================================================
// INPUT BAR
// ============================================================================

function InputBar({
  isConnected,
  isRecording,
  selectedRole,
  onRoleChange,
  onToggleRecording,
  onSettingsClick,
  showSettings,
}: {
  isConnected: boolean;
  isRecording: boolean;
  selectedRole: StreamRole;
  onRoleChange: (role: StreamRole) => void;
  onToggleRecording: () => void;
  onSettingsClick: () => void;
  showSettings: boolean;
}) {
  const roleEmoji: Record<StreamRole, string> = {
    provider: "🩺",
    interpreter: "🗣️",
    patient: "👤",
  };

  return (
    <div className="flex items-center gap-3 p-4 bg-gray-900 border-t border-gray-700">
      {/* Role selector */}
      <div className="flex rounded-lg overflow-hidden border border-gray-700">
        {(["provider", "interpreter", "patient"] as StreamRole[]).map((role) => (
          <button
            key={role}
            onClick={() => onRoleChange(role)}
            className={`px-3 py-2 text-sm flex items-center gap-1.5 transition-colors ${
              selectedRole === role
                ? "bg-purple-600 text-white"
                : "bg-gray-800 text-gray-400 hover:bg-gray-700"
            }`}
          >
            <span>{roleEmoji[role]}</span>
            <span className="capitalize hidden sm:inline">{role}</span>
          </button>
        ))}
      </div>

      {/* Record button */}
      <button
        onClick={onToggleRecording}
        disabled={!isConnected}
        className={`flex-1 max-w-md flex items-center justify-center gap-2 px-6 py-3 rounded-lg font-bold text-lg transition-all ${
          isRecording
            ? "bg-red-600 hover:bg-red-700 animate-pulse"
            : "bg-green-600 hover:bg-green-700"
        } disabled:opacity-50 disabled:cursor-not-allowed`}
      >
        {isRecording ? <MicOff size={24} /> : <Mic size={24} />}
        {isRecording ? "STOP" : "RECORD"}
      </button>

      {/* Settings */}
      <button
        onClick={onSettingsClick}
        className={`p-3 rounded-lg transition-colors ${
          showSettings ? "bg-purple-600" : "bg-gray-800 hover:bg-gray-700"
        }`}
      >
        <Settings size={20} />
      </button>
    </div>
  );
}

// ============================================================================
// SETTINGS PANEL
// ============================================================================

function SettingsPanel({
  providerLang,
  patientLang,
  onProviderLangChange,
  onPatientLangChange,
  asrBackend,
  onAsrBackendChange,
}: {
  providerLang: string;
  patientLang: string;
  onProviderLangChange: (lang: string) => void;
  onPatientLangChange: (lang: string) => void;
  asrBackend: string;
  onAsrBackendChange: (backend: "groq-turbo" | "groq-large") => void;
}) {
  const LANGUAGES = [
    { code: "en", name: "English" },
    { code: "es", name: "Spanish" },
    { code: "gu", name: "Gujarati" },
    { code: "hi", name: "Hindi" },
    { code: "pt", name: "Portuguese" },
    { code: "zh", name: "Chinese" },
    { code: "ar", name: "Arabic" },
    { code: "fr", name: "French" },
    { code: "auto", name: "Auto-detect" },
  ];

  return (
    <div className="p-4 bg-gray-800 border-t border-gray-700">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Provider Language</label>
          <select
            value={providerLang}
            onChange={(e) => onProviderLangChange(e.target.value)}
            className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm"
          >
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>{l.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Patient Language</label>
          <select
            value={patientLang}
            onChange={(e) => onPatientLangChange(e.target.value)}
            className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm"
          >
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>{l.name}</option>
            ))}
          </select>
        </div>
        <div className="col-span-2">
          <label className="block text-xs text-gray-500 mb-1">Whisper Model</label>
          <div className="flex gap-2">
            <button
              onClick={() => onAsrBackendChange("groq-turbo")}
              className={`flex-1 px-3 py-1.5 rounded text-sm ${
                asrBackend === "groq-turbo" ? "bg-emerald-600" : "bg-gray-700 hover:bg-gray-600"
              }`}
            >
              Turbo (faster)
            </button>
            <button
              onClick={() => onAsrBackendChange("groq-large")}
              className={`flex-1 px-3 py-1.5 rounded text-sm ${
                asrBackend === "groq-large" ? "bg-emerald-600" : "bg-gray-700 hover:bg-gray-600"
              }`}
            >
              Large (better)
            </button>
          </div>
        </div>
      </div>
      <div className="mt-3 text-xs text-gray-500">
        <p className="font-medium mb-1">3-Agent Tribunal:</p>
        <p>Llama (Groq) + GPT-4o-mini (OpenAI) + DeepSeek</p>
      </div>
    </div>
  );
}

// ============================================================================
// MAIN PAGE
// ============================================================================

export default function DashboardPage() {
  const {
    connectionState,
    sessionState,
    connect,
    disconnect,
    startRecording,
    stopRecording,
  } = useSarasvatiSimple({ backendUrl: BACKEND_URL });

  const [selectedRole, setSelectedRole] = useState<StreamRole>("provider");
  const [providerLang, setProviderLang] = useState("en");
  const [patientLang, setPatientLang] = useState("es");
  const [asrBackend, setAsrBackend] = useState<"groq-turbo" | "groq-large">("groq-turbo");
  const [showSettings, setShowSettings] = useState(false);
  const [activeTab, setActiveTab] = useState<"monitor" | "details">("monitor");
  const [dismissedErrors, setDismissedErrors] = useState<Set<string>>(new Set());

  // Fetch ASR config on mount
  useEffect(() => {
    const fetchAsrConfig = async () => {
      try {
        const httpUrl = BACKEND_URL.replace("ws://", "http://").replace("wss://", "https://");
        const response = await fetch(`${httpUrl}/admin/asr-config`);
        if (response.ok) {
          const data = await response.json();
          const mode = data.current_mode || data.current_config?.mode || "groq-turbo";
          setAsrBackend(mode === "groq-large" ? "groq-large" : "groq-turbo");
        }
      } catch (error) {
        console.error("Failed to fetch ASR config:", error);
      }
    };
    fetchAsrConfig();
  }, []);

  const handleAsrBackendChange = async (backend: "groq-turbo" | "groq-large") => {
    try {
      const httpUrl = BACKEND_URL.replace("ws://", "http://").replace("wss://", "https://");
      const response = await fetch(`${httpUrl}/admin/asr-config/switch-default`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ backend }),
      });
      if (response.ok) setAsrBackend(backend);
    } catch (error) {
      console.error("Error switching ASR backend:", error);
    }
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

  // Get clinical errors (non-system, deduplicated)
  const clinicalErrors = sessionState.errors.filter((e) => !e.is_system_error);
  const uniqueErrors = Array.from(new Map(clinicalErrors.map((e) => [e.error_id, e])).values());
  const activeErrors = uniqueErrors.filter((e) => !dismissedErrors.has(e.error_id));

  // Get latest verdict for Details tab
  const latestVerdict = sessionState.verdicts?.length > 0
    ? sessionState.verdicts[sessionState.verdicts.length - 1]
    : null;

  // Get source/interpreter text for error context
  const lastPatient = [...sessionState.transcripts].reverse().find((t) => t.role === "patient");
  const lastProvider = [...sessionState.transcripts].reverse().find((t) => t.role === "provider");
  const lastInterpreter = [...sessionState.transcripts].reverse().find((t) => t.role === "interpreter");
  const sourceText = lastPatient?.english_translation || lastPatient?.text || lastProvider?.english_translation || lastProvider?.text;
  const interpreterText = lastInterpreter?.english_translation || lastInterpreter?.text;

  const handleDismissError = (errorId: string) => {
    setDismissedErrors((prev) => new Set([...prev, errorId]));
  };

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 bg-gray-900 border-b border-gray-800">
        <div className="flex items-center gap-4">
          <div>
            <h1 className="text-xl font-bold text-white">SARASVATI</h1>
            <p className="text-xs text-gray-500">Medical Interpreter Monitor</p>
          </div>
          {/* Tabs */}
          <div className="flex rounded-lg overflow-hidden border border-gray-700 ml-4">
            <button
              onClick={() => setActiveTab("monitor")}
              className={`px-4 py-1.5 text-sm font-medium transition-colors ${
                activeTab === "monitor"
                  ? "bg-purple-600 text-white"
                  : "bg-gray-800 text-gray-400 hover:bg-gray-700"
              }`}
            >
              Monitor
            </button>
            <button
              onClick={() => setActiveTab("details")}
              className={`px-4 py-1.5 text-sm font-medium transition-colors ${
                activeTab === "details"
                  ? "bg-purple-600 text-white"
                  : "bg-gray-800 text-gray-400 hover:bg-gray-700"
              }`}
            >
              Details
            </button>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <StatusIndicator hasErrors={activeErrors.length > 0} errorCount={activeErrors.length} />
          <div className="flex items-center gap-2">
            {connectionState.websocketConnected ? (
              <Wifi className="text-green-500" size={18} />
            ) : (
              <WifiOff className="text-red-500" size={18} />
            )}
            <button
              onClick={connectionState.websocketConnected ? disconnect : connect}
              className={`px-3 py-1.5 rounded text-sm font-medium ${
                connectionState.websocketConnected
                  ? "bg-gray-700 hover:bg-gray-600"
                  : "bg-blue-600 hover:bg-blue-700"
              }`}
            >
              {connectionState.websocketConnected ? "Disconnect" : "Connect"}
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 p-4 overflow-y-auto">
        <div className="max-w-4xl mx-auto">
          {/* Error banner */}
          {connectionState.error && (
            <div className="mb-4 p-3 bg-red-900/50 border border-red-700 rounded text-sm text-red-300">
              {connectionState.error}
            </div>
          )}

          {activeTab === "monitor" ? (
            /* MONITOR TAB */
            <div className="space-y-4">
              {/* Prominent Error Alert */}
              {activeErrors.length > 0 && (
                <ErrorAlert
                  error={activeErrors[0]}
                  sourceText={sourceText}
                  interpreterText={interpreterText}
                  onDismiss={() => handleDismissError(activeErrors[0].error_id)}
                  onViewDetails={() => setActiveTab("details")}
                />
              )}

              {/* Status Box */}
              <div className={`rounded-lg p-6 border-2 ${
                activeErrors.length > 0
                  ? "border-red-600 bg-red-950/30"
                  : "border-green-600 bg-green-950/30"
              }`}>
                <div className="flex items-center gap-3 mb-2">
                  {activeErrors.length > 0 ? (
                    <XCircle size={32} className="text-red-400" />
                  ) : (
                    <CheckCircle size={32} className="text-green-400" />
                  )}
                  <h2 className={`text-2xl font-bold ${
                    activeErrors.length > 0 ? "text-red-300" : "text-green-300"
                  }`}>
                    {activeErrors.length > 0 ? "ERROR DETECTED" : "ALL CLEAR"}
                  </h2>
                </div>
                <p className="text-gray-400">
                  {activeErrors.length > 0
                    ? `${activeErrors.length} interpretation issue${activeErrors.length > 1 ? "s" : ""} detected. Review above.`
                    : "Interpretation is accurate. No issues detected."}
                </p>
              </div>

              {/* Compact Live Transcript (shows English) */}
              <div>
                <h3 className="text-sm font-bold text-gray-400 mb-2">LIVE TRANSCRIPT</h3>
                <CompactTranscript
                  transcripts={sessionState.transcripts}
                  errors={activeErrors}
                />
              </div>
            </div>
          ) : (
            /* DETAILS TAB */
            <DetailsTab
              transcripts={sessionState.transcripts}
              debateLogs={sessionState.debateLogs}
              errors={uniqueErrors}
              latestVerdict={latestVerdict}
            />
          )}
        </div>
      </main>

      {/* Settings Panel */}
      {showSettings && (
        <SettingsPanel
          providerLang={providerLang}
          patientLang={patientLang}
          onProviderLangChange={setProviderLang}
          onPatientLangChange={setPatientLang}
          asrBackend={asrBackend}
          onAsrBackendChange={handleAsrBackendChange}
        />
      )}

      {/* Input Bar */}
      <InputBar
        isConnected={connectionState.websocketConnected}
        isRecording={connectionState.isRecording}
        selectedRole={selectedRole}
        onRoleChange={setSelectedRole}
        onToggleRecording={handleToggleRecording}
        onSettingsClick={() => setShowSettings(!showSettings)}
        showSettings={showSettings}
      />
    </div>
  );
}
