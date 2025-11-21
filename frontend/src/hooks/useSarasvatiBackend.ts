/**
 * SARASVATI Backend Connection Hook
 * ==================================
 * Phase 4: Jiva (Integration) - Connect Drishya (Frontend) to Trisul (Backend)
 *
 * Connects to ws://localhost:8000/ws and subscribes to SarasvatiState updates.
 * Exposes detected_error events for TrisulWaveform to draw red regions.
 *
 * PROTOCOL ALIGNMENT: This hook matches the backend's TypedDict schemas exactly.
 * See backend/sarasvati/core/state.py for canonical definitions.
 */

"use client";

import { useEffect, useState, useCallback, useRef } from "react";

// ===== Types (aligned with backend/sarasvati/core/state.py) =====

export type StreamRole = "provider" | "interpreter" | "patient";
export type ErrorSeverity = "critical" | "high" | "medium" | "low";

/**
 * Matches backend TranscriptSegment TypedDict
 * timestamp: seconds since stream start (NOT Unix time)
 */
export interface TranscriptSegment {
  role: StreamRole;
  text: string;
  timestamp: number; // seconds since stream start
  duration: number; // duration in seconds
  confidence: number;
  is_final: boolean;
  speaker_id?: string;
}

/**
 * Matches backend MedicalEntity TypedDict
 */
export interface MedicalEntity {
  entity_type: string; // "drug", "dosage", "frequency", "condition", "instruction"
  text: string;
  normalized: string;
  confidence: number;
  timestamp: number; // seconds since stream start
  context: string;
  embedding?: number[];
}

/**
 * Matches backend AlignmentMatch TypedDict
 */
export interface AlignmentMatch {
  provider_segment: TranscriptSegment;
  interpreter_segment: TranscriptSegment | null;
  similarity_score: number; // [0.0-1.0]
  combined_score: number; // Truth Vector: 0.7*similarity + 0.3*(1-dtw)
  time_delta: number; // interpreter_time - provider_time
  is_matched: boolean;
  dtw_distance: number;
}

/**
 * Matches backend ClinicalError TypedDict
 * This is what Node C Arbiter emits when an error is detected.
 */
export interface ClinicalError {
  error_id: string;
  severity: ErrorSeverity;
  error_type: string; // "omission", "negation_mismatch", "dosage_error", etc.
  provider_entity: MedicalEntity;
  interpreter_entity: MedicalEntity | null;
  description: string;
  arbiter_reasoning: string;
  confidence: number;
  detected_at: string; // ISO timestamp from backend datetime
  alignment_info: AlignmentMatch;
}

/**
 * Simplified error for visualization (derived from ClinicalError)
 * This is what TrisulWaveform uses to draw red regions.
 */
export interface ErrorRegion {
  id: string;
  start: number; // seconds since stream start (from alignment_info.provider_segment.timestamp)
  end: number; // start + duration
  severity: ErrorSeverity;
  description: string;
  errorType: string;
  confidence: number;
  providerText: string;
  interpreterText: string;
  arbiterReasoning: string;
}

export interface BackendState {
  sessionId: string | null;
  isActive: boolean;
  errors: ClinicalError[]; // Raw errors from backend
  errorRegions: ErrorRegion[]; // Derived for visualization
  transcripts: TranscriptSegment[];
  alignments: AlignmentMatch[];
  stats: {
    totalSegments: number;
    totalErrors: number;
    criticalErrors: number;
  };
}

export interface WebSocketMessage {
  type:
    | "state_update"
    | "detected_error"
    | "transcript"
    | "alignment"
    | "session_start"
    | "session_end";
  data: unknown;
  timestamp: number; // Unix timestamp of when message was sent
}

interface UseSarasvatiBackendOptions {
  url?: string;
  autoConnect?: boolean;
  onError?: (error: ClinicalError, region: ErrorRegion) => void;
}

interface UseSarasvatiBackendReturn {
  isConnected: boolean;
  connectionError: string | null;
  state: BackendState;
  connect: () => void;
  disconnect: () => void;
  startSession: (sessionId?: string) => void;
  stopSession: () => void;
  clearErrors: () => void;
}

// ===== Helper: Convert ClinicalError to ErrorRegion =====

function clinicalErrorToRegion(error: ClinicalError): ErrorRegion {
  // Extract timestamp from alignment_info.provider_segment
  // This is "seconds since stream start", which matches Multitrack's timeline
  const providerSegment = error.alignment_info.provider_segment;
  const start = providerSegment.timestamp;
  const duration = providerSegment.duration || 2.0; // Default 2s if missing

  return {
    id: error.error_id,
    start,
    end: start + duration,
    severity: error.severity,
    description: error.description,
    errorType: error.error_type,
    confidence: error.confidence,
    providerText: providerSegment.text,
    interpreterText: error.alignment_info.interpreter_segment?.text || "[missing]",
    arbiterReasoning: error.arbiter_reasoning,
  };
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

  const [isConnected, setIsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  const [state, setState] = useState<BackendState>({
    sessionId: null,
    isActive: false,
    errors: [],
    errorRegions: [],
    transcripts: [],
    alignments: [],
    stats: {
      totalSegments: 0,
      totalErrors: 0,
      criticalErrors: 0,
    },
  });

  // Refs for WebSocket lifecycle management
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const MAX_RECONNECT_ATTEMPTS = 5;
  const RECONNECT_DELAY_BASE = 2000;

  // ===== Cleanup helper =====

  const cleanupSocket = useCallback(() => {
    // Clear any pending reconnect timeout
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    // Close existing socket if any
    if (wsRef.current) {
      // Remove handlers before closing to prevent reconnect loop
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      wsRef.current.onopen = null;

      if (
        wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING
      ) {
        wsRef.current.close(1000, "Client cleanup");
      }
      wsRef.current = null;
    }
  }, []);

  // ===== WebSocket Connection =====

  const connect = useCallback(() => {
    // Prevent duplicate connections
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      console.log("WebSocket already connected");
      return;
    }

    // Cleanup any existing socket/timeout first
    cleanupSocket();

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
        console.log(`⚠️ WebSocket closed: code=${event.code}, reason=${event.reason}`);
        setIsConnected(false);

        // Only attempt reconnect if this wasn't a clean close
        if (event.code !== 1000) {
          if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
            reconnectAttemptsRef.current += 1;
            const delay =
              RECONNECT_DELAY_BASE * Math.pow(2, reconnectAttemptsRef.current - 1);
            console.log(
              `🔄 Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current}/${MAX_RECONNECT_ATTEMPTS})...`
            );

            reconnectTimeoutRef.current = setTimeout(() => {
              connect();
            }, delay);
          } else {
            console.error("❌ Max reconnection attempts reached");
            setConnectionError("Failed to connect after multiple attempts");
          }
        }
      };

      ws.onerror = () => {
        // Note: The error event doesn't contain useful info in browsers
        // Actual error handling happens in onclose
        console.error("WebSocket error occurred");
      };

      ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          handleMessage(message);
        } catch (err) {
          console.error("Failed to parse WebSocket message:", err);
        }
      };

      wsRef.current = ws;
    } catch (err) {
      console.error("Failed to create WebSocket:", err);
      setConnectionError(`Failed to connect: ${err}`);
    }
  }, [url, cleanupSocket]);

  const disconnect = useCallback(() => {
    console.log("Disconnecting from backend...");
    reconnectAttemptsRef.current = MAX_RECONNECT_ATTEMPTS; // Prevent auto-reconnect
    cleanupSocket();
    setIsConnected(false);

    setState({
      sessionId: null,
      isActive: false,
      errors: [],
      errorRegions: [],
      transcripts: [],
      alignments: [],
      stats: {
        totalSegments: 0,
        totalErrors: 0,
        criticalErrors: 0,
      },
    });
  }, [cleanupSocket]);

  // ===== Message Handling =====

  const handleMessage = useCallback(
    (message: WebSocketMessage) => {
      console.log("📨 Backend message:", message.type);

      switch (message.type) {
        case "state_update": {
          // Full state sync from backend
          const data = message.data as Partial<BackendState>;
          setState((prev) => ({
            ...prev,
            ...data,
            // Recalculate errorRegions if errors changed
            errorRegions: data.errors
              ? data.errors.map(clinicalErrorToRegion)
              : prev.errorRegions,
          }));
          break;
        }

        case "detected_error": {
          // New error detected by Node C Arbiter
          const error = message.data as ClinicalError;
          const region = clinicalErrorToRegion(error);

          setState((prev) => ({
            ...prev,
            errors: [...prev.errors, error],
            errorRegions: [...prev.errorRegions, region],
            stats: {
              ...prev.stats,
              totalErrors: prev.stats.totalErrors + 1,
              criticalErrors:
                error.severity === "critical"
                  ? prev.stats.criticalErrors + 1
                  : prev.stats.criticalErrors,
            },
          }));

          // Trigger callback
          if (onError) {
            onError(error, region);
          }

          // Flash for critical errors
          if (error.severity === "critical") {
            triggerCriticalAlert(error);
          }
          break;
        }

        case "transcript": {
          const segment = message.data as TranscriptSegment;
          setState((prev) => ({
            ...prev,
            transcripts: [...prev.transcripts, segment].slice(-100),
            stats: {
              ...prev.stats,
              totalSegments: prev.stats.totalSegments + 1,
            },
          }));
          break;
        }

        case "alignment": {
          const alignment = message.data as AlignmentMatch;
          setState((prev) => ({
            ...prev,
            alignments: [...prev.alignments, alignment].slice(-50),
          }));
          break;
        }

        case "session_start": {
          const data = message.data as { session_id: string };
          setState((prev) => ({
            ...prev,
            sessionId: data.session_id,
            isActive: true,
          }));
          console.log("🟢 Session started:", data.session_id);
          break;
        }

        case "session_end": {
          setState((prev) => ({
            ...prev,
            isActive: false,
          }));
          console.log("🔴 Session ended");
          break;
        }

        default:
          console.warn("Unknown message type:", message.type);
      }
    },
    [onError]
  );

  // ===== Critical Alert =====

  const triggerCriticalAlert = useCallback((error: ClinicalError) => {
    console.error("🚨 CRITICAL ERROR:", error.description);

    if (typeof document !== "undefined") {
      document.body.classList.add("critical-alert");
      setTimeout(() => {
        document.body.classList.remove("critical-alert");
      }, 1000);
    }

    if (
      typeof window !== "undefined" &&
      "Notification" in window &&
      Notification.permission === "granted"
    ) {
      new Notification("🔴 CRITICAL ERROR DETECTED", {
        body: error.description,
        requireInteraction: true,
      });
    }
  }, []);

  // ===== Actions (wrapped sends, not exposing raw ws) =====

  const sendMessage = useCallback((type: string, data: unknown) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.error("Cannot send message: WebSocket not connected");
      return false;
    }

    wsRef.current.send(JSON.stringify({ type, data }));
    return true;
  }, []);

  const startSession = useCallback(
    (sessionId?: string) => {
      const id = sessionId || `session_${Date.now()}`;
      sendMessage("start_session", { session_id: id });
      console.log("Starting session:", id);
    },
    [sendMessage]
  );

  const stopSession = useCallback(() => {
    sendMessage("stop_session", {});
    console.log("Stopping session");
  }, [sendMessage]);

  const clearErrors = useCallback(() => {
    setState((prev) => ({
      ...prev,
      errors: [],
      errorRegions: [],
      stats: {
        ...prev.stats,
        totalErrors: 0,
        criticalErrors: 0,
      },
    }));
  }, []);

  // ===== Auto-connect & Cleanup =====

  useEffect(() => {
    if (autoConnect) {
      connect();
    }

    return () => {
      cleanupSocket();
    };
  }, [autoConnect, connect, cleanupSocket]);

  return {
    isConnected,
    connectionError,
    state,
    connect,
    disconnect,
    startSession,
    stopSession,
    clearErrors,
  };
}
