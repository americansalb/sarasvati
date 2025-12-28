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
  lastInterpreterLanguage: string | null;
  interpreterDetectionWarning: string | null;
}

interface UseSarasvatiOptions {
  backendUrl: string;
}

interface UseSarasvatiReturn {
  connectionState: ConnectionState;
  sessionState: SessionState;
  connect: () => Promise<void>;
  disconnect: () => void;
  startRecording: (role: StreamRole, language?: string, providerLang?: string, patientLang?: string) => Promise<void>;
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
    lastInterpreterLanguage: null,
    interpreterDetectionWarning: null,
  });

  const [sessionState, setSessionState] = useState<SessionState>({
    sessionId: null,
    isActive: false,
    startTime: null,
    errors: [],
    transcripts: [],
    alignments: [],
    verdicts: [],
    debugInfo: null,
    debateLogs: null,
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
        // Enhanced error logging to help debug JSON parsing issues (e.g., Infinity)
        console.error("Failed to parse WebSocket message:", e);
        if (event.data) {
          const preview = String(event.data).substring(0, 200);
          console.error("Message preview:", preview);
        }
        // Continue processing other messages - don't break the connection
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
        // CRITICAL: Reset ALL state on new session to prevent leakage
        setSessionState({
          sessionId: event.data.session_id,
          isActive: true,
          startTime: new Date(),
          errors: [],          // Clear old errors
          transcripts: [],     // Clear old transcripts
          alignments: [],      // Clear old alignments
          verdicts: [],        // Clear old verdicts
          debugInfo: null,     // Clear debug info
        });
        console.log("🔄 Session reset: all state cleared for new session");
        break;

      case "transcript":
        if (
          event.data?.role === "interpreter" &&
          event.data?.detected_language &&
          event.data.detected_language !== "auto"
        ) {
          const detectedLang: string = event.data.detected_language;
          setConnectionState((prev) => ({
            ...prev,
            lastInterpreterLanguage: detectedLang,
            interpreterDetectionWarning:
              detectedLang !== providerLangRef.current && detectedLang !== patientLangRef.current
                ? `Interpreter detected speaking "${detectedLang}" (expected ${providerLangRef.current} or ${patientLangRef.current})`
                : null,
          }));
        }
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

      case "tribunal_verdict":
        console.log("⚖️ TRIBUNAL VERDICT:", event.data);
        // Append tribunal errors to the errors list so they show in UI
        const verdictErrors = event.data.errors || [];
        setSessionState((prev) => ({
          ...prev,
          verdicts: [...(prev.verdicts || []), event.data].slice(-20),
          errors: [...prev.errors, ...verdictErrors].slice(-50),
          // Update debate logs if present in verdict
          debateLogs: event.data.debate_logs || prev.debateLogs,
        }));
        break;

      case "debate_log":
        console.log("🏛️ DEBATE LOG:", event.data);
        // Store the visible debate log from two-tribunal architecture
        setSessionState((prev) => ({
          ...prev,
          debateLogs: event.data,
        }));
        break;

      case "detected_error":
        console.warn("🚨 DETECTED ERROR:", event.data);
        setSessionState((prev) => ({
          ...prev,
          errors: [...prev.errors, event.data],
        }));
        break;
    }
  }, []);

  // ===== Audio Recording =====

  const providerLangRef = useRef<string>("en");
  const patientLangRef = useRef<string>("auto");

  const audioLevelRef = useRef<number>(0);
  const audioContextRef = useRef<AudioContext | null>(null);

  const startRecording = useCallback(async (
    role: StreamRole,
    language: string = "auto",
    providerLang: string = "en",
    patientLang: string = "auto"
  ) => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      currentRoleRef.current = role;
      currentLangRef.current = language;
      providerLangRef.current = providerLang;
      patientLangRef.current = patientLang;
      audioChunksRef.current = [];
      audioLevelRef.current = 0;

      // Create audio context to monitor audio levels
      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);

      const dataArray = new Uint8Array(analyser.frequencyBinCount);

      // Monitor audio levels
      const checkAudioLevel = () => {
        analyser.getByteFrequencyData(dataArray);
        const average = dataArray.reduce((a, b) => a + b) / dataArray.length;
        audioLevelRef.current = Math.max(audioLevelRef.current, average);
      };

      const levelCheckInterval = setInterval(checkAudioLevel, 100);

      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: "audio/webm;codecs=opus",
      });

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        clearInterval(levelCheckInterval);
        audioContextRef.current?.close();

        const audioBlob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        const maxLevel = audioLevelRef.current;

        // Validate audio blob size and audio levels
        console.log(`🎧 Audio blob: ${audioBlob.size} bytes (${audioChunksRef.current.length} chunks), max level: ${maxLevel.toFixed(1)}`);

        if (audioBlob.size < 100) {
          console.error("⚠️ Audio blob is too small! This will likely result in 'Thank you' hallucination.");
          console.error("   Make sure you speak for at least 1-2 seconds after clicking Start Recording.");
          setConnectionState((prev) => ({
            ...prev,
            error: "Audio too short - please record for at least 1-2 seconds",
          }));
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        // Check if audio contains actual sound (not just silence)
        // Typical speech has levels > 10-20, silence is < 5
        if (maxLevel < 5) {
          console.error("⚠️ NO AUDIO DETECTED! Microphone may be muted, off, or not selected.");
          console.error(`   Audio level: ${maxLevel.toFixed(1)} (expected > 10 for speech)`);
          console.error("   This would cause Whisper to hallucinate 'Thank you'");
          setConnectionState((prev) => ({
            ...prev,
            error: "No audio detected - check your microphone is on and selected",
          }));
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        await sendAudioForTranscription(
          audioBlob,
          currentRoleRef.current,
          currentLangRef.current,
          providerLangRef.current,
          patientLangRef.current
        );
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

  const sendAudioForTranscription = async (
    audioBlob: Blob,
    role: StreamRole,
    language: string = "auto",
    providerLang: string = "en",
    patientLang: string = "auto"
  ) => {
    try {
      const formData = new FormData();
      formData.append("audio", audioBlob, "recording.webm");
      formData.append("role", role);
      formData.append("language", language);
      formData.append("provider_lang", providerLang);
      formData.append("patient_lang", patientLang);

      console.log(`🌐 Sending ${audioBlob.size} bytes to /transcribe for ${role}`);

      const response = await fetch(`${options.backendUrl}/transcribe`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Transcription failed (${response.status}): ${errorText}`);
      }

      const result = await response.json();
      console.log(`📝 Transcription (${role}):`, result.text);
      console.log(`   🎧 Audio duration: ${result.duration?.toFixed(2)}s`);
      if (result.detected_language && result.detected_language !== "auto") {
        console.log(`   🌐 Detected language: ${result.detected_language}`);
      }

      // Warn if transcription seems suspicious (known Whisper hallucination)
      if (result.text === "Thank you." || result.text === "Thanks for watching!" || result.text === "Thank you for watching.") {
        console.warn("⚠️ POSSIBLE WHISPER HALLUCINATION detected!");
        console.warn("   This usually means the audio was too short, silent, or corrupted.");
        console.warn(`   Audio size: ${audioBlob.size} bytes, Duration: ${result.duration}s`);
      }

      if (role === "interpreter") {
        const detectedLang: string | null = result.detected_language || null;
        setConnectionState((prev) => ({
          ...prev,
          lastInterpreterLanguage: detectedLang,
          interpreterDetectionWarning:
            detectedLang &&
            detectedLang !== providerLang &&
            detectedLang !== patientLang
              ? `Interpreter detected speaking "${detectedLang}" (expected ${providerLang} or ${patientLang})`
              : null,
        }));
      }

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
