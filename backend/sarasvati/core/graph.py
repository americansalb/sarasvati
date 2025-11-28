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

from typing import Literal, Optional, Dict, Any
from datetime import datetime
import asyncio

try:
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.memory import MemorySaver
except ImportError:
    # Fallback for development without langgraph
    StateGraph = None
    END = None
    MemorySaver = None

from .state import (
    SarasvatiState,
    TranscriptSegment,
    BufferEntry,
    StreamRole,
    GraphConfig,
    create_initial_state,
)
from .alignment import AlignmentEngine, BatchAligner, create_alignment_engine
from .agent import ClinicalDebateOrchestrator


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
        self.debate_orchestrator = ClinicalDebateOrchestrator(
            groq_api_key=os.environ.get("GROQ_API_KEY", ""),
            model_extractor=config["groq_model_extractor"],
            model_monitor=config["groq_model_monitor"],
            model_arbiter=config["groq_model_arbiter"],
        )

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

        Returns:
            Compiled graph ready for invocation
        """
        # Use memory saver for checkpointing
        memory = MemorySaver()
        self.compiled_graph = self.graph.compile(checkpointer=memory)
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
            provider_text = case['provider_segment']['text'][:40] if case['provider_segment'] else 'NONE'
            interp_text = case['interpreter_segment']['text'][:40] if case['interpreter_segment'] else 'NONE'

            print(f"      🔍 [{case_type}] P='{provider_text}...' vs I='{interp_text}...'")
            debate_result = await self.debate_orchestrator.run_debate(case, patient_text)

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

        return state

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
        """
        if not self.state:
            return

        try:
            print(f"🔄 Processing cycle started. Buffers: P={len(self.state['provider_buffer'])}, I={len(self.state['interpreter_buffer'])}, Pt={len(self.state['patient_buffer'])}")

            # Run graph with current state
            result = await self.compiled.ainvoke(
                self.state,
                config={"configurable": {"thread_id": self.session_id}},
            )

            # Update state with result
            if result:
                self.state = result
                print(f"✅ Cycle done. Matched: {len(self.state['matched_pairs'])}, Errors: {len(self.state['detected_errors'])}")

        except Exception as e:
            print(f"⚠️  Processing error: {e}")
            import traceback
            traceback.print_exc()

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

        # CRITICAL FIX: Clear ALL buffers and state to prevent session leaks
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
        print(f"   ✅ All buffers cleared, ready for fresh session")

        return stats

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


# ===== Module Import Fix =====
import os  # Add missing import
