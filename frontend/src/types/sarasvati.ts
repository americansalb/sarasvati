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
  segment_id?: string;  // Unique ID for error-transcript mapping
  detected_language?: string;
  english_translation?: string;  // English translation for non-English text (for QA monitors)
  transliteration?: string;  // Romanized version of non-Latin scripts
}

export interface MedicalEntity {
  entity_type: string; // "drug", "dosage", "frequency", "condition", "instruction"
  text: string;
  normalized: string;
  confidence: number;
  timestamp: number;
  context: string;
}

// PHASE 3: Alignment alternative for transparency
export interface AlignmentAlternative {
  interpreter_segment: TranscriptSegment;
  similarity_score: number;
  combined_score: number;
  time_delta: number;
  rejection_reason: string;
}

export interface AlignmentMatch {
  provider_segment: TranscriptSegment;
  interpreter_segment: TranscriptSegment | null;
  similarity_score: number;
  time_delta: number;
  is_matched: boolean;
  dtw_distance: number;
  // PHASE 3: Transparency - show alternatives that were considered
  alternatives_considered?: AlignmentAlternative[];
}

export interface ClinicalError {
  error_id: string;
  severity: ErrorSeverity;
  error_type: string; // "omission", "fabrication_medical", "dosage_error", etc.
  provider_entity: MedicalEntity | null;
  interpreter_entity: MedicalEntity | null;
  description: string;
  arbiter_reasoning: string;
  confidence: number;
  detected_at: string; // ISO timestamp
  alignment_info: AlignmentMatch | null; // null for system errors
  is_system_error: boolean; // true for infrastructure failures, false for clinical errors
  case_type?: string; // "aligned_outbound", "aligned_inbound", "fabrication", "omission_outbound", "omission_inbound"
  // Interpreter-centric tribunal context
  source_role?: StreamRole; // Who we're protecting (provider/patient)
  interpreter_quote?: string; // Exact text interpreter said
  source_quote?: string; // Exact text from source (provider/patient)
  ideal_interpretation?: string; // What interpreter should have said
  // PHASE 3: Transparency - which entities triggered this error
  triggering_entities?: MedicalEntity[];
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
  debate_logs?: DebateLogs | null;
  has_debate_logs?: boolean;
}

// PHASE 2: Challenge-response debate structures
export interface Challenge {
  from_agent: string;
  to_agent: string;
  round_num: number;
  challenge_text: string;
  evidence_cited: string[];
}

export interface Rebuttal {
  from_agent: string;
  to_agent: string;
  round_num: number;
  rebuttal_text: string;
  position_changed: boolean;
  new_position: string | null;
}

export interface DissentingOpinion {
  agent_name: string;
  position: string;
  reasoning: string;
  evidence: string[];
  confidence: number;
}

export type ConvergenceType =
  | "full_consensus"      // All 3 agree
  | "strong_majority"     // 2 agree, 1 weak dissent
  | "structured_dissent"  // Clear disagreement, flag for human
  | "early_consensus";    // Agreed in <3 rounds

// Visible debate log types - shows the actual back-and-forth tribunal debate
export interface DebateTurn {
  round: number;
  agent: string;
  model: string;
  provider: string;
  statement: string;
  position: string;
  reasoning: string;
  agrees_with: string[];
  disagrees_with: string[];
  changed_mind: boolean;
  timestamp: string;
}

export interface DebateLogEntry {
  tribunal_type: string; // "translation" or "error"
  input_text: string;
  turns: DebateTurn[];
  final_consensus: string | null;
  consensus_reached: boolean;
  rounds_taken: number;
  duration_ms: number | null;
  // PHASE 2: Challenge-response and convergence tracking
  challenges?: Challenge[];
  rebuttals?: Rebuttal[];
  convergence_type?: ConvergenceType;
  dissenting_opinions?: DissentingOpinion[];
  consensus_confidence?: number;  // 0.0-1.0
  flagged_for_human_review?: boolean;
}

// PHASE 3: Frontend-optimized debate format
export interface DebateRound {
  round_number: number;
  turns: DebateTurn[];
  consensus_emerging: boolean;
  position_changes: number;
}

export interface AgentSummary {
  name: string;
  model: string;
  provider: string;
  position_changes: number;
  final_position: string;
  rounds_participated: number;
}

export interface DebateFlowEvent {
  type: "statement" | "position_change";
  round: number;
  agent: string;
  content: string;
  position: string;
  timestamp: string;
  highlight?: boolean;
}

export interface FrontendDebateLog {
  tribunal_type: string;
  input_text: string;
  rounds: DebateRound[];
  final_consensus: string | null;
  consensus_reached: boolean;
  rounds_taken: number;
  duration_ms: number | null;
  challenges: Challenge[];
  rebuttals: Rebuttal[];
  convergence_type?: ConvergenceType;
  dissenting_opinions: DissentingOpinion[];
  consensus_confidence: number;
  flagged_for_human_review: boolean;
  agent_summary: Record<string, AgentSummary>;
  debate_flow: DebateFlowEvent[];
}

export interface DebateLogs {
  source_translation: DebateLogEntry | null;
  interpreter_translation: DebateLogEntry | null;
  error_evaluation: DebateLogEntry | null;
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
  debateLogs: DebateLogs | null; // Visible debate logs from two-tribunal architecture
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

// ═══════════════════════════════════════════════════════════════════════════════
// PHASE 3: SESSION ANALYTICS & TRANSPARENCY
// ═══════════════════════════════════════════════════════════════════════════════

export interface ConsensusMetrics {
  full_consensus_count: number;       // 3/3 agreements
  strong_majority_count: number;      // 2/3 agreements
  structured_dissent_count: number;   // Flagged for human review
  total_debates: number;
  avg_rounds_to_consensus: number;
}

export interface ProviderPerformance {
  provider_name: string;
  total_positions: number;
  times_in_majority: number;
  times_in_minority: number;
  avg_confidence: number;
  error_detection_rate: number;  // % of errors this provider detected
}

export interface SessionAnalytics {
  consensus_metrics: ConsensusMetrics;
  provider_performance: Record<string, ProviderPerformance>;  // {provider_name: performance}
  error_concentration: Record<string, number>;  // {time_bucket: error_count}
  debate_duration_avg_ms: number;
  total_api_calls: number;
  estimated_cost_usd: number;
}
