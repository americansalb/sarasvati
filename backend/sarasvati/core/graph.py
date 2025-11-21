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
                "wait": "ingest",  # Loop back if not enough data
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

        return state

    async def verify_node(self, state: SarasvatiState) -> SarasvatiState:
        """
        Node 3: Verify interpretation quality (Combined Extract+Monitor+Arbiter).

        Runs the three-agent debate system on aligned segments.

        CRITICAL FIX: Only process NEW alignments (not already verified).
        Update last_verified_count after processing to prevent infinite loops.
        """
        # Get only matched pairs
        matched_pairs = [
            match for match in state["matched_pairs"]
            if match["is_matched"]
        ]

        # Get only NEW unverified alignments (since last verification)
        last_verified = state["last_verified_count"]
        new_alignments = matched_pairs[last_verified:]

        if not new_alignments:
            return state

        # Run debate for each NEW alignment
        for alignment in new_alignments:
            debate_result = await self.debate_orchestrator.run_debate(alignment)

            # Store result
            state["last_debate_result"] = debate_result

            # Add any detected errors
            if debate_result["detected_errors"]:
                state["detected_errors"].extend(debate_result["detected_errors"])
                state["should_emit_report"] = True

                # Update error flags
                for error in debate_result["detected_errors"]:
                    state["error_flags"][error["error_id"]] = True

        # Update last_verified_count to current matched count
        state["last_verified_count"] = len(matched_pairs)

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
            # In production, this would:
            # 1. Push to Redis pub/sub
            # 2. Send to WebSocket connections
            # 3. Log to monitoring system
            # 4. Trigger alerts for CRITICAL errors

            print(f"\n{'='*60}")
            print(f"🚨 CLINICAL ERRORS DETECTED: {len(errors_to_report)}")
            print(f"{'='*60}")

            for error in errors_to_report:
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
        Decide whether to continue processing or end session.

        Continue if session is still active.
        """
        if state["is_active"]:
            return "continue"
        else:
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

        # Trigger processing if buffer is large enough
        # Non-blocking: processing runs in the background
        if len(self.state["provider_buffer"]) >= 3:
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
            # Run graph with current state
            result = await self.compiled.ainvoke(
                self.state,
                config={"configurable": {"thread_id": self.session_id}},
            )

            # Update state with result
            if result:
                self.state = result

        except Exception as e:
            print(f"⚠️  Processing error: {e}")

    async def stop_session(self) -> Dict[str, Any]:
        """
        Stop the current session and return stats.

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
