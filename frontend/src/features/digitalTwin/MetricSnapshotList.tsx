import { formatNumber, formatTimestamp } from "@/shared/lib/format";
import { TelemetryProvenance } from "@/features/telemetry/TelemetryProvenance";
import type { DetectorRuleMirror, HeuristicLevel } from "@/features/digitalTwin/twinSeverity";
import { HEURISTIC_LEVEL_TEXT, VISUAL_HEURISTIC_LABEL } from "@/features/digitalTwin/twinSeverity";

export interface MetricSnapshotListItem {
  metric: string;
  value: number;
  unit: string | null;
  observedAt: string;
  source: string;
  tags: Record<string, unknown>;
  stale?: boolean;
  level?: HeuristicLevel;
  rule?: DetectorRuleMirror;
  severity?: string;
}

function heuristicText(metric: MetricSnapshotListItem): string {
  if (metric.stale) return "Stale observation, excluded from the visual heuristic";
  if (!metric.level || !metric.rule) return `${VISUAL_HEURISTIC_LABEL}: no backend detector rule for this metric`;
  return `${VISUAL_HEURISTIC_LABEL}: ${HEURISTIC_LEVEL_TEXT[metric.level]} (breach ≥ ${metric.rule.breach} ${metric.rule.unit}, recovery < ${metric.rule.recover} ${metric.rule.unit})`;
}

export function MetricSnapshotList({ metrics }: { metrics: readonly MetricSnapshotListItem[] }) {
  if (metrics.length === 0) {
    return <p className="twin-muted">No telemetry metrics covered by a backend detector rule.</p>;
  }
  return (
    <ul className="twin-metric-list" aria-label="Detector-covered telemetry">
      {metrics.slice(0, 4).map((metric) => (
        <li
          key={JSON.stringify([metric.metric, metric.observedAt, metric.source, metric.tags.run_id, metric.tags.port_no, metric.tags.peer_host, metric.tags.flow_index])}
          className="twin-card twin-card--compact"
        >
          <div className="twin-row">
            <strong>{metric.metric}</strong>
            <span className="mono twin-value">{formatNumber(metric.value)} {metric.unit ?? ""}</span>
          </div>
          <div className="mono twin-meta">{heuristicText(metric)} | {metric.source}</div>
          <TelemetryProvenance tags={metric.tags} />
          <div className="twin-meta">{formatTimestamp(metric.observedAt)}</div>
        </li>
      ))}
    </ul>
  );
}
