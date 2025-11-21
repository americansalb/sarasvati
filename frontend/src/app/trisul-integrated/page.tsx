/**
 * Trisul Integrated Demo Page
 * ============================
 * Phase 4: Jiva (Integration) - Backend-connected waveform visualization
 */

"use client";

import { TrisulWaveformIntegrated } from "@/components/TrisulWaveformIntegrated";

export default function TrisulIntegratedPage() {
  return (
    <div className="min-h-screen bg-gray-950 text-white p-8">
      {/* Header */}
      <div className="max-w-7xl mx-auto mb-8">
        <div className="flex items-center gap-3 mb-2">
          <span className="text-4xl">🔱</span>
          <h1 className="text-3xl font-bold">SARASVATI Trisul Protocol</h1>
        </div>
        <p className="text-gray-400">
          Phase 4: Jiva (Integration) — Real-time backend-connected error monitoring
        </p>
      </div>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto">
        <TrisulWaveformIntegrated
          backendUrl="ws://localhost:8000/ws"
          autoConnect={false}
        />
      </div>

      {/* Instructions */}
      <div className="max-w-7xl mx-auto mt-8 p-6 bg-gray-900 border border-gray-800 rounded-lg">
        <h3 className="text-lg font-semibold mb-3">Phase 4: Integration Instructions</h3>

        <div className="space-y-4 text-sm text-gray-300">
          <div>
            <h4 className="font-semibold text-white mb-2">Step 1: Start Backend</h4>
            <code className="block bg-gray-950 p-3 rounded text-purple-400">
              cd backend<br />
              python -m uvicorn sarasvati.api.main:app --host 0.0.0.0 --port 8000
            </code>
          </div>

          <div>
            <h4 className="font-semibold text-white mb-2">Step 2: Connect Frontend</h4>
            <ol className="list-decimal list-inside space-y-1 ml-4">
              <li>Click <strong className="text-purple-400">"Connect Backend"</strong> button above</li>
              <li>Wait for green "Connected to backend" status</li>
            </ol>
          </div>

          <div>
            <h4 className="font-semibold text-white mb-2">Step 3: Start Monitoring</h4>
            <ol className="list-decimal list-inside space-y-1 ml-4">
              <li>Click <strong className="text-blue-400">"Start Simulation"</strong> to render waveforms</li>
              <li>Backend session starts automatically</li>
              <li>Watch for <strong className="text-red-400">red error regions</strong> appearing in real-time</li>
            </ol>
          </div>

          <div>
            <h4 className="font-semibold text-white mb-2">What Happens:</h4>
            <ul className="list-disc list-inside space-y-1 ml-4">
              <li>Backend Node C Arbiter detects clinical errors</li>
              <li>
                <code className="text-purple-300">detected_error</code> events sent via WebSocket
              </li>
              <li>Frontend draws red regions on Interpreter track at exact timestamps</li>
              <li>Critical errors flash the screen red + show browser notification</li>
              <li>Error list updates in real-time</li>
            </ul>
          </div>
        </div>

        <div className="mt-6 p-4 bg-blue-950 border border-blue-800 rounded">
          <p className="text-sm text-blue-200">
            <strong>The Red Wire:</strong> When the backend emits a{" "}
            <code className="text-purple-300">detected_error</code> event,
            the <code className="text-purple-300">useSarasvatiBackend</code> hook
            captures it and exposes it to <code className="text-purple-300">TrisulWaveformIntegrated</code>,
            which then draws a real red region on the Interpreter track using RegionsPlugin.
          </p>
        </div>

        <div className="mt-4 p-4 bg-green-950 border border-green-800 rounded">
          <p className="text-sm text-green-200">
            <strong>Architecture:</strong> One Multitrack instance (Trident shaft) connected
            to the SARASVATI backend via WebSocket. Errors detected by the LangGraph
            adversarial agents (Node A, B, C) flow in real-time to the visualization.
          </p>
        </div>
      </div>
    </div>
  );
}
