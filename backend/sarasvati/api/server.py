"""
SARASVATI API Server (Phase 5: The Gatekeeper)
===============================================
Production-ready FastAPI server for the Trisul Protocol.

Exposes:
- WebSocket at /ws for real-time error streaming
- REST endpoints for session control
- Health check endpoint

Protocol: All WebSocket messages match PHASE4_INTEGRATION.md schema exactly.
"""

import asyncio
import json
import math
import os
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, Set, List
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

from ..core.state import (
    SarasvatiState,
    TranscriptSegment,
    ClinicalError,
    AlignmentMatch,
    StreamRole,
    GraphConfig,
    create_initial_state,
)
from ..core.graph import SarasvatiEngine, create_engine
from ..asr.providers import ASRProviderFactory, asr_config, ASRBackend, EnsembleASR
from ..asr.translation import TranslationService, EnsembleTranslation

logger = logging.getLogger(__name__)


# ===== Configuration =====

def parse_redis_url() -> tuple[str, int, int]:
    """
    Parse REDIS_URL env var (Render format) into host, port, db.
    Format: redis://user:pass@host:port/db or redis://host:port/db
    Fallback: localhost:6379/0 for local dev.
    """
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return ("localhost", 6379, 0)

    # Strip redis:// or rediss://
    url = redis_url.replace("redis://", "").replace("rediss://", "")

    # Remove auth if present (user:pass@)
    if "@" in url:
        url = url.split("@", 1)[1]

    # Parse host:port/db
    db = 0
    if "/" in url:
        url, db_str = url.rsplit("/", 1)
        db = int(db_str) if db_str.isdigit() else 0

    host = "localhost"
    port = 6379
    if ":" in url:
        host, port_str = url.split(":", 1)
        port = int(port_str)
    else:
        host = url

    return (host, port, db)

_redis_host, _redis_port, _redis_db = parse_redis_url()

# ═══════════════════════════════════════════════════════════════════════════════
# TRIBUNAL CONFIGURATION - STRICT MODE
# ═══════════════════════════════════════════════════════════════════════════════
#
# REQUIREMENTS (enforced - system fails if not met):
#   - 3 UNIQUE providers (groq, openai, deepseek - all different)
#   - 3 UNIQUE models (all different model names)
#   - NO FALLBACKS - missing API keys cause hard failure
#
# Environment Variables:
#   TRIBUNAL_MODEL_A    = Model for Agent A (default: llama-3.1-8b-instant)
#   TRIBUNAL_MODEL_B    = Model for Agent B (default: gpt-4o-mini)
#   TRIBUNAL_MODEL_C    = Model for Agent C (default: deepseek-chat)
#
#   TRIBUNAL_PROVIDER_A = Provider for Agent A (default: groq)
#   TRIBUNAL_PROVIDER_B = Provider for Agent B (default: openai)
#   TRIBUNAL_PROVIDER_C = Provider for Agent C (default: deepseek)
#
# API Keys (ALL REQUIRED for default config):
#   GROQ_API_KEY     = For Groq models (FREE)
#   OPENAI_API_KEY   = For OpenAI models (~$0.15/1M tokens)
#   DEEPSEEK_API_KEY = For DeepSeek models (~$0.14/1M tokens)
#
# Default tribunal (3 unique providers, 3 unique models):
#   Agent A: llama-3.1-8b-instant (Groq/Meta) - FREE
#   Agent B: gpt-4o-mini (OpenAI) - $0.15/1M
#   Agent C: deepseek-chat (DeepSeek) - $0.14/1M
#
# ═══════════════════════════════════════════════════════════════════════════════

# Legacy config (kept for backwards compatibility - actual config via agent.py defaults)
_model_extractor = os.getenv("GROQ_MODEL_EXTRACTOR", "llama-3.1-8b-instant")
_model_monitor = os.getenv("GROQ_MODEL_MONITOR", "llama-3.1-8b-instant")
_model_arbiter = os.getenv("OPENAI_MODEL_ARBITER", "gpt-3.5-turbo")

DEFAULT_CONFIG = GraphConfig(
    max_buffer_size=50,
    alignment_threshold=0.40,  # Lowered for cross-lingual matching (was 0.65)
    alignment_window_seconds=30.0,
    debounce_ms=500,
    enable_negation_check=True,
    groq_model_extractor=_model_extractor,   # Node A: Mistral Mixtral MoE
    groq_model_monitor=_model_monitor,       # Node B: Groq fallback (OpenAI preferred)
    groq_model_arbiter=_model_arbiter,       # Node C: Meta Llama 70B (judge)
    redis_host=_redis_host,
    redis_port=_redis_port,
    redis_db=_redis_db,
    livekit_url="wss://localhost:7880",
    deepgram_api_key="",
)


# ===== Pydantic Models (Request/Response) =====

class RoleLanguageConfig(BaseModel):
    """Language configuration for a specific role."""
    language: str  # ISO 639-1 code (e.g., "en", "gu", "es")
    script: Optional[str] = None  # Expected script (e.g., "gujarati", "devanagari")


class InterpreterModeConfig(BaseModel):
    """Configuration for interpreter direction-specific behavior."""
    direction: str  # "provider_to_patient" or "patient_to_provider"
    language: str  # Expected language for this direction


class ScenarioMetadata(BaseModel):
    """Metadata about the scenario being run."""
    scenario_id: Optional[str] = None  # e.g., "gujarati_body_pain_01"
    scenario_name: Optional[str] = None  # e.g., "Gujarati Patient - Abdominal Pain"
    provider_language: str = "en"  # Provider language (default: English)
    patient_language: str = "auto"  # Patient language (default: auto-detect)
    interpreter_modes: Optional[list[InterpreterModeConfig]] = None  # Interpreter direction config
    # Future: difficulty, expected_errors, learning_objectives, etc.


class SessionStartRequest(BaseModel):
    session_id: Optional[str] = None
    scenario: Optional[ScenarioMetadata] = None  # Scenario configuration


class SessionStartResponse(BaseModel):
    session_id: str
    status: str
    message: str


class SessionStopResponse(BaseModel):
    session_id: str
    status: str
    duration_seconds: float
    errors_detected: int
    critical_errors: int


class HealthResponse(BaseModel):
    status: str
    engine_active: bool
    active_connections: int
    timestamp: str


# ===== JSON Safety Utilities =====

def safe_number(value: Any) -> Optional[float]:
    """
    Ensure we never send NaN/Infinity over WebSocket JSON.
    Returns a finite float or None.

    JavaScript's JSON.parse rejects NaN/Infinity as invalid JSON.
    Python's json.dumps allows them by default, breaking the frontend.

    Usage:
        "dtw_distance": safe_number(alignment.get("dtw_distance"))
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if math.isfinite(value):
            return float(value)
        # Replace NaN/Inf with None so JSON is standards-compliant
        logger.warning(f"⚠️ Sanitizing non-finite value {value} to None for WS payload")
        return None
    # If it's not a number, return None
    return None


# ===== WebSocket Connection Manager =====

class ConnectionManager:
    """
    Manages WebSocket connections for broadcasting events.
    Thread-safe connection tracking.
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            self.active_connections.discard(websocket)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """
        Broadcast a message to all connected clients.

        CRITICAL: Pre-validate JSON serialization to prevent Infinity/NaN from breaking clients.
        """
        # Pre-validate that the message can be serialized without NaN/Infinity
        try:
            # Test serialization with allow_nan=False (JavaScript JSON.parse compatible)
            json.dumps(message, allow_nan=False)
        except (ValueError, TypeError) as e:
            logger.error(f"❌ Failed to serialize WS payload: {e} | message type: {message.get('type')} | data preview: {str(message.get('data', {}))[:200]}")
            return  # Don't broadcast invalid JSON

        async with self._lock:
            connections = list(self.active_connections)

        # Send to all connections, removing dead ones
        dead_connections = []
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"❌ Failed to send WS message to client: {e}")
                dead_connections.append(connection)

        # Clean up dead connections
        if dead_connections:
            async with self._lock:
                for conn in dead_connections:
                    self.active_connections.discard(conn)

    def connection_count(self) -> int:
        """Return the number of active connections."""
        return len(self.active_connections)


# ===== Global State =====

manager = ConnectionManager()
engine: Optional[SarasvatiEngine] = None
session_active = False
session_id: Optional[str] = None
session_start_time: Optional[datetime] = None
current_scenario: Optional[ScenarioMetadata] = None  # Current scenario metadata

# Background task for processing
_processing_task: Optional[asyncio.Task] = None

# Session lock to prevent race conditions on start/stop
_session_lock = asyncio.Lock()

# Turn/State Management (prevent ghost recordings)
from collections import deque
from time import time as get_time
_turn_history: deque = deque(maxlen=10)  # Track last 10 turns with timestamps
_last_turn_role: Optional[str] = None
_last_turn_time: float = 0.0


# ===== Schema Converters (Match Phase 4 exactly) =====

def clinical_error_to_ws_payload(error: ClinicalError) -> Dict[str, Any]:
    """
    Convert backend ClinicalError to Phase 4 WebSocket schema.

    The frontend expects:
    - error_id, severity, error_type, description, confidence
    - alignment_info with provider_segment/interpreter_segment
    - arbiter_reasoning, detected_at
    - is_system_error: separates infrastructure failures from clinical errors
    - case_type: extracted from alignment_info for tribunal context

    This matches frontend/src/hooks/useSarasvatiBackend.ts exactly.
    """
    # Extract case_type from alignment_info if present
    case_type = None
    if error["alignment_info"]:
        raw_case_type = error["alignment_info"].get("case_type")
        if raw_case_type:
            # Normalize enum to string
            case_type = raw_case_type.value if hasattr(raw_case_type, "value") else str(raw_case_type)

    # Strip debug metacommentary from arbiter_reasoning for user-facing display
    arbiter_reasoning = error["arbiter_reasoning"]
    if arbiter_reasoning:
        # Remove [OVERRIDE: ...] notes (internal tribunal debugging)
        import re
        arbiter_reasoning = re.sub(r'\s*\[OVERRIDE:.*?\]', '', arbiter_reasoning, flags=re.DOTALL)
        arbiter_reasoning = arbiter_reasoning.strip()

    # Strip debug placeholders from description
    description = error["description"]
    if description:
        import re
        # Remove [NO SOURCE], [NO INTERPRETATION], etc.
        description = re.sub(r"'\[NO SOURCE\]'", "the original message", description)
        description = re.sub(r"'\[NO INTERPRETATION\]'", "any translation", description)
        description = re.sub(r'\[NO SOURCE\]', "the original message", description)
        description = re.sub(r'\[NO INTERPRETATION\]', "any translation", description)
        description = description.strip()

    return {
        "error_id": error["error_id"],
        "severity": error["severity"].value if hasattr(error["severity"], "value") else error["severity"],
        "error_type": error["error_type"],
        "provider_entity": error["provider_entity"],
        "interpreter_entity": error["interpreter_entity"],
        "description": description,
        "arbiter_reasoning": arbiter_reasoning,
        "confidence": safe_number(error["confidence"]),
        "detected_at": error["detected_at"].isoformat() if isinstance(error["detected_at"], datetime) else error["detected_at"],
        "alignment_info": alignment_to_payload(error["alignment_info"]) if error["alignment_info"] else None,
        "is_system_error": error.get("is_system_error", False),
        "case_type": case_type,
        # Interpreter-centric tribunal context
        "source_role": error.get("source_role"),
        "interpreter_quote": error.get("interpreter_quote"),
        "source_quote": error.get("source_quote"),
        "ideal_interpretation": error.get("ideal_interpretation"),
    }


def alignment_to_payload(alignment: AlignmentMatch) -> Dict[str, Any]:
    """
    Convert AlignmentMatch to JSON-serializable dict.

    CRITICAL: Handle inbound cases where provider_segment may be None.
    For inbound cases (patient → interpreter → provider), patient is the source.

    CRITICAL: Sanitize all numeric values to prevent Infinity/NaN from breaking JSON.
    """
    # Safely handle potentially None segments (especially for inbound cases)
    provider_seg = alignment.get("provider_segment")
    interpreter_seg = alignment.get("interpreter_segment")
    patient_seg = alignment.get("patient_segment")

    return {
        "provider_segment": segment_to_payload(provider_seg) if provider_seg else None,
        "interpreter_segment": segment_to_payload(interpreter_seg) if interpreter_seg else None,
        "patient_segment": segment_to_payload(patient_seg) if patient_seg else None,
        "similarity_score": safe_number(alignment.get("similarity_score")),
        "combined_score": safe_number(alignment.get("combined_score")),
        "time_delta": safe_number(alignment.get("time_delta")),
        "is_matched": alignment.get("is_matched", False),
        "dtw_distance": safe_number(alignment.get("dtw_distance")),
        "case_type": str(alignment.get("case_type", "unknown")),
    }


def segment_to_payload(segment: TranscriptSegment) -> Dict[str, Any]:
    """Convert TranscriptSegment to JSON-serializable dict with NaN/Infinity safety."""
    return {
        "role": segment["role"].value if hasattr(segment["role"], "value") else segment["role"],
        "text": segment["text"],
        "timestamp": safe_number(segment["timestamp"]),
        "duration": safe_number(segment["duration"]),
        "confidence": safe_number(segment["confidence"]),
        "is_final": segment["is_final"],
        "speaker_id": segment.get("speaker_id"),
        "segment_id": segment.get("segment_id"),
    }


def build_ws_message(msg_type: str, data: Any) -> Dict[str, Any]:
    """
    Build a WebSocket message matching Phase 4 protocol.

    Format:
    {
        "type": "detected_error" | "state_update" | "transcript" | ...,
        "data": {...},
        "timestamp": 1731974653  // Unix timestamp
    }
    """
    return {
        "type": msg_type,
        "data": data,
        "timestamp": int(datetime.utcnow().timestamp()),
    }


# ===== Background Processing =====

async def emit_error_loop() -> None:
    """
    Background loop that monitors for new verdicts and errors and broadcasts them.

    Runs every 100ms to check for new tribunal verdicts.
    Emits tribunal_verdict for EVERY assessment (with confidence score).
    """
    global engine, session_active

    last_error_count = 0
    last_verdict_count = 0

    while session_active and engine:
        try:
            state = engine.get_state()
            if state:
                # Emit tribunal verdicts for ALL matched pairs (not just errors)
                matched_pairs = state.get("matched_pairs", [])
                current_verdict_count = len(matched_pairs)

                if current_verdict_count > last_verdict_count:
                    # Get the last debate result
                    debate_result = state.get("last_debate_result")
                    if debate_result:
                        # Compute confidence score (never 100%)
                        detected_errors = debate_result.get("detected_errors") or []
                        # Filter out None errors
                        valid_errors = [e for e in detected_errors if e]
                        num_errors = len(valid_errors)
                        severity = "none"
                        if num_errors > 0:
                            # Get max severity from errors
                            severities = [e.get("severity", "medium") for e in valid_errors]
                            if any(s == "critical" for s in severities):
                                severity = "critical"
                            elif any(s == "high" for s in severities):
                                severity = "high"
                            elif any(s == "medium" for s in severities):
                                severity = "medium"
                            else:
                                severity = "low"

                        confidence = compute_confidence(severity, num_errors)

                        # NEW: Include debate logs for visibility (user wants to see the debate!)
                        debate_logs = debate_result.get("debate_logs")
                        has_debate_logs = debate_logs is not None

                        verdict_payload = {
                            "confidence": confidence,
                            "severity": severity,
                            "num_issues": num_errors,
                            "arbiter_decision": debate_result.get("arbiter_decision", ""),
                            "monitor_findings": debate_result.get("monitor_findings", []) or [],
                            "errors": [
                                {
                                    "severity": str(e.get("severity", "medium")),
                                    "error_type": e.get("error_type", "unknown"),
                                    "description": e.get("description", ""),
                                }
                                for e in valid_errors
                            ],
                            # Visible debate logs from two-tribunal architecture
                            "debate_logs": debate_logs,
                            "has_debate_logs": has_debate_logs,
                        }

                        message = build_ws_message("tribunal_verdict", verdict_payload)
                        await manager.broadcast(message)
                        print(f"📢 Broadcast tribunal_verdict: confidence={confidence:.2f}, severity={severity}, issues={num_errors}, debate_visible={has_debate_logs}")

                        # NEW: Broadcast debate logs as separate message for UI (visible debate section)
                        if has_debate_logs:
                            debate_message = build_ws_message("debate_log", debate_logs)
                            await manager.broadcast(debate_message)
                            print(f"📢 Broadcast debate_log: {len(debate_logs)} tribunal logs")

                    last_verdict_count = current_verdict_count

                # Also emit individual errors (for backwards compatibility)
                current_errors = state.get("detected_errors") or []
                new_error_count = len(current_errors)

                if new_error_count > last_error_count:
                    new_errors = current_errors[last_error_count:]
                    for error in new_errors:
                        if error:  # Skip None errors
                            payload = clinical_error_to_ws_payload(error)
                            message = build_ws_message("detected_error", payload)
                            await manager.broadcast(message)

                    last_error_count = new_error_count

            await asyncio.sleep(0.1)  # 100ms polling

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Error in emit loop: {e}")
            await asyncio.sleep(0.5)


def compute_confidence(severity: str, num_issues: int) -> float:
    """
    Compute confidence score (0.01 - 0.99, never 100%).

    Starts high, penalizes for severity and number of issues.
    """
    base = 0.95

    # Severity penalties
    if severity == "low":
        base -= 0.05
    elif severity == "medium":
        base -= 0.15
    elif severity == "high":
        base -= 0.25
    elif severity == "critical":
        base -= 0.40

    # More issues → lower confidence
    base -= min(num_issues, 5) * 0.03

    # Clamp and never 0 or 1
    return max(0.01, min(0.99, base))


# ===== FastAPI Lifespan =====

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Initializes the SarasvatiEngine on startup.
    Cleans up on shutdown.
    """
    global engine

    print("=" * 60)
    print("SARASVATI API Server Starting...")
    print("=" * 60)

    try:
        engine = create_engine(DEFAULT_CONFIG)
        print("SarasvatiEngine initialized")
    except ImportError as e:
        print(f"Warning: Could not initialize full engine: {e}")
        print("Running in mock mode for development")
        engine = None

    yield

    # Cleanup
    print("Shutting down SARASVATI API Server...")
    if _processing_task and not _processing_task.done():
        _processing_task.cancel()


# ===== FastAPI App =====

app = FastAPI(
    title="SARASVATI API",
    description="Real-time medical interpreter monitoring system",
    version="0.5.0",
    lifespan=lifespan,
)

# CORS middleware for frontend access (Phase 6: Cloud-Native)
def get_cors_origins() -> List[str]:
    """Build CORS origins list from environment + localhost for dev."""
    origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    frontend_url = os.getenv("FRONTEND_URL")
    if frontend_url:
        origins.append(frontend_url)
        # Also allow without trailing slash
        origins.append(frontend_url.rstrip("/"))
    return origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== REST Endpoints =====

@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        engine_active=engine is not None and session_active,
        active_connections=manager.connection_count(),
        timestamp=datetime.utcnow().isoformat(),
    )


@app.post("/session/start", response_model=SessionStartResponse)
async def start_session(request: SessionStartRequest) -> SessionStartResponse:
    """
    Start a new monitoring session with optional scenario metadata.

    Creates a new session and initializes a FRESH engine.
    CRITICAL: Each session gets its own engine to prevent state leakage.

    Scenario metadata enables:
    - Role-specific language constraints (provider=en, patient=gu)
    - ASR model selection based on language
    - Language validation and error detection
    """
    global session_active, session_id, session_start_time, _processing_task, engine, current_scenario

    if session_active:
        raise HTTPException(status_code=409, detail="Session already active")

    # Generate session ID if not provided
    session_id = request.session_id or f"session_{uuid.uuid4().hex[:8]}"
    session_start_time = datetime.utcnow()
    session_active = True

    # Store scenario metadata
    current_scenario = request.scenario
    if current_scenario:
        print(f"\n📋 SCENARIO CONFIGURATION:")
        print(f"   ID: {current_scenario.scenario_id or 'N/A'}")
        print(f"   Name: {current_scenario.scenario_name or 'N/A'}")
        print(f"   Provider language: {current_scenario.provider_language}")
        print(f"   Patient language: {current_scenario.patient_language}")
        if current_scenario.interpreter_modes:
            print(f"   Interpreter modes:")
            for mode in current_scenario.interpreter_modes:
                print(f"      {mode.direction} → {mode.language}")
    else:
        print(f"⚠️ No scenario metadata provided - using defaults")

    # CRITICAL FIX: Create a fresh engine for each session to prevent state leakage
    # The old engine's buffers/state would carry over otherwise
    print(f"🔄 Creating fresh engine for session {session_id}")
    engine = create_engine(DEFAULT_CONFIG)
    await engine.start_session(session_id)
    print(f"✅ Fresh engine initialized for session {session_id}")

    # Start background error emission loop
    _processing_task = asyncio.create_task(emit_error_loop())

    # Broadcast session start
    message = build_ws_message("session_start", {
        "session_id": session_id,
        "scenario": current_scenario.dict() if current_scenario else None,
    })
    await manager.broadcast(message)

    return SessionStartResponse(
        session_id=session_id,
        status="started",
        message=f"Session {session_id} started successfully",
    )


@app.post("/session/stop", response_model=SessionStopResponse)
async def stop_session() -> SessionStopResponse:
    """
    Stop the current monitoring session.

    Returns session statistics.
    """
    global session_active, session_id, session_start_time, _processing_task, engine, current_scenario
    global _turn_history, _last_turn_role, _last_turn_time

    if not session_active:
        raise HTTPException(status_code=409, detail="No active session")

    # Stop background task
    if _processing_task and not _processing_task.done():
        _processing_task.cancel()
        try:
            await _processing_task
        except asyncio.CancelledError:
            pass

    # Calculate duration
    duration = 0.0
    if session_start_time:
        duration = (datetime.utcnow() - session_start_time).total_seconds()

    # Get stats from engine
    errors_detected = 0
    critical_errors = 0
    if engine:
        stats = await engine.stop_session()
        errors_detected = stats.get("errors_detected", 0)
        critical_errors = stats.get("critical_errors", 0)

    # Broadcast session end
    message = build_ws_message("session_end", {})
    await manager.broadcast(message)

    # Store session_id before resetting
    current_session_id = session_id

    # Reset state
    session_active = False
    session_id = None
    session_start_time = None
    current_scenario = None  # Clear scenario metadata

    # Reset turn tracking
    _turn_history.clear()
    _last_turn_role = None
    _last_turn_time = 0.0

    return SessionStopResponse(
        session_id=current_session_id or "unknown",
        status="stopped",
        duration_seconds=duration,
        errors_detected=errors_detected,
        critical_errors=critical_errors,
    )


# ===== Transcription Endpoint (Groq Whisper) =====

class TranscriptionResponse(BaseModel):
    text: str
    role: str
    duration: float
    detected_language: str = "auto"
    english_translation: Optional[str] = None
    transliteration: Optional[str] = None


def detect_script(text: str) -> str:
    """
    Detect the writing script used in text.
    Returns: 'latin', 'gujarati', 'devanagari', 'arabic', 'chinese', 'sinhala', 'thai', 'unknown'
    """
    if not text:
        return "unknown"

    # Count characters in each Unicode block
    char_counts = {
        "latin": 0,
        "gujarati": 0,
        "devanagari": 0,
        "arabic": 0,
        "chinese": 0,
        "sinhala": 0,
        "thai": 0,
    }

    for char in text:
        code_point = ord(char)
        if 0x0041 <= code_point <= 0x007A or 0x0041 <= code_point <= 0x005A:  # Latin A-Z, a-z
            char_counts["latin"] += 1
        elif 0x0A80 <= code_point <= 0x0AFF:  # Gujarati Unicode block
            char_counts["gujarati"] += 1
        elif 0x0900 <= code_point <= 0x097F:  # Devanagari Unicode block
            char_counts["devanagari"] += 1
        elif 0x0600 <= code_point <= 0x06FF or 0x0750 <= code_point <= 0x077F:  # Arabic
            char_counts["arabic"] += 1
        elif 0x4E00 <= code_point <= 0x9FFF:  # CJK Unified Ideographs
            char_counts["chinese"] += 1
        elif 0x0D80 <= code_point <= 0x0DFF:  # Sinhala
            char_counts["sinhala"] += 1
        elif 0x0E00 <= code_point <= 0x0E7F:  # Thai
            char_counts["thai"] += 1

    # Return script with highest count (if > 30% of non-space chars)
    total_chars = sum(char_counts.values())
    if total_chars == 0:
        return "unknown"

    for script, count in char_counts.items():
        if count / total_chars > 0.3:
            return script

    return "unknown"


def get_expected_scripts(language: str) -> list[str]:
    """
    Return expected writing scripts for a given language.
    Handles languages that can be written in multiple scripts.
    """
    script_map = {
        "en": ["latin"],
        "es": ["latin"],
        "fr": ["latin"],
        "de": ["latin"],
        "pt": ["latin"],
        "gu": ["gujarati", "devanagari"],  # Gujarati can be written in both
        "hi": ["devanagari"],
        "ar": ["arabic"],
        "zh": ["chinese"],
    }
    return script_map.get(language, ["unknown"])


async def call_whisper(
    client: httpx.AsyncClient,
    audio_data: bytes,
    filename: str,
    content_type: str,
    language: str,
    api_key: str,
    role: str = "provider",
    expected_scripts: Optional[list[str]] = None,
) -> dict:
    """
    Call ASR API with multi-model ensemble support.

    Modes:
    - "ensemble" (default): Run both Groq + OpenAI in parallel, pick best
    - "groq": Use only Groq Whisper Large V3
    - "openai-gpt4o-transcribe": Use only OpenAI gpt-4o-transcribe
    - "openai-gpt4o-mini-transcribe": Use only OpenAI gpt-4o-mini-transcribe
    - "openai-whisper1": Use only OpenAI whisper-1
    """
    backend_name = asr_config.get_backend(role, language or "auto")

    groq_key = api_key
    openai_key = os.getenv("OPENAI_API_KEY", "")

    # Determine which OpenAI model to use in ensemble mode
    # For high-quality languages (Gujarati, Hindi), use gpt-4o-transcribe
    openai_model = "gpt-4o-transcribe"  # Default to best quality
    if language in ["gu", "hi", "ar", "zh"]:
        # Use highest quality for complex scripts
        openai_model = "gpt-4o-transcribe"
    elif language in ["es", "en"]:
        # Ensemble mode with good quality (could use mini for cost savings later)
        openai_model = "gpt-4o-transcribe"

    # ENSEMBLE MODE: Run both providers in parallel
    if backend_name == "ensemble":
        result = await EnsembleASR.transcribe_ensemble(
            audio_data,
            filename,
            content_type,
            language,
            groq_key,
            openai_key,
            expected_scripts=expected_scripts,
            openai_model=openai_model,  # Pass model selection
        )
    else:
        # Single provider mode
        provider = ASRProviderFactory.create(backend_name, groq_key, openai_key)
        result = await provider.transcribe(audio_data, filename, content_type, language)

    # Convert ASRResult to dict for backwards compatibility
    return {
        "text": result.text,
        "duration": result.duration,
        "language": result.language,
        "error": result.error,
        "provider": result.provider,  # Track which provider/ensemble was used
    }


@app.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    audio: UploadFile = File(...),
    role: str = Form(default="provider"),
    language: str = Form(default="auto"),
    provider_lang: str = Form(default="en"),
    patient_lang: str = Form(default="auto"),
) -> TranscriptionResponse:
    """
    Transcribe audio using pluggable ASR backend (OpenAI or Groq).
    Accepts audio file, role (provider/interpreter/patient), and language hints.
    For interpreter: runs ASR with both languages plus an auto-detect pass and
    chooses the transcript that matches the detected language when possible.

    Uses OpenAI gpt-4o-transcribe by default (configurable via asr_config).

    Role-based language enforcement (when scenario metadata is available):
    - Provider: ALWAYS English (language="en")
    - Patient: Use scenario.patient_language (e.g., "gu" for Gujarati)
    - Interpreter: Dual-language detection (provider_lang + patient_lang)
    """
    global engine, session_active, current_scenario
    global _turn_history, _last_turn_role, _last_turn_time

    # TURN VALIDATION: Check for suspicious rapid-fire recordings from same role
    current_time = get_time()
    if _last_turn_role == role and (current_time - _last_turn_time) < 2.0:
        # Same role recording within 2 seconds - check recent history
        recent_same_role = sum(1 for r, t in _turn_history if r == role and (current_time - t) < 10.0)
        if recent_same_role >= 3:
            print(f"⚠️ TURN ANOMALY: {role} has recorded {recent_same_role+1} times in 10s - marking as non-gradable")
            # Still process ASR but tag segment as non-gradable
            segment_is_suspect = True
        else:
            segment_is_suspect = False
    else:
        segment_is_suspect = False

    # Update turn tracking
    _turn_history.append((role, current_time))
    _last_turn_role = role
    _last_turn_time = current_time

    # ROLE-BASED LANGUAGE ENFORCEMENT using scenario metadata
    if current_scenario:
        print(f"📋 Enforcing scenario language constraints:")
        if role == "provider":
            # Provider MUST speak English
            provider_lang = current_scenario.provider_language
            language = provider_lang
            print(f"   Provider → forcing language={provider_lang}")
        elif role == "patient":
            # Patient MUST speak scenario language
            patient_lang = current_scenario.patient_language
            language = patient_lang if patient_lang != "auto" else "auto"
            print(f"   Patient → forcing language={patient_lang}")
        elif role == "interpreter":
            # Interpreter: use scenario languages for dual-detection
            provider_lang = current_scenario.provider_language
            patient_lang = current_scenario.patient_language
            print(f"   Interpreter → dual-language ({provider_lang} / {patient_lang})")
    else:
        print(f"⚠️ No scenario metadata - using default language detection")

    # Get API keys - OpenAI is primary, Groq is fallback
    groq_api_key = os.getenv("GROQ_API_KEY", "")
    if not groq_api_key:
        # Allow empty Groq key if OpenAI is configured
        groq_api_key = ""

    # Read audio file
    audio_data = await audio.read()
    filename = audio.filename or "audio.webm"
    content_type = audio.content_type or "audio/webm"

    detected_language = "auto"

    async with httpx.AsyncClient() as client:
        if role == "interpreter" and provider_lang != patient_lang and patient_lang != "auto":
            # For interpreter: Use auto-detect and compare with hint transcripts to determine language
            # CRITICAL: Language hints cause Whisper to TRANSLATE, not transcribe!
            # We use hints only to detect which language was spoken, not to get the transcript.
            print(f"🔄 Interpreter dual-language detection: trying {provider_lang} and {patient_lang}")

            # Prepare expected scripts for ensemble validation
            expected_scripts_list = get_expected_scripts(provider_lang) + get_expected_scripts(patient_lang)

            result_auto, result_provider, result_patient = await asyncio.gather(
                call_whisper(client, audio_data, filename, content_type, "auto", groq_api_key, role, expected_scripts_list),
                call_whisper(client, audio_data, filename, content_type, provider_lang, groq_api_key, role, expected_scripts_list),
                call_whisper(client, audio_data, filename, content_type, patient_lang, groq_api_key, role, expected_scripts_list),
            )

            def extract_candidate(result: dict, fallback_lang: str) -> dict:
                return {
                    "text": result.get("text", "").strip(),
                    "duration": result.get("duration", 0.0),
                    "lang": result.get("language", fallback_lang),
                    "error": result.get("error"),
                }

            candidate_auto = extract_candidate(result_auto, "unknown")
            candidate_provider = extract_candidate(result_provider, provider_lang)
            candidate_patient = extract_candidate(result_patient, patient_lang)

            # Check for errors and raise if all failed
            errors = []
            for name, candidate in (
                ("auto", candidate_auto),
                ("provider", candidate_provider),
                ("patient", candidate_patient),
            ):
                if candidate.get("error"):
                    error_msg = f"{name}: {candidate['error']}"
                    print(f"   ⚠️ Whisper error for {name} hint: {candidate['error']}")
                    errors.append(error_msg)

            # If all three failed, raise with details
            if len(errors) == 3:
                raise HTTPException(
                    status_code=500,
                    detail=f"All ASR attempts failed: {'; '.join(errors)}"
                )

            # Debug logging: show all candidates
            print(f"   📊 Candidates:")
            auto_preview = candidate_auto['text'][:50] if candidate_auto['text'] else "(empty)"
            provider_preview = candidate_provider['text'][:50] if candidate_provider['text'] else "(empty)"
            patient_preview = candidate_patient['text'][:50] if candidate_patient['text'] else "(empty)"
            print(f"      auto: '{auto_preview}...' (lang={candidate_auto['lang']}, len={len(candidate_auto['text'])})")
            print(f"      {provider_lang}_hint: '{provider_preview}...' (len={len(candidate_provider['text'])})")
            print(f"      {patient_lang}_hint: '{patient_preview}...' (len={len(candidate_patient['text'])})")

            # Strategy: ALWAYS use auto transcript (it's already correct!)
            # Compare it with hints to determine which language was spoken
            auto_text = candidate_auto["text"].lower()
            provider_text = candidate_provider["text"].lower()
            patient_text = candidate_patient["text"].lower()

            # If auto matches provider hint closely, it's the provider language
            # If auto matches patient hint closely, it's the patient language
            # Otherwise, use Whisper's returned language code
            detected_language = candidate_auto["lang"]

            if auto_text and provider_text and auto_text == provider_text:
                detected_language = provider_lang
                print(f"   ✅ Detected {provider_lang}: Auto matches provider hint exactly")
            elif auto_text and patient_text and auto_text == patient_text:
                detected_language = patient_lang
                print(f"   ✅ Detected {patient_lang}: Auto matches patient hint exactly")
            elif auto_text and provider_text and patient_text:
                # Calculate similarity scores to determine language
                # If provider hint is a translation (very different), auto is probably patient lang
                # If patient hint is a translation (very different), auto is probably provider lang
                provider_similarity = len(set(auto_text.split()) & set(provider_text.split())) / max(len(auto_text.split()), len(provider_text.split())) if auto_text and provider_text else 0
                patient_similarity = len(set(auto_text.split()) & set(patient_text.split())) / max(len(auto_text.split()), len(patient_text.split())) if auto_text and patient_text else 0

                if provider_similarity > patient_similarity and provider_similarity > 0.5:
                    detected_language = provider_lang
                    print(f"   ✅ Detected {provider_lang}: Auto more similar to provider hint (score={provider_similarity:.2f})")
                elif patient_similarity > provider_similarity and patient_similarity > 0.5:
                    detected_language = patient_lang
                    print(f"   ✅ Detected {patient_lang}: Auto more similar to patient hint (score={patient_similarity:.2f})")
                else:
                    print(f"   ⚠️ Could not determine language from hints (provider={provider_similarity:.2f}, patient={patient_similarity:.2f})")
                    print(f"   → Using Whisper's auto language: {detected_language}")
            elif detected_language in {provider_lang, patient_lang}:
                print(f"   ✅ Using Whisper's auto-detected language: {detected_language}")
            else:
                # Whisper didn't return a valid language, default to provider lang
                detected_language = provider_lang
                print(f"   ⚠️ Whisper returned unknown language '{detected_language}', defaulting to {provider_lang}")

            # CRITICAL: ALWAYS use auto-detect transcript for UI (preserves raw Whisper text)
            # Language hints cause Whisper to TRANSLATE, not transcribe!
            # We only use hints for language detection, not for the actual transcript.
            # This ensures "no problema" stays as "no problema", not "No hay problema"
            text = candidate_auto["text"]
            duration = candidate_auto["duration"]
            print(f"   ✅ Using auto transcript for UI (language={detected_language}, raw text preserved)")

            if not text:
                raise HTTPException(status_code=500, detail="Failed to transcribe interpreter audio")
        elif role == "patient" and patient_lang != "auto" and patient_lang != provider_lang:
            # For patient in non-English scenarios: Use dual-language detection
            # This helps with Gujarati, Hindi, Arabic, Chinese, etc.
            print(f"🔄 Patient dual-language detection: trying auto and {patient_lang}")

            # Prepare expected scripts for ensemble validation
            expected_scripts_list = get_expected_scripts(patient_lang)

            result_auto, result_patient = await asyncio.gather(
                call_whisper(client, audio_data, filename, content_type, "auto", groq_api_key, role, expected_scripts_list),
                call_whisper(client, audio_data, filename, content_type, patient_lang, groq_api_key, role, expected_scripts_list),
            )

            candidate_auto = {
                "text": result_auto.get("text", "").strip(),
                "duration": result_auto.get("duration", 0.0),
                "lang": result_auto.get("language", "unknown"),
            }
            candidate_patient = {
                "text": result_patient.get("text", "").strip(),
                "duration": result_patient.get("duration", 0.0),
                "lang": patient_lang,
            }

            print(f"   📊 Candidates:")
            print(f"      auto: '{candidate_auto['text'][:50]}...' (lang={candidate_auto['lang']}, len={len(candidate_auto['text'])})")
            print(f"      {patient_lang}_hint: '{candidate_patient['text'][:50]}...' (len={len(candidate_patient['text'])})")

            # Use patient hint if auto gives gibberish or wrong script
            auto_text = candidate_auto["text"]
            patient_text = candidate_patient["text"]

            # Detect if auto transcript contains valid patient language script
            has_valid_script = detect_script(auto_text) in get_expected_scripts(patient_lang)

            if has_valid_script or candidate_auto["lang"] == patient_lang:
                # Auto is good - use it
                text = auto_text
                duration = candidate_auto["duration"]
                detected_language = patient_lang
                print(f"   ✅ Using auto transcript (detected {patient_lang} script)")
            elif patient_text and len(patient_text) > 0:
                # Auto failed, use patient hint
                text = patient_text
                duration = candidate_patient["duration"]
                detected_language = patient_lang
                print(f"   ✅ Using {patient_lang} hint transcript (auto gave wrong script)")
            else:
                # Both failed, fallback to auto
                text = auto_text
                duration = candidate_auto["duration"]
                detected_language = candidate_auto["lang"]
                print(f"   ⚠️ Both transcripts questionable, using auto")

            if not text:
                raise HTTPException(status_code=500, detail="Failed to transcribe patient audio")
        elif role == "patient" and patient_lang == "auto":
            # Patient language not specified - try to auto-detect with multi-language hints
            # This helps when frontend doesn't know patient language yet
            print(f"🔄 Patient language auto-detection: trying common languages")

            # Try auto first, then common non-English languages if auto looks wrong
            # For auto-detect, we don't know expected scripts yet, so pass None
            result_auto = await call_whisper(client, audio_data, filename, content_type, "auto", groq_api_key, role, None)
            auto_text = result_auto.get("text", "").strip()
            auto_lang = result_auto.get("language", "unknown")
            auto_script = detect_script(auto_text)

            print(f"   📊 Auto result: '{auto_text[:50]}...' (lang={auto_lang}, script={auto_script})")

            # If auto gives wrong script (Sinhala, Thai when we expect Gujarati/Hindi/Arabic),
            # try common Indic languages
            if auto_script in ["sinhala", "thai"] or (auto_lang == "unknown" and len(auto_text) > 0):
                print(f"   ⚠️ Auto gave suspicious script ({auto_script}), trying Gujarati/Hindi hints")

                result_gu, result_hi, result_ar = await asyncio.gather(
                    call_whisper(client, audio_data, filename, content_type, "gu", groq_api_key, role),
                    call_whisper(client, audio_data, filename, content_type, "hi", groq_api_key, role),
                    call_whisper(client, audio_data, filename, content_type, "ar", groq_api_key, role),
                )

                candidates = [
                    ("gu", result_gu.get("text", "").strip(), detect_script(result_gu.get("text", ""))),
                    ("hi", result_hi.get("text", "").strip(), detect_script(result_hi.get("text", ""))),
                    ("ar", result_ar.get("text", "").strip(), detect_script(result_ar.get("text", ""))),
                ]

                # Pick the one with correct script
                for lang_code, candidate_text, candidate_script in candidates:
                    expected = get_expected_scripts(lang_code)
                    print(f"      {lang_code}_hint: '{candidate_text[:40]}...' (script={candidate_script})")
                    if candidate_script in expected and len(candidate_text) > 0:
                        text = candidate_text
                        detected_language = lang_code
                        duration = result_auto.get("duration", 0.0)
                        print(f"   ✅ Using {lang_code} hint (valid {candidate_script} script)")
                        break
                else:
                    # No good candidate, use auto
                    text = auto_text
                    detected_language = auto_lang
                    duration = result_auto.get("duration", 0.0)
                    print(f"   ⚠️ No valid Indic script found, using auto")
            else:
                # Auto is reasonable
                text = auto_text
                detected_language = auto_lang
                duration = result_auto.get("duration", 0.0)

            if not text:
                raise HTTPException(status_code=500, detail="Failed to transcribe patient audio")
        else:
            # For provider or when languages are same: use role-specific language
            # CRITICAL: Language hints cause Whisper to TRANSLATE, not transcribe!
            # For English provider, we can use "auto" safely since Whisper detects English well
            # For non-English patient (like Gujarati), we pass language hint to ASR

            # Determine which language to pass to ASR
            asr_language = language if language != "auto" else "auto"

            # For provider, force English detection
            if role == "provider":
                asr_language = provider_lang  # Already enforced to "en" above
                expected_scripts_for_role = None  # English doesn't need script validation
            elif role == "patient":
                asr_language = patient_lang
                expected_scripts_for_role = get_expected_scripts(patient_lang) if patient_lang != "auto" else None
            else:
                expected_scripts_for_role = None

            result = await call_whisper(client, audio_data, filename, content_type, asr_language, groq_api_key, role, expected_scripts_for_role)
            if result.get("error"):  # Only raise if error is not None/empty
                raise HTTPException(status_code=500, detail=f"ASR error: {result['error']}")
            text = result.get("text", "").strip()
            duration = result.get("duration", 0.0)
            detected_language = result.get("language", asr_language)

            # ENFORCE LANGUAGE CONSTRAINT: Provider MUST NOT have "unknown" language
            if role == "provider" and detected_language == "unknown":
                print(f"   ⚠️ Provider returned unknown language - forcing to {provider_lang}")
                detected_language = provider_lang

    # Create transcript segment with unique ID for error mapping
    segment_id = f"seg_{uuid.uuid4().hex[:12]}"

    # ═══════════════════════════════════════════════════════════
    # ASR RELIABILITY CHECK: Detect when transcription is likely unreliable
    # ═══════════════════════════════════════════════════════════
    asr_reliable = True

    # Detect script in the transcript
    detected_script = detect_script(text)
    print(f"   📝 Detected script: {detected_script}")

    # For patient/interpreter, check if script matches expected language
    expected_scripts: list[str] = []
    if role == "patient" and patient_lang != "auto":
        expected_scripts = get_expected_scripts(patient_lang)
    elif role == "interpreter" and patient_lang != "auto":
        # Interpreter can use both provider and patient scripts
        expected_scripts = get_expected_scripts(provider_lang) + get_expected_scripts(patient_lang)

    # REMOVED: Offensive content detection - not clinically relevant
    # Focus only on clinical errors: omissions, fabrications, dosage errors, etc.
    # Interpreter professionalism/ethics are out of scope for medical accuracy monitoring

    # Check if script matches expected language (Indic scripts are valid, not gibberish!)
    if detected_script in expected_scripts and detected_script in ["gujarati", "devanagari", "arabic", "chinese"]:
        # Valid Indic/non-Latin script detected - mark as reliable even if Whisper says unknown
        asr_reliable = True
        # Override language if Whisper said unknown but we detected valid script
        if detected_language == "unknown" or detected_language == "auto":
            if role == "patient" and patient_lang != "auto":
                detected_language = patient_lang
                print(f"   ✅ Valid {detected_script} script detected for {patient_lang} - marking as reliable")
            elif role == "interpreter":
                # Guess based on script
                if detected_script in ["gujarati", "devanagari"] and patient_lang in ["gu", "hi"]:
                    detected_language = patient_lang
                    print(f"   ✅ Valid {detected_script} script detected - marking as {patient_lang}")

    # Check for unknown language with wrong script
    elif detected_language == "unknown" or detected_language not in ["en", "es", "gu", "hi", "pt", "zh", "ar", "fr", "de", "auto"]:
        # Check if script is completely wrong (e.g., Sinhala or Thai when expecting Gujarati)
        if detected_script in ["sinhala", "thai"] and expected_scripts and detected_script not in expected_scripts:
            asr_reliable = False
            print(f"   ⚠️ ASR UNRELIABLE: Wrong script {detected_script} (expected {expected_scripts}), likely Whisper hallucination")
        elif len(text) < 5:
            # Very short unknown language - probably noise
            asr_reliable = False
            print(f"   ⚠️ ASR UNRELIABLE: Unknown language with very short text ({len(text)} chars)")
        else:
            # Unknown language but reasonable length - might be valid
            # Only mark unreliable if we have strong evidence
            print(f"   ⚠️ Unknown language detected: {detected_language}, but text seems reasonable")

    # Check for high character entropy (gibberish detection) - BUT ONLY FOR LATIN SCRIPTS
    # Indic scripts naturally have high entropy, so we skip this check for them
    elif detected_script == "latin" and len(text) > 10:
        # Improved entropy check: Remove common valid characters before checking
        # Spanish/Portuguese have accented chars, question marks, etc. that are valid
        import re
        # Keep only alphanumeric and remove spaces
        cleaned_text = re.sub(r'[^a-zA-ZáéíóúñüÁÉÍÓÚÑÜ]', '', text.lower())
        if len(cleaned_text) > 0:
            unique_chars = len(set(cleaned_text))
            total_chars = len(cleaned_text)
            entropy_ratio = unique_chars / total_chars if total_chars > 0 else 0
            # Raised threshold to 0.85 to avoid false positives on Spanish/Portuguese
            # Real gibberish has 0.9+ entropy (every char is unique)
            if entropy_ratio > 0.85 and len(cleaned_text) > 15:
                asr_reliable = False
                print(f"   ⚠️ ASR UNRELIABLE: High character entropy detected ({entropy_ratio:.2f}) - possible gibberish")
            elif entropy_ratio > 0.7:
                # Medium entropy - just log but don't mark unreliable
                print(f"   ℹ️ Moderate character entropy ({entropy_ratio:.2f}) - text seems valid")

    if not asr_reliable:
        print(f"   🚨 ASR RELIABILITY WARNING: This transcript may be unreliable. Tribunal should not judge interpreter based on this segment.")

    # Add English translation for non-English segments (BEFORE creating segment for Tribunal)
    # This ensures the Tribunal has canonical English meaning and doesn't re-translate
    #
    # CRITICAL: Use different translation modes based on role:
    # - Provider/Patient: "ground_truth" mode (smooth, natural English)
    # - Interpreter: "interpreter_eval" mode (literal, error-preserving)
    english_translation_smooth = None
    english_translation_literal = None
    transliteration = None

    if detected_language not in ["en", "unknown", "auto"] and len(text.strip()) > 0:
        # Use ensemble translation for medical accuracy (3 strategies with consensus)
        openai_key = os.getenv("OPENAI_API_KEY", "")
        if openai_key:
            try:
                # Determine translation mode based on role
                if role == "interpreter":
                    # LITERAL MODE: Preserve errors for interpreter grading
                    # Example: "Lo siento porque yo escucho" → "I'm sorry because I listen" (NOT "I'm sorry to hear that")
                    translation_mode = "interpreter_eval"
                    print(f"   🔍 Using LITERAL translation mode for interpreter (error-preserving)")
                else:
                    # GROUND TRUTH MODE: Smooth, natural English for provider/patient
                    translation_mode = "ground_truth"
                    print(f"   ✅ Using GROUND TRUTH translation mode for {role} (smooth)")

                # ENSEMBLE MODE: Run 3 GPT-4o strategies in parallel with medical term validation
                translation_result = await EnsembleTranslation.translate_ensemble(
                    text=text,
                    suspected_language=detected_language,
                    api_key=openai_key,
                    mode=translation_mode,
                )

                # Store in appropriate field based on mode
                if translation_mode == "interpreter_eval":
                    english_translation_literal = translation_result.translation
                    print(f"   🌐 Translation (LITERAL): {text[:40]}... → {english_translation_literal[:40] if english_translation_literal else 'N/A'}...")
                else:
                    english_translation_smooth = translation_result.translation
                    print(f"   🌐 Translation (SMOOTH): {text[:40]}... → {english_translation_smooth[:40] if english_translation_smooth else 'N/A'}...")

                transliteration = translation_result.transliteration
            except Exception as e:
                print(f"   ⚠️ Translation failed: {str(e)}")

    segment = TranscriptSegment(
        role=role,  # type: ignore
        text=text,
        # Backward compatibility: populate old text_english field
        text_english=(english_translation_literal or english_translation_smooth) if (english_translation_literal or english_translation_smooth) else text,
        # New fields: separate smooth and literal translations
        text_english_smooth=english_translation_smooth if english_translation_smooth else (text if detected_language in ["en", "unknown", "auto"] else None),
        text_english_literal=english_translation_literal,
        timestamp=datetime.utcnow().timestamp(),
        duration=duration,
        confidence=1.0,
        is_final=True,
        segment_id=segment_id,
        asr_reliable=asr_reliable,
        detected_language=detected_language,
    )

    # Feed to engine if session active
    if session_active and engine:
        await engine.ingest_transcript(segment)

    # Prepare text in all 3 formats for QA/UI
    # For English text: original = english, no translation needed
    # For non-English: original = native script, transliteration = Latin, english = translation
    # IMPORTANT: Use smooth for provider/patient, literal for interpreter
    if detected_language in ["en", "unknown"]:
        text_original = text
        text_transliteration = None  # English doesn't need transliteration
        text_english = text  # Already English
    else:
        text_original = text  # Original script (Gujarati, Hindi, etc.)
        text_transliteration = transliteration  # Latin transliteration
        # Use literal for interpreter (shows errors), smooth for provider/patient (natural)
        if role == "interpreter":
            text_english = english_translation_literal or f"[No translation: {text}]"
        else:
            text_english = english_translation_smooth or f"[No translation: {text}]"

    # Broadcast transcript to all clients
    message = build_ws_message("transcript", {
        "role": role,
        # NEW FIELDS (QA-friendly):
        "text_original": text_original,  # Original script
        "text_transliteration": text_transliteration,  # Latin transliteration (or null for English)
        "text_english": text_english,  # English translation (smooth for P/P, literal for I)
        # OLD FIELDS (backwards compatibility - will deprecate):
        "text": text,  # Keep for legacy UI
        "english_translation": english_translation_literal or english_translation_smooth,
        "transliteration": transliteration,
        # METADATA:
        "timestamp": segment["timestamp"],
        "duration": duration,
        "confidence": 1.0,
        "is_final": True,
        "detected_language": detected_language,
        "segment_id": segment_id,
    })
    await manager.broadcast(message)

    return TranscriptionResponse(
        text=text,
        role=role,
        duration=duration,
        detected_language=detected_language,
        english_translation=english_translation_literal or english_translation_smooth,
        transliteration=transliteration
    )


# ===== Admin API Endpoints =====

class ASRSwitchRequest(BaseModel):
    backend: str

@app.get("/admin/asr-config")
async def get_asr_config():
    """Get current ASR backend configuration."""
    return {
        "current_config": asr_config.get_all(),
        "current_mode": asr_config.get_mode(),
        "groq_model": asr_config.get_groq_model(),
        "available_modes": ["groq-turbo", "groq-large", "ensemble", "openai"],
        "note": "Groq Whisper: Turbo=$0.04/hr (fast), Large=$0.111/hr (accurate). Ensemble runs Groq+OpenAI in parallel.",
    }


@app.post("/admin/asr-config/switch-default")
async def switch_default_asr(request: ASRSwitchRequest):
    """
    Switch ASR mode.

    Modes:
    - "groq-turbo": Groq Whisper Turbo ($0.04/hr, 228x speed) - DEFAULT
    - "groq-large": Groq Whisper Large ($0.111/hr, most accurate)
    - "ensemble": Run both Groq + OpenAI in parallel, pick best
    - "openai": Use only OpenAI gpt-4o-transcribe
    """
    backend = request.backend

    if backend == "groq-turbo" or backend == "groq":
        asr_config.set_default("groq-turbo")
        asr_config.set_groq_model("whisper-large-v3-turbo")
        asr_config.set_backend("provider", "en", "groq-turbo")
        asr_config.set_backend("patient", "auto", "groq-turbo")
        asr_config.set_backend("interpreter", "auto", "groq-turbo")
        return {
            "status": "success",
            "message": "Switched to Groq Whisper TURBO ($0.04/hr, 228x speed)",
            "config": asr_config.get_all()
        }
    elif backend == "groq-large":
        asr_config.set_default("groq-large")
        asr_config.set_groq_model("whisper-large-v3")
        asr_config.set_backend("provider", "en", "groq-large")
        asr_config.set_backend("patient", "auto", "groq-large")
        asr_config.set_backend("interpreter", "auto", "groq-large")
        return {
            "status": "success",
            "message": "Switched to Groq Whisper LARGE ($0.111/hr, most accurate)",
            "config": asr_config.get_all()
        }
    elif backend == "ensemble":
        asr_config.set_default("ensemble")
        asr_config.set_backend("provider", "en", "ensemble")
        asr_config.set_backend("patient", "auto", "ensemble")
        asr_config.set_backend("interpreter", "auto", "ensemble")
        return {
            "status": "success",
            "message": "Switched to ENSEMBLE mode (Groq + OpenAI in parallel)",
            "config": asr_config.get_all()
        }
    elif backend == "openai":
        asr_config.set_default("openai-gpt4o-transcribe")
        asr_config.set_backend("provider", "en", "openai-gpt4o-transcribe")
        asr_config.set_backend("patient", "auto", "openai-gpt4o-transcribe")
        asr_config.set_backend("interpreter", "auto", "openai-gpt4o-transcribe")
        return {
            "status": "success",
            "message": "Switched to OpenAI gpt-4o-transcribe",
            "config": asr_config.get_all()
        }
    else:
        raise HTTPException(status_code=400, detail=f"Invalid backend: {backend}. Use 'groq-turbo', 'groq-large', 'ensemble', or 'openai'")


@app.post("/admin/asr-config/update")
async def update_asr_config(config: dict):
    """
    Update ASR configuration directly.

    Example:
        {
            "provider_en": "groq",
            "patient_gu": "openai-gpt4o-transcribe",
            "interpreter_auto": "openai-gpt4o-transcribe"
        }
    """
    asr_config.update(config)
    return {"status": "success", "config": asr_config.get_all()}


# ===== WebSocket Endpoint =====

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time communication.

    Protocol (Phase 4 Jiva compliant):

    Frontend → Backend:
        - start_session: { session_id?: string }
        - stop_session: {}
        - transcript: TranscriptSegment (role, text, timestamp, duration, confidence, is_final)
        - audio_data: { segment: TranscriptSegment } (legacy/mock)
        - get_state: {} (debug)

    Backend → Frontend:
        - detected_error: ClinicalError with alignment_info
        - transcript: TranscriptSegment echo for rolling display
        - state_update: { sessionId, isActive, stats }
        - session_start: { session_id }
        - session_end: {}

    All messages are JSON: { "type": "<msg_type>", "data": {...}, "timestamp": <unix_ts> }
    """
    global session_active, session_id, engine

    await manager.connect(websocket)
    print(f"WebSocket client connected. Total connections: {manager.connection_count()}")

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                msg_type = message.get("type", "unknown")
                msg_data = message.get("data", {})

                if msg_type == "start_session":
                    # Handle session start via WebSocket
                    new_session_id = msg_data.get("session_id") or f"session_{uuid.uuid4().hex[:8]}"

                    if not session_active:
                        session_id = new_session_id
                        session_active = True

                        if engine:
                            await engine.start_session(session_id)

                        # Start error emission loop
                        global _processing_task
                        _processing_task = asyncio.create_task(emit_error_loop())

                    # Send confirmation to this client
                    response = build_ws_message("session_start", {"session_id": session_id})
                    await websocket.send_json(response)

                elif msg_type == "stop_session":
                    # Handle session stop via WebSocket
                    if session_active:
                        session_active = False
                        if engine:
                            await engine.stop_session()

                        if _processing_task and not _processing_task.done():
                            _processing_task.cancel()

                    response = build_ws_message("session_end", {})
                    await websocket.send_json(response)

                elif msg_type == "audio_data":
                    # Mock audio data ingestion (for simulation)
                    # In production, audio comes from LiveKit, not WebSocket
                    if session_active and engine:
                        segment_data = msg_data.get("segment")
                        if segment_data:
                            segment = TranscriptSegment(
                                role=StreamRole(segment_data.get("role", "provider")),
                                text=segment_data.get("text", ""),
                                timestamp=segment_data.get("timestamp", 0.0),
                                duration=segment_data.get("duration", 1.0),
                                confidence=segment_data.get("confidence", 0.9),
                                is_final=segment_data.get("is_final", True),
                                speaker_id=segment_data.get("speaker_id"),
                            )
                            await engine.ingest_transcript(segment)

                elif msg_type == "transcript":
                    # Transcript ingestion (Phase 4 Jiva protocol)
                    # Frontend sends structured TranscriptSegment, we ingest and echo back
                    if session_active and engine:
                        segment_data = msg_data  # data IS the segment (not nested)
                        if segment_data and segment_data.get("text"):
                            segment = TranscriptSegment(
                                role=StreamRole(segment_data.get("role", "provider")),
                                text=segment_data.get("text", ""),
                                timestamp=segment_data.get("timestamp", 0.0),
                                duration=segment_data.get("duration", 1.0),
                                confidence=segment_data.get("confidence", 0.9),
                                is_final=segment_data.get("is_final", True),
                                speaker_id=segment_data.get("speaker_id"),
                            )
                            await engine.ingest_transcript(segment)

                            # Echo transcript back to all clients for rolling display
                            echo_payload = segment_to_payload(segment)
                            echo_msg = build_ws_message("transcript", echo_payload)
                            await manager.broadcast(echo_msg)

                elif msg_type == "get_state":
                    # Return current state (for debugging)
                    if engine:
                        state = engine.get_state()
                        if state:
                            response = build_ws_message("state_update", {
                                "sessionId": state["session_id"],
                                "isActive": state["is_active"],
                                "stats": state["processing_stats"],
                            })
                            await websocket.send_json(response)

                else:
                    # Unknown message type
                    print(f"Unknown WebSocket message type: {msg_type}")

            except json.JSONDecodeError:
                print(f"Invalid JSON received: {data[:100]}")

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
        print(f"WebSocket client disconnected. Total connections: {manager.connection_count()}")

        # CRITICAL FIX: Auto-stop session when last client disconnects
        # This prevents session state from leaking into next connection
        if manager.connection_count() == 0 and session_active:
            print("⚠️ Last client disconnected - auto-stopping session to prevent state leak")
            session_active = False
            if engine:
                try:
                    await engine.stop_session()
                except Exception as e:
                    print(f"Error stopping engine on disconnect: {e}")

            if _processing_task and not _processing_task.done():
                _processing_task.cancel()
                try:
                    await _processing_task
                except asyncio.CancelledError:
                    pass

            print("✅ Session auto-stopped, ready for fresh session on reconnect")


# ===== Development Runner =====

if __name__ == "__main__":
    import uvicorn

    # Phase 6: Use PORT env var (Render assigns dynamic port)
    port = int(os.getenv("PORT", "8000"))

    print("\n" + "=" * 60)
    print("SARASVATI API Server - Phase 5: The Gatekeeper")
    print("=" * 60)
    print(f"\nPort: {port}")
    print("\nEndpoints:")
    print("  - GET  /health          Health check")
    print("  - POST /session/start   Start monitoring session")
    print("  - POST /session/stop    Stop monitoring session")
    print("  - WS   /ws              WebSocket for real-time events")
    print("\nRun with: uvicorn sarasvati.api.server:app --host 0.0.0.0 --port $PORT --reload")
    print("=" * 60 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=port)
