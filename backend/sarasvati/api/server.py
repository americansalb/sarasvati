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
import os
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, Set, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form
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

# Independent Tribunal: 3 TOTALLY DIFFERENT model families for maximum diversity
# Using LARGEST available models from each company on Groq - critical for medical interpretation
# NOTE: Claude (Anthropic), GPT (OpenAI), and Gemini (Google) are NOT available via Groq
# Groq only provides open-source models. For proprietary models, we'd need multi-provider architecture.
# WARNING: Groq has decommissioned all Gemma models (gemma2-27b-it, gemma2-9b-it)
_model_extractor = os.getenv("GROQ_MODEL_EXTRACTOR", "llama-3.3-70b-versatile")  # Meta AI (70B, latest Llama)
_model_monitor = os.getenv("GROQ_MODEL_MONITOR", "mixtral-8x7b-32768")           # Mistral AI (MoE, 46.7B active)
_model_arbiter = os.getenv("GROQ_MODEL_ARBITER", "llama-3.1-8b-instant")         # Meta AI (8B, fast inference - Gemma deprecated)

DEFAULT_CONFIG = GraphConfig(
    max_buffer_size=50,
    alignment_threshold=0.40,  # Lowered for cross-lingual matching (was 0.65)
    alignment_window_seconds=30.0,
    debounce_ms=500,
    enable_negation_check=True,
    groq_model_extractor=_model_extractor,   # Node A: Meta Llama 3.3 70B
    groq_model_monitor=_model_monitor,       # Node B: Mistral Mixtral 8x7B MoE
    groq_model_arbiter=_model_arbiter,       # Node C: Meta Llama 3.1 8B (Gemma decommissioned)
    redis_host=_redis_host,
    redis_port=_redis_port,
    redis_db=_redis_db,
    livekit_url="wss://localhost:7880",
    deepgram_api_key="",
)


# ===== Pydantic Models (Request/Response) =====

class SessionStartRequest(BaseModel):
    session_id: Optional[str] = None


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
        """Broadcast a message to all connected clients."""
        async with self._lock:
            connections = list(self.active_connections)

        # Send to all connections, removing dead ones
        dead_connections = []
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:
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

# Background task for processing
_processing_task: Optional[asyncio.Task] = None

# Session lock to prevent race conditions on start/stop
_session_lock = asyncio.Lock()


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

    return {
        "error_id": error["error_id"],
        "severity": error["severity"].value if hasattr(error["severity"], "value") else error["severity"],
        "error_type": error["error_type"],
        "provider_entity": error["provider_entity"],
        "interpreter_entity": error["interpreter_entity"],
        "description": error["description"],
        "arbiter_reasoning": error["arbiter_reasoning"],
        "confidence": error["confidence"],
        "detected_at": error["detected_at"].isoformat() if isinstance(error["detected_at"], datetime) else error["detected_at"],
        "alignment_info": alignment_to_payload(error["alignment_info"]) if error["alignment_info"] else None,
        "is_system_error": error.get("is_system_error", False),
        "case_type": case_type,
    }


def alignment_to_payload(alignment: AlignmentMatch) -> Dict[str, Any]:
    """Convert AlignmentMatch to JSON-serializable dict."""
    return {
        "provider_segment": segment_to_payload(alignment["provider_segment"]),
        "interpreter_segment": segment_to_payload(alignment["interpreter_segment"]) if alignment["interpreter_segment"] else None,
        "similarity_score": alignment["similarity_score"],
        "combined_score": alignment["combined_score"],
        "time_delta": alignment["time_delta"],
        "is_matched": alignment["is_matched"],
        "dtw_distance": alignment["dtw_distance"],
    }


def segment_to_payload(segment: TranscriptSegment) -> Dict[str, Any]:
    """Convert TranscriptSegment to JSON-serializable dict."""
    return {
        "role": segment["role"].value if hasattr(segment["role"], "value") else segment["role"],
        "text": segment["text"],
        "timestamp": segment["timestamp"],
        "duration": segment["duration"],
        "confidence": segment["confidence"],
        "is_final": segment["is_final"],
        "speaker_id": segment.get("speaker_id"),
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
                        num_errors = len(debate_result.get("detected_errors", []))
                        severity = "none"
                        if num_errors > 0:
                            # Get max severity from errors
                            severities = [e.get("severity", "medium") for e in debate_result.get("detected_errors", [])]
                            if any(s == "critical" for s in severities):
                                severity = "critical"
                            elif any(s == "high" for s in severities):
                                severity = "high"
                            elif any(s == "medium" for s in severities):
                                severity = "medium"
                            else:
                                severity = "low"

                        confidence = compute_confidence(severity, num_errors)

                        verdict_payload = {
                            "confidence": confidence,
                            "severity": severity,
                            "num_issues": num_errors,
                            "arbiter_decision": debate_result.get("arbiter_decision", ""),
                            "monitor_findings": debate_result.get("monitor_findings", []),
                            "errors": [
                                {
                                    "severity": str(e.get("severity", "medium")),
                                    "error_type": e.get("error_type", "unknown"),
                                    "description": e.get("description", ""),
                                }
                                for e in debate_result.get("detected_errors", [])
                            ],
                        }

                        message = build_ws_message("tribunal_verdict", verdict_payload)
                        await manager.broadcast(message)
                        print(f"📢 Broadcast tribunal_verdict: confidence={confidence:.2f}, severity={severity}, issues={num_errors}")

                    last_verdict_count = current_verdict_count

                # Also emit individual errors (for backwards compatibility)
                current_errors = state["detected_errors"]
                new_error_count = len(current_errors)

                if new_error_count > last_error_count:
                    new_errors = current_errors[last_error_count:]
                    for error in new_errors:
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
    Start a new monitoring session.

    Creates a new session and initializes a FRESH engine.
    CRITICAL: Each session gets its own engine to prevent state leakage.
    """
    global session_active, session_id, session_start_time, _processing_task, engine

    if session_active:
        raise HTTPException(status_code=409, detail="Session already active")

    # Generate session ID if not provided
    session_id = request.session_id or f"session_{uuid.uuid4().hex[:8]}"
    session_start_time = datetime.utcnow()
    session_active = True

    # CRITICAL FIX: Create a fresh engine for each session to prevent state leakage
    # The old engine's buffers/state would carry over otherwise
    print(f"🔄 Creating fresh engine for session {session_id}")
    engine = create_engine(DEFAULT_CONFIG)
    await engine.start_session(session_id)
    print(f"✅ Fresh engine initialized for session {session_id}")

    # Start background error emission loop
    _processing_task = asyncio.create_task(emit_error_loop())

    # Broadcast session start
    message = build_ws_message("session_start", {"session_id": session_id})
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
    global session_active, session_id, session_start_time, _processing_task, engine

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


async def call_whisper(client: httpx.AsyncClient, audio_data: bytes, filename: str, content_type: str, language: str, api_key: str) -> dict:
    """Helper to call Whisper API with a specific language hint."""
    whisper_data: dict = {"model": "whisper-large-v3", "response_format": "json"}
    if language and language != "auto":
        whisper_data["language"] = language

    response = await client.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {api_key}"},
        files={"file": (filename, audio_data, content_type)},
        data=whisper_data,
        timeout=30.0,
    )
    if response.status_code != 200:
        return {"text": "", "duration": 0.0, "error": response.text}
    return response.json()


@app.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    audio: UploadFile = File(...),
    role: str = Form(default="provider"),
    language: str = Form(default="auto"),
    provider_lang: str = Form(default="en"),
    patient_lang: str = Form(default="auto"),
) -> TranscriptionResponse:
    """
    Transcribe audio using Groq Whisper API.
    Accepts audio file, role (provider/interpreter/patient), and language hints.
    For interpreter: runs Whisper with both languages plus an auto-detect pass and
    chooses the transcript that matches the detected language when possible.
    """
    global engine, session_active

    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured")

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

            result_auto, result_provider, result_patient = await asyncio.gather(
                call_whisper(client, audio_data, filename, content_type, "auto", groq_api_key),
                call_whisper(client, audio_data, filename, content_type, provider_lang, groq_api_key),
                call_whisper(client, audio_data, filename, content_type, patient_lang, groq_api_key),
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

            for name, candidate in (
                ("auto", candidate_auto),
                ("provider", candidate_provider),
                ("patient", candidate_patient),
            ):
                if candidate.get("error"):
                    print(f"   ⚠️ Whisper error for {name} hint: {candidate['error']}")

            # Debug logging: show all candidates
            print(f"   📊 Candidates:")
            print(f"      auto: '{candidate_auto['text'][:50]}...' (lang={candidate_auto['lang']}, len={len(candidate_auto['text'])})")
            print(f"      {provider_lang}_hint: '{candidate_provider['text'][:50]}...' (len={len(candidate_provider['text'])})")
            print(f"      {patient_lang}_hint: '{candidate_patient['text'][:50]}...' (len={len(candidate_patient['text'])})")

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
        else:
            # For provider/patient or when languages are same: ALWAYS use auto-detect
            # CRITICAL: Language hints cause Whisper to TRANSLATE, not transcribe!
            # We must ALWAYS use "auto" to get accurate transcription in the original language
            result = await call_whisper(client, audio_data, filename, content_type, "auto", groq_api_key)
            if "error" in result:
                raise HTTPException(status_code=500, detail=f"Groq API error: {result['error']}")
            text = result.get("text", "").strip()
            duration = result.get("duration", 0.0)
            detected_language = result.get("language", "auto")

    # Create transcript segment
    segment = TranscriptSegment(
        role=role,  # type: ignore
        text=text,
        timestamp=datetime.utcnow().timestamp(),
        duration=duration,
        confidence=1.0,
        is_final=True,
    )

    # Feed to engine if session active
    if session_active and engine:
        await engine.ingest_transcript(segment)

    # Broadcast transcript to all clients
    message = build_ws_message("transcript", {
        "role": role,
        "text": text,
        "timestamp": segment["timestamp"],
        "duration": duration,
        "confidence": 1.0,
        "is_final": True,
        "detected_language": detected_language,
    })
    await manager.broadcast(message)

    return TranscriptionResponse(text=text, role=role, duration=duration, detected_language=detected_language)


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
