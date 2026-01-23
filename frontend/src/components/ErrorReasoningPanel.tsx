/**
 * Error Reasoning Panel Component
 * ================================
 * PHASE 3: Shows medical entities extracted, alignment alternatives,
 * and which entities triggered the error - full transparency.
 */

"use client";

import { useState } from "react";
import { clsx } from "clsx";
import {
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Target,
  Activity,
  TrendingUp,
  Maximize2,
} from "lucide-react";
import {
  ClinicalError,
  MedicalEntity,
  AlignmentMatch,
  AlignmentAlternative,
} from "@/types/sarasvati";

interface ErrorReasoningPanelProps {
  error: ClinicalError;
  className?: string;
}

const ENTITY_TYPE_COLORS: Record<string, string> = {
  drug: "bg-purple-500/20 text-purple-400 border-purple-500",
  dosage: "bg-blue-500/20 text-blue-400 border-blue-500",
  frequency: "bg-green-500/20 text-green-400 border-green-500",
  condition: "bg-red-500/20 text-red-400 border-red-500",
  instruction: "bg-yellow-500/20 text-yellow-400 border-yellow-500",
  default: "bg-gray-500/20 text-gray-400 border-gray-500",
};

function EntityBadge({
  entity,
  isTriggering,
}: {
  entity: MedicalEntity;
  isTriggering?: boolean;
}) {
  const colorClass =
    ENTITY_TYPE_COLORS[entity.entity_type] || ENTITY_TYPE_COLORS.default;

  return (
    <div
      className={clsx(
        "inline-flex items-center gap-2 px-2 py-1 rounded border text-xs",
        colorClass,
        isTriggering && "ring-2 ring-yellow-400 ring-offset-2 ring-offset-gray-900"
      )}
    >
      {isTriggering && <AlertTriangle className="w-3 h-3 text-yellow-400" />}
      <span className="font-medium">{entity.entity_type}</span>
      <span className="opacity-75">|</span>
      <span>{entity.text}</span>
      {entity.normalized !== entity.text && (
        <>
          <span className="opacity-50">→</span>
          <span className="opacity-75">{entity.normalized}</span>
        </>
      )}
      <span className="opacity-50 text-[10px]">
        ({(entity.confidence * 100).toFixed(0)}%)
      </span>
    </div>
  );
}

function MedicalEntitiesSection({ error }: { error: ClinicalError }) {
  const [isExpanded, setIsExpanded] = useState(true);

  const providerEntities = error.provider_entity ? [error.provider_entity] : [];
  const interpreterEntities = error.interpreter_entity
    ? [error.interpreter_entity]
    : [];

  // Get triggering entities
  const triggeringEntityIds = new Set(
    error.triggering_entities?.map((e) => `${e.entity_type}-${e.text}`) || []
  );

  const isTriggeringEntity = (entity: MedicalEntity) => {
    return triggeringEntityIds.has(`${entity.entity_type}-${entity.text}`);
  };

  if (providerEntities.length === 0 && interpreterEntities.length === 0) {
    return null;
  }

  return (
    <div className="bg-gray-800/50 rounded-lg border border-gray-700">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-3 hover:bg-gray-800/70"
      >
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-semibold text-gray-200">
            Medical Entities Extracted
          </span>
        </div>
        {isExpanded ? (
          <ChevronUp className="w-4 h-4 text-gray-400" />
        ) : (
          <ChevronDown className="w-4 h-4 text-gray-400" />
        )}
      </button>

      {isExpanded && (
        <div className="p-3 pt-0 space-y-3">
          {providerEntities.length > 0 && (
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">
                Provider/Patient (Source)
              </div>
              <div className="flex flex-wrap gap-2">
                {providerEntities.map((entity, idx) => (
                  <EntityBadge
                    key={idx}
                    entity={entity}
                    isTriggering={isTriggeringEntity(entity)}
                  />
                ))}
              </div>
            </div>
          )}

          {interpreterEntities.length > 0 && (
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">
                Interpreter
              </div>
              <div className="flex flex-wrap gap-2">
                {interpreterEntities.map((entity, idx) => (
                  <EntityBadge
                    key={idx}
                    entity={entity}
                    isTriggering={isTriggeringEntity(entity)}
                  />
                ))}
              </div>
            </div>
          )}

          {error.triggering_entities && error.triggering_entities.length > 0 && (
            <div className="bg-yellow-500/10 border border-yellow-500/30 rounded p-2">
              <div className="text-xs text-yellow-400 flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" />
                <span className="font-semibold">
                  {error.triggering_entities.length} triggering entit
                  {error.triggering_entities.length === 1 ? "y" : "ies"}
                </span>
                <span className="text-gray-400 ml-1">
                  (highlighted with yellow ring)
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AlignmentAlternativesSection({ error }: { error: ClinicalError }) {
  const [isExpanded, setIsExpanded] = useState(false);

  const alignment = error.alignment_info;
  if (!alignment || !alignment.alternatives_considered) {
    return null;
  }

  const alternatives = alignment.alternatives_considered;
  if (alternatives.length === 0) {
    return null;
  }

  return (
    <div className="bg-gray-800/50 rounded-lg border border-gray-700">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-3 hover:bg-gray-800/70"
      >
        <div className="flex items-center gap-2">
          <Target className="w-4 h-4 text-purple-400" />
          <span className="text-sm font-semibold text-gray-200">
            Alignment Analysis
          </span>
          <span className="text-xs text-gray-500">
            ({alternatives.length} alternative{alternatives.length !== 1 ? "s" : ""}{" "}
            considered)
          </span>
        </div>
        {isExpanded ? (
          <ChevronUp className="w-4 h-4 text-gray-400" />
        ) : (
          <ChevronDown className="w-4 h-4 text-gray-400" />
        )}
      </button>

      {isExpanded && (
        <div className="p-3 pt-0 space-y-3">
          {/* Primary match */}
          <div>
            <div className="flex items-center gap-2 text-xs text-green-400 mb-2">
              <CheckCircle className="w-3 h-3" />
              <span className="font-semibold uppercase tracking-wide">
                Primary Match (Chosen)
              </span>
            </div>
            <div className="bg-green-500/10 border border-green-500/30 rounded p-3">
              <div className="grid grid-cols-3 gap-3 text-xs mb-2">
                <div>
                  <div className="text-gray-500">Similarity</div>
                  <div className="text-gray-200 font-mono">
                    {(alignment.similarity_score * 100).toFixed(1)}%
                  </div>
                </div>
                <div>
                  <div className="text-gray-500">DTW Distance</div>
                  <div className="text-gray-200 font-mono">
                    {alignment.dtw_distance.toFixed(3)}
                  </div>
                </div>
                <div>
                  <div className="text-gray-500">Time Delta</div>
                  <div className="text-gray-200 font-mono">
                    {alignment.time_delta.toFixed(1)}s
                  </div>
                </div>
              </div>
              {alignment.interpreter_segment && (
                <div className="text-xs">
                  <div className="text-gray-500">Interpreter text:</div>
                  <div className="text-gray-300 mt-1">
                    "{alignment.interpreter_segment.text}"
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Alternatives */}
          <div>
            <div className="flex items-center gap-2 text-xs text-gray-400 mb-2">
              <XCircle className="w-3 h-3" />
              <span className="font-semibold uppercase tracking-wide">
                Rejected Alternatives
              </span>
            </div>
            <div className="space-y-2">
              {alternatives.map((alt, idx) => (
                <div
                  key={idx}
                  className="bg-gray-900/50 border border-gray-700 rounded p-3"
                >
                  <div className="grid grid-cols-3 gap-3 text-xs mb-2">
                    <div>
                      <div className="text-gray-500">Similarity</div>
                      <div className="text-gray-400 font-mono">
                        {(alt.similarity_score * 100).toFixed(1)}%
                      </div>
                    </div>
                    <div>
                      <div className="text-gray-500">Combined Score</div>
                      <div className="text-gray-400 font-mono">
                        {(alt.combined_score * 100).toFixed(1)}%
                      </div>
                    </div>
                    <div>
                      <div className="text-gray-500">Time Delta</div>
                      <div className="text-gray-400 font-mono">
                        {alt.time_delta.toFixed(1)}s
                      </div>
                    </div>
                  </div>
                  <div className="text-xs">
                    <div className="text-gray-500">Interpreter text:</div>
                    <div className="text-gray-400 mt-1">
                      "{alt.interpreter_segment.text}"
                    </div>
                  </div>
                  <div className="text-xs text-red-400 mt-2 flex items-start gap-1">
                    <XCircle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                    <span>{alt.rejection_reason}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* DTW explanation */}
          <div className="bg-blue-500/10 border border-blue-500/30 rounded p-2 text-xs">
            <div className="flex items-start gap-2">
              <TrendingUp className="w-4 h-4 text-blue-400 mt-0.5" />
              <div>
                <div className="text-blue-400 font-semibold mb-1">
                  Alignment Scoring
                </div>
                <div className="text-gray-400">
                  Combined score = 70% semantic similarity + 30% temporal alignment
                  (DTW). Lower DTW distance = better temporal match.
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ContextSection({ error }: { error: ClinicalError }) {
  const [isExpanded, setIsExpanded] = useState(true);

  return (
    <div className="bg-gray-800/50 rounded-lg border border-gray-700">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-3 hover:bg-gray-800/70"
      >
        <div className="flex items-center gap-2">
          <Maximize2 className="w-4 h-4 text-orange-400" />
          <span className="text-sm font-semibold text-gray-200">
            Tribunal Context
          </span>
        </div>
        {isExpanded ? (
          <ChevronUp className="w-4 h-4 text-gray-400" />
        ) : (
          <ChevronDown className="w-4 h-4 text-gray-400" />
        )}
      </button>

      {isExpanded && (
        <div className="p-3 pt-0 space-y-3">
          {error.source_quote && (
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">
                {error.source_role || "Source"} Said
              </div>
              <div className="text-sm text-gray-300 bg-gray-900/50 rounded p-2">
                "{error.source_quote}"
              </div>
            </div>
          )}

          {error.interpreter_quote && (
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">
                Interpreter Said
              </div>
              <div className="text-sm text-gray-300 bg-gray-900/50 rounded p-2">
                "{error.interpreter_quote}"
              </div>
            </div>
          )}

          {error.ideal_interpretation && (
            <div>
              <div className="text-xs text-green-500 uppercase tracking-wide mb-1">
                Ideal Interpretation
              </div>
              <div className="text-sm text-green-400 bg-green-500/10 border border-green-500/30 rounded p-2">
                "{error.ideal_interpretation}"
              </div>
            </div>
          )}

          {error.arbiter_reasoning && (
            <div>
              <div className="text-xs text-blue-500 uppercase tracking-wide mb-1">
                Arbiter Reasoning
              </div>
              <div className="text-sm text-gray-300 bg-blue-500/10 border border-blue-500/30 rounded p-2">
                {error.arbiter_reasoning}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ErrorReasoningPanel({
  error,
  className,
}: ErrorReasoningPanelProps) {
  return (
    <div className={clsx("space-y-3", className)}>
      <div className="text-sm font-semibold text-gray-200 flex items-center gap-2">
        <AlertTriangle className="w-4 h-4 text-yellow-400" />
        Error Reasoning & Transparency
      </div>

      <MedicalEntitiesSection error={error} />
      <AlignmentAlternativesSection error={error} />
      <ContextSection error={error} />
    </div>
  );
}
