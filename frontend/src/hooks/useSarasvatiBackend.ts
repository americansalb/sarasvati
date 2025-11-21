/**
 * SARASVATI Backend Connection Hook
 * ==================================
 * Phase 4: Jiva (Integration) - Connect Drishya (Frontend) to Trisul (Backend)
 *
 * Connects to ws://localhost:8000/ws and subscribes to SarasvatiState updates.
 * Exposes detected_error events for TrisulWaveform to draw red regions.
 */

"use client";

import { useEffect, useState, useCallback, useRef } from "react";

// ===== Types =====

export interface DetectedError {
  id: string;
  timestamp: number; // Unix timestamp in seconds
  duration: number; // Duration of error region in seconds
  severity: "critical" | "high" | "medium" | "low";
  description: string;
  providerText: string;
  interpreterText: string;
  alignmentScore: number;
  source: "arbiter" | "alignment";
}

export interface TranscriptSegment {
  role: "provider" | "interpreter" | "patient";
  text: string;
  timestamp: number;
}

export interface AlignmentMatch {
  provider_segment: TranscriptSegment;
  interpreter_segment: TranscriptSegment | null;
  similarity_score: number;
  combined_score: number;
  time_delta: number;
  is_matched: boolean;
  dtw_distance: number;
}

export interface BackendState {
  sessionId: string | null;
  isActive: boolean;
  errors: DetectedError[];
  transcripts: TranscriptSegment[];
  alignments: AlignmentMatch[];
  stats: {
    totalSegments: number;
    totalErrors: number;
    criticalErrors: number;
  };
}

export interface WebSocketMessage {
  type: "state_update" | "detected_error" | "transcript" | "alignment" | "session_start" | "session_end";
  data: any;
  timestamp: number;
}

interface UseSarasvatiBackendOptions {
  url?: string;
  autoConnect?: boolean;
  onError?: (error: DetectedError) => void;
}

interface UseSarasvatiBackendReturn {
  // Connection state
  isConnected: boolean;
  connectionError: string | null;

  // Backend state
  state: BackendState;

  // Actions
  connect: () => void;
  disconnect: () => void;
  startSession: (sessionId?: string) => void;
  clearErrors: () => void;

  // Raw WebSocket for advanced usage
  ws: WebSocket | null;
}

// ===== Hook =====

export function useSarasvatiBackend(
  options: UseSarasvatiBackendOptions = {}
): UseSarasvatiBackendReturn {
  const {
    url = "ws://localhost:8000/ws",
    autoConnect = false,
    onError,
  } = options;

  // Connection state
  const [isConnected, setIsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  // Backend state
  const [state, setState] = useState<BackendState>({
    sessionId: null,
    isActive: false,
    errors: [],
    transcripts: [],
    alignments: [],
    stats: {
      totalSegments: 0,
      totalErrors: 0,
      criticalErrors: 0,
    },
  });

  // Refs
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const MAX_RECONNECT_ATTEMPTS = 5;
  const RECONNECT_DELAY = 2000;

  // ===== WebSocket Connection =====

  const connect = useCallback(() => {
    // Prevent duplicate connections
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      console.log("WebSocket already connected");
      return;
    }

    // Clear any pending reconnect
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    console.log(`🔌 Connecting to SARASVATI backend: ${url}`);
    setConnectionError(null);

    try {
      const ws = new WebSocket(url);

      ws.onopen = () => {
        console.log("✅ WebSocket connected to backend");
        setIsConnected(true);
        setConnectionError(null);
        reconnectAttemptsRef.current = 0;
      };

      ws.onclose = (event) => {
        console.log("⚠️ WebSocket disconnected:", event.code, event.reason);
        setIsConnected(false);
        wsRef.current = null;

        // Attempt reconnection
        if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptsRef.current += 1;
          const delay = RECONNECT_DELAY * reconnectAttemptsRef.current;
          console.log(`🔄 Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current}/${MAX_RECONNECT_ATTEMPTS})...`);

          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, delay);
        } else {
          console.error("❌ Max reconnection attempts reached");
          setConnectionError("Failed to connect after multiple attempts");
        }
      };

      ws.onerror = (error) => {
        console.error("WebSocket error:", error);
        setConnectionError("WebSocket connection error");
      };

      ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          handleMessage(message);
        } catch (error) {
          console.error("Failed to parse WebSocket message:", error);
        }
      };

      wsRef.current = ws;
    } catch (error) {
      console.error("Failed to create WebSocket:", error);
      setConnectionError(`Failed to connect: ${error}`);
    }
  }, [url]);

  const disconnect = useCallback(() => {
    console.log("Disconnecting from backend...");

    // Clear reconnect timeout
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    // Close WebSocket
    if (wsRef.current) {
      wsRef.current.close(1000, "Client disconnect");
      wsRef.current = null;
    }

    setIsConnected(false);
    setState({
      sessionId: null,
      isActive: false,
      errors: [],
      transcripts: [],
      alignments: [],
      stats: {
        totalSegments: 0,
        totalErrors: 0,
        criticalErrors: 0,
      },
    });
  }, []);

  // ===== Message Handling =====

  const handleMessage = useCallback((message: WebSocketMessage) => {
    console.log("📨 Backend message:", message.type, message.data);

    switch (message.type) {
      case "state_update":
        // Full state update from backend
        setState((prev) => ({
          ...prev,
          ...message.data,
        }));
        break;

      case "detected_error":
        // CRITICAL: New error detected by Node C Arbiter
        const error: DetectedError = message.data;

        setState((prev) => ({
          ...prev,
          errors: [...prev.errors, error],
          stats: {
            ...prev.stats,
            totalErrors: prev.stats.totalErrors + 1,
            criticalErrors: error.severity === "critical"
              ? prev.stats.criticalErrors + 1
              : prev.stats.criticalErrors,
          },
        }));

        // Trigger callback if provided
        if (onError) {
          onError(error);
        }

        // Flash critical errors
        if (error.severity === "critical") {
          triggerCriticalAlert(error);
        }
        break;

      case "transcript":
        // New transcript segment
        setState((prev) => ({
          ...prev,
          transcripts: [...prev.transcripts, message.data].slice(-100), // Keep last 100
          stats: {
            ...prev.stats,
            totalSegments: prev.stats.totalSegments + 1,
          },
        }));
        break;

      case "alignment":
        // New alignment match
        setState((prev) => ({
          ...prev,
          alignments: [...prev.alignments, message.data].slice(-50), // Keep last 50
        }));
        break;

      case "session_start":
        setState((prev) => ({
          ...prev,
          sessionId: message.data.session_id,
          isActive: true,
        }));
        console.log("🟢 Session started:", message.data.session_id);
        break;

      case "session_end":
        setState((prev) => ({
          ...prev,
          isActive: false,
        }));
        console.log("🔴 Session ended");
        break;

      default:
        console.warn("Unknown message type:", message.type);
    }
  }, [onError]);

  // ===== Critical Alert =====

  const triggerCriticalAlert = useCallback((error: DetectedError) => {
    console.error("🚨 CRITICAL ERROR DETECTED:", error.description);

    // Flash screen red
    if (typeof document !== "undefined") {
      document.body.classList.add("critical-alert");
      setTimeout(() => {
        document.body.classList.remove("critical-alert");
      }, 1000);
    }

    // Browser notification (if permitted)
    if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "granted") {
      new Notification("🔴 CRITICAL ERROR DETECTED", {
        body: error.description,
        requireInteraction: true,
      });
    }
  }, []);

  // ===== Actions =====

  const startSession = useCallback((sessionId?: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.error("Cannot start session: WebSocket not connected");
      return;
    }

    const message = {
      type: "start_session",
      data: { session_id: sessionId || `session_${Date.now()}` },
    };

    wsRef.current.send(JSON.stringify(message));
    console.log("Starting session:", message.data.session_id);
  }, []);

  const clearErrors = useCallback(() => {
    setState((prev) => ({
      ...prev,
      errors: [],
      stats: {
        ...prev.stats,
        totalErrors: 0,
        criticalErrors: 0,
      },
    }));
  }, []);

  // ===== Auto-connect Effect =====

  useEffect(() => {
    if (autoConnect) {
      connect();
    }

    // Cleanup on unmount
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close(1000, "Component unmount");
      }
    };
  }, [autoConnect, connect]);

  // ===== Return =====

  return {
    isConnected,
    connectionError,
    state,
    connect,
    disconnect,
    startSession,
    clearErrors,
    ws: wsRef.current,
  };
}
