/**
 * SARASVATI Connection Hook
 * ==========================
 * Custom hook for managing LiveKit room + Backend WebSocket connection.
 */

"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  Room,
  RoomEvent,
  Track,
  RemoteTrack,
  RemoteAudioTrack,
  createLocalTracks,
  LocalAudioTrack,
} from "livekit-client";
import { io, Socket } from "socket.io-client";
import {
  TranscriptSegment,
  ClinicalError,
  AlignmentMatch,
  AgentDebateResult,
  WSEvent,
  SessionState,
  ConnectionState,
  StreamRole,
  SimulationConfig,
} from "@/types/sarasvati";

interface UseSarasvatiOptions {
  livekitUrl: string;
  livekitToken?: string;
  backendWsUrl: string;
  roomName: string;
  autoConnect?: boolean;
}

interface UseSarasvatiReturn {
  // Connection state
  connectionState: ConnectionState;
  sessionState: SessionState;

  // Actions
  connect: () => Promise<void>;
  disconnect: () => Promise<void>;
  startSimulation: (config: SimulationConfig) => Promise<void>;
  clearErrors: () => void;

  // LiveKit room (for advanced usage)
  room: Room | null;
}

export function useSarasvati(
  options: UseSarasvatiOptions
): UseSarasvatiReturn {
  // State
  const [connectionState, setConnectionState] = useState<ConnectionState>({
    livekitConnected: false,
    websocketConnected: false,
    error: null,
    roomName: options.roomName,
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

  // Refs
  const roomRef = useRef<Room | null>(null);
  const socketRef = useRef<Socket | null>(null);
  const isConnectingRef = useRef(false);

  // ===== WebSocket Connection =====

  const connectWebSocket = useCallback(() => {
    if (socketRef.current?.connected) {
      console.log("WebSocket already connected");
      return;
    }

    console.log("Connecting to backend WebSocket...", options.backendWsUrl);

    const socket = io(options.backendWsUrl, {
      transports: ["websocket", "polling"],
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionAttempts: 5,
    });

    socket.on("connect", () => {
      console.log("✅ WebSocket connected");
      setConnectionState((prev) => ({ ...prev, websocketConnected: true }));
    });

    socket.on("disconnect", () => {
      console.log("⚠️ WebSocket disconnected");
      setConnectionState((prev) => ({ ...prev, websocketConnected: false }));
    });

    socket.on("error", (error: Error) => {
      console.error("WebSocket error:", error);
      setConnectionState((prev) => ({ ...prev, error: error.message }));
    });

    // Listen for backend events
    socket.on("sarasvati:event", (event: WSEvent) => {
      handleBackendEvent(event);
    });

    socketRef.current = socket;
  }, [options.backendWsUrl]);

  const disconnectWebSocket = useCallback(() => {
    if (socketRef.current) {
      socketRef.current.disconnect();
      socketRef.current = null;
      setConnectionState((prev) => ({ ...prev, websocketConnected: false }));
    }
  }, []);

  // ===== Backend Event Handler =====

  const handleBackendEvent = useCallback((event: WSEvent) => {
    console.log("Backend event:", event.type, event.data);

    switch (event.type) {
      case "transcript":
        setSessionState((prev) => ({
          ...prev,
          transcripts: [...prev.transcripts, event.data].slice(-50), // Keep last 50
        }));
        break;

      case "error":
        // CRITICAL: Flash the UI red!
        if (event.data.severity === "critical") {
          triggerCriticalAlert(event.data);
        }

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

      case "debate":
        setSessionState((prev) => ({
          ...prev,
          debugInfo: event.data,
        }));
        break;

      case "session":
        if (event.data.status === "started") {
          setSessionState((prev) => ({
            ...prev,
            sessionId: event.data.session_id,
            isActive: true,
            startTime: new Date(),
          }));
        } else if (event.data.status === "ended") {
          setSessionState((prev) => ({
            ...prev,
            isActive: false,
          }));
        }
        break;
    }
  }, []);

  // ===== Critical Alert =====

  const triggerCriticalAlert = useCallback((error: ClinicalError) => {
    // Flash screen red
    document.body.classList.add("critical-alert");
    setTimeout(() => {
      document.body.classList.remove("critical-alert");
    }, 1000);

    // Play alert sound (optional)
    if (typeof Audio !== "undefined") {
      try {
        const alert = new Audio("/sounds/alert.mp3");
        alert.volume = 0.3;
        alert.play().catch(console.error);
      } catch (e) {
        console.warn("Could not play alert sound:", e);
      }
    }

    // Browser notification (if permitted)
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification("🔴 CRITICAL ERROR DETECTED", {
        body: error.description,
        icon: "/icon-192.png",
        requireInteraction: true,
      });
    }
  }, []);

  // ===== LiveKit Connection =====

  const connectLiveKit = useCallback(async () => {
    if (roomRef.current?.state === "connected") {
      console.log("LiveKit already connected");
      return;
    }

    console.log("Connecting to LiveKit...", options.livekitUrl);

    const room = new Room({
      adaptiveStream: true,
      dynacast: true,
      videoCaptureDefaults: {
        resolution: { width: 0, height: 0 }, // Audio only
      },
    });

    // Room event handlers
    room.on(RoomEvent.Connected, () => {
      console.log("✅ LiveKit connected to room:", room.name);
      setConnectionState((prev) => ({
        ...prev,
        livekitConnected: true,
        roomName: room.name,
      }));
    });

    room.on(RoomEvent.Disconnected, () => {
      console.log("⚠️ LiveKit disconnected");
      setConnectionState((prev) => ({ ...prev, livekitConnected: false }));
    });

    room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
      console.log("Track subscribed:", track.kind, track.source);

      if (track.kind === Track.Kind.Audio) {
        const audioTrack = track as RemoteAudioTrack;
        // Attach to audio element for playback
        const audioElement = audioTrack.attach();
        document.body.appendChild(audioElement);
      }
    });

    room.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
      console.log("Track unsubscribed:", track.kind);
      track.detach().forEach((el) => el.remove());
    });

    // Connect to room
    try {
      // In production, get token from your auth server
      // For MVP, we'll connect without token (insecure!)
      await room.connect(options.livekitUrl, options.livekitToken || "");

      roomRef.current = room;
    } catch (error) {
      console.error("LiveKit connection failed:", error);
      setConnectionState((prev) => ({
        ...prev,
        error: `LiveKit connection failed: ${error}`,
      }));
      throw error;
    }
  }, [options.livekitUrl, options.livekitToken]);

  const disconnectLiveKit = useCallback(async () => {
    if (roomRef.current) {
      await roomRef.current.disconnect();
      roomRef.current = null;
      setConnectionState((prev) => ({ ...prev, livekitConnected: false }));
    }
  }, []);

  // ===== Main Connect/Disconnect =====

  const connect = useCallback(async () => {
    if (isConnectingRef.current) {
      console.log("Connection already in progress");
      return;
    }

    isConnectingRef.current = true;
    setConnectionState((prev) => ({ ...prev, error: null }));

    try {
      // Connect both LiveKit and WebSocket in parallel
      await Promise.all([connectLiveKit(), connectWebSocket()]);

      // Request notification permission
      if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission();
      }
    } catch (error) {
      console.error("Connection failed:", error);
      setConnectionState((prev) => ({
        ...prev,
        error: `Connection failed: ${error}`,
      }));
    } finally {
      isConnectingRef.current = false;
    }
  }, [connectLiveKit, connectWebSocket]);

  const disconnect = useCallback(async () => {
    await disconnectLiveKit();
    disconnectWebSocket();

    // Reset session state
    setSessionState({
      sessionId: null,
      isActive: false,
      startTime: null,
      errors: [],
      transcripts: [],
      alignments: [],
      debugInfo: null,
    });
  }, [disconnectLiveKit, disconnectWebSocket]);

  // ===== Simulation Mode =====

  const startSimulation = useCallback(
    async (config: SimulationConfig) => {
      console.log("Starting simulation mode...", config);

      if (!roomRef.current) {
        throw new Error("Not connected to LiveKit");
      }

      try {
        // Load audio files
        const providerAudio = await fetch(config.providerAudioUrl).then((r) =>
          r.arrayBuffer()
        );
        const interpreterAudio = await fetch(
          config.interpreterAudioUrl
        ).then((r) => r.arrayBuffer());
        const patientAudio = await fetch(config.patientAudioUrl).then((r) =>
          r.arrayBuffer()
        );

        // Create audio contexts
        const audioContext = new AudioContext();

        // Decode audio data
        const providerBuffer = await audioContext.decodeAudioData(
          providerAudio
        );
        const interpreterBuffer = await audioContext.decodeAudioData(
          interpreterAudio
        );
        const patientBuffer = await audioContext.decodeAudioData(patientAudio);

        // Create MediaStreamDestination for each track
        const providerDestination = audioContext.createMediaStreamDestination();
        const interpreterDestination =
          audioContext.createMediaStreamDestination();
        const patientDestination = audioContext.createMediaStreamDestination();

        // Create and play sources
        const playAudio = (
          buffer: AudioBuffer,
          destination: MediaStreamAudioDestinationNode,
          delay: number
        ) => {
          setTimeout(() => {
            const source = audioContext.createBufferSource();
            source.buffer = buffer;
            source.connect(destination);
            source.start();
          }, delay);
        };

        // Play with staggered timing
        playAudio(providerBuffer, providerDestination, 0); // Start immediately
        playAudio(interpreterBuffer, interpreterDestination, 5000); // 5s delay
        playAudio(patientBuffer, patientDestination, 10000); // 10s delay

        // Publish tracks to LiveKit (name set via publishTrack options)
        const providerTrack = new LocalAudioTrack(
          providerDestination.stream.getAudioTracks()[0]
        );
        const interpreterTrack = new LocalAudioTrack(
          interpreterDestination.stream.getAudioTracks()[0]
        );
        const patientTrack = new LocalAudioTrack(
          patientDestination.stream.getAudioTracks()[0]
        );

        await roomRef.current.localParticipant.publishTrack(providerTrack, { name: "provider" });
        await roomRef.current.localParticipant.publishTrack(interpreterTrack, { name: "interpreter" });
        await roomRef.current.localParticipant.publishTrack(patientTrack, { name: "patient" });

        console.log("✅ Simulation tracks published");
      } catch (error) {
        console.error("Simulation failed:", error);
        throw error;
      }
    },
    []
  );

  // ===== Utility Actions =====

  const clearErrors = useCallback(() => {
    setSessionState((prev) => ({ ...prev, errors: [] }));
  }, []);

  // ===== Auto-connect =====

  useEffect(() => {
    if (options.autoConnect) {
      connect();
    }

    // Cleanup on unmount
    return () => {
      if (roomRef.current || socketRef.current) {
        disconnect();
      }
    };
  }, [options.autoConnect]); // Only run on mount

  return {
    connectionState,
    sessionState,
    connect,
    disconnect,
    startSimulation,
    clearErrors,
    room: roomRef.current,
  };
}
