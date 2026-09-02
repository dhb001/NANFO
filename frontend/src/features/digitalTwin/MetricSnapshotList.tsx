import type { TwinMetricSnapshot } from "@/features/digitalTwin/sceneAdapter";
import { formatNumber, formatTimestamp } from "@/shared/lib/format";

interface MetricSnapshotListProps {
  metrics: TwinMetricSnapshot[];
}

export function MetricSnapshotList({ metrics }: MetricSnapshotListProps) {
  if (metrics.length === 0) {
    return <div style={{ color: "var(--ink-3)", fontSize: "0.84rem" }}>No congestion-relevant telemetry metrics found.</div>;
  }

  return (
    <div style={{ display: "grid", gap: "0.3rem" }}>
      {metrics.slice(0, 4).map((metric) => (
        <div
          key={`${metric.metric}:${metric.observedAt}`}
          style={{
            border: "1px solid var(--line-soft)",
            borderRadius: "8px",
            padding: "0.34rem 0.42rem",
            display: "grid",
            gap: "0.14rem",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: "0.4rem" }}>
            <strong>{metric.metric}</strong>
            <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-2)" }}>
              {formatNumber(metric.value)} {metric.unit ?? ""}
            </span>
          </div>
          <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.72rem" }}>
            score {formatNumber(metric.normalizedScore * 100, 0)}% | {metric.policyId} {metric.severity} | {metric.source}
          </div>
          <div style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>{formatTimestamp(metric.observedAt)}</div>
        </div>
      ))}
    </div>
  );
}
