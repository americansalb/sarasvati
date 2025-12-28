"""
SARASVATI State Management
==========================
TypedDict definitions for LangGraph state management in the Trisul Protocol.

This module defines the stateful processing state that flows through the
cyclic graph: ingest -> align -> verify -> report.
"""

from typing import TypedDict, List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class StreamRole(str, Enum):
    """Audio stream roles in the Trisul Protocol."""
    PROVIDER = "provider"
    INTERPRETER = "interpreter"
    PATIENT = "patient"


class ErrorSeverity(str, Enum):
    """Severity levels for detected clinical errors."""
    CRITICAL = "critical"      # Negation, dosage errors, omitted critical info
    HIGH = "high"              # Missing key medical entities
    MEDIUM = "medium"          # Partial omissions
    LOW = "low"                # Minor linguistic variations


class TribunalCaseType(str, Enum):
    """
    Type of tribunal case - determines review context and prompts.

    Bidirectional flows:
    - OUTBOUND: Provider → Interpreter → Patient (doctor-to-patient leg)
    - INBOUND: Patient → Interpreter → Provider (patient-to-doctor leg)
    """
    ALIGNED_OUTBOUND = "aligned_outbound"      # Provider → Interpreter matched
    ALIGNED_INBOUND = "aligned_inbound"        # Patient → Interpreter matched
    OMISSION_OUTBOUND = "omission_outbound"    # Provider spoke, interpreter silent
    OMISSION_INBOUND = "omission_inbound"      # Patient spoke, interpreter silent
    FABRICATION = "fabrication"                # Interpreter spoke without prompt


class MedicalEntity(TypedDict):
    """Extracted medical entity from clinical speech."""
    entity_type: str           # "drug", "dosage", "frequency", "condition", "instruction"
    text: str                  # Raw extracted text
    normalized: str            # Normalized form (e.g., "500mg" -> "500 milligrams")
    confidence: float          # Extraction confidence [0.0-1.0]
    timestamp: float           # When this entity was spoken (seconds from stream start)
    context: str               # Surrounding sentence for semantic analysis
    embedding: Optional[List[float]]  # Vector embedding for semantic matching


class TranscriptSegment(TypedDict):
    """A segment of transcribed audio from a single stream."""
    role: StreamRole           # Which stream this came from
    text: str                  # Transcribed text (original language/script)
    text_english: Optional[str]  # DEPRECATED: Use text_english_smooth or text_english_literal
    text_english_smooth: Optional[str]   # Smooth, natural English (for provider/patient ground truth)
    text_english_literal: Optional[str]  # Literal, error-preserving English (for interpreter eval)
    timestamp: float           # Start time in stream (seconds)
    duration: float            # Duration of segment (seconds)
    confidence: float          # ASR confidence score
    is_final: bool             # Whether this is a final transcript (not interim)
    speaker_id: Optional[str]  # Optional: speaker identifier from ASR
    segment_id: Optional[str]  # Unique ID for error-transcript mapping
    asr_reliable: Optional[bool]  # False if ASR failed/low confidence/unknown language
    detected_language: Optional[str]  # Language detected by Whisper (for debugging)


class AlignmentMatch(TypedDict):
    """
    Result of DTW/semantic alignment.

    Represents a tribunal case - either aligned, omission, or fabrication.
    Every provider/patient segment and every interpreter segment creates a case.
    """
    provider_segment: Optional[TranscriptSegment]     # None for FABRICATION cases
    interpreter_segment: Optional[TranscriptSegment]  # None for OMISSION cases
    patient_segment: Optional[TranscriptSegment]      # Patient context (optional)
    similarity_score: float    # Raw semantic similarity [0.0-1.0] (cosine distance)
    combined_score: float      # Truth Vector: 0.7*similarity + 0.3*(1-dtw) [0.0-1.0]
    time_delta: float          # Actual delay (interpreter_time - provider_time)
    is_matched: bool           # Whether alignment threshold was met
    dtw_distance: float        # DTW distance metric
    case_type: TribunalCaseType  # Type of tribunal review needed


class ClinicalError(TypedDict):
    """Detected error in interpretation OR system error."""
    error_id: str              # Unique identifier
    severity: ErrorSeverity
    error_type: str            # "omission", "negation_mismatch", "dosage_error", "fabrication_medical", etc.
    provider_entity: Optional[MedicalEntity]     # None for system errors or some fabrications
    interpreter_entity: Optional[MedicalEntity]  # None for omissions or system errors
    description: str           # Human-readable error description
    arbiter_reasoning: str     # Explanation from the Arbiter agent
    confidence: float          # Error detection confidence
    detected_at: datetime
    alignment_info: Optional[AlignmentMatch]  # None for system errors
    is_system_error: bool      # True for infrastructure failures, False for clinical errors
    # Interpreter-centric fields for detailed tribunal context
    source_role: Optional[StreamRole]  # Who we're protecting (provider/patient)
    interpreter_quote: Optional[str]   # Exact text interpreter said
    source_quote: Optional[str]        # Exact text from source (provider/patient)
    ideal_interpretation: Optional[str]  # What interpreter should have said


class BufferEntry(TypedDict):
    """Entry in the Redis FIFO buffer for temporal alignment."""
    segment: TranscriptSegment
    entities: List[MedicalEntity]
    buffered_at: datetime
    is_processed: bool
    alignment_attempts: int    # How many times we've tried to align this


class AgentDebateResult(TypedDict):
    """Result of the adversarial agent debate (Extractor vs Monitor)."""
    extractor_entities: List[MedicalEntity]     # What Node A found
    monitor_findings: List[str]                 # What Node B flagged
    arbiter_decision: str                       # Final verdict
    detected_errors: List[ClinicalError]
    processing_time_ms: float
    debate_log: List[dict]                      # Visible debate transcript


class SarasvatiState(TypedDict):
    """
    Main state object for the LangGraph cyclic processing loop.

    This state flows through the graph nodes:
    1. ingest_node: Receives transcripts, updates buffers
    2. align_node: Performs DTW/semantic matching
    3. extract_node: Node A - extracts medical entities
    4. monitor_node: Node B - checks for omissions
    5. arbiter_node: Node C - makes final decision
    6. report_node: Emits errors to monitoring system
    """

    # ===== Stream Buffers =====
    provider_buffer: List[BufferEntry]         # FIFO buffer for provider stream
    interpreter_buffer: List[BufferEntry]      # FIFO buffer for interpreter stream
    patient_buffer: List[BufferEntry]          # FIFO buffer for patient stream

    # ===== Current Processing Context =====
    current_provider_segment: Optional[TranscriptSegment]
    current_interpreter_segment: Optional[TranscriptSegment]
    current_alignment: Optional[AlignmentMatch]

    # ===== Extracted Data =====
    pending_entities: List[MedicalEntity]      # Entities waiting for alignment
    matched_pairs: List[AlignmentMatch]        # Successfully aligned segments

    # ===== Error Tracking =====
    detected_errors: List[ClinicalError]
    error_flags: Dict[str, bool]               # Quick lookup for active error states

    # ===== Agent State =====
    last_debate_result: Optional[AgentDebateResult]

    # ===== Configuration & Metadata =====
    session_id: str                            # Unique session identifier
    session_start: datetime
    processing_stats: Dict[str, Any]           # Performance metrics

    # ===== Control Flags =====
    is_active: bool                            # Whether processing is active
    should_emit_report: bool                   # Flag to trigger report emission
    buffer_size_limit: int                     # Max buffer size before forced processing
    alignment_window_seconds: float            # Time window for semantic search (default: 30s)
    last_verified_count: int                   # Count of matched_pairs last verified (for cycle control)

    # ===== Redis Keys =====
    redis_buffer_key: str                      # Key for Redis FIFO buffer
    redis_session_key: str                     # Key for session metadata


class GraphConfig(TypedDict):
    """Configuration for the LangGraph execution."""
    max_buffer_size: int                       # Maximum entries in buffer before processing
    alignment_threshold: float                 # Minimum similarity score to consider a match
    alignment_window_seconds: float            # Time window for searching alignments
    debounce_ms: int                          # Debounce time for rapid transcript updates
    enable_negation_check: bool                # Enable strict negation detection
    # Independent Tribunal: 3 diverse models on Groq
    groq_model_extractor: str                  # Node A: llama-3.1-8b-instant (Meta - Fast/Structured)
    groq_model_monitor: str                    # Node B: llama3-8b-8192 (Meta - Different for diversity)
    groq_model_arbiter: str                    # Node C: llama-3.3-70b-versatile (Meta - Heavy Judge)
    redis_host: str
    redis_port: int
    redis_db: int
    livekit_url: str
    deepgram_api_key: str


def create_initial_state(session_id: str, config: GraphConfig) -> SarasvatiState:
    """
    Factory function to create initial state for a new monitoring session.

    Args:
        session_id: Unique identifier for this session
        config: Graph configuration

    Returns:
        Initialized SarasvatiState
    """
    return SarasvatiState(
        # Buffers
        provider_buffer=[],
        interpreter_buffer=[],
        patient_buffer=[],

        # Current context
        current_provider_segment=None,
        current_interpreter_segment=None,
        current_alignment=None,

        # Extracted data
        pending_entities=[],
        matched_pairs=[],

        # Errors
        detected_errors=[],
        error_flags={},

        # Agent state
        last_debate_result=None,

        # Metadata
        session_id=session_id,
        session_start=datetime.utcnow(),
        processing_stats={
            "segments_processed": 0,
            "alignments_found": 0,
            "alignments_missed": 0,
            "errors_detected": 0,
            "avg_processing_time_ms": 0.0,
        },

        # Control
        is_active=True,
        should_emit_report=False,
        buffer_size_limit=config["max_buffer_size"],
        alignment_window_seconds=config["alignment_window_seconds"],
        last_verified_count=0,

        # Redis keys
        redis_buffer_key=f"sarasvati:session:{session_id}:buffer",
        redis_session_key=f"sarasvati:session:{session_id}:meta",
    )
