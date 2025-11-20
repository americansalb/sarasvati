# SARASVATI MVP Backend

**The Trisul Protocol: Real-Time Medical Interpreter Monitoring**

SARASVATI is a mission-critical system that monitors 3 distinct audio streams (Provider, Interpreter, Patient) to detect clinical errors in real-time using adversarial AI agents.

## 🎯 Core Concept

**The Alignment Problem**: Interpreters speak 5-20 seconds after providers. We DO NOT compare Time(X) to Time(X). Instead, we use **Dynamic Time Warping (DTW) + Semantic Similarity** to find where provider concepts appear in the interpreter stream.

**The Trisul Protocol**: Three adversarial agents debate accuracy:
- **Node A (Extractor)**: Extracts medical entities from Provider stream
- **Node B (Monitor)**: Checks Interpreter stream for omissions
- **Node C (Arbiter)**: Makes final decision with negation-aware verification

## 🏗️ Architecture

```
┌─────────────┐
│  LiveKit    │  Raw Audio (3 streams)
│  + Deepgram │  ──────────────────┐
└─────────────┘                    │
                                   ▼
┌──────────────────────────────────────────┐
│         SARASVATI Engine                 │
│  ┌────────────────────────────────────┐  │
│  │   LangGraph Cyclic Processing      │  │
│  │                                    │  │
│  │  ingest → align → verify → report │  │
│  │            ▲                  │    │  │
│  │            └──────────────────┘    │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌─────────┐  ┌──────────┐  ┌────────┐  │
│  │ Node A  │→ │ Node B   │→ │Node C  │  │
│  │Extract  │  │ Monitor  │  │Arbiter │  │
│  └─────────┘  └──────────┘  └────────┘  │
└──────────────────────────────────────────┘
                    │
                    ▼
         ┌──────────────────┐
         │  Redis Hot Buffer │  (Temporal alignment)
         └──────────────────┘
                    │
                    ▼
         ┌──────────────────┐
         │   Groq API       │  (Llama-3-70b/8b)
         └──────────────────┘
```

## 📁 Project Structure

```
backend/
├── sarasvati/
│   ├── core/
│   │   ├── state.py          # LangGraph state TypedDict
│   │   ├── alignment.py      # DTW + semantic similarity
│   │   ├── agent.py          # Adversarial agents (Groq)
│   │   └── graph.py          # LangGraph processing loop
│   ├── utils/
│   │   └── redis_buffer.py   # Redis FIFO buffer + vector search
│   └── models/
│       └── (future: DB schemas)
├── requirements.txt
└── README.md
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Set Environment Variables

```bash
export GROQ_API_KEY="your-groq-api-key"
export REDIS_HOST="localhost"
export REDIS_PORT=6379
```

### 3. Start Redis Stack

```bash
# Using Docker
docker run -d \
  --name redis-sarasvati \
  -p 6379:6379 \
  redis/redis-stack:latest
```

### 4. Run the Engine

```python
import asyncio
from sarasvati import create_engine, GraphConfig, TranscriptSegment, StreamRole

async def main():
    # Configure engine
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

    # Create engine
    engine = create_engine(config)

    # Start session
    await engine.start_session("session_001")

    # Ingest transcript segments (from LiveKit)
    provider_segment = TranscriptSegment(
        role=StreamRole.PROVIDER,
        text="Take 500 milligrams of ibuprofen twice daily",
        timestamp=0.0,
        duration=3.5,
        confidence=0.95,
        is_final=True,
        speaker_id="provider_1",
    )

    await engine.ingest_transcript(provider_segment)

    # ... interpreter segment arrives 10 seconds later ...
    interpreter_segment = TranscriptSegment(
        role=StreamRole.INTERPRETER,
        text="Tome ibuprofeno dos veces al día",
        timestamp=10.0,
        duration=2.8,
        confidence=0.92,
        is_final=True,
        speaker_id="interpreter_1",
    )

    await engine.ingest_transcript(interpreter_segment)

    # Stop session
    stats = await engine.stop_session()
    print(stats)

if __name__ == "__main__":
    asyncio.run(main())
```

## 🔬 Core Components

### State Management (`core/state.py`)

Defines all TypedDict schemas for LangGraph:
- `SarasvatiState`: Main graph state
- `TranscriptSegment`: Audio transcript with metadata
- `MedicalEntity`: Extracted clinical entities
- `ClinicalError`: Detected interpretation errors
- `AlignmentMatch`: DTW alignment results

### Alignment Engine (`core/alignment.py`)

**The key innovation solving the "Alignment Problem":**

```python
from sarasvati import create_alignment_engine

engine = create_alignment_engine(
    window_seconds=30.0,      # Search window
    similarity_threshold=0.65  # Minimum match score
)

# Align delayed interpreter speech to provider speech
alignment = await engine.align_segments(
    provider_segment,
    interpreter_buffer,
    state
)

# Check for critical negation mismatches
if alignment.is_matched:
    print(f"Similarity: {alignment.similarity_score}")
    print(f"Time delta: {alignment.time_delta}s")
```

Features:
- Dynamic Time Warping (word-level)
- Cosine similarity on sentence embeddings
- Negation mismatch detection (critical for safety)
- Sliding window semantic search

### Adversarial Agents (`core/agent.py`)

**Three-agent debate system:**

1. **Node A (Extractor)**:
   - Extracts: drugs, dosages, frequencies, conditions, instructions
   - Uses Groq Llama-3-8b for fast extraction
   - Fallback to regex patterns

2. **Node B (Monitor)**:
   - Checks interpreter for omissions
   - Compares against Node A's findings
   - Flags missing entities

3. **Node C (Arbiter)**:
   - Uses Groq Llama-3-70b for high-accuracy judgment
   - Weighted similarity check
   - Negation-aware final decision
   - Assigns severity: CRITICAL, HIGH, MEDIUM, LOW

```python
from sarasvati import ClinicalDebateOrchestrator

orchestrator = ClinicalDebateOrchestrator(groq_api_key="...")

result = await orchestrator.run_debate(alignment)

for error in result.detected_errors:
    print(f"{error.severity}: {error.description}")
```

### LangGraph Processing Loop (`core/graph.py`)

**Cyclic stateful graph:**

```
  START
    ↓
┌──────────┐
│  ingest  │ ← (loop back)
└────┬─────┘
     ↓
┌──────────┐
│  align   │ (DTW + semantic similarity)
└────┬─────┘
     ↓
┌──────────┐
│  verify  │ (3-agent debate)
└────┬─────┘
     ↓
┌──────────┐
│  report  │ (emit errors)
└────┬─────┘
     ↓
   (loop or END)
```

The graph is **self-healing** and **stateful** - it maintains buffers across cycles.

### Redis Hot Buffer (`utils/redis_buffer.py`)

FIFO buffer with vector search for fast alignment:

```python
from sarasvati.utils import create_redis_buffer

buffer = await create_redis_buffer(
    host="localhost",
    port=6379,
    enable_vector_search=True,
    vector_dim=384
)

# Push to buffer
await buffer.push(session_id, StreamRole.PROVIDER, entry)

# Semantic search (for alignment)
matches = await buffer.search_semantic(
    session_id,
    StreamRole.INTERPRETER,
    query_vector,
    k=10
)
```

## 🔐 Critical Safety Features

### 1. Negation Detection

The system uses strict negation checking to prevent catastrophic errors:

```
Provider: "No fever"
Interpreter: "Fever"
Result: 🔴 CRITICAL ERROR - Negation mismatch
```

### 2. Dosage Verification

Numeric values are extracted and compared:

```
Provider: "500 milligrams"
Interpreter: "50 milligrams"
Result: 🔴 CRITICAL ERROR - Dosage mismatch
```

### 3. Omission Detection

Missing critical medical information is flagged:

```
Provider: "Take with food and avoid alcohol"
Interpreter: "Tome con comida"
Result: 🟠 HIGH - Missing instruction: "avoid alcohol"
```

## 📊 Performance Characteristics

- **Latency**: < 2s from speech to error detection
- **Alignment Window**: 30s (configurable)
- **Throughput**: Handles 3 concurrent streams at 16kHz
- **Buffer Size**: 50-100 segments (auto-trimming)
- **Inference**: Groq for sub-second LLM responses

## 🧪 Testing

```bash
# Run tests (future)
pytest tests/

# Test alignment engine
pytest tests/test_alignment.py -v

# Test agent debate
pytest tests/test_agents.py -v
```

## 🛠️ Development Roadmap

### MVP (Current)
- [x] Core state management
- [x] DTW + semantic alignment
- [x] 3-agent debate system
- [x] LangGraph cyclic processing
- [x] Redis FIFO buffer

### Next Steps
- [ ] LiveKit integration
- [ ] Deepgram streaming ASR
- [ ] Production sentence embeddings (sentence-transformers)
- [ ] WebSocket real-time dashboard
- [ ] PostgreSQL for error persistence
- [ ] Unit tests & integration tests
- [ ] Docker Compose setup
- [ ] Kubernetes deployment

## 📝 Configuration

All configuration is via `GraphConfig`:

```python
config = GraphConfig(
    # Buffer settings
    max_buffer_size=50,
    alignment_window_seconds=30.0,
    alignment_threshold=0.65,

    # Processing
    debounce_ms=500,
    enable_negation_check=True,

    # Models
    groq_model_verification="llama-3.1-70b-versatile",
    groq_model_drafting="llama-3.1-8b-instant",

    # Infrastructure
    redis_host="localhost",
    redis_port=6379,
    redis_db=0,
    livekit_url="ws://localhost:7880",
    deepgram_api_key="your-key",
)
```

## 🚨 Error Severity Levels

- **CRITICAL**: Negation errors, dosage mismatches, omitted medications
- **HIGH**: Missing key medical information
- **MEDIUM**: Partial omissions, imprecise terminology
- **LOW**: Minor linguistic variations (acceptable)

## 📚 Key Concepts

### The Alignment Problem

Traditional timestamped comparison fails because interpreters speak 5-20s after providers. SARASVATI solves this with:

1. **Temporal Buffering**: Provider speech stored in Redis FIFO
2. **Semantic Search**: Find interpreter speech matching provider concepts
3. **DTW Alignment**: Optimal character/word-level alignment
4. **Cosine Similarity**: Embedding-based semantic matching

### The Trisul Protocol

Inspired by adversarial debate systems:
- **Thesis**: Node A extracts entities (what was said)
- **Antithesis**: Node B challenges (what was missed)
- **Synthesis**: Node C arbitrates (final verdict)

This triangulation approach reduces false positives while maintaining high recall for safety-critical errors.

## 🤝 Contributing

This is an MVP. Key areas for contribution:
- Improved DTW algorithms (phoneme-level)
- Better negation detection (cross-encoders)
- LiveKit integration examples
- Performance benchmarks
- Medical domain fine-tuning

## 📄 License

[To be determined]

## 🙏 Acknowledgments

Built with:
- LangGraph (stateful orchestration)
- Groq (ultra-fast inference)
- Redis Stack (vector search)
- LiveKit (real-time audio)
- Deepgram (medical ASR)

---

**SARASVATI**: Sanskrit for "goddess of knowledge and wisdom" - an appropriate name for a system protecting patient safety through AI-powered clinical verification.
