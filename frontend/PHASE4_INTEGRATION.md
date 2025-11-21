# Phase 4: Jiva (Integration)

## Overview

**Phase 4** connects the **Drishya (Frontend)** to the **Trisul (Backend)** via WebSocket, enabling real-time error detection visualization.

---

## 🔌 The Red Wire: Backend → Frontend

### Connection Flow

```
Backend (ws://localhost:8000/ws)
    ↓
    WebSocket Connection
    ↓
useSarasvatiBackend Hook
    ↓
TrisulWaveformIntegrated Component
    ↓
Red Regions on Interpreter Track
```

---

## 📁 New Files Created

### 1. **useSarasvatiBackend Hook**
**Location:** `frontend/src/hooks/useSarasvatiBackend.ts`

**Purpose:** Manages WebSocket connection to SARASVATI backend

**Key Features:**
- Connects to `ws://localhost:8000/ws`
- Auto-reconnect with exponential backoff (max 5 attempts)
- Subscribes to `SarasvatiState` updates
- Handles `detected_error` events from Node C Arbiter
- Exposes errors array for visualization
- Critical error flash (red screen + notification)

**API:**
```typescript
const {
  isConnected,           // WebSocket connection status
  connectionError,       // Connection error message
  state,                // Backend state (errors, transcripts, alignments, stats)
  connect,              // Connect to backend
  disconnect,           // Disconnect from backend
  startSession,         // Start monitoring session
  clearErrors,          // Clear error list
  ws,                   // Raw WebSocket (advanced usage)
} = useSarasvatiBackend({
  url: "ws://localhost:8000/ws",
  autoConnect: false,
  onError: (error) => {
    // Called when new error detected
  },
});
```

---

### 2. **TrisulWaveformIntegrated Component**
**Location:** `frontend/src/components/TrisulWaveformIntegrated.tsx`

**Purpose:** Integrated waveform with real-time error visualization

**Key Features:**
- Uses `useSarasvatiBackend` hook to receive backend events
- Automatically draws red regions when errors detected
- Shows connection status (connected/disconnected)
- Displays backend stats (total segments, total errors, critical errors)
- Lists all detected errors with severity and details

**Error Region Mapping:**
```typescript
// When backend sends detected_error:
{
  timestamp: 3.5,        // Start of error (seconds)
  duration: 2.0,        // Duration of error (seconds)
  severity: "critical", // Severity level
  description: "Omitted critical medication dosage",
  ...
}

// Frontend draws red region:
interpreterRegions.addRegion({
  start: 3.5,
  end: 5.5,  // timestamp + duration
  color: "rgba(239, 68, 68, 0.4)", // Red with opacity based on severity
  content: "Omitted critical medication dosage",
});
```

---

## 🔥 WebSocket Message Protocol

### Messages from Backend → Frontend

#### 1. **detected_error**
Sent when Node C Arbiter detects a clinical error.

```json
{
  "type": "detected_error",
  "data": {
    "id": "error_1731974653_001",
    "timestamp": 3.5,
    "duration": 2.0,
    "severity": "critical",
    "description": "Omitted critical medication dosage",
    "providerText": "Take 500mg metformin twice daily",
    "interpreterText": "Take metformin twice daily",
    "alignmentScore": 0.45,
    "source": "arbiter"
  },
  "timestamp": 1731974653
}
```

**Frontend Action:**
- Adds error to `state.errors` array
- Draws red region on Interpreter track
- Flashes screen red if severity is "critical"
- Shows browser notification if permitted

---

#### 2. **state_update**
Full state sync from backend.

```json
{
  "type": "state_update",
  "data": {
    "sessionId": "session_001",
    "isActive": true,
    "errors": [...],
    "transcripts": [...],
    "alignments": [...],
    "stats": {
      "totalSegments": 42,
      "totalErrors": 3,
      "criticalErrors": 1
    }
  },
  "timestamp": 1731974653
}
```

---

#### 3. **transcript**
New ASR transcript segment.

```json
{
  "type": "transcript",
  "data": {
    "role": "provider",
    "text": "Take 500mg metformin twice daily",
    "timestamp": 3.2
  },
  "timestamp": 1731974653
}
```

---

#### 4. **alignment**
New alignment match from DTW + semantic similarity.

```json
{
  "type": "alignment",
  "data": {
    "provider_segment": {...},
    "interpreter_segment": {...},
    "similarity_score": 0.85,
    "combined_score": 0.78,
    "time_delta": 5.2,
    "is_matched": true,
    "dtw_distance": 0.12
  },
  "timestamp": 1731974653
}
```

---

#### 5. **session_start**
Session monitoring started.

```json
{
  "type": "session_start",
  "data": {
    "session_id": "session_001"
  },
  "timestamp": 1731974653
}
```

---

#### 6. **session_end**
Session monitoring ended.

```json
{
  "type": "session_end",
  "data": {},
  "timestamp": 1731974653
}
```

---

### Messages from Frontend → Backend

#### 1. **start_session**
Request to start monitoring session.

```json
{
  "type": "start_session",
  "data": {
    "session_id": "session_001"
  }
}
```

---

## 🎨 Visual Error Indicators

### 1. Red Regions on Waveform
- **Color:** `rgba(239, 68, 68, 0.4)` for critical, `rgba(239, 68, 68, 0.2)` for others
- **Position:** `start = error.timestamp`, `end = timestamp + duration`
- **Label:** Error description shown on hover

### 2. Error Count Badge
Shown on Interpreter track header:
```
🌐 Interpreter     [⚠ 3 Errors Detected]
```

### 3. Critical Alert Flash
- Screen flashes red for 1 second
- Browser notification with error description
- Only for `severity: "critical"`

### 4. Error List
Scrollable list below waveform showing:
- Error description
- Timestamp and alignment score
- Severity color coding

---

## 🚀 Usage Example

### Standalone Integration

```tsx
import { TrisulWaveformIntegrated } from "@/components/TrisulWaveformIntegrated";

export default function MonitoringPage() {
  return (
    <div className="p-8">
      <TrisulWaveformIntegrated
        backendUrl="ws://localhost:8000/ws"
        autoConnect={true}
      />
    </div>
  );
}
```

### Advanced: Custom Hook Usage

```tsx
import { useSarasvatiBackend } from "@/hooks/useSarasvatiBackend";

function MyComponent() {
  const { isConnected, state, connect } = useSarasvatiBackend({
    url: "ws://localhost:8000/ws",
    autoConnect: false,
    onError: (error) => {
      console.log("New error detected:", error);
      // Custom handling
    },
  });

  return (
    <div>
      <button onClick={connect}>Connect</button>
      <p>Connected: {isConnected ? "Yes" : "No"}</p>
      <p>Errors: {state.errors.length}</p>
    </div>
  );
}
```

---

## 🔧 Backend Requirements

For this integration to work, the backend must:

### 1. WebSocket Server
Run on `ws://localhost:8000/ws` (configurable via `backendUrl` prop)

### 2. Message Format
Send JSON messages with structure:
```typescript
{
  type: "detected_error" | "state_update" | "transcript" | "alignment" | "session_start" | "session_end",
  data: any,
  timestamp: number
}
```

### 3. Error Event Structure
When Node C Arbiter detects an error:
```typescript
{
  id: string,
  timestamp: number,      // Unix timestamp or offset in seconds
  duration: number,       // Duration in seconds
  severity: "critical" | "high" | "medium" | "low",
  description: string,
  providerText: string,
  interpreterText: string,
  alignmentScore: number,
  source: "arbiter" | "alignment"
}
```

---

## 🧪 Testing the Integration

### Local Development

1. **Start Backend:**
   ```bash
   cd backend
   python -m uvicorn sarasvati.api.main:app --host 0.0.0.0 --port 8000
   ```

2. **Start Frontend:**
   ```bash
   cd frontend
   npm run dev
   ```

3. **Open Browser:**
   ```
   http://localhost:3000/trisul-integrated
   ```

4. **Test Flow:**
   - Click "Connect Backend" (should see green "Connected" status)
   - Click "Start Simulation" (waveforms render)
   - Backend sends `detected_error` events
   - Red regions appear on Interpreter track automatically

---

## 📋 Integration Checklist

- [x] **useSarasvatiBackend hook** created
- [x] **TrisulWaveformIntegrated component** created
- [x] **WebSocket connection** to `ws://localhost:8000/ws`
- [x] **State updates** subscribed
- [x] **detected_error handling** implemented
- [x] **Red regions** drawn automatically
- [x] **Auto-reconnect** with exponential backoff
- [x] **Critical alerts** (flash + notification)
- [x] **Backend stats** display
- [x] **Error list** with clear button

---

## 🔗 Next Steps (Production)

1. **Authentication:** Add JWT token to WebSocket connection
2. **Encryption:** Use WSS (WebSocket Secure) in production
3. **Error Persistence:** Save errors to database for audit trail
4. **Multi-Session:** Support multiple concurrent monitoring sessions
5. **Playback:** Add ability to replay past sessions with error regions
6. **Export:** Download error report as PDF/CSV

---

**Phase 4 Complete. Drishya and Trisul are now connected.** 🔱
