"""
integration_test_agni.py

AGNI (The Burn-In) – Verifies that Sarasvati's ingest loop remains non-blocking
even while the alignment engine is under heavy CPU load.

Test idea:

1. Patch AlignmentEngine._get_embedding to simulate a 50ms "model call"
   using time.sleep(0.05). This runs in the ThreadPoolExecutor worker thread,
   not in the main event loop.

2. Start a SarasvatiEngine session and pre-fill the interpreter buffer so that
   alignment will actually do work (and invoke _get_embedding).

3. Send enough provider segments to trigger at least one alignment cycle.

4. While alignment is "thinking", blast ingest_transcript with 100 additional
   provider segments and measure per-call latency with time.perf_counter().

5. Assertions:
   - Every ingest_transcript call returns in < 5ms (event loop not blocked).
   - All 100 barrage segments end up in the provider_buffer (no data loss).

No external libraries are used beyond the standard library + the project itself.
"""

import asyncio
import time
import unittest
from datetime import datetime, timedelta
from typing import cast, Dict, Any, List

import numpy as np  # Already a dependency of the core alignment module

# Adjust these imports to match your actual package layout if needed.
from backend.sarasvati.core.graph import SarasvatiEngine
from backend.sarasvati.core.state import (
    GraphConfig,
    StreamRole,
    SarasvatiState,
    TranscriptSegment,
)
from backend.sarasvati.core.alignment import AlignmentEngine


class AgniIngestionLatencyTest(unittest.IsolatedAsyncioTestCase):
    """
    AGNI – Burn-in test for non-blocking ingest under heavy alignment load.
    """

    async def asyncSetUp(self) -> None:
        # Minimal but valid graph configuration.
        # Only a subset of fields are used in this test, but we provide
        # sensible defaults for all defined in GraphConfig for clarity.
        self.config: GraphConfig = cast(
            GraphConfig,
            {
                "max_buffer_size": 1024,
                "alignment_threshold": 0.5,
                "alignment_window_seconds": 30.0,
                "debounce_ms": 0,
                "enable_negation_check": True,
                "groq_model_verification": "dummy-groq-verify",
                "groq_model_drafting": "dummy-groq-draft",
                "redis_host": "localhost",
                "redis_port": 6379,
                "redis_db": 0,
                "livekit_url": "wss://dummy-livekit",
                # Name here may differ in your actual GraphConfig; adjust if needed.
                # It is not used by this test, but included for completeness.
                "deepgram_api_key": "dummy-deepgram-api-key",
            },
        )

        # Patch AlignmentEngine._get_embedding to simulate heavy CPU load.
        # This will run in the ThreadPoolExecutor worker threads.
        async_patch_target = AlignmentEngine._get_embedding

        def slow_embedding(self: AlignmentEngine, text: str) -> np.ndarray:
            """
            Simulated heavy embedding computation.

            - Sleeps for ~50ms to emulate a large model call.
            - Returns a fixed embedding vector.
            """
            # Burn ~50ms (sleep releases GIL but still simulates latency)
            time.sleep(0.05)

            # Simple deterministic embedding; dimension chosen to be plausible
            # but not critical for the test.
            return np.ones(384, dtype=np.float32)

        # Keep reference in case we want to restore later (not strictly required in this test)
        self._original_get_embedding = async_patch_target
        AlignmentEngine._get_embedding = slow_embedding  # type: ignore[assignment]

        # Create Sarasvati engine and start a session
        self.engine = SarasvatiEngine(self.config)
        await self.engine.start_session("agni-burn-in")

    async def asyncTearDown(self) -> None:
        # Restore original embedding method to avoid side effects on other tests
        AlignmentEngine._get_embedding = self._original_get_embedding  # type: ignore[assignment]

    async def test_ingest_is_non_blocking_under_heavy_alignment(self) -> None:
        """
        Main AGNI test:

        - Ensure ingest_transcript calls return quickly (< 5ms).
        - Ensure all barrage segments appear in provider_buffer.
        """

        assert self.engine.state is not None, "Engine state must be initialized"
        state: SarasvatiState = self.engine.state

        # 1) Pre-fill interpreter buffer so alignment has candidates in the window.
        now = datetime.utcnow()
        interpreter_segments: List[TranscriptSegment] = []

        for i in range(5):
            seg: TranscriptSegment = {
                "role": StreamRole.INTERPRETER,
                "text": f"interpreter segment {i}",
                "timestamp": now + timedelta(milliseconds=i),
            }
            interpreter_segments.append(seg)
            await self.engine.ingest_transcript(seg)

        # 2) Add initial provider segments to trigger at least one alignment cycle.
        #    The current implementation starts processing when provider_buffer size >= 3.
        for i in range(3):
            seg: TranscriptSegment = {
                "role": StreamRole.PROVIDER,
                "text": f"provider warmup segment {i}",
                "timestamp": now + timedelta(milliseconds=10 + i),
            }
            await self.engine.ingest_transcript(seg)

        # Optional: tiny delay to give the first _process_cycle a head start.
        # Not strictly required, but increases chance that alignment is running
        # in worker threads when we start the barrage.
        await asyncio.sleep(0.01)

        # Sanity: capture baseline provider buffer size before the barrage.
        state = self.engine.state  # refreshed reference
        baseline_provider_count = len(state["provider_buffer"])

        # 3) The Barrage – blast ingest_transcript with 100 provider segments
        #    and measure per-call latency.
        NUM_BARRAGE = 100
        latencies_ms: List[float] = []

        for i in range(NUM_BARRAGE):
            seg: TranscriptSegment = {
                "role": StreamRole.PROVIDER,
                "text": f"provider barrage segment {i}",
                "timestamp": now + timedelta(milliseconds=100 + i),
            }

            t0 = time.perf_counter()
            await self.engine.ingest_transcript(seg)
            t1 = time.perf_counter()

            latency_ms = (t1 - t0) * 1000.0
            latencies_ms.append(latency_ms)

        # 4) Assertions

        # 4a) Latency: ingest_transcript should be effectively non-blocking.
        max_latency_ms = max(latencies_ms) if latencies_ms else 0.0
        avg_latency_ms = sum(latencies_ms) / len(latencies_ms)

        # The hard assertion: no call may exceed 5 ms.
        # Ideal target is < 1 ms; 5 ms provides margin for CI noise.
        self.assertLess(
            max_latency_ms,
            5.0,
            msg=(
                f"ingest_transcript is blocking the event loop under load: "
                f"max latency = {max_latency_ms:.3f} ms, avg = {avg_latency_ms:.3f} ms"
            ),
        )

        # 4b) Data integrity: all barrage segments must be present in the provider buffer.
        state = self.engine.state
        final_provider_count = len(state["provider_buffer"])

        expected_min_provider_count = baseline_provider_count + NUM_BARRAGE
        self.assertGreaterEqual(
            final_provider_count,
            expected_min_provider_count,
            msg=(
                "Provider buffer lost segments under concurrent load: "
                f"expected at least {expected_min_provider_count}, "
                f"found {final_provider_count}"
            ),
        )

        # Optional: print diagnostics if running interactively
        print(
            f"\n[AGNI] Barrage complete. "
            f"max_latency={max_latency_ms:.3f} ms, avg_latency={avg_latency_ms:.3f} ms, "
            f"provider_buffer={final_provider_count}"
        )


if __name__ == "__main__":
    # Allow running directly via: python integration_test_agni.py
    unittest.main()
