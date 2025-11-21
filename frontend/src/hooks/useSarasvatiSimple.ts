/**
 * SARASVATI Simple Connection Hook
 * =================================
 * Browser audio capture + Groq Whisper + Backend WebSocket
 * No LiveKit dependency.
 */

"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  SessionState,
  StreamRole,
} from "@/types/sarasvati";

// ===== Types =====

interface ConnectionState {
  websocketConnected: boolean;
  microphoneActive: boolean;
  isRecording: boolean;
  error: string | null;
}

interface UseSarasvatiOptions {
  backendUrl: string;
}

interface UseSarasvatiReturn {
  connectionState: ConnectionState;
  sessionState: SessionState;
  connect: () => Promise<void>;
  disconnect: () => void;
  startRecording: (role: StreamRole) => Promise<void>;
  stopRecording: () => void;
  sendTranscript: (role: StreamRole, text: string) => void;
}

// ===== Helper: Get WebSocket URL =====

function getWebSocketUrl(backendUrl: string): string {
  return backendUrl
    .replace(/^https:\/\//, "wss://")
    .replace(/^http:\/\//, "ws://")
    .replace(/\/$/, "") + "/ws";
}

// ===== Hook =====

export function useSarasvatiSimple(options: UseSarasvatiOptions): UseSarasvatiReturn {
  const [connectionState, setConnectionState] = useState<ConnectionState>({
    websocketConnected: false,
    microphoneActive: false,
    isRecording: false,
    error: null,
  });

  const [sessionState, setSessionState] = useState<SessionState>({
    sessionId: null,
    isActive: false,
    startTime: null,
    errors: [],
    transcripts: [],
    alignments: [],
    debugInfo: null,
  });

  const socketRef = useRef<WebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const currentRoleRef = useRef<StreamRole>("provider");
  const currentLangRef = useRef<string>("auto");

  // ===== WebSocket Connection =====

  const connect = useCallback(async () => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      console.log("WebSocket already connected");
      return;
    }

    const wsUrl = getWebSocketUrl(options.backendUrl);
    console.log("Connecting to backend WebSocket...", wsUrl);

    const socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      console.log("✅ WebSocket connected");
      setConnectionState((prev) => ({ ...prev, websocketConnected: true, error: null }));
      socket.send(JSON.stringify({ type: "start_session", data: {} }));
    };

    socket.onclose = () => {
      console.log("⚠️ WebSocket disconnected");
      setConnectionState((prev) => ({ ...prev, websocketConnected: false }));
    };

    socket.onerror = () => {
      console.error("WebSocket error");
      setConnectionState((prev) => ({ ...prev, error: "WebSocket connection error" }));
    };

    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleBackendEvent({ type: msg.type, data: msg.data });
      } catch (e) {
        console.error("Failed to parse WebSocket message:", e);
      }
    };

    socketRef.current = socket;
  }, [options.backendUrl]);

  const disconnect = useCallback(() => {
    stopRecording();
    if (socketRef.current) {
      socketRef.current.close();
      socketRef.current = null;
      setConnectionState((prev) => ({ ...prev, websocketConnected: false }));
    }
  }, []);

  // ===== Backend Event Handler =====

  const handleBackendEvent = useCallback((event: { type: string; data: any }) => {
    console.log("Backend event:", event.type, event.data);

    switch (event.type) {
      case "session_start":
      case "session":
        setSessionState((prev) => ({
          ...prev,
          sessionId: event.data.session_id,
          isActive: true,
          startTime: new Date(),
        }));
        break;

      case "transcript":
        setSessionState((prev) => ({
          ...prev,
          transcripts: [...prev.transcripts, event.data].slice(-50),
        }));
        break;

      case "error":
        console.warn("🚨 Error detected:", event.data);
        setSessionState((prev) => ({
          ...prev,
          errors: [...prev.errors, event.data],
        }));
        break;

      case "alignment":
        setSessionState((prev) => ({
          ...prev,
          alignments: [...prev.alignments, event.data].slice(-20),
        }));
        break;
    }
  }, []);

  // ===== Audio Recording =====

  const startRecording = useCallback(async (role: StreamRole, language: string = "auto") => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      currentRoleRef.current = role;
      currentLangRef.current = language;
      audioChunksRef.current = [];

      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: "audio/webm;codecs=opus",
      });

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        await sendAudioForTranscription(audioBlob, currentRoleRef.current, currentLangRef.current);
        stream.getTracks().forEach((track) => track.stop());
      };

      mediaRecorder.start(1000); // Collect data every second
      mediaRecorderRef.current = mediaRecorder;

      setConnectionState((prev) => ({
        ...prev,
        microphoneActive: true,
        isRecording: true,
      }));

      console.log(`🎤 Recording started for ${role}`);
    } catch (error) {
      console.error("Failed to start recording:", error);
      setConnectionState((prev) => ({
        ...prev,
        error: "Microphone access denied",
      }));
    }
  }, []);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current = null;
      setConnectionState((prev) => ({
        ...prev,
        isRecording: false,
        microphoneActive: false,
      }));
      console.log("🎤 Recording stopped");
    }
  }, []);

  // ===== Send Audio to Backend for Whisper Transcription =====

  const sendAudioForTranscription = async (audioBlob: Blob, role: StreamRole, language: string = "auto") => {
    try {
      const formData = new FormData();
      formData.append("audio", audioBlob, "recording.webm");
      formData.append("role", role);
      formData.append("language", language);

      const response = await fetch(`${options.backendUrl}/transcribe`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`Transcription failed: ${response.statusText}`);
      }

      const result = await response.json();
      console.log(`📝 Transcription (${role}):`, result.text);

      // The backend will broadcast the transcript via WebSocket
    } catch (error) {
      console.error("Transcription error:", error);
    }
  };

  // ===== Manual Transcript Input (for testing) =====

  const sendTranscript = useCallback((role: StreamRole, text: string) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          type: "transcript",
          data: {
            role,
            text,
            timestamp: Date.now() / 1000,
            duration: 0,
            confidence: 1.0,
            is_final: true,
          },
        })
      );
      console.log(`📝 Sent transcript (${role}):`, text);
    }
  }, []);

  // ===== Cleanup on unmount =====

  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return {
    connectionState,
    sessionState,
    connect,
    disconnect,
    startRecording,
    stopRecording,
    sendTranscript,
  };
}
