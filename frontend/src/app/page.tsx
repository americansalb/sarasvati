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
// GROUPED ERROR CARD - Groups multiple findings per utterance pair
// ===========================================================================
interface GroupedError {
  sourceQuote: string;
  interpreterQuote: string;
  highestSeverity: string;
  avgConfidence: number; // 0-100 clinical significance score
  arbiterSummary: string; // Summary reasoning from tribunal
  idealInterpretation?: string; // What should have been said
  issues: Array<{
    type: string;
    severity: string;
    description: string;
    confidence: number;
  }>;
  errorIds: string[];
}

// Convert confidence to clinical significance percentage
function getClinicialSignificance(confidence: number): number {
  return Math.round((confidence || 0.5) * 100);
}

// Get color for clinical significance score
function getSignificanceColor(score: number): string {
  if (score >= 80) return "text-red-400";
  if (score >= 60) return "text-orange-400";
  if (score >= 40) return "text-yellow-400";
  return "text-blue-400";
}

// Map backend error types to user-friendly labels
function formatErrorType(type: string): string {
  const typeMap: Record<string, string> = {
    unknown: "Translation Issue",
    omission: "Omission",
    fabrication: "Added Content",
    fabrication_medical: "Medical Fabrication",
    distortion: "Distortion",
    distortion_medical: "Medical Distortion",
    register_shift: "Tone/Register Shift",
    negation_mismatch: "Negation Error",
    dosage_error: "Dosage Error",
    asr_unreliable: "Speech Recognition Issue",
    system_error: "System Error",
  };
  const key = (type || "unknown").toLowerCase().replace(/[^a-z_]/g, "_");
  return typeMap[key] || type.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

// Normalize severity value (handles "ErrorSeverity.CRITICAL", "CRITICAL", "critical", etc.)
function normalizeSeverity(severity: string | undefined): string {
  if (!severity) return "medium";
  // Handle enum-style values like "ErrorSeverity.CRITICAL" or "ERRORSEVERITY.HIGH"
  const cleaned = String(severity)
    .toLowerCase()
    .replace(/errorseverity\./gi, "")
    .replace(/severity\./gi, "")
    .trim();
  // Validate it's a known severity
  if (["critical", "high", "medium", "low"].includes(cleaned)) {
    return cleaned;
  }
  return "medium";
}

// Get severity badge color
function getSeverityBadge(severity: string): { bg: string; text: string } {
  const s = normalizeSeverity(severity);
  switch (s) {
    case "critical": return { bg: "bg-red-600", text: "CRITICAL" };
    case "high": return { bg: "bg-orange-600", text: "HIGH" };
    case "medium": return { bg: "bg-yellow-600", text: "MEDIUM" };
    case "low": return { bg: "bg-blue-600", text: "LOW" };
    default: return { bg: "bg-gray-600", text: "MEDIUM" };
  }
}

// Get card border based on highest severity
function getCardStyle(severity: string): string {
  const s = normalizeSeverity(severity);
  switch (s) {
    case "critical": return "border-l-4 border-l-red-500 bg-red-950/50";
    case "high": return "border-l-4 border-l-orange-500 bg-orange-950/30";
    case "medium": return "border-l-4 border-l-yellow-500 bg-yellow-950/30";
    case "low": return "border-l-4 border-l-blue-500 bg-blue-950/30";
    default: return "border-l-4 border-l-yellow-500 bg-yellow-950/30";
  }
}

function GroupedErrorCard({
  group,
  onDismiss,
}: {
  group: GroupedError;
  onDismiss: () => void;
}) {
  const badge = getSeverityBadge(group.highestSeverity);
  const cardStyle = getCardStyle(group.highestSeverity);

  return (
    <div className={`${cardStyle} rounded-lg p-4 mb-3`}>
      {/* Header with severity and dismiss */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <AlertTriangle className="text-yellow-400" size={18} />
          <span className={`text-xs px-2 py-1 rounded font-bold ${badge.bg}`}>
            {badge.text}
          </span>
          <span className="text-gray-400 text-sm">
            {group.issues.length} issue{group.issues.length > 1 ? "s" : ""} found
          </span>
        </div>
        <button
          onClick={onDismiss}
          className="text-gray-400 hover:text-white transition-colors"
          title="Dismiss all issues for this utterance"
        >
          <X size={18} />
        </button>
      </div>

      {/* Source and Interpreter quotes */}
      <div className="space-y-2 mb-3">
        {group.sourceQuote && (
          <div className="flex gap-2 text-sm">
            <span className="text-blue-400 font-medium shrink-0">Provider:</span>
            <span className="text-gray-200">"{group.sourceQuote}"</span>
          </div>
        )}
        {group.interpreterQuote && (
          <div className="flex gap-2 text-sm">
            <span className="text-purple-400 font-medium shrink-0">Interpreter:</span>
            <span className="text-gray-200">"{group.interpreterQuote}"</span>
          </div>
        )}
      </div>

      {/* Issues list */}
      <div className="bg-gray-900/50 rounded p-3 space-y-2">
        {group.issues.map((issue, idx) => (
          <div key={idx} className="flex items-start gap-2 text-sm">
            <span className="text-yellow-500 mt-0.5">•</span>
            <div>
              <span className="text-gray-400 font-medium">{formatErrorType(issue.type)}: </span>
              <span className="text-gray-300">{issue.description}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// Group errors by source+interpreter quote pair
function groupErrorsByUtterance(errors: ClinicalError[]): GroupedError[] {
  const groups = new Map<string, GroupedError & { confidenceSum: number; confidenceCount: number }>();
  const severityRank: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };

  for (const err of errors) {
    const key = `${err.source_quote || ""}|||${err.interpreter_quote || ""}`;

    if (!groups.has(key)) {
      groups.set(key, {
        sourceQuote: err.source_quote || "",
        interpreterQuote: err.interpreter_quote || "",
        highestSeverity: err.severity || "medium",
        avgConfidence: 0,
        arbiterSummary: "",
        idealInterpretation: err.ideal_interpretation || undefined,
        issues: [],
        errorIds: [],
        confidenceSum: 0,
        confidenceCount: 0,
      });
    }

    const group = groups.get(key)!;
    const confidence = getClinicialSignificance(err.confidence);

    group.issues.push({
      type: err.error_type || "unknown",
      severity: err.severity || "medium",
      description: err.description || "Issue detected",
      confidence: confidence,
    });
    group.errorIds.push(err.error_id);
    group.confidenceSum += confidence;
    group.confidenceCount += 1;

    // Capture arbiter reasoning (use the most detailed one)
    if (err.arbiter_reasoning && err.arbiter_reasoning.length > (group.arbiterSummary?.length || 0)) {
      group.arbiterSummary = err.arbiter_reasoning;
    }

    // Capture ideal interpretation if available
    if (err.ideal_interpretation && !group.idealInterpretation) {
      group.idealInterpretation = err.ideal_interpretation;
    }

    // Update highest severity
    const currentRank = severityRank[(group.highestSeverity || "medium").toLowerCase()] || 2;
    const newRank = severityRank[(err.severity || "medium").toLowerCase()] || 2;
    if (newRank > currentRank) {
      group.highestSeverity = err.severity || "medium";
    }
  }

  // Calculate average confidence and sort by severity
  return Array.from(groups.values())
    .map(g => ({
      ...g,
      avgConfidence: g.confidenceCount > 0 ? Math.round(g.confidenceSum / g.confidenceCount) : 50,
    }))
    .sort((a, b) => {
      const rankA = severityRank[a.highestSeverity.toLowerCase()] || 2;
      const rankB = severityRank[b.highestSeverity.toLowerCase()] || 2;
      return rankB - rankA;
    });
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
// SINGLE DEBATE SECTION - Shows one tribunal's debate
// ===========================================================================
function SingleDebateSection({
  title,
  debate,
  icon
}: {
  title: string;
  debate: any;
  icon: string;
}) {
  const [expanded, setExpanded] = useState(false);

  if (!debate || !debate.turns || debate.turns.length === 0) {
    return null;
  }

  // Get position color
  const getPositionColor = (position: string) => {
    const p = (position || "").toLowerCase();
    if (p === "accurate" || p.includes("agree")) return "bg-green-800";
    if (p === "critical_errors" || p.includes("critical")) return "bg-red-800";
    if (p === "significant_errors" || p.includes("significant")) return "bg-orange-800";
    return "bg-yellow-800";
  };

  return (
    <div className="bg-gray-800/50 rounded-lg border border-gray-700 mb-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-3 hover:bg-gray-700/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          <span className="text-lg">{icon}</span>
          <span className="font-medium text-sm">{title}</span>
          <span className="text-xs text-gray-500">
            {debate.rounds_taken || debate.turns?.length || 0} round{(debate.rounds_taken || 1) > 1 ? 's' : ''}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {debate.consensus_reached !== undefined && (
            <span className={`text-xs px-2 py-0.5 rounded ${
              debate.consensus_reached ? "bg-green-900 text-green-300" : "bg-yellow-900 text-yellow-300"
            }`}>
              {debate.consensus_reached ? "✓ Consensus" : "No Consensus"}
            </span>
          )}
          {debate.final_consensus && (
            <span className={`text-xs px-2 py-0.5 rounded font-medium ${getPositionColor(debate.final_consensus)}`}>
              {debate.final_consensus.replace(/_/g, ' ').toUpperCase()}
            </span>
          )}
        </div>
      </button>

      {expanded && (
        <div className="p-3 border-t border-gray-700 max-h-64 overflow-y-auto space-y-2">
          {debate.turns.map((turn: any, idx: number) => {
            const isNewRound = idx === 0 || turn.round !== debate.turns[idx - 1]?.round;
            return (
              <div key={idx}>
                {isNewRound && idx > 0 && (
                  <div className="flex items-center gap-2 my-2">
                    <div className="flex-1 h-px bg-gray-600" />
                    <span className="text-xs text-gray-500">Round {turn.round}</span>
                    <div className="flex-1 h-px bg-gray-600" />
                  </div>
                )}
                <div className={`p-2 rounded text-sm ${turn.changed_mind ? "bg-yellow-900/20 border border-yellow-800" : "bg-gray-900/50"}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium text-purple-300 text-xs">{turn.agent}</span>
                    <span className="text-xs px-1.5 py-0.5 bg-gray-700 text-gray-300 rounded">
                      {turn.model || turn.provider}
                    </span>
                    {turn.changed_mind && (
                      <span className="text-xs text-yellow-400">🔄 Changed position</span>
                    )}
                    <span className={`ml-auto text-xs px-1.5 py-0.5 rounded ${getPositionColor(turn.position)}`}>
                      {(turn.position || "").substring(0, 20)}
                    </span>
                  </div>
                  <p className="text-xs text-gray-400 line-clamp-2">
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
// DEBATE PANEL - Shows all tribunal debates
// ===========================================================================
function DebatePanel({ debateLogs }: { debateLogs: any }) {
  // Check if we have any debates at all
  const hasSourceTranslation = debateLogs?.source_translation?.turns?.length > 0;
  const hasInterpreterTranslation = debateLogs?.interpreter_translation?.turns?.length > 0;
  const hasErrorEvaluation = debateLogs?.error_evaluation?.turns?.length > 0;

  const hasAnyDebate = hasSourceTranslation || hasInterpreterTranslation || hasErrorEvaluation;

  if (!debateLogs || !hasAnyDebate) {
    return (
      <div className="bg-gray-900/50 rounded-lg border border-gray-700 p-6 text-center">
        <div className="text-gray-500 text-4xl mb-2">🏛️</div>
        <p className="text-gray-400 font-medium">No tribunal debates yet</p>
        <p className="text-gray-500 text-sm mt-1">
          Debates will appear here when the system evaluates interpretations
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* Source Translation Tribunal */}
      {hasSourceTranslation && (
        <SingleDebateSection
          title="Source Translation"
          debate={debateLogs.source_translation}
          icon="🌐"
        />
      )}

      {/* Interpreter Translation Tribunal */}
      {hasInterpreterTranslation && (
        <SingleDebateSection
          title="Interpreter Translation"
          debate={debateLogs.interpreter_translation}
          icon="🗣️"
        />
      )}

      {/* Error Evaluation Tribunal */}
      {hasErrorEvaluation && (
        <SingleDebateSection
          title="Error Evaluation"
          debate={debateLogs.error_evaluation}
          icon="⚖️"
        />
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

  const [activeTab, setActiveTab] = useState<"monitor" | "details" | "upload">("monitor");
  const [selectedRole, setSelectedRole] = useState<StreamRole>("provider");
  const [dismissedGroups, setDismissedGroups] = useState<Set<string>>(new Set());
  const [showSettings, setShowSettings] = useState(false);
  const [providerLang, setProviderLang] = useState("en");
  const [patientLang, setPatientLang] = useState("auto"); // Auto-detect by default
  const [selectedErrorDetail, setSelectedErrorDetail] = useState<GroupedError | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const analyzeTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Upload tab state
  const [uploadState, setUploadState] = useState<{
    isUploading: boolean;
    isAnalyzing: boolean;
    uploadId: string | null;
    segments: Array<{
      segment_id: string;
      speaker_id: string;
      start_time: number;
      end_time: number;
      text: string;
      detected_language?: string;
    }>;
    detectedSpeakers: string[];
    speakerLanguageInfo: Array<{
      speaker_id: string;
      primary_language: string;
      segment_count: number;
      sample_text: string;
    }>;
    roleMappings: Record<string, string>;
    results: {
      transcripts: Array<unknown>;
      errors: Array<unknown>;
      verdicts: Array<unknown>;
    } | null;
    error: string | null;
  }>({
    isUploading: false,
    isAnalyzing: false,
    uploadId: null,
    segments: [],
    detectedSpeakers: [],
    speakerLanguageInfo: [],
    roleMappings: {},
    results: null,
    error: null,
  });

  // Track when interpreter transcripts arrive to show analyzing state
  const lastInterpreterCountRef = useRef(0);
  useEffect(() => {
    const interpreterCount = sessionState.transcripts.filter(t => t.role === "interpreter").length;
    if (interpreterCount > lastInterpreterCountRef.current) {
      // New interpreter transcript - start analyzing indicator
      setIsAnalyzing(true);
      // Clear any existing timeout
      if (analyzeTimeoutRef.current) {
        clearTimeout(analyzeTimeoutRef.current);
      }
      // Set timeout to auto-clear after 30 seconds (in case no verdict comes)
      analyzeTimeoutRef.current = setTimeout(() => {
        setIsAnalyzing(false);
      }, 30000);
    }
    lastInterpreterCountRef.current = interpreterCount;
  }, [sessionState.transcripts]);

  // Clear analyzing state when verdict arrives
  const lastVerdictCountRef = useRef(0);
  useEffect(() => {
    if (sessionState.verdicts.length > lastVerdictCountRef.current) {
      setIsAnalyzing(false);
      if (analyzeTimeoutRef.current) {
        clearTimeout(analyzeTimeoutRef.current);
      }
    }
    lastVerdictCountRef.current = sessionState.verdicts.length;
  }, [sessionState.verdicts]);

  // Get clinical errors and group by utterance
  const clinicalErrors = sessionState.errors.filter((e) => !e.is_system_error);
  const groupedErrors = groupErrorsByUtterance(clinicalErrors);
  const activeGroups = groupedErrors.filter(
    (g) => !dismissedGroups.has(`${g.sourceQuote}|||${g.interpreterQuote}`)
  );

  // Get error counts by category for summary
  const errorSummary = {
    omissions: clinicalErrors.filter(e => e.error_type?.toLowerCase().includes("omission")).length,
    additions: clinicalErrors.filter(e => e.error_type?.toLowerCase().includes("fabrication") || e.error_type?.toLowerCase().includes("addition")).length,
    distortions: clinicalErrors.filter(e => e.error_type?.toLowerCase().includes("distortion") || e.error_type?.toLowerCase().includes("substitution")).length,
    other: clinicalErrors.filter(e => {
      const t = e.error_type?.toLowerCase() || "";
      return !t.includes("omission") && !t.includes("fabrication") && !t.includes("addition") && !t.includes("distortion") && !t.includes("substitution");
    }).length,
  };

  // Find errors for a specific interpreter quote
  const getErrorsForInterpreter = (interpreterText: string): GroupedError | null => {
    return groupedErrors.find(g =>
      g.interpreterQuote && interpreterText?.includes(g.interpreterQuote.substring(0, 20))
    ) || null;
  };

  const handleDismissGroup = (group: GroupedError) => {
    const key = `${group.sourceQuote}|||${group.interpreterQuote}`;
    setDismissedGroups((prev) => new Set([...prev, key]));
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

  // All Whisper-supported languages (99 languages)
  // Auto-detect first, then alphabetical by name
  const LANGUAGES = [
    { code: "auto", name: "🌐 Auto-detect" },
    // Common medical interpretation languages first
    { code: "en", name: "English" },
    { code: "es", name: "Spanish" },
    { code: "zh", name: "Chinese (Mandarin)" },
    { code: "vi", name: "Vietnamese" },
    { code: "tl", name: "Tagalog" },
    { code: "ko", name: "Korean" },
    { code: "ar", name: "Arabic" },
    { code: "fr", name: "French" },
    { code: "pt", name: "Portuguese" },
    { code: "ru", name: "Russian" },
    { code: "hi", name: "Hindi" },
    { code: "gu", name: "Gujarati" },
    // All other languages alphabetically
    { code: "af", name: "Afrikaans" },
    { code: "sq", name: "Albanian" },
    { code: "am", name: "Amharic" },
    { code: "hy", name: "Armenian" },
    { code: "as", name: "Assamese" },
    { code: "az", name: "Azerbaijani" },
    { code: "ba", name: "Bashkir" },
    { code: "eu", name: "Basque" },
    { code: "be", name: "Belarusian" },
    { code: "bn", name: "Bengali" },
    { code: "bs", name: "Bosnian" },
    { code: "br", name: "Breton" },
    { code: "bg", name: "Bulgarian" },
    { code: "my", name: "Burmese" },
    { code: "yue", name: "Cantonese" },
    { code: "ca", name: "Catalan" },
    { code: "hr", name: "Croatian" },
    { code: "cs", name: "Czech" },
    { code: "da", name: "Danish" },
    { code: "nl", name: "Dutch" },
    { code: "et", name: "Estonian" },
    { code: "fo", name: "Faroese" },
    { code: "fi", name: "Finnish" },
    { code: "gl", name: "Galician" },
    { code: "ka", name: "Georgian" },
    { code: "de", name: "German" },
    { code: "el", name: "Greek" },
    { code: "ht", name: "Haitian Creole" },
    { code: "ha", name: "Hausa" },
    { code: "haw", name: "Hawaiian" },
    { code: "he", name: "Hebrew" },
    { code: "hu", name: "Hungarian" },
    { code: "is", name: "Icelandic" },
    { code: "id", name: "Indonesian" },
    { code: "it", name: "Italian" },
    { code: "ja", name: "Japanese" },
    { code: "jv", name: "Javanese" },
    { code: "kn", name: "Kannada" },
    { code: "kk", name: "Kazakh" },
    { code: "km", name: "Khmer" },
    { code: "lo", name: "Lao" },
    { code: "la", name: "Latin" },
    { code: "lv", name: "Latvian" },
    { code: "ln", name: "Lingala" },
    { code: "lt", name: "Lithuanian" },
    { code: "lb", name: "Luxembourgish" },
    { code: "mk", name: "Macedonian" },
    { code: "mg", name: "Malagasy" },
    { code: "ms", name: "Malay" },
    { code: "ml", name: "Malayalam" },
    { code: "mt", name: "Maltese" },
    { code: "mi", name: "Maori" },
    { code: "mr", name: "Marathi" },
    { code: "mn", name: "Mongolian" },
    { code: "ne", name: "Nepali" },
    { code: "no", name: "Norwegian" },
    { code: "nn", name: "Norwegian Nynorsk" },
    { code: "oc", name: "Occitan" },
    { code: "pa", name: "Punjabi" },
    { code: "ps", name: "Pashto" },
    { code: "fa", name: "Persian" },
    { code: "pl", name: "Polish" },
    { code: "ro", name: "Romanian" },
    { code: "sa", name: "Sanskrit" },
    { code: "sr", name: "Serbian" },
    { code: "sn", name: "Shona" },
    { code: "sd", name: "Sindhi" },
    { code: "si", name: "Sinhala" },
    { code: "sk", name: "Slovak" },
    { code: "sl", name: "Slovenian" },
    { code: "so", name: "Somali" },
    { code: "su", name: "Sundanese" },
    { code: "sw", name: "Swahili" },
    { code: "sv", name: "Swedish" },
    { code: "tg", name: "Tajik" },
    { code: "ta", name: "Tamil" },
    { code: "tt", name: "Tatar" },
    { code: "te", name: "Telugu" },
    { code: "th", name: "Thai" },
    { code: "bo", name: "Tibetan" },
    { code: "tr", name: "Turkish" },
    { code: "tk", name: "Turkmen" },
    { code: "uk", name: "Ukrainian" },
    { code: "ur", name: "Urdu" },
    { code: "uz", name: "Uzbek" },
    { code: "cy", name: "Welsh" },
    { code: "yi", name: "Yiddish" },
    { code: "yo", name: "Yoruba" },
  ];

  // Upload handlers
  const handleFileUpload = async (file: File) => {
    setUploadState(prev => ({ ...prev, isUploading: true, error: null, results: null }));

    const formData = new FormData();
    formData.append("audio", file);
    formData.append("provider_language", providerLang);
    formData.append("patient_language", patientLang);

    try {
      const response = await fetch(`${BACKEND_URL}/upload-recording`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const error = await response.text();
        throw new Error(error);
      }

      const data = await response.json();

      // Smart auto-assign based on language detection:
      // - English speakers -> likely provider or interpreter
      // - Non-English speakers -> likely patient or interpreter
      // But don't assume - let the user confirm
      const autoMappings: Record<string, string> = {};
      const langInfo = data.speaker_language_info || [];

      // Group by language
      const englishSpeakers: string[] = [];
      const nonEnglishSpeakers: string[] = [];

      langInfo.forEach((info: { speaker_id: string; primary_language: string }) => {
        if (info.primary_language === "en") {
          englishSpeakers.push(info.speaker_id);
        } else {
          nonEnglishSpeakers.push(info.speaker_id);
        }
      });

      // Auto-suggest roles but leave as "unassigned" for non-obvious cases
      data.detected_speakers.forEach((speaker: string) => {
        const isEnglish = englishSpeakers.includes(speaker);
        // For 2 speakers: likely provider + patient
        // For 3 speakers: likely provider + interpreter + patient
        // For 4+: don't assume, leave unassigned
        if (data.detected_speakers.length <= 3) {
          const idx = data.detected_speakers.indexOf(speaker);
          if (data.detected_speakers.length === 2) {
            autoMappings[speaker] = idx === 0 ? "provider" : "patient";
          } else if (data.detected_speakers.length === 3) {
            const roles = ["provider", "interpreter", "patient"];
            autoMappings[speaker] = roles[idx];
          }
        } else {
          // 4+ speakers - leave unassigned, user must assign
          autoMappings[speaker] = "unassigned";
        }
      });

      setUploadState(prev => ({
        ...prev,
        isUploading: false,
        uploadId: data.upload_id,
        segments: data.segments,
        detectedSpeakers: data.detected_speakers,
        speakerLanguageInfo: data.speaker_language_info || [],
        roleMappings: autoMappings,
      }));
    } catch (error) {
      setUploadState(prev => ({
        ...prev,
        isUploading: false,
        error: error instanceof Error ? error.message : "Upload failed",
      }));
    }
  };

  const handleAnalyzeRecording = async () => {
    if (!uploadState.uploadId) return;

    // Filter out unassigned speakers
    const assignedMappings = Object.entries(uploadState.roleMappings)
      .filter(([, role]) => role !== "unassigned")
      .map(([speaker_id, role]) => ({ speaker_id, role }));

    if (assignedMappings.length === 0) {
      setUploadState(prev => ({
        ...prev,
        error: "Please assign at least one speaker to a role before analyzing.",
      }));
      return;
    }

    setUploadState(prev => ({ ...prev, isAnalyzing: true, error: null }));

    try {
      const response = await fetch(`${BACKEND_URL}/analyze-recording`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          upload_id: uploadState.uploadId,
          role_mappings: assignedMappings,
          provider_language: providerLang,
          patient_language: patientLang,
        }),
      });

      if (!response.ok) {
        const error = await response.text();
        throw new Error(error);
      }

      const results = await response.json();
      setUploadState(prev => ({
        ...prev,
        isAnalyzing: false,
        results,
      }));
    } catch (error) {
      setUploadState(prev => ({
        ...prev,
        isAnalyzing: false,
        error: error instanceof Error ? error.message : "Analysis failed",
      }));
    }
  };

  const updateRoleMapping = (speakerId: string, role: string) => {
    setUploadState(prev => ({
      ...prev,
      roleMappings: { ...prev.roleMappings, [speakerId]: role },
    }));
  };

  const resetUpload = () => {
    setUploadState({
      isUploading: false,
      isAnalyzing: false,
      uploadId: null,
      segments: [],
      detectedSpeakers: [],
      speakerLanguageInfo: [],
      roleMappings: {},
      results: null,
      error: null,
    });
  };

  // Merge two speakers into one
  const mergeSpeakers = (keepSpeaker: string, removeSpeaker: string) => {
    setUploadState(prev => ({
      ...prev,
      segments: prev.segments.map(seg =>
        seg.speaker_id === removeSpeaker
          ? { ...seg, speaker_id: keepSpeaker }
          : seg
      ),
      detectedSpeakers: prev.detectedSpeakers.filter(s => s !== removeSpeaker),
      speakerLanguageInfo: prev.speakerLanguageInfo.filter(s => s.speaker_id !== removeSpeaker),
      roleMappings: Object.fromEntries(
        Object.entries(prev.roleMappings).filter(([k]) => k !== removeSpeaker)
      ),
    }));
  };

  // Get language info for a speaker
  const getSpeakerLangInfo = (speakerId: string) => {
    return uploadState.speakerLanguageInfo.find(s => s.speaker_id === speakerId);
  };

  // Get language name from code
  const getLangName = (code: string) => {
    const lang = LANGUAGES.find(l => l.code === code);
    return lang?.name || code;
  };

  return (
    <main className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 text-gray-100">
      {/* Header */}
      <header className="sticky top-0 z-50 bg-gray-900/95 backdrop-blur border-b border-gray-700 px-6 py-4">
        <div className="flex items-center justify-between max-w-7xl mx-auto">
          <div className="flex items-center gap-4">
            <h1 className="text-2xl font-bold text-white">SARASVATI</h1>
            <div className="flex items-center gap-4">
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
              {isAnalyzing && (
                <div className="flex items-center gap-2 px-3 py-1 bg-yellow-900/50 border border-yellow-700 rounded-full animate-pulse">
                  <div className="w-2 h-2 bg-yellow-400 rounded-full animate-ping" />
                  <span className="text-xs text-yellow-300 font-medium">Analyzing interpretation...</span>
                </div>
              )}
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
              <button
                onClick={() => setActiveTab("upload")}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                  activeTab === "upload"
                    ? "bg-purple-600 text-white"
                    : "text-gray-400 hover:text-white"
                }`}
              >
                Upload
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
          <div className="space-y-4">
            {/* Error Summary Bar */}
            {activeGroups.length > 0 ? (
              <details className="bg-red-950/50 border border-red-800 rounded-lg">
                <summary className="px-4 py-3 cursor-pointer">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <AlertTriangle className="text-red-400" size={18} />
                      <span className="font-medium text-red-300">
                        {activeGroups.length} interpretation{activeGroups.length > 1 ? "s" : ""} flagged
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-xs">
                      {errorSummary.omissions > 0 && (
                        <span className="px-2 py-1 bg-orange-900/50 text-orange-300 rounded">
                          {errorSummary.omissions} omission{errorSummary.omissions > 1 ? "s" : ""}
                        </span>
                      )}
                      {errorSummary.additions > 0 && (
                        <span className="px-2 py-1 bg-purple-900/50 text-purple-300 rounded">
                          {errorSummary.additions} addition{errorSummary.additions > 1 ? "s" : ""}
                        </span>
                      )}
                      {errorSummary.distortions > 0 && (
                        <span className="px-2 py-1 bg-yellow-900/50 text-yellow-300 rounded">
                          {errorSummary.distortions} distortion{errorSummary.distortions > 1 ? "s" : ""}
                        </span>
                      )}
                      <span className="text-red-400">▼</span>
                    </div>
                  </div>
                </summary>
                <div className="px-4 pb-4 pt-2 border-t border-red-800/50 mt-2">
                  <p className="text-xs text-gray-400 mb-2">Click on a flagged interpreter statement below to see details</p>
                </div>
              </details>
            ) : (
              <div className="flex items-center gap-2 px-4 py-3 bg-green-950/50 border border-green-800 rounded-lg">
                <CheckCircle className="text-green-400" size={18} />
                <span className="font-medium text-green-300">All clear - no interpretation issues detected</span>
              </div>
            )}

            {/* Main Transcript View - Full style like Details page */}
            <div className="bg-gray-900/50 rounded-lg p-4 space-y-3" style={{ maxHeight: "calc(100vh - 320px)", overflowY: "auto" }}>
              {sessionState.transcripts.length === 0 ? (
                <div className="text-center py-12">
                  <p className="text-gray-500 text-lg">Waiting for speech...</p>
                  <p className="text-gray-600 text-sm mt-2">Select a role below and click Record to start</p>
                </div>
              ) : (
                sessionState.transcripts.map((t, idx) => {
                  // ONLY flag interpreter statements - that's what we're evaluating
                  const isInterpreter = t.role === "interpreter";
                  const errorGroup = isInterpreter ? getErrorsForInterpreter(t.text || "") : null;
                  const hasError = errorGroup !== null;

                  return (
                    <div
                      key={idx}
                      onClick={() => hasError && setSelectedErrorDetail(errorGroup)}
                      className={`p-3 rounded-lg transition-colors ${
                        hasError
                          ? "bg-red-950/30 border-l-4 border-l-red-500 cursor-pointer hover:bg-red-950/50"
                          : "bg-gray-800/50"
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-xs px-2 py-0.5 rounded capitalize font-medium ${
                          t.role === "provider" ? "bg-blue-700" :
                          t.role === "interpreter" ? "bg-purple-700" : "bg-green-700"
                        }`}>
                          {t.role}
                        </span>
                        {t.detected_language && (
                          <span className="text-xs text-gray-500">[{t.detected_language}]</span>
                        )}
                        {hasError && (
                          <span className="text-xs text-red-400 ml-auto flex items-center gap-1">
                            ⚠ {errorGroup.issues.length} issue{errorGroup.issues.length > 1 ? "s" : ""}
                            <span className="text-gray-500">· click for details</span>
                          </span>
                        )}
                      </div>
                      <p className="text-gray-200">{t.text}</p>
                      {t.english_translation && t.english_translation !== t.text && (
                        <p className="text-green-400/80 text-sm mt-1">
                          → English: {t.english_translation}
                        </p>
                      )}
                    </div>
                  );
                })
              )}
            </div>

            {/* Error Detail Modal */}
            {selectedErrorDetail && (
              <div
                className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
                onClick={() => setSelectedErrorDetail(null)}
              >
                <div
                  className="bg-gray-800 rounded-xl max-w-2xl w-full max-h-[80vh] overflow-y-auto"
                  onClick={e => e.stopPropagation()}
                >
                  <div className="sticky top-0 bg-gray-800 border-b border-gray-700 p-4 flex items-center justify-between">
                    <h3 className="text-lg font-semibold text-white">Interpretation Issues</h3>
                    <button
                      onClick={() => setSelectedErrorDetail(null)}
                      className="text-gray-400 hover:text-white"
                    >
                      <X size={24} />
                    </button>
                  </div>

                  <div className="p-4 space-y-4">
                    {/* Clinical Significance Score */}
                    <div className="flex items-center justify-between bg-gray-900/50 rounded-lg p-3">
                      <div>
                        <div className="text-xs text-gray-400">Clinical Significance</div>
                        <div className={`text-2xl font-bold ${getSignificanceColor(selectedErrorDetail.avgConfidence)}`}>
                          {selectedErrorDetail.avgConfidence}%
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-xs text-gray-400">Severity Level</div>
                        <div className={`text-lg font-semibold ${
                          selectedErrorDetail.highestSeverity === "critical" ? "text-red-400" :
                          selectedErrorDetail.highestSeverity === "high" ? "text-orange-400" :
                          selectedErrorDetail.highestSeverity === "medium" ? "text-yellow-400" :
                          "text-blue-400"
                        }`}>
                          {selectedErrorDetail.highestSeverity.toUpperCase()}
                        </div>
                      </div>
                    </div>

                    {/* What was said */}
                    <div className="space-y-2">
                      {selectedErrorDetail.sourceQuote && (
                        <div className="p-3 bg-blue-950/30 rounded-lg">
                          <div className="text-xs text-blue-400 mb-1">Original (Provider/Patient said):</div>
                          <p className="text-gray-200">"{selectedErrorDetail.sourceQuote}"</p>
                        </div>
                      )}
                      {selectedErrorDetail.interpreterQuote && (
                        <div className="p-3 bg-purple-950/30 rounded-lg">
                          <div className="text-xs text-purple-400 mb-1">Interpreter said:</div>
                          <p className="text-gray-200">"{selectedErrorDetail.interpreterQuote}"</p>
                        </div>
                      )}
                      {selectedErrorDetail.idealInterpretation && (
                        <div className="p-3 bg-green-950/30 rounded-lg border border-green-800">
                          <div className="text-xs text-green-400 mb-1">✓ Ideal Interpretation:</div>
                          <p className="text-gray-200">"{selectedErrorDetail.idealInterpretation}"</p>
                        </div>
                      )}
                    </div>

                    {/* Issues found */}
                    <div>
                      <h4 className="text-sm font-medium text-gray-400 mb-2">
                        Issues Found ({selectedErrorDetail.issues.length})
                      </h4>
                      <div className="space-y-2">
                        {selectedErrorDetail.issues.map((issue, i) => {
                          const badge = getSeverityBadge(issue.severity);
                          return (
                            <div key={i} className={`p-3 rounded-lg ${getCardStyle(issue.severity)}`}>
                              <div className="flex items-center justify-between mb-2">
                                <div className="flex items-center gap-2">
                                  <span className={`text-xs px-2 py-0.5 rounded font-bold ${badge.bg}`}>
                                    {badge.text}
                                  </span>
                                  <span className="text-sm font-medium text-white">
                                    {formatErrorType(issue.type)}
                                  </span>
                                </div>
                                <span className={`text-xs font-medium ${getSignificanceColor(issue.confidence)}`}>
                                  {issue.confidence}% confidence
                                </span>
                              </div>
                              <p className="text-sm text-gray-300">{issue.description}</p>
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    {/* Tribunal Summary/Conclusion */}
                    {selectedErrorDetail.arbiterSummary && (
                      <div className="bg-gray-900/70 rounded-lg p-3 border border-gray-700">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="text-lg">⚖️</span>
                          <span className="text-sm font-medium text-gray-300">Tribunal Conclusion</span>
                        </div>
                        <p className="text-sm text-gray-400 leading-relaxed">
                          {selectedErrorDetail.arbiterSummary}
                        </p>
                      </div>
                    )}

                    {/* Dismiss button */}
                    <div className="flex gap-2 pt-2">
                      <button
                        onClick={() => {
                          handleDismissGroup(selectedErrorDetail);
                          setSelectedErrorDetail(null);
                        }}
                        className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm"
                      >
                        Dismiss This Issue
                      </button>
                      <button
                        onClick={() => setSelectedErrorDetail(null)}
                        className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm"
                      >
                        Close
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : activeTab === "details" ? (
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
                      <p className="text-gray-200">{t.text}</p>
                      {t.english_translation && t.english_translation !== t.text && (
                        <p className="text-green-400/80 text-sm mt-1">
                          → English: {t.english_translation}
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

            {/* All Error Groups */}
            <div>
              <h3 className="text-lg font-semibold mb-3">All Detected Issues ({groupedErrors.length} utterances, {clinicalErrors.length} total findings)</h3>
              <div className="bg-gray-900/50 rounded-lg p-4 max-h-96 overflow-y-auto space-y-4">
                {groupedErrors.length === 0 ? (
                  <p className="text-gray-500 italic">No errors detected</p>
                ) : (
                  groupedErrors.map((group, idx) => {
                    const badge = getSeverityBadge(group.highestSeverity);
                    return (
                      <div key={idx} className={`p-4 rounded-lg ${getCardStyle(group.highestSeverity)}`}>
                        {/* Header with severity and clinical significance */}
                        <div className="flex items-center justify-between mb-3">
                          <div className="flex items-center gap-2">
                            <span className={`text-xs px-2 py-0.5 rounded font-bold ${badge.bg}`}>
                              {badge.text}
                            </span>
                            <span className="text-gray-400 text-xs">
                              {group.issues.length} finding{group.issues.length > 1 ? "s" : ""}
                            </span>
                          </div>
                          <div className={`text-sm font-medium ${getSignificanceColor(group.avgConfidence)}`}>
                            {group.avgConfidence}% significance
                          </div>
                        </div>

                        {/* Quotes */}
                        {group.sourceQuote && (
                          <p className="text-sm text-gray-300 mb-1">
                            <span className="text-blue-400">Provider:</span> "{group.sourceQuote}"
                          </p>
                        )}
                        {group.interpreterQuote && (
                          <p className="text-sm text-gray-300 mb-2">
                            <span className="text-purple-400">Interpreter:</span> "{group.interpreterQuote}"
                          </p>
                        )}
                        {group.idealInterpretation && (
                          <p className="text-sm text-green-400 mb-2 bg-green-950/30 p-2 rounded">
                            <span className="font-medium">✓ Should say:</span> "{group.idealInterpretation}"
                          </p>
                        )}

                        {/* Issue list with confidence */}
                        <div className="text-xs text-gray-400 space-y-1.5 mt-2 bg-gray-900/50 p-2 rounded">
                          {group.issues.map((issue, i) => (
                            <div key={i} className="flex items-start justify-between gap-2">
                              <span>• <span className="text-gray-300">{formatErrorType(issue.type)}:</span> {issue.description}</span>
                              <span className={`shrink-0 ${getSignificanceColor(issue.confidence)}`}>
                                {issue.confidence}%
                              </span>
                            </div>
                          ))}
                        </div>

                        {/* Arbiter summary */}
                        {group.arbiterSummary && (
                          <div className="mt-3 pt-3 border-t border-gray-700">
                            <div className="flex items-center gap-2 mb-1">
                              <span>⚖️</span>
                              <span className="text-xs font-medium text-gray-400">Tribunal Conclusion:</span>
                            </div>
                            <p className="text-xs text-gray-500 leading-relaxed">
                              {group.arbiterSummary}
                            </p>
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        ) : (
          /* ================ UPLOAD TAB ================ */
          <div className="space-y-6">
            <div className="max-w-4xl mx-auto">
              {/* Language Settings for Upload */}
              <div className="bg-gray-800/50 rounded-lg p-4 mb-6">
                <h3 className="text-lg font-semibold mb-3">Recording Settings</h3>
                <div className="flex gap-4">
                  <div className="flex-1">
                    <label className="block text-sm text-gray-400 mb-1">Provider Language</label>
                    <select
                      value={providerLang}
                      onChange={(e) => setProviderLang(e.target.value)}
                      className="w-full px-3 py-2 bg-gray-700 rounded-lg text-white"
                    >
                      {LANGUAGES.filter(l => l.code !== "auto").map(lang => (
                        <option key={lang.code} value={lang.code}>{lang.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex-1">
                    <label className="block text-sm text-gray-400 mb-1">Patient Language</label>
                    <select
                      value={patientLang}
                      onChange={(e) => setPatientLang(e.target.value)}
                      className="w-full px-3 py-2 bg-gray-700 rounded-lg text-white"
                    >
                      {LANGUAGES.filter(l => l.code !== "auto").map(lang => (
                        <option key={lang.code} value={lang.code}>{lang.name}</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>

              {/* Upload Area */}
              {!uploadState.uploadId && (
                <div
                  className="border-2 border-dashed border-gray-600 rounded-xl p-12 text-center hover:border-purple-500 transition-colors cursor-pointer"
                  onClick={() => document.getElementById("audio-upload")?.click()}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault();
                    const file = e.dataTransfer.files[0];
                    if (file) handleFileUpload(file);
                  }}
                >
                  <input
                    id="audio-upload"
                    type="file"
                    accept="audio/*"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) handleFileUpload(file);
                    }}
                  />
                  {uploadState.isUploading ? (
                    <div className="flex flex-col items-center gap-4">
                      <div className="w-12 h-12 border-4 border-purple-500 border-t-transparent rounded-full animate-spin" />
                      <p className="text-gray-400">Transcribing audio...</p>
                    </div>
                  ) : (
                    <>
                      <div className="w-16 h-16 mx-auto mb-4 bg-gray-700 rounded-full flex items-center justify-center">
                        <span className="text-3xl">🎤</span>
                      </div>
                      <p className="text-xl font-medium text-gray-300 mb-2">
                        Upload Recording
                      </p>
                      <p className="text-gray-500">
                        Drag and drop an audio file, or click to browse
                      </p>
                      <p className="text-gray-600 text-sm mt-2">
                        Supports MP3, WAV, M4A, WEBM, and other audio formats
                      </p>
                    </>
                  )}
                </div>
              )}

              {/* Error Display */}
              {uploadState.error && (
                <div className="bg-red-900/50 border border-red-700 rounded-lg p-4 mt-4">
                  <p className="text-red-400">{uploadState.error}</p>
                  <button
                    onClick={resetUpload}
                    className="mt-2 text-sm text-red-300 hover:text-white"
                  >
                    Try again
                  </button>
                </div>
              )}

              {/* Speaker Assignment */}
              {uploadState.uploadId && !uploadState.results && (
                <div className="space-y-6">
                  <div className="bg-gray-800/50 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-lg font-semibold">Assign Speakers</h3>
                      <button
                        onClick={resetUpload}
                        className="text-sm text-gray-400 hover:text-white"
                      >
                        ← Upload different file
                      </button>
                    </div>
                    <p className="text-gray-400 text-sm mb-4">
                      We detected {uploadState.detectedSpeakers.length} speaker{uploadState.detectedSpeakers.length !== 1 ? "s" : ""}. Assign each to a role:
                    </p>

                    {/* Merge suggestion for speakers with same language */}
                    {uploadState.speakerLanguageInfo.length > 1 && (() => {
                      const langGroups: Record<string, string[]> = {};
                      uploadState.speakerLanguageInfo.forEach(info => {
                        if (!langGroups[info.primary_language]) langGroups[info.primary_language] = [];
                        langGroups[info.primary_language].push(info.speaker_id);
                      });
                      const mergeable = Object.entries(langGroups).filter(([, speakers]) => speakers.length > 1);
                      if (mergeable.length === 0) return null;
                      return (
                        <div className="bg-yellow-900/30 border border-yellow-700 rounded-lg p-3 mb-4">
                          <p className="text-yellow-300 text-sm font-medium mb-2">💡 Same-language speakers detected:</p>
                          {mergeable.map(([lang, speakers]) => (
                            <div key={lang} className="flex items-center gap-2 text-sm text-gray-300">
                              <span>{getLangName(lang)}:</span>
                              <span>{speakers.join(", ")}</span>
                              <button
                                onClick={() => mergeSpeakers(speakers[0], speakers[1])}
                                className="ml-2 px-2 py-1 bg-yellow-600 hover:bg-yellow-700 rounded text-xs"
                              >
                                Merge
                              </button>
                            </div>
                          ))}
                        </div>
                      );
                    })()}

                    <div className="grid gap-3">
                      {uploadState.detectedSpeakers.map((speaker) => {
                        const langInfo = getSpeakerLangInfo(speaker);
                        const currentRole = uploadState.roleMappings[speaker] || "unassigned";
                        return (
                          <div key={speaker} className="bg-gray-900/50 p-3 rounded-lg">
                            <div className="flex items-center gap-4 mb-2">
                              <span className="font-medium text-gray-300 w-24">{speaker.replace("_", " ").toUpperCase()}</span>
                              {langInfo && (
                                <span className="text-xs px-2 py-1 bg-gray-700 rounded text-gray-400">
                                  {getLangName(langInfo.primary_language)} · {langInfo.segment_count} seg
                                </span>
                              )}
                              <span className="text-gray-500 text-xs ml-auto">
                                {langInfo?.sample_text || ""}
                              </span>
                            </div>
                            <div className="flex gap-2 flex-wrap">
                              {["provider", "interpreter", "patient", "unassigned"].map((role) => (
                                <button
                                  key={role}
                                  onClick={() => updateRoleMapping(speaker, role)}
                                  className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                                    currentRole === role
                                      ? role === "provider" ? "bg-blue-600 text-white" :
                                        role === "interpreter" ? "bg-purple-600 text-white" :
                                        role === "patient" ? "bg-green-600 text-white" :
                                        "bg-gray-600 text-white"
                                      : "bg-gray-700 text-gray-300 hover:bg-gray-600"
                                  }`}
                                >
                                  {role === "provider" ? "🩺 Provider" :
                                   role === "interpreter" ? "🗣️ Interpreter" :
                                   role === "patient" ? "👤 Patient" :
                                   "❓ Skip"}
                                </button>
                              ))}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Transcript Preview */}
                  <div className="bg-gray-800/50 rounded-lg p-4">
                    <h3 className="text-lg font-semibold mb-4">Transcript Preview</h3>
                    <div className="max-h-64 overflow-y-auto space-y-2">
                      {uploadState.segments.map((seg) => {
                        const role = uploadState.roleMappings[seg.speaker_id] || "unknown";
                        return (
                          <div key={seg.segment_id} className="p-2 bg-gray-900/50 rounded">
                            <div className="flex items-center gap-2 mb-1">
                              <span className={`text-xs px-2 py-0.5 rounded ${
                                role === "provider" ? "bg-blue-700" :
                                role === "interpreter" ? "bg-purple-700" :
                                role === "patient" ? "bg-green-700" : "bg-gray-600"
                              }`}>
                                {role}
                              </span>
                              <span className="text-xs text-gray-500">
                                {seg.start_time.toFixed(1)}s - {seg.end_time.toFixed(1)}s
                              </span>
                            </div>
                            <p className="text-sm text-gray-300">{seg.text}</p>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Analyze Button */}
                  <button
                    onClick={handleAnalyzeRecording}
                    disabled={uploadState.isAnalyzing}
                    className="w-full py-4 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-xl font-semibold text-lg transition-colors"
                  >
                    {uploadState.isAnalyzing ? (
                      <span className="flex items-center justify-center gap-2">
                        <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                        Analyzing with Tribunal...
                      </span>
                    ) : (
                      "⚖️ Analyze Interpretation"
                    )}
                  </button>
                </div>
              )}

              {/* Results */}
              {uploadState.results && (
                <div className="space-y-6">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xl font-semibold">Analysis Results</h3>
                    <button
                      onClick={resetUpload}
                      className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm"
                    >
                      Analyze Another Recording
                    </button>
                  </div>

                  {/* Summary */}
                  <div className="grid grid-cols-3 gap-4">
                    <div className="bg-gray-800/50 rounded-lg p-4 text-center">
                      <div className="text-3xl font-bold text-blue-400">
                        {uploadState.results.transcripts.length}
                      </div>
                      <div className="text-sm text-gray-400">Segments</div>
                    </div>
                    <div className="bg-gray-800/50 rounded-lg p-4 text-center">
                      <div className="text-3xl font-bold text-purple-400">
                        {uploadState.results.verdicts.length}
                      </div>
                      <div className="text-sm text-gray-400">Evaluations</div>
                    </div>
                    <div className="bg-gray-800/50 rounded-lg p-4 text-center">
                      <div className={`text-3xl font-bold ${
                        uploadState.results.errors.length > 0 ? "text-red-400" : "text-green-400"
                      }`}>
                        {uploadState.results.errors.length}
                      </div>
                      <div className="text-sm text-gray-400">Issues Found</div>
                    </div>
                  </div>

                  {/* Errors List */}
                  {uploadState.results.errors.length > 0 && (
                    <div className="bg-gray-800/50 rounded-lg p-4">
                      <h4 className="font-semibold mb-3">Detected Issues</h4>
                      <div className="space-y-3">
                        {(uploadState.results.errors as Array<{
                          error_type?: string;
                          severity?: string;
                          description?: string;
                        }>).map((err, idx) => (
                          <div key={idx} className={`p-3 rounded-lg ${getCardStyle(err.severity || "medium")}`}>
                            <div className="flex items-center gap-2 mb-1">
                              <span className={`text-xs px-2 py-0.5 rounded font-bold ${getSeverityBadge(err.severity || "medium").bg}`}>
                                {getSeverityBadge(err.severity || "medium").text}
                              </span>
                              <span className="text-sm font-medium text-white">
                                {formatErrorType(err.error_type || "unknown")}
                              </span>
                            </div>
                            <p className="text-sm text-gray-300">{err.description}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {uploadState.results.errors.length === 0 && (
                    <div className="bg-green-900/30 border border-green-700 rounded-lg p-6 text-center">
                      <div className="text-4xl mb-2">✅</div>
                      <p className="text-green-400 font-medium">No interpretation errors detected!</p>
                      <p className="text-gray-400 text-sm mt-1">The interpretation appears to be accurate.</p>
                    </div>
                  )}
                </div>
              )}
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
