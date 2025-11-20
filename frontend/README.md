# SARASVATI Frontend - Drishya (Vision)

**Real-time medical interpreter monitoring dashboard using the Trisul Protocol.**

Built with Next.js 14, TypeScript, LiveKit, and Tailwind CSS.

## 🎨 Features

### Visual Components

1. **Three-Stream Audio Visualization**
   - Provider (Blue) 👨‍⚕️
   - Interpreter (Purple) 🌐
   - Patient (Green) 🧑
   - Real-time waveforms using wavesurfer.js
   - Volume controls and mute functionality

2. **Live Transcript Stream**
   - Auto-scrolling transcript view
   - Speaker identification with color coding
   - Confidence scores for each segment
   - Interim vs. final transcript indicators

3. **Arbiter's Log**
   - Real-time error detection display
   - Severity-based color coding (Critical/High/Medium/Low)
   - Expandable error cards with full reasoning
   - Alignment details (similarity scores, DTW distance)

4. **Critical Alert System**
   - Red screen flash on critical errors
   - Browser notifications (if permitted)
   - Audio alerts
   - Visual severity indicators

### Technical Features

- **LiveKit Integration**: Real-time audio streaming
- **WebSocket Connection**: Backend event streaming
- **Simulation Mode**: Test without 3 physical microphones
- **Responsive Design**: Dark mode medical dashboard aesthetic
- **Type Safety**: Full TypeScript coverage
- **Performance**: Optimized rendering with React

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd frontend
npm install
```

### 2. Configure Environment

```bash
cp .env.local.example .env.local
```

Edit `.env.local`:

```env
NEXT_PUBLIC_LIVEKIT_URL=ws://localhost:7880
NEXT_PUBLIC_BACKEND_WS_URL=http://localhost:3001
NEXT_PUBLIC_ROOM_NAME=sarasvati-session
```

### 3. Run Development Server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

## 📁 Project Structure

```
frontend/
├── src/
│   ├── app/
│   │   ├── page.tsx              # Main dashboard
│   │   ├── layout.tsx            # Root layout
│   │   └── globals.css           # Global styles
│   ├── components/
│   │   ├── AudioWaveform.tsx     # Waveform visualization
│   │   ├── TranscriptStream.tsx  # Live transcript display
│   │   └── ArbiterLog.tsx        # Error log component
│   ├── hooks/
│   │   └── useSarasvati.ts       # Main connection hook
│   └── types/
│       └── sarasvati.ts          # TypeScript definitions
├── package.json
├── next.config.mjs
├── tailwind.config.ts
└── tsconfig.json
```

## 🎯 Usage

### Normal Mode (3 Microphones)

1. Click **"Connect"** to establish LiveKit + WebSocket connections
2. System will automatically detect and visualize 3 audio streams
3. Watch the Arbiter's Log for real-time error detection

### Simulation Mode (Testing)

1. Click **"Connect"**
2. Click **"Start Simulation"**
3. System will inject pre-recorded audio files with intentional errors
4. Observe how the Trisul Protocol detects and reports errors

### Dashboard Sections

#### Top Row: Audio Waveforms
- **Provider (Blue)**: Doctor/healthcare provider
- **Interpreter (Purple)**: Medical interpreter
- **Patient (Green)**: Patient

Each waveform shows:
- Live audio visualization
- Activity indicator (green dot when active)
- Volume control and mute button

#### Middle Row: Live Transcript
- Auto-scrolling transcript of all three streams
- Color-coded by speaker role
- Confidence scores
- Timestamps
- "Jump to Latest" button

#### Bottom Row: Arbiter's Log
- Detected errors sorted by severity
- Expandable cards showing:
  - Error description
  - Arbiter's reasoning
  - Extracted medical entities
  - Alignment details (similarity, DTW distance)
- Severity summary counters

## 🎨 Color System

### Stream Colors
- **Provider**: Blue (#3b82f6)
- **Interpreter**: Purple (#a855f7)
- **Patient**: Green (#10b981)

### Error Severity
- **Critical**: Red (🔴) - Negation errors, dosage mismatches
- **High**: Orange (🟠) - Missing key medical info
- **Medium**: Yellow (🟡) - Partial omissions
- **Low**: Blue (🟢) - Minor variations

## 🔧 Development

### Type Checking

```bash
npm run type-check
```

### Linting

```bash
npm run lint
```

### Build for Production

```bash
npm run build
npm start
```

## 🔌 Integration

### LiveKit Connection

The `useSarasvati` hook handles LiveKit connection:

```typescript
const {
  connectionState,
  sessionState,
  connect,
  disconnect,
  room,
} = useSarasvati({
  livekitUrl: "ws://localhost:7880",
  backendWsUrl: "http://localhost:3001",
  roomName: "sarasvati-session",
  autoConnect: false,
});
```

### Backend Events

The hook listens for these WebSocket events:

```typescript
type WSEvent =
  | { type: "transcript"; data: TranscriptSegment }
  | { type: "error"; data: ClinicalError }
  | { type: "alignment"; data: AlignmentMatch }
  | { type: "debate"; data: AgentDebateResult }
  | { type: "session"; data: SessionInfo };
```

## 🎭 Simulation Mode

To test without LiveKit backend:

1. Place audio files in `public/audio/`:
   - `provider.mp3`
   - `interpreter.mp3`
   - `patient.mp3`

2. Click "Start Simulation" in the UI

The system will:
- Load audio files
- Create MediaStream objects
- Publish to LiveKit with staggered timing (0s, 5s, 10s)
- Trigger the backend processing pipeline

## 🐛 Troubleshooting

### "WebSocket connection failed"

- Check backend is running on port 3001
- Verify `NEXT_PUBLIC_BACKEND_WS_URL` in `.env.local`

### "LiveKit connection failed"

- Ensure LiveKit server is running on port 7880
- Check `NEXT_PUBLIC_LIVEKIT_URL` configuration
- Verify room permissions (token may be required)

### "No audio waveforms showing"

- Check browser microphone permissions
- Verify audio tracks are being published to LiveKit
- Look for console errors related to wavesurfer.js

### "Critical errors not flashing"

- Check browser notification permissions
- Verify critical errors are being received via WebSocket
- Look for CSS animation errors in console

## 📦 Dependencies

### Core
- **next**: 14.2.0 - React framework
- **react**: 18.3.0 - UI library
- **typescript**: 5.3.0 - Type safety

### Real-time
- **livekit-client**: 2.5.0 - Audio streaming
- **socket.io-client**: 4.7.0 - WebSocket events
- **@livekit/components-react**: 2.5.0 - React hooks

### Visualization
- **wavesurfer.js**: 7.7.0 - Audio waveforms
- **framer-motion**: 11.0.0 - Animations

### UI
- **tailwindcss**: 3.4.0 - Styling
- **lucide-react**: 0.344.0 - Icons
- **clsx**: 2.1.0 - Class utilities

### State
- **zustand**: 4.5.0 - State management (for future use)

## 🔜 Next Steps

- [ ] Add authentication (JWT tokens for LiveKit)
- [ ] Implement recording playback
- [ ] Add error history/analytics
- [ ] Export error reports (PDF/CSV)
- [ ] Multi-session support
- [ ] Admin dashboard
- [ ] Mobile responsive improvements
- [ ] Accessibility (WCAG 2.1 AA)

## 📝 Notes

### Performance Considerations

- Waveforms use `requestAnimationFrame` for smooth rendering
- Transcripts are limited to last 50 segments
- Errors are kept in memory (consider pagination for long sessions)

### Browser Compatibility

- **Recommended**: Chrome 90+, Firefox 88+, Safari 14+
- **Required**: WebRTC, WebSocket, AudioContext support
- **Optional**: Notifications API, MediaRecorder API

### Security

- **Production**: Use HTTPS/WSS (not HTTP/WS)
- **LiveKit**: Generate access tokens server-side
- **CORS**: Configure backend to allow frontend origin

## 🎓 Learning Resources

- [Next.js Documentation](https://nextjs.org/docs)
- [LiveKit Docs](https://docs.livekit.io/)
- [wavesurfer.js Guide](https://wavesurfer-js.org/)
- [Tailwind CSS](https://tailwindcss.com/docs)

---

**Built with ❤️ for patient safety**
