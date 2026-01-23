/**
 * System Health Dashboard Component
 * ==================================
 * PHASE 3: Real-time system health metrics - consensus rates, debate patterns,
 * error concentration, and cost tracking.
 */

"use client";

import { useState, useEffect } from "react";
import { clsx } from "clsx";
import {
  Activity,
  TrendingUp,
  Users,
  AlertTriangle,
  DollarSign,
  Clock,
  BarChart3,
  PieChart,
  Zap,
} from "lucide-react";
import { SessionAnalytics, ConsensusMetrics } from "@/types/sarasvati";

interface SystemHealthDashboardProps {
  sessionActive: boolean;
  className?: string;
}

interface MetricCardProps {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string | number;
  subtext?: string;
  color: string;
  bgColor: string;
}

function MetricCard({ icon: Icon, label, value, subtext, color, bgColor }: MetricCardProps) {
  return (
    <div className={clsx("rounded-lg border border-gray-700 p-4", bgColor)}>
      <div className="flex items-center gap-2 mb-2">
        <Icon className={clsx("w-5 h-5", color)} />
        <div className="text-xs text-gray-400 uppercase tracking-wide">{label}</div>
      </div>
      <div className={clsx("text-2xl font-bold", color)}>{value}</div>
      {subtext && <div className="text-xs text-gray-500 mt-1">{subtext}</div>}
    </div>
  );
}

function ConsensusBreakdown({ metrics }: { metrics: ConsensusMetrics }) {
  const total = metrics.total_debates || 1; // Prevent division by zero

  const fullPct = ((metrics.full_consensus_count / total) * 100).toFixed(0);
  const majorityPct = ((metrics.strong_majority_count / total) * 100).toFixed(0);
  const dissentPct = ((metrics.structured_dissent_count / total) * 100).toFixed(0);

  return (
    <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
      <div className="flex items-center gap-2 mb-4">
        <PieChart className="w-5 h-5 text-blue-400" />
        <div className="text-sm font-semibold text-gray-200">Consensus Breakdown</div>
      </div>

      <div className="space-y-3">
        {/* Full consensus */}
        <div>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-green-400">Full Consensus (3/3)</span>
            <span className="text-gray-400">{fullPct}%</span>
          </div>
          <div className="h-2 bg-gray-900 rounded-full overflow-hidden">
            <div
              className="h-full bg-green-500"
              style={{ width: `${fullPct}%` }}
            />
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {metrics.full_consensus_count} debates
          </div>
        </div>

        {/* Strong majority */}
        <div>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-blue-400">Strong Majority (2/3)</span>
            <span className="text-gray-400">{majorityPct}%</span>
          </div>
          <div className="h-2 bg-gray-900 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500"
              style={{ width: `${majorityPct}%` }}
            />
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {metrics.strong_majority_count} debates
          </div>
        </div>

        {/* Structured dissent */}
        <div>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-yellow-400">Structured Dissent</span>
            <span className="text-gray-400">{dissentPct}%</span>
          </div>
          <div className="h-2 bg-gray-900 rounded-full overflow-hidden">
            <div
              className="h-full bg-yellow-500"
              style={{ width: `${dissentPct}%` }}
            />
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {metrics.structured_dissent_count} debates (human review needed)
          </div>
        </div>
      </div>

      <div className="mt-4 pt-4 border-t border-gray-700 text-xs">
        <div className="flex justify-between text-gray-400">
          <span>Avg rounds to consensus:</span>
          <span className="text-gray-200 font-mono">
            {metrics.avg_rounds_to_consensus.toFixed(1)} rounds
          </span>
        </div>
      </div>
    </div>
  );
}

function ErrorConcentrationChart({
  errorConcentration,
}: {
  errorConcentration: Record<string, number>;
}) {
  const buckets = Object.entries(errorConcentration).sort((a, b) =>
    a[0].localeCompare(b[0])
  );

  if (buckets.length === 0) {
    return (
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
        <div className="flex items-center gap-2 mb-4">
          <BarChart3 className="w-5 h-5 text-purple-400" />
          <div className="text-sm font-semibold text-gray-200">
            Error Concentration
          </div>
        </div>
        <div className="text-xs text-gray-500 text-center py-8">
          No error data yet
        </div>
      </div>
    );
  }

  const maxErrors = Math.max(...buckets.map(([_, count]) => count));

  return (
    <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
      <div className="flex items-center gap-2 mb-4">
        <BarChart3 className="w-5 h-5 text-purple-400" />
        <div className="text-sm font-semibold text-gray-200">
          Error Concentration Over Time
        </div>
      </div>

      <div className="space-y-2">
        {buckets.map(([bucket, count]) => {
          const heightPct = maxErrors > 0 ? (count / maxErrors) * 100 : 0;
          return (
            <div key={bucket} className="flex items-center gap-2">
              <div className="text-xs text-gray-400 w-20 flex-shrink-0">
                {bucket}
              </div>
              <div className="flex-1 h-6 bg-gray-900 rounded overflow-hidden">
                <div
                  className="h-full bg-purple-500 flex items-center justify-end pr-2"
                  style={{ width: `${heightPct}%` }}
                >
                  {count > 0 && (
                    <span className="text-xs text-white font-semibold">
                      {count}
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-4 pt-4 border-t border-gray-700 text-xs text-gray-500">
        Errors are grouped by time bucket to show when in the session they occurred
      </div>
    </div>
  );
}

function CostTracker({ analytics }: { analytics: SessionAnalytics }) {
  return (
    <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
      <div className="flex items-center gap-2 mb-4">
        <DollarSign className="w-5 h-5 text-green-400" />
        <div className="text-sm font-semibold text-gray-200">Session Costs</div>
      </div>

      <div className="space-y-3">
        <div className="flex justify-between items-center">
          <span className="text-xs text-gray-400">Total API calls</span>
          <span className="text-lg font-mono text-gray-200">
            {analytics.total_api_calls}
          </span>
        </div>

        <div className="flex justify-between items-center">
          <span className="text-xs text-gray-400">Estimated cost</span>
          <span className="text-2xl font-bold text-green-400">
            ${analytics.estimated_cost_usd.toFixed(2)}
          </span>
        </div>

        <div className="flex justify-between items-center">
          <span className="text-xs text-gray-400">Avg debate duration</span>
          <span className="text-sm font-mono text-gray-200">
            {analytics.debate_duration_avg_ms.toFixed(0)}ms
          </span>
        </div>
      </div>

      <div className="mt-4 pt-4 border-t border-gray-700 text-xs text-gray-500">
        Cost is estimated based on model pricing and may vary
      </div>
    </div>
  );
}

export default function SystemHealthDashboard({
  sessionActive,
  className,
}: SystemHealthDashboardProps) {
  const [analytics, setAnalytics] = useState<SessionAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionActive) {
      setLoading(false);
      return;
    }

    const fetchAnalytics = async () => {
      try {
        const response = await fetch("http://localhost:8000/api/analytics");
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();

        // Check if there's an error in the response
        if (data.error) {
          setError(data.error);
          setAnalytics(null);
        } else {
          setAnalytics(data);
          setError(null);
        }
      } catch (err) {
        console.error("Failed to fetch analytics:", err);
        setError(err instanceof Error ? err.message : "Failed to fetch analytics");
      } finally {
        setLoading(false);
      }
    };

    // Initial fetch
    fetchAnalytics();

    // Poll every 5 seconds while session is active
    const interval = setInterval(fetchAnalytics, 5000);

    return () => clearInterval(interval);
  }, [sessionActive]);

  if (!sessionActive) {
    return (
      <div className={clsx("bg-gray-800/50 rounded-lg border border-gray-700 p-8", className)}>
        <div className="text-center text-gray-500">
          <Activity className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <div className="text-sm">No active session</div>
          <div className="text-xs mt-1">Start a session to see health metrics</div>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className={clsx("bg-gray-800/50 rounded-lg border border-gray-700 p-8", className)}>
        <div className="text-center text-gray-500">
          <Zap className="w-12 h-12 mx-auto mb-3 animate-pulse text-blue-400" />
          <div className="text-sm">Loading analytics...</div>
        </div>
      </div>
    );
  }

  if (error || !analytics) {
    return (
      <div className={clsx("bg-gray-800/50 rounded-lg border border-gray-700 p-8", className)}>
        <div className="text-center text-yellow-500">
          <AlertTriangle className="w-12 h-12 mx-auto mb-3" />
          <div className="text-sm">No analytics available yet</div>
          <div className="text-xs mt-1 text-gray-500">
            {error || "Waiting for first debate to complete"}
          </div>
        </div>
      </div>
    );
  }

  const metrics = analytics.consensus_metrics;

  return (
    <div className={clsx("space-y-4", className)}>
      {/* Header */}
      <div className="flex items-center gap-2">
        <Activity className="w-5 h-5 text-blue-400" />
        <div className="text-sm font-semibold text-gray-200">System Health Dashboard</div>
        <div className="ml-auto text-xs text-gray-500">
          {sessionActive && (
            <span className="flex items-center gap-1">
              <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
              Live
            </span>
          )}
        </div>
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard
          icon={Users}
          label="Total Debates"
          value={metrics.total_debates}
          color="text-blue-400"
          bgColor="bg-blue-500/10"
        />
        <MetricCard
          icon={TrendingUp}
          label="Full Consensus"
          value={`${metrics.full_consensus_count}`}
          subtext={`${((metrics.full_consensus_count / (metrics.total_debates || 1)) * 100).toFixed(0)}% of debates`}
          color="text-green-400"
          bgColor="bg-green-500/10"
        />
        <MetricCard
          icon={AlertTriangle}
          label="Needs Review"
          value={metrics.structured_dissent_count}
          subtext="Human review required"
          color="text-yellow-400"
          bgColor="bg-yellow-500/10"
        />
        <MetricCard
          icon={Clock}
          label="Avg Rounds"
          value={metrics.avg_rounds_to_consensus.toFixed(1)}
          subtext="To reach consensus"
          color="text-purple-400"
          bgColor="bg-purple-500/10"
        />
      </div>

      {/* Detailed views */}
      <div className="grid md:grid-cols-2 gap-4">
        <ConsensusBreakdown metrics={metrics} />
        <CostTracker analytics={analytics} />
      </div>

      <ErrorConcentrationChart errorConcentration={analytics.error_concentration} />
    </div>
  );
}
