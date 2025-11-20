# SARASVATI Installation Guide

## Quick Start (5 minutes)

### 1. Install Python Dependencies

```bash
cd backend

# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

**Note**: The first time you run the code, `sentence-transformers` will download the `all-MiniLM-L6-v2` model (~80MB). This happens automatically.

### 2. Start Redis

You need Redis Stack for the buffer management:

**Option A: Docker (Recommended)**
```bash
docker run -d \
  --name redis-sarasvati \
  -p 6379:6379 \
  redis/redis-stack:latest
```

**Option B: Native Installation**
```bash
# macOS
brew install redis-stack

# Ubuntu/Debian
curl -fsSL https://packages.redis.io/gpg | sudo gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/redis.list
sudo apt-get update
sudo apt-get install redis-stack-server

# Start Redis
redis-stack-server
```

Verify Redis is running:
```bash
redis-cli ping
# Should return: PONG
```

### 3. Set Up API Keys

Get a Groq API key from: https://console.groq.com/keys

```bash
# Set environment variable
export GROQ_API_KEY="gsk_your_key_here"

# Or create a .env file
cp .env.example .env
# Edit .env and add your key
```

### 4. Run the Simulation

```bash
python simulation.py
```

You should see:
```
🔄 Loading sentence embedding model (all-MiniLM-L6-v2)...
✅ Embedding model loaded successfully
🟢 Sarasvati session sim_session_001 started
   Monitoring 3 streams: Provider, Interpreter, Patient
```

If it detects the intentional errors, you'll see:
```
✅ SUCCESS: System detected 2 error(s)!

1. 🔴 SEVERITY: CRITICAL
   Type: omission
   Description: Dosage '500mg' was not mentioned in interpretation
```

## Troubleshooting

### Error: "sentence-transformers not installed"

```bash
pip install sentence-transformers torch
```

### Error: "Connection refused" (Redis)

Make sure Redis is running:
```bash
# Check if Redis is running
redis-cli ping

# If not, start it
docker start redis-sarasvati
# or
redis-stack-server
```

### Error: "GROQ_API_KEY not set"

```bash
export GROQ_API_KEY="your_key_here"
```

### Error: "No errors detected" in simulation

Check these:
1. **Embeddings loaded?** Look for "✅ Embedding model loaded successfully"
2. **Groq API working?** Check your API key and quota
3. **Alignment threshold?** Try lowering it in `simulation.py`:
   ```python
   alignment_threshold=0.5  # Lower = more lenient
   ```

### Slow first run?

The first run downloads:
- Sentence transformer model (~80MB)
- PyTorch dependencies (if not installed)

This is normal and only happens once.

## System Requirements

- **Python**: 3.10+
- **RAM**: 4GB minimum (8GB recommended for PyTorch)
- **Disk**: 500MB for models
- **Redis**: 6.0+ (Redis Stack recommended)

## Next Steps

Once the simulation works:

1. **Test with different scenarios**: Edit `simulation.py` to add more cases
2. **Integrate with LiveKit**: See `docs/livekit_integration.md` (coming soon)
3. **Run tests**: `pytest tests/` (coming soon)
4. **Deploy**: See `docs/deployment.md` (coming soon)

## Dependencies Explained

- **langgraph**: Stateful cyclic processing graph
- **groq**: Fast LLM inference (Llama-3)
- **sentence-transformers**: Semantic embeddings for alignment
- **torch**: Required by sentence-transformers
- **redis**: FIFO buffer with vector search
- **numpy/scipy**: DTW algorithms

## Performance Notes

- **Alignment**: ~10-20ms per segment (CPU)
- **LLM calls**: ~200-500ms (Groq API)
- **Total latency**: <2s from speech to error detection

## Getting Help

- Check the main [README.md](README.md) for architecture details
- Review [simulation.py](simulation.py) for usage examples
- Open an issue on GitHub for bugs
