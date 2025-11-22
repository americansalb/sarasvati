/**
 * SARASVATI Frontend Types
 * =========================
 * TypeScript definitions for the Trisul Protocol frontend.
 * These mirror the backend Python TypedDict schemas.
 */

export type StreamRole = "provider" | "interpreter" | "patient";

export type ErrorSeverity = "critical" | "high" | "medium" | "low";

export interface TranscriptSegment {
  role: StreamRole;
  text: string;
  timestamp: number;
  duration: number;
  confidence: number;
  is_final: boolean;
  speaker_id?: string;
}

export interface MedicalEntity {
  entity_type: string; // "drug", "dosage", "frequency", "condition", "instruction"
  text: string;
  normalized: string;
  confidence: number;
  timestamp: number;
  context: string;
}

export interface AlignmentMatch {
  provider_segment: TranscriptSegment;
  interpreter_segment: TranscriptSegment | null;
  similarity_score: number;
  time_delta: number;
  is_matched: boolean;
  dtw_distance: number;
}

export interface ClinicalError {
  error_id: string;
  severity: ErrorSeverity;
  error_type: string; // "omission", "negation_mismatch", "dosage_error", etc.
  provider_entity: MedicalEntity | null;
  interpreter_entity: MedicalEntity | null;
  description: string;
  arbiter_reasoning: string;
  confidence: number;
  detected_at: string; // ISO timestamp
  alignment_info: AlignmentMatch | null; // null for system errors
  is_system_error: boolean; // true for infrastructure failures, false for clinical errors
}

export interface AgentDebateResult {
  extractor_entities: MedicalEntity[];
  monitor_findings: string[];
  arbiter_decision: string;
  detected_errors: ClinicalError[];
  processing_time_ms: number;
}

// WebSocket Event Types
export interface WSEventTranscript {
  type: "transcript";
  data: TranscriptSegment;
}

export interface WSEventError {
  type: "error";
  data: ClinicalError;
}

export interface WSEventAlignment {
  type: "alignment";
  data: AlignmentMatch;
}

export interface WSEventDebate {
  type: "debate";
  data: AgentDebateResult;
}

export interface WSEventSession {
  type: "session";
  data: {
    session_id: string;
    status: "started" | "ended";
    stats?: {
      segments_processed: number;
      alignments_found: number;
      errors_detected: number;
    };
  };
}

export type WSEvent =
  | WSEventTranscript
  | WSEventError
  | WSEventAlignment
  | WSEventDebate
  | WSEventSession;

// UI State Types
export interface AudioTrackState {
  role: StreamRole;
  isActive: boolean;
  volume: number;
  isMuted: boolean;
  waveformData: Float32Array | null;
}

export interface TribunalVerdict {
  confidence: number;
  severity: string;
  num_issues: number;
  arbiter_decision: string;
  monitor_findings: string[];
  errors: Array<{
    severity: string;
    error_type: string;
    description: string;
  }>;
}

export interface SessionState {
  sessionId: string | null;
  isActive: boolean;
  startTime: Date | null;
  errors: ClinicalError[];
  transcripts: TranscriptSegment[];
  alignments: AlignmentMatch[];
  verdicts: TribunalVerdict[];
  debugInfo: AgentDebateResult | null;
}

export interface ConnectionState {
  livekitConnected: boolean;
  websocketConnected: boolean;
  error: string | null;
  roomName: string | null;
}

// Simulation Mode Types
export interface SimulationConfig {
  enabled: boolean;
  providerAudioUrl: string;
  interpreterAudioUrl: string;
  patientAudioUrl: string;
  autoPlay: boolean;
}
