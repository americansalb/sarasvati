/**
 * Debate Conversation Component
 * ==============================
 * PHASE 3: Full transparency - visualize tribunal debate rounds with
 * challenge-response cycles, convergence tracking, and dissenting opinions.
 */

"use client";

import { useState } from "react";
import { clsx } from "clsx";
import {
  MessageCircle,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  CheckCircle,
  Users,
  Clock,
  TrendingUp,
  Flag,
  ArrowRight,
} from "lucide-react";
import {
  FrontendDebateLog,
  DebateRound,
  DebateTurn,
  Challenge,
  Rebuttal,
  DissentingOpinion,
  ConvergenceType,
} from "@/types/sarasvati";

interface DebateConversationProps {
  debateLog: FrontendDebateLog;
  className?: string;
}

const CONVERGENCE_CONFIG: Record<
  ConvergenceType,
  {
    icon: React.ComponentType<{ className?: string }>;
    color: string;
    bgColor: string;
    label: string;
    description: string;
  }
> = {
  full_consensus: {
    icon: CheckCircle,
    color: "text-green-400",
    bgColor: "bg-green-500/10",
    label: "Full Consensus (3/3)",
    description: "All agents agreed through debate",
  },
  strong_majority: {
    icon: Users,
    color: "text-blue-400",
    bgColor: "bg-blue-500/10",
    label: "Strong Majority (2/3)",
    description: "Two agents agreed, one weak dissent",
  },
  structured_dissent: {
    icon: AlertCircle,
    color: "text-yellow-400",
    bgColor: "bg-yellow-500/10",
    label: "Structured Dissent",
    description: "Clear disagreement - flagged for human review",
  },
  early_consensus: {
    icon: TrendingUp,
    color: "text-emerald-400",
    bgColor: "bg-emerald-500/10",
    label: "Early Consensus",
    description: "Agreed in <3 rounds",
  },
};

function ConvergenceBadge({
  convergenceType,
  consensusConfidence,
  flagged,
}: {
  convergenceType?: ConvergenceType;
  consensusConfidence: number;
  flagged: boolean;
}) {
  if (!convergenceType) return null;

  const config = CONVERGENCE_CONFIG[convergenceType];
  const Icon = config.icon;

  return (
    <div
      className={clsx(
        "flex items-center gap-2 px-3 py-2 rounded-lg border",
        config.bgColor,
        flagged ? "border-yellow-500" : "border-gray-700"
      )}
    >
      <Icon className={clsx("w-5 h-5", config.color)} />
      <div>
        <div className={clsx("text-sm font-semibold", config.color)}>
          {config.label}
        </div>
        <div className="text-xs text-gray-400">{config.description}</div>
        <div className="text-xs text-gray-500 mt-1">
          Confidence: {(consensusConfidence * 100).toFixed(0)}%
        </div>
      </div>
      {flagged && (
        <Flag className="w-4 h-4 text-yellow-400 ml-auto" title="Flagged for human review" />
      )}
    </div>
  );
}

function AgentAvatar({ agentName, provider }: { agentName: string; provider: string }) {
  const colors: Record<string, string> = {
    groq: "bg-orange-500",
    openai: "bg-green-500",
    anthropic: "bg-purple-500",
    deepseek: "bg-blue-500",
  };

  return (
    <div
      className={clsx(
        "w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-bold",
        colors[provider.toLowerCase()] || "bg-gray-500"
      )}
      title={`${agentName} (${provider})`}
    >
      {agentName.charAt(0).toUpperCase()}
    </div>
  );
}

function TurnCard({
  turn,
  challenges,
  rebuttals,
}: {
  turn: DebateTurn;
  challenges: Challenge[];
  rebuttals: Rebuttal[];
}) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Find challenges directed TO this agent
  const incomingChallenges = challenges.filter(
    (c) => c.to_agent === turn.agent && c.round_num === turn.round
  );

  // Find rebuttals FROM this agent
  const agentRebuttals = rebuttals.filter(
    (r) => r.from_agent === turn.agent && r.round_num === turn.round
  );

  return (
    <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
      <div className="flex items-start gap-3">
        <AgentAvatar agentName={turn.agent} provider={turn.provider} />

        <div className="flex-1">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-semibold text-gray-200">
                {turn.agent}
                {turn.changed_mind && (
                  <span className="ml-2 text-xs px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded">
                    🔄 Changed Position
                  </span>
                )}
              </div>
              <div className="text-xs text-gray-500">
                {turn.model} via {turn.provider}
              </div>
            </div>
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="text-gray-400 hover:text-gray-200"
            >
              {isExpanded ? (
                <ChevronUp className="w-4 h-4" />
              ) : (
                <ChevronDown className="w-4 h-4" />
              )}
            </button>
          </div>

          <div className="mt-2">
            <div className="text-sm font-medium text-blue-400">
              Position: {turn.position}
            </div>
          </div>

          {/* Incoming challenges */}
          {incomingChallenges.length > 0 && (
            <div className="mt-2 space-y-1">
              {incomingChallenges.map((challenge, idx) => (
                <div key={idx} className="text-xs bg-yellow-500/10 border border-yellow-500/30 rounded px-2 py-1">
                  <span className="text-yellow-400">⚠️ Challenge from {challenge.from_agent}:</span>
                  <span className="text-gray-300 ml-1">{challenge.challenge_text}</span>
                </div>
              ))}
            </div>
          )}

          {isExpanded && (
            <div className="mt-3 space-y-2 text-sm">
              <div>
                <div className="text-xs text-gray-500 uppercase tracking-wide">Statement</div>
                <div className="text-gray-300 mt-1">{turn.statement}</div>
              </div>

              <div>
                <div className="text-xs text-gray-500 uppercase tracking-wide">Reasoning</div>
                <div className="text-gray-300 mt-1">{turn.reasoning}</div>
              </div>

              {turn.agrees_with.length > 0 && (
                <div className="flex items-center gap-2 text-xs">
                  <CheckCircle className="w-3 h-3 text-green-400" />
                  <span className="text-gray-400">Agrees with:</span>
                  <span className="text-green-400">{turn.agrees_with.join(", ")}</span>
                </div>
              )}

              {turn.disagrees_with.length > 0 && (
                <div className="flex items-center gap-2 text-xs">
                  <AlertCircle className="w-3 h-3 text-red-400" />
                  <span className="text-gray-400">Disagrees with:</span>
                  <span className="text-red-400">{turn.disagrees_with.join(", ")}</span>
                </div>
              )}

              {/* Rebuttals from this agent */}
              {agentRebuttals.length > 0 && (
                <div className="mt-2 space-y-1">
                  {agentRebuttals.map((rebuttal, idx) => (
                    <div key={idx} className="text-xs bg-blue-500/10 border border-blue-500/30 rounded px-2 py-1">
                      <span className="text-blue-400">🔄 Rebuttal to {rebuttal.to_agent}:</span>
                      <span className="text-gray-300 ml-1">{rebuttal.rebuttal_text}</span>
                      {rebuttal.position_changed && rebuttal.new_position && (
                        <div className="text-green-400 mt-1">
                          → New position: {rebuttal.new_position}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function RoundSection({
  round,
  challenges,
  rebuttals,
}: {
  round: DebateRound;
  challenges: Challenge[];
  rebuttals: Rebuttal[];
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm">
        <div className="flex items-center gap-2 px-3 py-1 bg-gray-700 rounded-full">
          <MessageCircle className="w-4 h-4 text-blue-400" />
          <span className="text-gray-200 font-semibold">Round {round.round_number}</span>
        </div>

        {round.consensus_emerging && (
          <div className="flex items-center gap-1 text-xs text-green-400">
            <CheckCircle className="w-3 h-3" />
            Consensus emerging
          </div>
        )}

        {round.position_changes > 0 && (
          <div className="flex items-center gap-1 text-xs text-blue-400">
            <TrendingUp className="w-3 h-3" />
            {round.position_changes} position change{round.position_changes > 1 ? "s" : ""}
          </div>
        )}
      </div>

      <div className="space-y-2">
        {round.turns.map((turn, idx) => (
          <TurnCard
            key={idx}
            turn={turn}
            challenges={challenges.filter((c) => c.round_num === round.round_number)}
            rebuttals={rebuttals.filter((r) => r.round_num === round.round_number)}
          />
        ))}
      </div>
    </div>
  );
}

function DissentSection({ opinions }: { opinions: DissentingOpinion[] }) {
  if (opinions.length === 0) return null;

  return (
    <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-3">
        <AlertCircle className="w-5 h-5 text-yellow-400" />
        <div className="text-sm font-semibold text-yellow-400">
          Dissenting Opinions ({opinions.length})
        </div>
      </div>

      <div className="space-y-3">
        {opinions.map((opinion, idx) => (
          <div key={idx} className="bg-gray-800/50 rounded p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-medium text-gray-200">{opinion.agent_name}</div>
              <div className="text-xs text-gray-400">
                Confidence: {(opinion.confidence * 100).toFixed(0)}%
              </div>
            </div>
            <div className="text-sm text-blue-400 mb-1">Position: {opinion.position}</div>
            <div className="text-xs text-gray-300">{opinion.reasoning}</div>
            {opinion.evidence.length > 0 && (
              <div className="mt-2 text-xs text-gray-400">
                Evidence: {opinion.evidence.join(", ")}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function DebateConversation({
  debateLog,
  className,
}: DebateConversationProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  return (
    <div className={clsx("bg-gray-900 rounded-lg border border-gray-700", className)}>
      {/* Header */}
      <div className="p-4 border-b border-gray-700">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <MessageCircle className="w-5 h-5 text-blue-400" />
            <div>
              <div className="text-sm font-semibold text-gray-200">
                Tribunal Debate: {debateLog.tribunal_type}
              </div>
              <div className="text-xs text-gray-400">
                {debateLog.rounds_taken} round{debateLog.rounds_taken !== 1 ? "s" : ""} •{" "}
                {debateLog.duration_ms ? `${Math.round(debateLog.duration_ms)}ms` : "In progress"}
              </div>
            </div>
          </div>

          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="text-gray-400 hover:text-gray-200"
          >
            {isExpanded ? (
              <ChevronUp className="w-5 h-5" />
            ) : (
              <ChevronDown className="w-5 h-5" />
            )}
          </button>
        </div>

        {/* Convergence badge */}
        {debateLog.convergence_type && (
          <div className="mt-3">
            <ConvergenceBadge
              convergenceType={debateLog.convergence_type}
              consensusConfidence={debateLog.consensus_confidence}
              flagged={debateLog.flagged_for_human_review}
            />
          </div>
        )}
      </div>

      {/* Body */}
      {isExpanded && (
        <div className="p-4 space-y-4">
          {/* Input context */}
          <div className="bg-gray-800/50 rounded p-3">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">
              Input Text
            </div>
            <div className="text-sm text-gray-300">{debateLog.input_text}</div>
          </div>

          {/* Rounds timeline */}
          <div className="space-y-4">
            {debateLog.rounds.map((round) => (
              <RoundSection
                key={round.round_number}
                round={round}
                challenges={debateLog.challenges}
                rebuttals={debateLog.rebuttals}
              />
            ))}
          </div>

          {/* Dissenting opinions */}
          {debateLog.dissenting_opinions.length > 0 && (
            <DissentSection opinions={debateLog.dissenting_opinions} />
          )}

          {/* Final consensus */}
          {debateLog.final_consensus && (
            <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <CheckCircle className="w-5 h-5 text-green-400" />
                <div className="text-sm font-semibold text-green-400">Final Consensus</div>
              </div>
              <div className="text-sm text-gray-200">{debateLog.final_consensus}</div>
            </div>
          )}

          {/* Agent summary */}
          <div className="grid grid-cols-3 gap-3">
            {Object.values(debateLog.agent_summary).map((agent) => (
              <div key={agent.name} className="bg-gray-800/50 rounded p-3 text-xs">
                <div className="font-medium text-gray-200">{agent.name}</div>
                <div className="text-gray-500 mt-1">{agent.model}</div>
                <div className="text-gray-400 mt-2">
                  Position changes: {agent.position_changes}
                </div>
                <div className="text-gray-400">
                  Rounds: {agent.rounds_participated}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
