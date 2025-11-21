/**
 * Trisul Waveform Demo Page
 * ==========================
 * Standalone demo of the 3-track waveform visualization
 */

"use client";

import { TrisulWaveform } from "@/components/TrisulWaveform";

export default function TrisulDemoPage() {
  return (
    <div className="min-h-screen bg-gray-950 text-white p-8">
      {/* Header */}
      <div className="max-w-7xl mx-auto mb-8">
        <div className="flex items-center gap-3 mb-2">
          <span className="text-4xl">🔱</span>
          <h1 className="text-3xl font-bold">SARASVATI Trisul Protocol</h1>
        </div>
        <p className="text-gray-400">
          Phase 3: Drishya (Vision) — Multi-track waveform visualization demo
        </p>
      </div>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto">
        <TrisulWaveform />
      </div>

      {/* Instructions */}
      <div className="max-w-7xl mx-auto mt-8 p-6 bg-gray-900 border border-gray-800 rounded-lg">
        <h3 className="text-lg font-semibold mb-3">How to Use</h3>
        <ol className="list-decimal list-inside space-y-2 text-sm text-gray-300">
          <li>
            Click <strong className="text-blue-400">"Start Simulation"</strong>{" "}
            to generate dummy waveforms for all 3 tracks
          </li>
          <li>
            The <strong className="text-purple-400">Interpreter track</strong>{" "}
            will show a <strong className="text-red-400">red error region</strong>{" "}
            (simulated misinterpretation detected by Node C Arbiter)
          </li>
          <li>
            Use <strong className="text-green-400">Play/Pause</strong> to control
            playback
          </li>
          <li>
            Click <strong className="text-red-400">"Stop Simulation"</strong> to
            reset
          </li>
        </ol>

        <div className="mt-6 p-4 bg-blue-950 border border-blue-800 rounded">
          <p className="text-sm text-blue-200">
            <strong>Note:</strong> This is a frontend-only demo using generated
            waveforms. In production, these tracks will connect to LiveKit audio
            streams and display real-time ASR transcripts with alignment-based
            error detection from the backend LangGraph engine.
          </p>
        </div>
      </div>
    </div>
  );
}
