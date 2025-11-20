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
    text: str                  # Transcribed text
    timestamp: float           # Start time in stream (seconds)
    duration: float            # Duration of segment (seconds)
    confidence: float          # ASR confidence score
    is_final: bool             # Whether this is a final transcript (not interim)
    speaker_id: Optional[str]  # Optional: speaker identifier from ASR


class AlignmentMatch(TypedDict):
    """Result of DTW/semantic alignment between provider and interpreter."""
    provider_segment: TranscriptSegment
    interpreter_segment: Optional[TranscriptSegment]
    similarity_score: float    # Raw semantic similarity [0.0-1.0] (cosine distance)
    combined_score: float      # Truth Vector: 0.7*similarity + 0.3*(1-dtw) [0.0-1.0]
    time_delta: float          # Actual delay (interpreter_time - provider_time)
    is_matched: bool           # Whether a match was found in the search window
    dtw_distance: float        # DTW distance metric


class ClinicalError(TypedDict):
    """Detected error in interpretation."""
    error_id: str              # Unique identifier
    severity: ErrorSeverity
    error_type: str            # "omission", "negation_mismatch", "dosage_error", etc.
    provider_entity: MedicalEntity
    interpreter_entity: Optional[MedicalEntity]
    description: str           # Human-readable error description
    arbiter_reasoning: str     # Explanation from the Arbiter agent
    confidence: float          # Error detection confidence
    detected_at: datetime
    alignment_info: AlignmentMatch


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
    groq_model_verification: str               # Model for verification (llama-3-70b)
    groq_model_drafting: str                   # Model for speculative drafting (llama-3-8b)
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
