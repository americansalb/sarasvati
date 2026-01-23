"""
SARASVATI LangGraph Processing Loop
====================================
The cyclic stateful graph that orchestrates the Trisul Protocol.

Flow: ingest → align → extract → monitor → arbitrate → report → (loop)

This is the heart of the system - a continuous processing loop that:
1. Ingests transcript segments from LiveKit
2. Aligns provider and interpreter streams
3. Runs adversarial agent debate
4. Reports clinical errors in real-time
"""

from typing import Literal, Optional, Dict, Any, List
from datetime import datetime
import asyncio
import os

try:
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.memory import MemorySaver
    # PHASE 1 FIX: Import SqliteSaver for persistent checkpointing
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        SQLITE_SAVER_AVAILABLE = True
    except ImportError:
        SqliteSaver = None
        SQLITE_SAVER_AVAILABLE = False
except ImportError:
    # Fallback for development without langgraph
    StateGraph = None
    END = None
    MemorySaver = None
    SqliteSaver = None
    SQLITE_SAVER_AVAILABLE = False

from .state import (
    SarasvatiState,
    TranscriptSegment,
    BufferEntry,
    StreamRole,
    GraphConfig,
    create_initial_state,
    AlignmentMatch,
)
from .alignment import AlignmentEngine, BatchAligner, create_alignment_engine
from .agent import ClinicalDebateOrchestrator
from .tribunal import DualTribunalOrchestrator


class SarasvatiGraph:
    """
    Main LangGraph implementation for Trisul Protocol.

    This class builds and manages the cyclic processing graph.
    """

    def __init__(self, config: GraphConfig):
        if StateGraph is None:
            raise ImportError(
                "langgraph not installed. Install with: pip install langgraph"
            )

        self.config = config

        # Initialize components
        self.alignment_engine = create_alignment_engine(
            window_seconds=config["alignment_window_seconds"],
            similarity_threshold=config["alignment_threshold"],
        )
        self.batch_aligner = BatchAligner(self.alignment_engine)
        # Import configurable defaults from agent module
        from .agent import (
            DEFAULT_MODEL_A, DEFAULT_MODEL_B, DEFAULT_MODEL_C,
            DEFAULT_PROVIDER_A, DEFAULT_PROVIDER_B, DEFAULT_PROVIDER_C,
        )

        self.debate_orchestrator = ClinicalDebateOrchestrator(
            # API Keys - set via environment variables
            groq_api_key=os.environ.get("GROQ_API_KEY", ""),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            # Models - configurable via TRIBUNAL_MODEL_A/B/C env vars
            model_a=DEFAULT_MODEL_A,
            model_b=DEFAULT_MODEL_B,
            model_c=DEFAULT_MODEL_C,
            # Providers - configurable via TRIBUNAL_PROVIDER_A/B/C env vars
            provider_a=DEFAULT_PROVIDER_A,
            provider_b=DEFAULT_PROVIDER_B,
            provider_c=DEFAULT_PROVIDER_C,
        )

        # NEW: Dual Tribunal Orchestrator (Translation + Error with visible debate)
        # This is the NEW two-stage tribunal architecture with visible debate logs
        self.dual_tribunal = None
        try:
            self.dual_tribunal = DualTribunalOrchestrator(
                groq_api_key=os.environ.get("GROQ_API_KEY", ""),
                openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
                anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
                model_a=DEFAULT_MODEL_A,
                model_b=DEFAULT_MODEL_B,
                model_c=DEFAULT_MODEL_C,
            )
            print("✅ Dual Tribunal (Translation + Error) initialized with Anthropic")
        except Exception as e:
            print(f"⚠️ Dual Tribunal init failed, using legacy orchestrator: {e}")

        # Build the graph
        self.graph = self._build_graph()
        self.compiled_graph = None

    def _build_graph(self) -> StateGraph:
        """
        Build the LangGraph state machine.

        Nodes:
        - ingest_node: Receives transcript segments
        - align_node: Performs temporal alignment
        - extract_node: Node A entity extraction
        - monitor_node: Node B omission checking
        - arbiter_node: Node C final decision
        - report_node: Emit errors to monitoring

        Edges define the cyclic flow with conditional routing.
        """
        # Create graph with our state schema
        workflow = StateGraph(SarasvatiState)

        # Add nodes
        workflow.add_node("ingest", self.ingest_node)
        workflow.add_node("align", self.align_node)
        workflow.add_node("verify", self.verify_node)  # Combined extract+monitor+arbiter
        workflow.add_node("report", self.report_node)

        # Define edges
        # Start -> ingest
        workflow.set_entry_point("ingest")

        # ingest -> align (always)
        workflow.add_edge("ingest", "align")

        # align -> verify or back to ingest (conditional)
        workflow.add_conditional_edges(
            "align",
            self._should_verify,
            {
                "verify": "verify",
                "wait": END,  # End cycle if not enough data
            },
        )

        # verify -> report (always)
        workflow.add_edge("verify", "report")

        # report -> ingest or END (conditional)
        workflow.add_conditional_edges(
            "report",
            self._should_continue,
            {
                "continue": "ingest",
                "end": END,
            },
        )

        return workflow

    def compile(self) -> Any:
        """
        Compile the graph for execution.

        PHASE 1 FIX: Use SqliteSaver for persistent checkpointing (crash recovery).

        Returns:
            Compiled graph ready for invocation
        """
        # PHASE 1 FIX: Use SqliteSaver for persistent checkpointing if available
        import os
        if SQLITE_SAVER_AVAILABLE and SqliteSaver:
            checkpoint_path = os.getenv(
                "SARASVATI_CHECKPOINT_DB",
                "/tmp/sarasvati_checkpoints.db"
            )
            try:
                memory = SqliteSaver.from_conn_string(checkpoint_path)
                print(f"✅ Using persistent checkpointing: {checkpoint_path}")
            except Exception as e:
                print(f"⚠️  Failed to initialize SqliteSaver: {e}")
                print("   Falling back to in-memory checkpointing")
                memory = MemorySaver()
        else:
            # Fallback to in-memory checkpointing
            print("⚠️  SqliteSaver not available, using in-memory checkpointing (no crash recovery)")
            memory = MemorySaver()

        self.compiled_graph = self.graph.compile(checkpointer=memory)
        self.checkpointer = memory  # Store reference for crash recovery
        return self.compiled_graph

    # ===== Graph Node Implementations =====

    async def ingest_node(self, state: SarasvatiState) -> SarasvatiState:
        """
        Node 1: Ingest transcript segments.

        This node receives transcript segments from LiveKit and adds them
        to the appropriate stream buffer.

        In production, this would be called by LiveKit recv() loop.
        For MVP, this is a placeholder that simulates ingestion.
        """
        # NOTE: In production, this receives segments from LiveKit
        # For MVP, we assume segments are being added externally

        # Check buffer sizes
        provider_size = len(state["provider_buffer"])
        interpreter_size = len(state["interpreter_buffer"])

        # Update stats
        state["processing_stats"]["segments_processed"] += 1

        # If buffers are getting large, set flag to force processing
        if provider_size >= state["buffer_size_limit"]:
            state["should_emit_report"] = True

        return state

    async def align_node(self, state: SarasvatiState) -> SarasvatiState:
        """
        Node 2: Align provider and interpreter streams.

        This is where the DTW/semantic similarity magic happens.
        We find matching segments despite the temporal delay.
        """
        # Process batch of unaligned segments
        alignments = await self.batch_aligner.process_buffer_batch(state)

        # Add alignments to state
        state["matched_pairs"].extend(alignments)

        # Update stats
        matched_count = sum(1 for a in alignments if a["is_matched"])
        missed_count = len(alignments) - matched_count

        state["processing_stats"]["alignments_found"] += matched_count
        state["processing_stats"]["alignments_missed"] += missed_count

        print(f"   🔗 Alignment: found {len(alignments)} alignments ({matched_count} matched, {missed_count} missed)")

        return state

    async def verify_node(self, state: SarasvatiState) -> SarasvatiState:
        """
        Node 3: Verify interpretation quality (Combined Extract+Monitor+Arbiter).

        Runs the three-agent debate system on ALL tribunal cases.

        CRITICAL ARCHITECTURAL CHANGE (per Shiva's guidance):
        - EVERY utterance goes to tribunal review
        - Alignment determines TYPE of review (not WHETHER it happens)
        - Case types: ALIGNED_OUTBOUND, ALIGNED_INBOUND, OMISSION_OUTBOUND,
          OMISSION_INBOUND, FABRICATION

        CRITICAL FIX: Only process NEW cases (not already verified).
        Update last_verified_count after processing to prevent infinite loops.
        """
        # Get ALL cases (matched and unmatched) - tribunal reviews everything
        all_cases = state["matched_pairs"]

        # Get only NEW unverified cases (since last verification)
        last_verified = state["last_verified_count"]
        new_cases = all_cases[last_verified:]

        if not new_cases:
            print(f"   📭 No new cases to verify (total_cases={len(all_cases)}, last_verified={last_verified})")
            return state

        # Get most recent patient text for triadic validation (Trisul Protocol)
        patient_text = ""
        if state["patient_buffer"]:
            # Get most recent patient segment
            patient_text = state["patient_buffer"][-1]["segment"]["text"]

        print(f"   ⚖️  Running tribunal on {len(new_cases)} new cases. Patient context: {patient_text[:50] if patient_text else 'NONE'}...")

        # Run debate for each NEW case (matched, omission, or fabrication)
        for case in new_cases:
            case_type = case.get("case_type", "unknown")
            provider_seg = case.get('provider_segment')
            interp_seg = case.get('interpreter_segment')
            provider_text = provider_seg['text'][:40] if provider_seg else 'NONE'
            interp_text = interp_seg['text'][:40] if interp_seg else 'NONE'

            print(f"      🔍 [{case_type}] P='{provider_text}...' vs I='{interp_text}...'")

            # ═══════════════════════════════════════════════════════════
            # TWO-TRIBUNAL ARCHITECTURE (if available)
            # Stage 1: Translation Tribunal - 3 agents debate on meaning
            # Stage 2: Error Tribunal - 3 agents debate on errors
            # ═══════════════════════════════════════════════════════════
            debate_result = None
            if self.dual_tribunal and provider_seg and interp_seg:
                # Extract raw text and detected languages
                raw_source = provider_seg.get("text", "")
                raw_interp = interp_seg.get("text", "")
                source_lang = provider_seg.get("detected_language", "en")
                interp_lang = interp_seg.get("detected_language", "en")

                # Determine source role based on case type
                if "inbound" in str(case_type).lower():
                    source_role = "patient"
                else:
                    source_role = "provider"

                try:
                    print(f"      🏛️  DUAL TRIBUNAL: Translation + Error (with visible debate)")
                    tribunal_result = await self.dual_tribunal.evaluate_interpretation(
                        raw_source_text=raw_source,
                        raw_interpreter_text=raw_interp,
                        source_language=source_lang,
                        interpreter_language=interp_lang,
                        source_role=source_role,
                    )

                    # Convert tribunal result to AgentDebateResult format
                    from .state import ClinicalError, ErrorSeverity
                    detected_errors = []
                    for err in tribunal_result.get("errors", []):
                        severity_map = {
                            "critical": ErrorSeverity.CRITICAL,
                            "high": ErrorSeverity.HIGH,
                            "medium": ErrorSeverity.MEDIUM,
                            "low": ErrorSeverity.LOW,
                        }
                        detected_errors.append(ClinicalError(
                            error_id=f"err_{datetime.utcnow().timestamp()}_{err.get('type', 'unknown')}",
                            severity=severity_map.get(err.get("severity", "medium"), ErrorSeverity.MEDIUM),
                            error_type=err.get("type", "unknown"),
                            provider_entity=None,
                            interpreter_entity=None,
                            description=err.get("description", ""),
                            arbiter_reasoning=f"Tribunal verdict: {tribunal_result.get('verdict', 'unknown')}",
                            confidence=0.9 if tribunal_result.get("consensus_reached", False) else 0.6,
                            detected_at=datetime.utcnow(),
                            alignment_info=case,
                            is_system_error=False,
                            source_role=source_role,
                            interpreter_quote=tribunal_result.get("interpreter_meaning", ""),
                            source_quote=tribunal_result.get("source_meaning", ""),
                            ideal_interpretation=None,
                        ))

                    debate_result = {
                        "extractor_entities": [],
                        "monitor_findings": [f"Tribunal verdict: {tribunal_result.get('verdict', 'unknown')}"],
                        "arbiter_decision": f"[{tribunal_result.get('verdict', 'unknown').upper()}] Consensus: {tribunal_result.get('consensus_reached', False)}. Source meaning: {tribunal_result.get('source_meaning', '')[:100]}... Interpreter meaning: {tribunal_result.get('interpreter_meaning', '')[:100]}...",
                        "detected_errors": detected_errors,
                        "processing_time_ms": 0,
                        "debate_logs": tribunal_result.get("debate_logs", {}),
                    }
                    print(f"      📋 Dual Tribunal verdict: {tribunal_result.get('verdict', '?')}, consensus: {tribunal_result.get('consensus_reached', '?')}")
                except Exception as e:
                    print(f"      ⚠️ Dual tribunal failed, falling back: {e}")
                    import traceback
                    traceback.print_exc()
                    debate_result = None

            # Fallback to legacy orchestrator
            if debate_result is None:
                debate_result = await self.debate_orchestrator.run_debate(case, patient_text)
                debate_result["debate_logs"] = None  # Legacy doesn't have structured debate logs

            # Store result
            state["last_debate_result"] = debate_result
            print(f"      📋 Verdict: {debate_result['arbiter_decision'][:100]}...")

            # Add any detected errors
            if debate_result["detected_errors"]:
                state["detected_errors"].extend(debate_result["detected_errors"])
                state["should_emit_report"] = True
                print(f"      🚨 ERRORS FOUND: {len(debate_result['detected_errors'])}")

                # Update error flags
                for error in debate_result["detected_errors"]:
                    state["error_flags"][error["error_id"]] = True
            else:
                print(f"      ✅ No errors detected")

        # Update last_verified_count to current total case count
        state["last_verified_count"] = len(all_cases)

        # Update stats
        state["processing_stats"]["errors_detected"] = len(state["detected_errors"])

        # PHASE 3: Update session analytics
        self._update_analytics(state, new_cases)

        return state

    def _update_analytics(self, state: SarasvatiState, processed_cases: List[AlignmentMatch]) -> None:
        """
        PHASE 3: Update session analytics with latest debate results.

        Args:
            state: Current state with session_analytics
            processed_cases: Cases just processed in this cycle
        """
        if not state.get("session_analytics"):
            return

        analytics = state["session_analytics"]
        debate_result = state.get("last_debate_result")

        if not debate_result:
            return

        # Update consensus metrics from debate logs
        debate_logs = debate_result.get("debate_logs", {})
        if debate_logs:
            for log_key, log in debate_logs.items():
                if log and isinstance(log, dict):
                    analytics["consensus_metrics"]["total_debates"] += 1

                    # Track convergence type
                    convergence_type = log.get("convergence_type")
                    if convergence_type == "full_consensus":
                        analytics["consensus_metrics"]["full_consensus_count"] += 1
                    elif convergence_type == "strong_majority":
                        analytics["consensus_metrics"]["strong_majority_count"] += 1
                    elif convergence_type == "structured_dissent":
                        analytics["consensus_metrics"]["structured_dissent_count"] += 1

                    # Track rounds to consensus
                    rounds = log.get("rounds_taken", 0)
                    if rounds > 0:
                        current_avg = analytics["consensus_metrics"]["avg_rounds_to_consensus"]
                        total = analytics["consensus_metrics"]["total_debates"]
                        new_avg = (current_avg * (total - 1) + rounds) / total if total > 0 else rounds
                        analytics["consensus_metrics"]["avg_rounds_to_consensus"] = new_avg

        # Update error concentration (time buckets)
        if state["detected_errors"]:
            session_duration = (datetime.utcnow() - state["session_start"]).total_seconds()
            time_bucket = f"{int(session_duration // 30) * 30}s"  # 30-second buckets
            analytics["error_concentration"][time_bucket] = analytics["error_concentration"].get(time_bucket, 0) + len(processed_cases)

    async def report_node(self, state: SarasvatiState) -> SarasvatiState:
        """
        Node 4: Report errors to monitoring system.

        Emits critical errors for human review.
        """
        if not state["should_emit_report"]:
            return state

        # Get unreported errors (in production, track which errors have been reported)
        errors_to_report = state["detected_errors"]

        if errors_to_report:
            # Separate clinical errors from system/ASR errors
            clinical_errors = [e for e in errors_to_report if not e.get("is_system_error", False)]
            system_errors = [e for e in errors_to_report if e.get("is_system_error", False)]

            # In production, this would:
            # 1. Push to Redis pub/sub
            # 2. Send to WebSocket connections
            # 3. Log to monitoring system
            # 4. Trigger alerts for CRITICAL errors

            print(f"\n{'='*60}")
            print(f"🚨 CLINICAL ERRORS DETECTED: {len(clinical_errors)}")
            if system_errors:
                print(f"🛠️  SYSTEM / ASR ISSUES: {len(system_errors)}")
            print(f"{'='*60}")

            # Display clinical errors in detail
            for error in clinical_errors:
                severity_emoji = {
                    "critical": "🔴",
                    "high": "🟠",
                    "medium": "🟡",
                    "low": "🟢",
                }
                emoji = severity_emoji.get(error["severity"], "⚪")

                print(f"\n{emoji} [{error['severity'].upper()}] {error['error_type']}")
                print(f"   Description: {error['description']}")
                print(f"   Confidence: {error['confidence']:.2f}")
                print(f"   Detected at: {error['detected_at']}")

            # Display system errors (ASR issues) separately with less detail
            if system_errors:
                print(f"\n{'─'*60}")
                print(f"🛠️  SYSTEM / ASR ISSUES ({len(system_errors)}):")
                print(f"{'─'*60}")
                for error in system_errors:
                    print(f"\n🟡 [{error['severity'].upper()}] {error['error_type']}")
                    print(f"   Description: {error['description'][:100]}...")

            print(f"\n{'='*60}\n")

        # Reset report flag
        state["should_emit_report"] = False

        return state

    # ===== Conditional Edge Functions =====

    def _should_verify(
        self,
        state: SarasvatiState,
    ) -> Literal["verify", "wait"]:
        """
        Decide whether to proceed to verification or wait for more data.

        We verify if:
        - We have NEW unverified matched alignments (not historical ones!)
        - Buffer is near capacity (force processing)

        CRITICAL FIX: Only check for NEW matches, not ALL historical matches.
        Otherwise we loop forever once we get a single match.
        """
        # Count matched (not unmatched) pairs
        current_match_count = sum(
            1 for match in state["matched_pairs"] if match["is_matched"]
        )

        # Check if we have NEW matches since last verification
        has_new_matches = current_match_count > state["last_verified_count"]

        buffer_near_capacity = (
            len(state["provider_buffer"]) >= state["buffer_size_limit"] * 0.8
        )

        if has_new_matches or buffer_near_capacity:
            return "verify"
        else:
            return "wait"

    def _should_continue(
        self,
        state: SarasvatiState,
    ) -> Literal["continue", "end"]:
        """
        Decide whether to continue processing or end this cycle.

        Always return "end" to complete the graph cycle.
        The external _process_cycle loop handles continuous processing.
        """
        # Always end the cycle - external loop drives continuous processing
        return "end"


# ===== High-Level API =====

class SarasvatiEngine:
    """
    High-level API for the Sarasvati monitoring system.

    This is the main entry point for integrating with LiveKit.
    """

    def __init__(self, config: GraphConfig):
        self.config = config
        self.graph = SarasvatiGraph(config)
        self.compiled = self.graph.compile()
        self.state: Optional[SarasvatiState] = None
        self.session_id: Optional[str] = None

        # Single-flight guard
        self._processing_task: Optional[asyncio.Task] = None

        # PHASE 1 FIX: Add locks for thread-safe state management
        self._state_lock = asyncio.Lock()  # Protects self.state updates
        self._cycle_lock = asyncio.Lock()  # Single-flight guarantee for processing cycles

        # PHASE 1 FIX: Circuit breaker for failure resilience
        self._failure_count = 0
        self._circuit_open = False
        self._circuit_open_time: Optional[datetime] = None
        self._circuit_threshold = 3  # Open circuit after 3 consecutive failures
        self._circuit_reset_seconds = 60  # Reset circuit after 60 seconds

    async def start_session(self, session_id: str) -> None:
        """
        Start a new monitoring session.

        Args:
            session_id: Unique identifier for this session
        """
        self.session_id = session_id
        self.state = create_initial_state(session_id, self.config)

        print(f"🟢 Sarasvati session {session_id} started")
        print(f"   Monitoring 3 streams: Provider, Interpreter, Patient")
        print(f"   Alignment window: {self.config['alignment_window_seconds']}s")
        print(f"   Using models: {self.config['groq_model_extractor']}, {self.config['groq_model_monitor']}, {self.config['groq_model_arbiter']}")

    async def ingest_transcript(
        self,
        segment: TranscriptSegment,
    ) -> None:
        """
        Ingest a new transcript segment.

        This is called by LiveKit recv() loop whenever new transcription
        arrives from Deepgram.

        Args:
            segment: Transcript segment with role, text, timestamp
        """
        if not self.state:
            raise RuntimeError("Session not started. Call start_session() first.")

        # Add to appropriate buffer
        buffer_entry = BufferEntry(
            segment=segment,
            entities=[],
            buffered_at=datetime.utcnow(),
            is_processed=False,
            alignment_attempts=0,
        )

        if segment["role"] == StreamRole.PROVIDER:
            self.state["provider_buffer"].append(buffer_entry)
        elif segment["role"] == StreamRole.INTERPRETER:
            self.state["interpreter_buffer"].append(buffer_entry)
        elif segment["role"] == StreamRole.PATIENT:
            self.state["patient_buffer"].append(buffer_entry)

        # Trigger processing when we have segments to align
        # Changed from >= 3 to >= 1 for responsive real-time monitoring
        provider_count = len(self.state["provider_buffer"])
        interpreter_count = len(self.state["interpreter_buffer"])

        # Trigger if we have both provider and interpreter segments
        if provider_count >= 1 and interpreter_count >= 1:
            # Single-flight: only one cycle at a time
            if not self._processing_task or self._processing_task.done():
                self._processing_task = asyncio.create_task(self._process_cycle())

    async def _process_cycle(self) -> None:
        """
        Run one processing cycle through the graph.

        This executes: ingest -> align -> verify -> report

        PHASE 1 FIX: Includes circuit breaker to prevent cascading failures.
        """
        if not self.state:
            return

        # PHASE 1 FIX: Check circuit breaker
        if self._circuit_open:
            # Check if enough time has passed to reset circuit
            if self._circuit_open_time:
                elapsed = (datetime.utcnow() - self._circuit_open_time).total_seconds()
                if elapsed >= self._circuit_reset_seconds:
                    print(f"🔄 Circuit breaker reset after {elapsed:.1f}s")
                    self._circuit_open = False
                    self._circuit_open_time = None
                    self._failure_count = 0
                else:
                    print(f"⚠️  Circuit breaker OPEN - skipping cycle ({elapsed:.1f}s/{self._circuit_reset_seconds}s)")
                    return

        # PHASE 1 FIX: Single-flight guarantee - only one cycle at a time
        async with self._cycle_lock:
            try:
                print(f"🔄 Processing cycle started. Buffers: P={len(self.state['provider_buffer'])}, I={len(self.state['interpreter_buffer'])}, Pt={len(self.state['patient_buffer'])}")

                # PHASE 1 FIX: Add 30-second timeout to prevent hanging
                result = await asyncio.wait_for(
                    self.compiled.ainvoke(
                        self.state,
                        config={"configurable": {"thread_id": self.session_id}},
                    ),
                    timeout=30.0
                )

                # PHASE 1 FIX: Atomic state update with lock
                if result:
                    async with self._state_lock:
                        self.state = result
                    print(f"✅ Cycle done. Matched: {len(self.state['matched_pairs'])}, Errors: {len(self.state['detected_errors'])}")

                # PHASE 1 FIX: Reset failure count on success
                self._failure_count = 0

            except asyncio.TimeoutError:
                print(f"⚠️  Processing cycle timed out after 30 seconds")
                self._handle_cycle_failure()
            except Exception as e:
                print(f"⚠️  Processing error: {e}")
                import traceback
                traceback.print_exc()
                self._handle_cycle_failure()

    def _handle_cycle_failure(self) -> None:
        """
        PHASE 1 FIX: Handle processing cycle failure with circuit breaker.
        """
        self._failure_count += 1
        print(f"⚠️  Failure count: {self._failure_count}/{self._circuit_threshold}")

        if self._failure_count >= self._circuit_threshold:
            self._circuit_open = True
            self._circuit_open_time = datetime.utcnow()
            print(f"🚨 Circuit breaker OPENED after {self._failure_count} consecutive failures")
            print(f"   Circuit will reset after {self._circuit_reset_seconds} seconds")

    async def stop_session(self) -> Dict[str, Any]:
        """
        Stop the current session and return stats.

        CRITICAL: Clears ALL buffers and state to prevent leaks into next session.

        Returns:
            Session statistics and detected errors
        """
        if not self.state:
            return {}

        self.state["is_active"] = False

        stats = {
            "session_id": self.session_id,
            "duration_seconds": (
                datetime.utcnow() - self.state["session_start"]
            ).total_seconds(),
            "stats": self.state["processing_stats"],
            "errors_detected": len(self.state["detected_errors"]),
            "critical_errors": len([
                e for e in self.state["detected_errors"]
                if e["severity"] == "critical"
            ]),
        }

        print(f"\n🔴 Sarasvati session {self.session_id} stopped")
        print(f"   Duration: {stats['duration_seconds']:.1f}s")
        print(f"   Errors detected: {stats['errors_detected']}")
        print(f"   Critical errors: {stats['critical_errors']}")

        # PHASE 1 FIX: Comprehensive cleanup to prevent resource leaks
        # Old segments must not appear in next session
        print(f"   🧹 Clearing buffers: P={len(self.state['provider_buffer'])}, I={len(self.state['interpreter_buffer'])}, Pt={len(self.state['patient_buffer'])}")
        self.state["provider_buffer"].clear()
        self.state["interpreter_buffer"].clear()
        self.state["patient_buffer"].clear()
        self.state["matched_pairs"].clear()
        self.state["detected_errors"].clear()
        self.state["error_flags"].clear()
        self.state["last_verified_count"] = 0
        self.state["last_debate_result"] = None

        # PHASE 1 FIX: Shutdown alignment engine ThreadPoolExecutor
        if hasattr(self.graph, 'alignment_engine') and self.graph.alignment_engine:
            self.graph.alignment_engine.shutdown()

        # PHASE 1 FIX: Force garbage collection to reclaim memory
        import gc
        gc.collect()
        print(f"   ✅ All buffers cleared, alignment engine shut down, memory reclaimed")

        return stats

    async def recover_from_crash(self, session_id: str) -> bool:
        """
        PHASE 1 FIX: Recover from a crash using persistent checkpoints.

        Args:
            session_id: Session identifier to recover

        Returns:
            True if recovery successful, False otherwise
        """
        if not hasattr(self.graph, 'checkpointer') or not self.graph.checkpointer:
            print("⚠️  No checkpointer available for crash recovery")
            return False

        try:
            # Attempt to load the last checkpoint for this session
            config = {"configurable": {"thread_id": session_id}}
            snapshot = self.compiled.get_state(config)

            if snapshot and snapshot.values:
                self.state = snapshot.values
                self.session_id = session_id
                print(f"✅ Recovered session {session_id} from checkpoint")
                print(f"   Buffers: P={len(self.state['provider_buffer'])}, I={len(self.state['interpreter_buffer'])}")
                return True
            else:
                print(f"⚠️  No checkpoint found for session {session_id}")
                return False

        except Exception as e:
            print(f"❌ Failed to recover session {session_id}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_state(self) -> Optional[SarasvatiState]:
        """Get current state (for debugging/monitoring)."""
        return self.state


# ===== Factory Function =====

def create_engine(config: GraphConfig) -> SarasvatiEngine:
    """
    Factory function to create a configured Sarasvati engine.

    Args:
        config: Graph configuration

    Returns:
        Configured SarasvatiEngine instance
    """
    return SarasvatiEngine(config)
