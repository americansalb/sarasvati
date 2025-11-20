/**
 * Arbiter Log Component
 * ======================
 * Displays detected clinical errors with severity-based styling
 */

"use client";

import { useState } from "react";
import { ClinicalError, ErrorSeverity } from "@/types/sarasvati";
import { formatDistanceToNow } from "date-fns";
import { clsx } from "clsx";
import {
  AlertTriangle,
  AlertCircle,
  Info,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  X,
} from "lucide-react";

interface ArbiterLogProps {
  errors: ClinicalError[];
  onClearErrors?: () => void;
  className?: string;
}

const SEVERITY_CONFIG: Record<
  ErrorSeverity,
  {
    icon: React.ComponentType<{ className?: string }>;
    color: string;
    bgColor: string;
    borderColor: string;
    label: string;
  }
> = {
  critical: {
    icon: AlertTriangle,
    color: "text-red-400",
    bgColor: "bg-red-500/10",
    borderColor: "border-red-500",
    label: "CRITICAL",
  },
  high: {
    icon: AlertCircle,
    color: "text-orange-400",
    bgColor: "bg-orange-500/10",
    borderColor: "border-orange-500",
    label: "HIGH",
  },
  medium: {
    icon: Info,
    color: "text-yellow-400",
    bgColor: "bg-yellow-500/10",
    borderColor: "border-yellow-500",
    label: "MEDIUM",
  },
  low: {
    icon: CheckCircle,
    color: "text-blue-400",
    bgColor: "bg-blue-500/10",
    borderColor: "border-blue-500",
    label: "LOW",
  },
};

function ErrorCard({ error }: { error: ClinicalError }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const config = SEVERITY_CONFIG[error.severity];
  const Icon = config.icon;
  const timestamp = new Date(error.detected_at);

  return (
    <div
      className={clsx(
        "error-card rounded-lg border-l-4 p-4 transition-all",
        config.bgColor,
        config.borderColor,
        "hover:shadow-lg"
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-start gap-3 flex-1">
          <Icon className={clsx("w-5 h-5 mt-0.5", config.color)} />

          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <span
                className={clsx(
                  "px-2 py-0.5 rounded text-xs font-bold uppercase",
                  config.color
                )}
              >
                {config.label}
              </span>
              <span className="text-xs text-gray-500">
                {error.error_type.replace(/_/g, " ")}
              </span>
              <span
                className="text-xs text-gray-500"
                title="Confidence score"
              >
                {(error.confidence * 100).toFixed(0)}%
              </span>
            </div>

            <p className="text-sm text-gray-200 font-medium">
              {error.description}
            </p>
          </div>
        </div>

        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="p-1 rounded hover:bg-gray-800 transition ml-2"
        >
          {isExpanded ? (
            <ChevronUp className="w-4 h-4" />
          ) : (
            <ChevronDown className="w-4 h-4" />
          )}
        </button>
      </div>

      {/* Timestamp */}
      <p className="text-xs text-gray-500 ml-8 mb-2">
        Detected {formatDistanceToNow(timestamp, { addSuffix: true })}
      </p>

      {/* Expanded Details */}
      {isExpanded && (
        <div className="ml-8 mt-3 pt-3 border-t border-gray-800 space-y-3">
          {/* Arbiter Reasoning */}
          <div>
            <h4 className="text-xs font-semibold text-gray-400 mb-1">
              💭 Arbiter&apos;s Reasoning:
            </h4>
            <p className="text-sm text-gray-300 leading-relaxed">
              {error.arbiter_reasoning}
            </p>
          </div>

          {/* Entities */}
          {error.provider_entity && (
            <div>
              <h4 className="text-xs font-semibold text-gray-400 mb-1">
                📝 Provider Entity:
              </h4>
              <div className="text-sm bg-gray-900 rounded p-2">
                <span className="text-blue-400">
                  {error.provider_entity.entity_type}:
                </span>{" "}
                {error.provider_entity.text}
                <span className="text-gray-500 ml-2">
                  (normalized: {error.provider_entity.normalized})
                </span>
              </div>
            </div>
          )}

          {error.interpreter_entity && (
            <div>
              <h4 className="text-xs font-semibold text-gray-400 mb-1">
                🌐 Interpreter Entity:
              </h4>
              <div className="text-sm bg-gray-900 rounded p-2">
                <span className="text-purple-400">
                  {error.interpreter_entity.entity_type}:
                </span>{" "}
                {error.interpreter_entity.text}
              </div>
            </div>
          )}

          {/* Alignment Info */}
          <div>
            <h4 className="text-xs font-semibold text-gray-400 mb-1">
              🔗 Alignment Details:
            </h4>
            <div className="text-sm bg-gray-900 rounded p-2 space-y-1">
              <div>
                <span className="text-gray-400">Similarity:</span>{" "}
                <span
                  className={clsx(
                    "font-mono",
                    error.alignment_info.similarity_score > 0.8
                      ? "text-green-400"
                      : error.alignment_info.similarity_score > 0.5
                      ? "text-yellow-400"
                      : "text-red-400"
                  )}
                >
                  {(error.alignment_info.similarity_score * 100).toFixed(1)}%
                </span>
              </div>
              <div>
                <span className="text-gray-400">Time Delta:</span>{" "}
                <span className="font-mono text-gray-300">
                  {error.alignment_info.time_delta.toFixed(1)}s
                </span>
              </div>
              <div>
                <span className="text-gray-400">DTW Distance:</span>{" "}
                <span className="font-mono text-gray-300">
                  {error.alignment_info.dtw_distance.toFixed(3)}
                </span>
              </div>
            </div>
          </div>

          {/* Error ID */}
          <p className="text-xs text-gray-600 font-mono">{error.error_id}</p>
        </div>
      )}
    </div>
  );
}

export function ArbiterLog({
  errors,
  onClearErrors,
  className = "",
}: ArbiterLogProps) {
  // Count by severity
  const severityCounts = errors.reduce(
    (acc, error) => {
      acc[error.severity] = (acc[error.severity] || 0) + 1;
      return acc;
    },
    {} as Record<ErrorSeverity, number>
  );

  return (
    <div className={`arbiter-log ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <span className="text-2xl">⚖️</span>
            Arbiter&apos;s Log
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            Real-time clinical error detection
          </p>
        </div>

        {errors.length > 0 && (
          <button
            onClick={onClearErrors}
            className="px-3 py-2 rounded bg-red-500/20 hover:bg-red-500/30 text-red-400 text-sm flex items-center gap-2 transition"
          >
            <X className="w-4 h-4" />
            Clear All
          </button>
        )}
      </div>

      {/* Severity Summary */}
      {errors.length > 0 && (
        <div className="grid grid-cols-4 gap-3 mb-4">
          {(["critical", "high", "medium", "low"] as ErrorSeverity[]).map(
            (severity) => {
              const config = SEVERITY_CONFIG[severity];
              const count = severityCounts[severity] || 0;
              const Icon = config.icon;

              return (
                <div
                  key={severity}
                  className={clsx(
                    "p-3 rounded-lg border",
                    config.bgColor,
                    config.borderColor
                  )}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <Icon className={clsx("w-4 h-4", config.color)} />
                    <span className={clsx("text-xs font-bold", config.color)}>
                      {config.label}
                    </span>
                  </div>
                  <p className="text-2xl font-bold">{count}</p>
                </div>
              );
            }
          )}
        </div>
      )}

      {/* Error List */}
      <div className="error-list space-y-3 max-h-96 overflow-y-auto scrollbar-thin scrollbar-thumb-gray-700 scrollbar-track-gray-900">
        {errors.length === 0 ? (
          <div className="text-center py-12">
            <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-gray-800 flex items-center justify-center">
              <CheckCircle className="w-8 h-8 text-green-500" />
            </div>
            <p className="text-gray-400">No errors detected</p>
            <p className="text-sm text-gray-500 mt-1">
              The Trisul Protocol is monitoring for clinical inaccuracies
            </p>
          </div>
        ) : (
          // Sort by severity (critical first) and timestamp (newest first)
          errors
            .sort((a, b) => {
              const severityOrder = {
                critical: 0,
                high: 1,
                medium: 2,
                low: 3,
              };
              const severityDiff =
                severityOrder[a.severity] - severityOrder[b.severity];
              if (severityDiff !== 0) return severityDiff;

              return (
                new Date(b.detected_at).getTime() -
                new Date(a.detected_at).getTime()
              );
            })
            .map((error) => <ErrorCard key={error.error_id} error={error} />)
        )}
      </div>
    </div>
  );
}
