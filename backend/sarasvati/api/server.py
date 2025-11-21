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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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

DEFAULT_CONFIG = GraphConfig(
    max_buffer_size=50,
    alignment_threshold=0.65,
    alignment_window_seconds=30.0,
    debounce_ms=500,
    enable_negation_check=True,
    groq_model_verification="llama-3.1-70b-versatile",
    groq_model_drafting="llama-3.1-8b-instant",
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

    This matches frontend/src/hooks/useSarasvatiBackend.ts exactly.
    """
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
        "alignment_info": alignment_to_payload(error["alignment_info"]),
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
    Background loop that monitors for new errors and broadcasts them.

    Runs every 100ms to check for new errors in the engine state.
    Uses single-flight pattern to avoid duplicate emissions.
    """
    global engine, session_active

    last_error_count = 0

    while session_active and engine:
        try:
            state = engine.get_state()
            if state:
                current_errors = state["detected_errors"]
                new_error_count = len(current_errors)

                # Emit any new errors
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

    Creates a new session and initializes the engine.
    """
    global session_active, session_id, session_start_time, _processing_task, engine

    if session_active:
        raise HTTPException(status_code=409, detail="Session already active")

    # Generate session ID if not provided
    session_id = request.session_id or f"session_{uuid.uuid4().hex[:8]}"
    session_start_time = datetime.utcnow()
    session_active = True

    # Start engine session
    if engine:
        await engine.start_session(session_id)

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
