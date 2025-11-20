"""
SARASVATI SIMULATION
====================
Simulates a live session with:
1. Provider speaking (Source)
2. Interpreter speaking (Delayed + Error injected)
3. System detecting the error

This tests the full pipeline without needing LiveKit/Deepgram.
"""

import asyncio
import os
from datetime import datetime

# Make sure Groq API key is set
# export GROQ_API_KEY="gsk_..."
if not os.environ.get("GROQ_API_KEY"):
    print("⚠️  WARNING: GROQ_API_KEY not set in environment")
    print("   Set it with: export GROQ_API_KEY='your-key-here'")
    print()

# Import from the sarasvati package
import sys
sys.path.insert(0, '/home/user/sarasvati/backend')

from sarasvati import (
    create_engine,
    GraphConfig,
    TranscriptSegment,
    StreamRole,
)


# CONFIGURATION
CONFIG = GraphConfig(
    max_buffer_size=5,
    alignment_threshold=0.5,  # Lower threshold for testing
    alignment_window_seconds=30.0,
    debounce_ms=500,
    enable_negation_check=True,
    groq_model_verification="llama-3.1-70b-versatile",
    groq_model_drafting="llama-3.1-8b-instant",
    redis_host="localhost",
    redis_port=6379,
    redis_db=0,
    livekit_url="",
    deepgram_api_key=""
)


async def run_simulation():
    """
    Run a simulated medical consultation with intentional interpretation errors.
    """
    print("=" * 70)
    print("🚀 SARASVATI SIMULATION - Testing Error Detection")
    print("=" * 70)
    print()

    # Initialize engine
    print("⚙️  Initializing SARASVATI engine...")
    engine = create_engine(CONFIG)
    await engine.start_session("sim_session_001")
    print()

    # SCENARIO: Doctor prescribes Metformin with specific dosage and frequency
    # Interpreter OMITS the dosage "500mg" and frequency "twice a day"

    print("=" * 70)
    print("📋 SIMULATION SCENARIO")
    print("=" * 70)
    print("Provider: Prescribes Metformin 500mg twice daily")
    print("Interpreter: Says 'Metformin for diabetes' (OMITS dosage & frequency)")
    print("Expected: System should detect CRITICAL omissions")
    print("=" * 70)
    print()

    # --- PROVIDER SPEAKS (Time: 00:00) ---
    print("[T=00:00] 👨‍⚕️ PROVIDER:")
    provider_text = "Okay, I am going to prescribe Metformin 500 milligrams twice a day for your diabetes."
    print(f"          \"{provider_text}\"")
    print()

    provider_segment = TranscriptSegment(
        role=StreamRole.PROVIDER,
        text=provider_text,
        timestamp=0.0,
        duration=5.0,
        confidence=0.99,
        is_final=True,
        speaker_id="doc_smith",
    )

    await engine.ingest_transcript(provider_segment)
    print("          ✓ Ingested into provider buffer")
    print()

    # --- SIMULATE LAG ---
    print("⏳ Simulating 8-second interpreter lag...")
    await asyncio.sleep(1.0)  # Give system time to process
    print()

    # --- INTERPRETER SPEAKS (Time: 00:08) WITH CRITICAL ERROR ---
    print("[T=00:08] 🌐 INTERPRETER (with ERROR):")
    # ERROR INJECTION: Missing "500mg" and "twice a day"
    interpreter_text = "Le voy a recetar Metformina para su diabetes."
    print(f"          \"{interpreter_text}\"")
    print(f"          [Translation: 'I will prescribe Metformin for your diabetes']")
    print()
    print("          ⚠️  INJECTED ERRORS:")
    print("             - OMISSION: '500 milligrams' dosage missing")
    print("             - OMISSION: 'twice a day' frequency missing")
    print()

    interpreter_segment = TranscriptSegment(
        role=StreamRole.INTERPRETER,
        text=interpreter_text,
        timestamp=8.0,  # 8 second lag
        duration=4.0,
        confidence=0.95,
        is_final=True,
        speaker_id="interpreter_maria",
    )

    await engine.ingest_transcript(interpreter_segment)
    print("          ✓ Ingested into interpreter buffer")
    print()

    # --- FORCE PROCESSING CYCLE ---
    print("=" * 70)
    print("⚙️  RUNNING TRISUL PROTOCOL")
    print("=" * 70)
    print("1. Aligning provider & interpreter streams (DTW + semantic similarity)")
    print("2. Node A: Extracting medical entities from provider speech")
    print("3. Node B: Checking interpreter for omissions")
    print("4. Node C: Arbiter making final judgment")
    print()

    # Trigger processing
    await engine._process_cycle()

    # Give agents time to complete (Groq API calls)
    print("⏳ Waiting for agent debate to complete...")
    await asyncio.sleep(3.0)
    print()

    # --- CHECK RESULTS ---
    print("=" * 70)
    print("📊 RESULTS")
    print("=" * 70)

    state = engine.get_state()

    if not state:
        print("❌ ERROR: No state available")
        return

    # Print alignment info
    print(f"\n📈 Processing Statistics:")
    print(f"   Segments processed: {state['processing_stats']['segments_processed']}")
    print(f"   Alignments found: {state['processing_stats']['alignments_found']}")
    print(f"   Alignments missed: {state['processing_stats']['alignments_missed']}")

    # Check for matched pairs
    if state['matched_pairs']:
        for alignment in state['matched_pairs']:
            if alignment['is_matched']:
                print(f"\n🔗 Alignment Match Found:")
                print(f"   Similarity score: {alignment['similarity_score']:.2%}")
                print(f"   Time delta: {alignment['time_delta']:.1f}s")
                print(f"   DTW distance: {alignment['dtw_distance']:.3f}")

    # Check errors
    errors = state["detected_errors"]

    print(f"\n🚨 Errors Detected: {len(errors)}")

    if errors:
        print(f"\n✅ SUCCESS: System detected {len(errors)} error(s)!\n")

        for i, error in enumerate(errors, 1):
            severity_emoji = {
                "critical": "🔴",
                "high": "🟠",
                "medium": "🟡",
                "low": "🟢",
            }
            emoji = severity_emoji.get(str(error["severity"]), "⚪")

            print(f"{i}. {emoji} SEVERITY: {error['severity'].upper()}")
            print(f"   Type: {error['error_type']}")
            print(f"   Description: {error['description']}")
            print(f"   Confidence: {error['confidence']:.1%}")
            print(f"   Detected at: {error['detected_at'].strftime('%H:%M:%S')}")

            if error.get('arbiter_reasoning'):
                print(f"\n   💭 Arbiter Reasoning:")
                reasoning_lines = error['arbiter_reasoning'].split('\n')
                for line in reasoning_lines[:3]:  # First 3 lines
                    if line.strip():
                        print(f"      {line.strip()}")
            print()

    else:
        print("\n❌ FAILURE: No errors detected!")
        print("\nPossible causes:")
        print("1. Embedding model not loaded (check for warnings above)")
        print("2. Groq API key not set or invalid")
        print("3. Alignment threshold too high")
        print("4. Agent prompts need tuning")
        print()

        # Debug info
        if state.get('last_debate_result'):
            debate = state['last_debate_result']
            print("Debug - Last Debate Result:")
            print(f"  Extractor entities: {len(debate['extractor_entities'])}")
            print(f"  Monitor findings: {len(debate['monitor_findings'])}")
            print(f"  Decision: {debate['arbiter_decision'][:100]}...")

    # Stop session
    print("\n" + "=" * 70)
    stats = await engine.stop_session()
    print()

    print("📋 Final Session Report:")
    print(f"   Duration: {stats.get('duration_seconds', 0):.1f}s")
    print(f"   Total errors: {stats.get('errors_detected', 0)}")
    print(f"   Critical errors: {stats.get('critical_errors', 0)}")
    print()

    print("=" * 70)
    if errors:
        print("✅ SIMULATION PASSED - Error detection working!")
    else:
        print("⚠️  SIMULATION FAILED - No errors detected")
    print("=" * 70)


async def main():
    """Main entry point."""
    try:
        await run_simulation()
    except KeyboardInterrupt:
        print("\n\n⚠️  Simulation interrupted by user")
    except Exception as e:
        print(f"\n❌ SIMULATION ERROR: {e}")
        import traceback
        print("\nFull traceback:")
        traceback.print_exc()


if __name__ == "__main__":
    print("\n🚀 Starting SARASVATI simulation...\n")
    asyncio.run(main())
