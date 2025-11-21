# Trisul Waveform Setup Guide

## Phase 3: Drishya (Frontend) — Complete

The TrisulWaveform component has been successfully created using **Next.js 14**, **TypeScript**, and **wavesurfer.js**.

---

## ✅ What's Been Built

### 1. **TrisulWaveform Component** (`src/components/TrisulWaveform.tsx`)
   - Unified 3-track waveform visualization
   - Uses wavesurfer.js v7.7.0 with RegionsPlugin
   - Synchronized tracks for Provider, Interpreter, Patient
   - Real-time simulation mode with dummy waveforms
   - Red error region overlay on Interpreter track

### 2. **Demo Page** (`src/app/trisul-demo/page.tsx`)
   - Standalone demo of the TrisulWaveform
   - Clean UI with instructions
   - Accessible at `/trisul-demo`

---

## 🚀 Quick Start

### Step 1: Install Dependencies
```bash
cd /home/user/sarasvati/frontend
npm install
```

### Step 2: Run Development Server
```bash
npm run dev
```

### Step 3: View the Demo
Open your browser and navigate to:
```
http://localhost:3000/trisul-demo
```

---

## 🎯 Features Demo

### Simulation Mode
1. Click **"Start Simulation"** button
2. Three waveforms generate automatically:
   - **Provider** (Blue, 200 Hz) — Doctor's speech
   - **Interpreter** (Purple, 300 Hz) — Interpreter's translation
   - **Patient** (Green, 250 Hz) — Patient's response
3. A **Red Error Region** appears on the Interpreter track (30%-50% of timeline)
   - This simulates a detected misinterpretation by Node C Arbiter
4. Use **Play/Pause** to control synchronized playback
5. Click **Stop Simulation** to reset

---

## 📁 File Structure

```
frontend/
├── src/
│   ├── components/
│   │   └── TrisulWaveform.tsx       # ← NEW: Unified 3-track waveform
│   ├── app/
│   │   └── trisul-demo/
│   │       └── page.tsx              # ← NEW: Standalone demo page
│   └── ...
├── package.json                       # wavesurfer.js already included
└── TRISUL_SETUP.md                   # ← This file
```

---

## 🔧 Technical Implementation

### Wavesurfer.js Integration
- **Version:** 7.7.0 (core library)
- **Multitrack Plugin:** v0.4.12
- **Architecture:**
  - **One Multitrack instance** (the Trident shaft)
  - **Three tracks** (the prongs): Provider, Interpreter, Patient
  - Centralized cursor, zoom, and playback control
  - RegionsPlugin attached to Interpreter track for error highlighting

### Audio Generation
- Dummy waveforms generated using Web Audio API
- AudioBuffer → WAV conversion for wavesurfer.js
- Different frequencies for visual distinction:
  - Provider: 200 Hz
  - Interpreter: 300 Hz
  - Patient: 250 Hz

### Error Region Simulation
- RegionsPlugin adds red overlay on Interpreter track
- Positioned at 30%-50% of timeline
- Simulates Node C Arbiter detection of critical error

---

## 🎨 Color Scheme (Aligned with Backend)

| Role        | Color       | Hex       |
|-------------|-------------|-----------|
| Provider    | Blue        | `#3b82f6` |
| Interpreter | Purple      | `#a855f7` |
| Patient     | Green       | `#10b981` |
| Error       | Red (30%)   | `rgba(239, 68, 68, 0.3)` |

---

## 🔗 Next Steps (Production Integration)

To connect TrisulWaveform to real backend:

1. **LiveKit Audio Streams**
   - Replace `generateDummyAudio()` with LiveKit `MediaStreamTrack`
   - Use `wavesurfer.loadMediaStream()` for real-time visualization

2. **WebSocket Backend Events**
   - Listen for alignment events from SarasvatiEngine
   - Add error regions dynamically when Node C detects issues
   - Update region positions based on `AlignmentMatch.time_delta`

3. **Transcript Integration**
   - Overlay ASR transcript text on waveforms
   - Highlight misaligned segments in real-time
   - Show semantic similarity scores

---

## 📸 Expected Visual Output

When you run the demo, you'll see:

```
┌─────────────────────────────────────────────────┐
│ 🔱 Trisul Protocol — Live Audio Streams         │
│                         [Start Simulation] ──── │
├─────────────────────────────────────────────────┤
│ 👨‍⚕️ Provider (Doctor)                           │
│ ▂▃▅▇▅▃▂▁▂▃▄▅▆▅▄▃▂▁▁▂▃▄▅▆▇▅▃▂▁▁▂▃▅▇  (Blue)      │
├─────────────────────────────────────────────────┤
│ 🌐 Interpreter                  [Error Detected]│
│ ▁▂▃▄▅▆▇█▇▆▅▄▃▂▁▂▃▄▅▆▇▆▅▄▃▂▁▁▂▃▄▅▇  (Purple)     │
│         └───────────┘ ← RED REGION              │
├─────────────────────────────────────────────────┤
│ 🧑 Patient                                       │
│ ▂▃▄▅▆▅▄▃▂▁▁▂▃▄▅▇▅▃▂▁▂▃▅▇▅▃▂▁▁▂▃▄▅  (Green)      │
└─────────────────────────────────────────────────┘
```

---

## ✅ Requirements Met

Per the Architectural Bible:

- [x] **Setup:** Next.js 14 + TypeScript + Tailwind CSS ✅
- [x] **Component:** TrisulWaveform using wavesurfer.js ✅
- [x] **3 Tracks:** Provider, Interpreter, Patient ✅
- [x] **Simulation Mode:** Dummy waveform generation ✅
- [x] **Error Region:** Red overlay on Interpreter track ✅

---

## 🔥 Test the Fire

Run this command to verify everything works:

```bash
cd /home/user/sarasvati/frontend
npm run dev
```

Then navigate to `http://localhost:3000/trisul-demo`

**The Sudarshana Chakra of visualization spins.** 🔱
