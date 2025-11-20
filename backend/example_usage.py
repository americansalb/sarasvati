"""
SARASVATI MVP Example Usage
===========================

This script demonstrates the core Trisul Protocol with a simulated
medical consultation scenario.
"""

import asyncio
import os
from datetime import datetime

# Set environment variables (in production, use .env file)
os.environ.setdefault("GROQ_API_KEY", "your-groq-api-key-here")

from sarasvati import (
    create_engine,
    GraphConfig,
    TranscriptSegment,
    StreamRole,
)


async def simulate_medical_consultation():
    """
    Simulate a medical consultation with Provider, Interpreter, and Patient.

    Scenario: Provider prescribes medication, interpreter translates to Spanish.
    We'll inject an intentional error to demonstrate detection.
    """

    print("=" * 70)
    print("🏥 SARASVATI MVP Demo: Medical Consultation Monitoring")
    print("=" * 70)
    print()

    # Step 1: Configure the engine
    print("⚙️  Configuring SARASVATI engine...")
    config = GraphConfig(
        max_buffer_size=50,
        alignment_threshold=0.65,
        alignment_window_seconds=30.0,
        debounce_ms=500,
        enable_negation_check=True,
        groq_model_verification="llama-3.1-70b-versatile",
        groq_model_drafting="llama-3.1-8b-instant",
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        livekit_url="ws://localhost:7880",
        deepgram_api_key="",
    )

    # Step 2: Create engine
    engine = create_engine(config)
    print("✅ Engine created")
    print()

    # Step 3: Start monitoring session
    session_id = f"demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    await engine.start_session(session_id)
    print()

    # Step 4: Simulate conversation with transcripts
    print("🎤 Simulating medical consultation...\n")

    # --- Provider speaks (T=0s) ---
    print("[T=0.0s] 👨‍⚕️ Provider:")
    provider_text_1 = (
        "I'm prescribing you ibuprofen, 500 milligrams, "
        "twice daily with food. Do not take if you have no fever."
    )
    print(f"           {provider_text_1}")

    provider_seg_1 = TranscriptSegment(
        role=StreamRole.PROVIDER,
        text=provider_text_1,
        timestamp=0.0,
        duration=5.2,
        confidence=0.96,
        is_final=True,
        speaker_id="dr_smith",
    )

    await engine.ingest_transcript(provider_seg_1)
    print("           ✓ Ingested\n")

    # Simulate processing delay
    await asyncio.sleep(0.5)

    # --- Interpreter speaks (T=8s) with ERROR ---
    print("[T=8.0s] 🌐 Interpreter:")
    # Intentional ERROR: Missing dosage + negation reversal
    interpreter_text_1 = (
        "Le receto ibuprofeno, dos veces al día con comida. "
        "Tome si tiene fiebre."  # WRONG: Should be "no tome si NO tiene fiebre"
    )
    print(f"           {interpreter_text_1}")

    interpreter_seg_1 = TranscriptSegment(
        role=StreamRole.INTERPRETER,
        text=interpreter_text_1,
        timestamp=8.0,
        duration=4.1,
        confidence=0.93,
        is_final=True,
        speaker_id="interpreter_maria",
    )

    await engine.ingest_transcript(interpreter_seg_1)
    print("           ✓ Ingested\n")

    # Give the system time to process
    print("⏳ Processing alignment and running agent debate...")
    await asyncio.sleep(2.0)
    print()

    # --- Patient responds (T=15s) ---
    print("[T=15.0s] 🧑 Patient:")
    patient_text = "Entiendo, gracias doctor."
    print(f"           {patient_text}")

    patient_seg = TranscriptSegment(
        role=StreamRole.PATIENT,
        text=patient_text,
        timestamp=15.0,
        duration=1.8,
        confidence=0.89,
        is_final=True,
        speaker_id="patient_juan",
    )

    await engine.ingest_transcript(patient_seg)
    print("           ✓ Ingested\n")

    # Final processing
    await asyncio.sleep(1.0)

    # Step 5: Check for detected errors
    print("\n" + "=" * 70)
    print("📊 Processing Results")
    print("=" * 70)

    state = engine.get_state()

    if state:
        print(f"\n📈 Session Statistics:")
        print(f"   Segments processed: {state['processing_stats']['segments_processed']}")
        print(f"   Alignments found: {state['processing_stats']['alignments_found']}")
        print(f"   Alignments missed: {state['processing_stats']['alignments_missed']}")
        print(f"   Errors detected: {len(state['detected_errors'])}")

        if state["detected_errors"]:
            print(f"\n⚠️  DETECTED ERRORS:\n")

            for i, error in enumerate(state["detected_errors"], 1):
                severity_emoji = {
                    "critical": "🔴",
                    "high": "🟠",
                    "medium": "🟡",
                    "low": "🟢",
                }
                emoji = severity_emoji.get(str(error["severity"]), "⚪")

                print(f"{i}. {emoji} [{error['severity'].upper()}] {error['error_type']}")
                print(f"   Description: {error['description']}")
                print(f"   Confidence: {error['confidence']:.2%}")
                print(f"   Arbiter reasoning: {error['arbiter_reasoning']}")
                print()

                # Show alignment info
                alignment = error["alignment_info"]
                print(f"   📍 Alignment Details:")
                print(f"      Similarity score: {alignment['similarity_score']:.2%}")
                print(f"      Time delta: {alignment['time_delta']:.1f}s")
                print()

        else:
            print("\n✅ No critical errors detected - interpretation appears accurate")

    # Step 6: Stop session
    print("\n" + "=" * 70)
    stats = await engine.stop_session()
    print()

    print("📋 Final Session Report:")
    print(f"   Duration: {stats.get('duration_seconds', 0):.1f}s")
    print(f"   Total errors: {stats.get('errors_detected', 0)}")
    print(f"   Critical errors: {stats.get('critical_errors', 0)}")
    print()

    print("=" * 70)
    print("✅ Demo completed successfully!")
    print("=" * 70)


async def main():
    """Main entry point."""
    try:
        await simulate_medical_consultation()
    except Exception as e:
        print(f"\n❌ Error during demo: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Run the demo
    print("\n🚀 Starting SARASVATI demo...\n")
    asyncio.run(main())
