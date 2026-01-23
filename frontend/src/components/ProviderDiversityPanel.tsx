/**
 * Provider Diversity Panel Component
 * ===================================
 * PHASE 3: Shows provider performance, perspective dominance, and bias detection.
 * Alerts if any provider dominates >60% of verdicts (potential bias).
 */

"use client";

import { clsx } from "clsx";
import {
  Users,
  TrendingUp,
  AlertTriangle,
  Target,
  Award,
  BarChart3,
} from "lucide-react";
import { ProviderPerformance } from "@/types/sarasvati";

interface ProviderDiversityPanelProps {
  providerPerformance: Record<string, ProviderPerformance>;
  className?: string;
}

const PROVIDER_COLORS: Record<string, string> = {
  groq: "bg-orange-500",
  openai: "bg-green-500",
  anthropic: "bg-purple-500",
  deepseek: "bg-blue-500",
  default: "bg-gray-500",
};

const PROVIDER_TEXT_COLORS: Record<string, string> = {
  groq: "text-orange-400",
  openai: "text-green-400",
  anthropic: "text-purple-400",
  deepseek: "text-blue-400",
  default: "text-gray-400",
};

function ProviderBadge({ providerName }: { providerName: string }) {
  const normalizedName = providerName.toLowerCase();
  const color = PROVIDER_COLORS[normalizedName] || PROVIDER_COLORS.default;

  return (
    <div
      className={clsx(
        "w-6 h-6 rounded-full flex items-center justify-center text-white text-xs font-bold",
        color
      )}
      title={providerName}
    >
      {providerName.charAt(0).toUpperCase()}
    </div>
  );
}

function DominanceAlert({ performance }: { performance: ProviderPerformance }) {
  const dominancePct =
    (performance.times_in_majority / (performance.total_positions || 1)) * 100;

  if (dominancePct < 60) {
    return null;
  }

  return (
    <div className="bg-yellow-500/10 border border-yellow-500/30 rounded px-2 py-1 flex items-center gap-1">
      <AlertTriangle className="w-3 h-3 text-yellow-400" />
      <span className="text-xs text-yellow-400">
        {dominancePct.toFixed(0)}% dominance - potential bias
      </span>
    </div>
  );
}

function ProviderCard({ performance }: { performance: ProviderPerformance }) {
  const normalizedName = performance.provider_name.toLowerCase();
  const textColor =
    PROVIDER_TEXT_COLORS[normalizedName] || PROVIDER_TEXT_COLORS.default;

  const majorityPct =
    (performance.times_in_majority / (performance.total_positions || 1)) * 100;
  const minorityPct =
    (performance.times_in_minority / (performance.total_positions || 1)) * 100;

  return (
    <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
      <div className="flex items-center gap-2 mb-3">
        <ProviderBadge providerName={performance.provider_name} />
        <div>
          <div className={clsx("text-sm font-semibold", textColor)}>
            {performance.provider_name}
          </div>
          <div className="text-xs text-gray-500">
            {performance.total_positions} position{performance.total_positions !== 1 ? "s" : ""}
          </div>
        </div>
      </div>

      {/* Dominance warning */}
      <DominanceAlert performance={performance} />

      {/* Performance metrics */}
      <div className="mt-3 space-y-2">
        {/* In majority */}
        <div>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-gray-400">In majority</span>
            <span className="text-gray-300 font-mono">{majorityPct.toFixed(0)}%</span>
          </div>
          <div className="h-1.5 bg-gray-900 rounded-full overflow-hidden">
            <div
              className="h-full bg-green-500"
              style={{ width: `${majorityPct}%` }}
            />
          </div>
          <div className="text-xs text-gray-600 mt-0.5">
            {performance.times_in_majority} times
          </div>
        </div>

        {/* In minority */}
        <div>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-gray-400">In minority</span>
            <span className="text-gray-300 font-mono">{minorityPct.toFixed(0)}%</span>
          </div>
          <div className="h-1.5 bg-gray-900 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500"
              style={{ width: `${minorityPct}%` }}
            />
          </div>
          <div className="text-xs text-gray-600 mt-0.5">
            {performance.times_in_minority} times
          </div>
        </div>
      </div>

      {/* Additional metrics */}
      <div className="mt-3 pt-3 border-t border-gray-700 space-y-1 text-xs">
        <div className="flex justify-between">
          <span className="text-gray-500">Avg confidence</span>
          <span className="text-gray-300 font-mono">
            {(performance.avg_confidence * 100).toFixed(0)}%
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Error detection rate</span>
          <span className={clsx("font-mono", performance.error_detection_rate > 0.7 ? "text-green-400" : "text-gray-300")}>
            {(performance.error_detection_rate * 100).toFixed(0)}%
          </span>
        </div>
      </div>

      {/* Specialization badge */}
      {performance.error_detection_rate > 0.8 && (
        <div className="mt-3 flex items-center gap-1 text-xs text-green-400 bg-green-500/10 border border-green-500/30 rounded px-2 py-1">
          <Award className="w-3 h-3" />
          <span>High error detection specialist</span>
        </div>
      )}
    </div>
  );
}

function DiversityScore({
  providerPerformance,
}: {
  providerPerformance: Record<string, ProviderPerformance>;
}) {
  const providers = Object.values(providerPerformance);

  if (providers.length === 0) {
    return null;
  }

  // Calculate diversity score based on how evenly distributed the majority votes are
  const majorityVotes = providers.map((p) => p.times_in_majority);
  const totalMajority = majorityVotes.reduce((a, b) => a + b, 0);

  if (totalMajority === 0) {
    return (
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
        <div className="flex items-center gap-2 mb-2">
          <Target className="w-5 h-5 text-blue-400" />
          <div className="text-sm font-semibold text-gray-200">Diversity Score</div>
        </div>
        <div className="text-xs text-gray-500">Not enough data yet</div>
      </div>
    );
  }

  // Calculate standard deviation of majority percentages
  const majorityPercentages = majorityVotes.map((votes) => (votes / totalMajority) * 100);
  const mean = majorityPercentages.reduce((a, b) => a + b, 0) / majorityPercentages.length;
  const variance =
    majorityPercentages.reduce((sum, pct) => sum + Math.pow(pct - mean, 2), 0) /
    majorityPercentages.length;
  const stdDev = Math.sqrt(variance);

  // Lower std dev = more balanced = higher diversity score
  // Perfect balance (33.33% each for 3 providers) has stdDev = 0
  // 100% dominance by one provider has high stdDev
  const diversityScore = Math.max(0, 100 - stdDev * 3); // Scale and invert

  const getDiversityColor = (score: number) => {
    if (score >= 80) return { text: "text-green-400", bg: "bg-green-500/10", label: "Excellent" };
    if (score >= 60) return { text: "text-blue-400", bg: "bg-blue-500/10", label: "Good" };
    if (score >= 40) return { text: "text-yellow-400", bg: "bg-yellow-500/10", label: "Fair" };
    return { text: "text-red-400", bg: "bg-red-500/10", label: "Poor" };
  };

  const color = getDiversityColor(diversityScore);

  return (
    <div className={clsx("rounded-lg border border-gray-700 p-4", color.bg)}>
      <div className="flex items-center gap-2 mb-2">
        <Target className={clsx("w-5 h-5", color.text)} />
        <div className="text-sm font-semibold text-gray-200">Diversity Score</div>
      </div>
      <div className={clsx("text-3xl font-bold", color.text)}>
        {diversityScore.toFixed(0)}
        <span className="text-lg">/100</span>
      </div>
      <div className={clsx("text-xs mt-1", color.text)}>{color.label}</div>
      <div className="text-xs text-gray-500 mt-2">
        Measures how evenly distributed verdicts are across providers
      </div>
    </div>
  );
}

function AgentDisagreementMatrix({
  providerPerformance,
}: {
  providerPerformance: Record<string, ProviderPerformance>;
}) {
  const providers = Object.keys(providerPerformance);

  if (providers.length < 2) {
    return null;
  }

  return (
    <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
      <div className="flex items-center gap-2 mb-3">
        <BarChart3 className="w-5 h-5 text-purple-400" />
        <div className="text-sm font-semibold text-gray-200">
          Provider Comparison
        </div>
      </div>

      <div className="space-y-2">
        {providers.map((providerName) => {
          const perf = providerPerformance[providerName];
          const majorityPct =
            (perf.times_in_majority / (perf.total_positions || 1)) * 100;

          return (
            <div key={providerName} className="flex items-center gap-2">
              <ProviderBadge providerName={providerName} />
              <div className="flex-1">
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-gray-400">{providerName}</span>
                  <span className="text-gray-300 font-mono">
                    {majorityPct.toFixed(0)}%
                  </span>
                </div>
                <div className="h-2 bg-gray-900 rounded-full overflow-hidden">
                  <div
                    className={clsx(
                      "h-full",
                      PROVIDER_COLORS[providerName.toLowerCase()] ||
                        PROVIDER_COLORS.default
                    )}
                    style={{ width: `${majorityPct}%` }}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 pt-3 border-t border-gray-700 text-xs text-gray-500">
        Percentage shows how often each provider's position was in the majority
      </div>
    </div>
  );
}

export default function ProviderDiversityPanel({
  providerPerformance,
  className,
}: ProviderDiversityPanelProps) {
  const providers = Object.values(providerPerformance);

  if (providers.length === 0) {
    return (
      <div className={clsx("bg-gray-800/50 rounded-lg border border-gray-700 p-8", className)}>
        <div className="text-center text-gray-500">
          <Users className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <div className="text-sm">No provider data yet</div>
          <div className="text-xs mt-1">Complete debates to see diversity metrics</div>
        </div>
      </div>
    );
  }

  // Check for dominance warnings
  const hasDominanceWarning = providers.some((p) => {
    const pct = (p.times_in_majority / (p.total_positions || 1)) * 100;
    return pct >= 60;
  });

  return (
    <div className={clsx("space-y-4", className)}>
      {/* Header */}
      <div className="flex items-center gap-2">
        <Users className="w-5 h-5 text-purple-400" />
        <div className="text-sm font-semibold text-gray-200">
          Provider Diversity & Performance
        </div>
        {hasDominanceWarning && (
          <div className="ml-auto flex items-center gap-1 text-xs text-yellow-400">
            <AlertTriangle className="w-3 h-3" />
            Bias detected
          </div>
        )}
      </div>

      {/* Diversity score */}
      <DiversityScore providerPerformance={providerPerformance} />

      {/* Provider cards */}
      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-3">
        {providers.map((performance) => (
          <ProviderCard key={performance.provider_name} performance={performance} />
        ))}
      </div>

      {/* Comparison matrix */}
      <AgentDisagreementMatrix providerPerformance={providerPerformance} />

      {/* Explanation */}
      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 text-xs">
        <div className="flex items-start gap-2">
          <TrendingUp className="w-4 h-4 text-blue-400 mt-0.5 flex-shrink-0" />
          <div>
            <div className="text-blue-400 font-semibold mb-1">
              Provider Diversity Ensures Quality
            </div>
            <div className="text-gray-400">
              Using 3 diverse LLM providers (different companies, models, and
              architectures) prevents systematic bias. If any provider dominates
              &gt;60% of verdicts, it may indicate bias in the prompting or
              insufficient model diversity.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
