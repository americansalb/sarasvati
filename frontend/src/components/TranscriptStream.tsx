/**
 * Transcript Stream Component
 * ============================
 * Live scrolling transcript display with speaker identification
 */

"use client";

import { useEffect, useRef } from "react";
import { TranscriptSegment, StreamRole } from "@/types/sarasvati";
import { formatDistanceToNow } from "date-fns";
import { clsx } from "clsx";

interface TranscriptStreamProps {
  transcripts: TranscriptSegment[];
  maxHeight?: number;
  className?: string;
}

const ROLE_STYLES = {
  provider: {
    bg: "bg-blue-500/10",
    border: "border-blue-500/30",
    text: "text-blue-400",
    icon: "👨‍⚕️",
    label: "Provider",
  },
  interpreter: {
    bg: "bg-purple-500/10",
    border: "border-purple-500/30",
    text: "text-purple-400",
    icon: "🌐",
    label: "Interpreter",
  },
  patient: {
    bg: "bg-green-500/10",
    border: "border-green-500/30",
    text: "text-green-400",
    icon: "🧑",
    label: "Patient",
  },
};

function TranscriptEntry({ segment }: { segment: TranscriptSegment }) {
  const style = ROLE_STYLES[segment.role];
  const timestamp = new Date(Date.now() - segment.timestamp * 1000);

  return (
    <div
      className={clsx(
        "transcript-entry p-3 rounded-lg border transition-all",
        style.bg,
        style.border,
        !segment.is_final && "opacity-60 italic"
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className="text-lg">{style.icon}</span>
          <span className={clsx("font-semibold text-sm", style.text)}>
            {style.label}
          </span>
          {segment.speaker_id && (
            <span className="text-xs text-gray-500">
              ({segment.speaker_id})
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span
            className="px-2 py-0.5 rounded bg-gray-800"
            title="Confidence score"
          >
            {(segment.confidence * 100).toFixed(0)}%
          </span>
          <span title="Timestamp">
            {formatDistanceToNow(timestamp, { addSuffix: true })}
          </span>
        </div>
      </div>

      {/* Text */}
      <p className="text-gray-200 leading-relaxed">{segment.text}</p>

      {/* Status */}
      {!segment.is_final && (
        <p className="text-xs text-gray-500 mt-1">Interim transcript...</p>
      )}
    </div>
  );
}

export function TranscriptStream({
  transcripts,
  maxHeight = 400,
  className = "",
}: TranscriptStreamProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);

  // Auto-scroll to bottom when new transcripts arrive
  useEffect(() => {
    if (autoScrollRef.current && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [transcripts]);

  // Detect manual scroll (disable auto-scroll if user scrolls up)
  const handleScroll = () => {
    if (!containerRef.current) return;

    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;

    autoScrollRef.current = isAtBottom;
  };

  return (
    <div className={`transcript-stream ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <span className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
          Live Transcript
        </h2>

        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-400">
            {transcripts.length} segments
          </span>

          <button
            onClick={() => {
              autoScrollRef.current = true;
              if (containerRef.current) {
                containerRef.current.scrollTop =
                  containerRef.current.scrollHeight;
              }
            }}
            className="px-3 py-1 text-xs rounded bg-gray-800 hover:bg-gray-700 transition"
          >
            Jump to Latest
          </button>
        </div>
      </div>

      {/* Transcript Container */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="transcript-container space-y-3 overflow-y-auto scrollbar-thin scrollbar-thumb-gray-700 scrollbar-track-gray-900"
        style={{ maxHeight: `${maxHeight}px` }}
      >
        {transcripts.length === 0 ? (
          <div className="text-center py-12">
            <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-gray-800 flex items-center justify-center">
              <span className="text-3xl">🎤</span>
            </div>
            <p className="text-gray-400">Waiting for conversation to start...</p>
            <p className="text-sm text-gray-500 mt-1">
              Transcripts will appear here in real-time
            </p>
          </div>
        ) : (
          transcripts.map((segment, index) => (
            <TranscriptEntry key={index} segment={segment} />
          ))
        )}
      </div>

      {/* Auto-scroll indicator */}
      {!autoScrollRef.current && (
        <div className="mt-2 text-center">
          <p className="text-xs text-gray-500">
            Auto-scroll disabled (scroll to bottom to re-enable)
          </p>
        </div>
      )}
    </div>
  );
}
