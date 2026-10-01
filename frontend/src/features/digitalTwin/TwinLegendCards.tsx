import { useId } from "react";
import { describeApiError } from "@/shared/lib/errors";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import type { TwinNode } from "./sceneAdapter";
import { BACKEND_DETECTOR_RULES, VISUAL_HEURISTIC_LABEL, describeDetectorRule } from "./twinSeverity";

const DETECTOR_RULE_TEXT = Object.entries(BACKEND_DETECTOR_RULES).map(([metric, rule]) => describeDetectorRule(metric, rule));

export interface AlertsQueryState {
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  data?: unknown;
  refetch: () => unknown;
}

function AlertSourceStatus({ query, enabled, alertingCount }: { query: AlertsQueryState; enabled: boolean; alertingCount: number }) {
  if (!enabled) return <p className="twin-muted">Backend alert history needs the read:telemetry permission; only live alert events are shown.</p>;
  if (query.isError) {
    return (
      <div role="alert" className="twin-error">
        Backend alerts unavailable: {describeApiError(query.error)} Alert states may be incomplete.{" "}
        <Button type="button" tone="ghost" onClick={() => void query.refetch()}>Retry loading alerts</Button>
      </div>
    );
  }
  if (query.isLoading || !query.data) return <p role="status" className="twin-muted">Loading backend alerts…</p>;
  return <p>{alertingCount} device{alertingCount === 1 ? "" : "s"} with active backend alerts.</p>;
}

/** Severity legend: backend alerts are authoritative; the ring colour is a labelled visual heuristic. */
export function CongestionLegendCard({ alertsQuery, alertsEnabled, alertingCount }: { alertsQuery: AlertsQueryState; alertsEnabled: boolean; alertingCount: number }) {
  const titleId = useId();
  return (
    <section className="twin-card" aria-labelledby={titleId}>
      <h4 id={titleId} className="twin-card-title">Congestion legend</h4>
      <p>Authoritative severity: backend alerts. Devices with an active alert carry an “ALERT” label in the scene, so severity never depends on colour alone.</p>
      <AlertSourceStatus query={alertsQuery} enabled={alertsEnabled} alertingCount={alertingCount} />
      <p>{VISUAL_HEURISTIC_LABEL} (ring colour, not an alert, never sent as policy) mirrors the backend detector defaults:</p>
      <ul className="twin-diff-list">{DETECTOR_RULE_TEXT.map((line) => <li key={line}>{line}</li>)}</ul>
    </section>
  );
}

/** Placement provenance; counts are only shown once topology has loaded (never a false zero). */
export function SpatialMappingCard({ nodes, ready }: { nodes: readonly TwinNode[]; ready: boolean }) {
  const titleId = useId();
  const canonical = ready ? nodes.filter((node) => node.placementSource === "canonical").length : null;
  return (
    <section className="twin-card" aria-labelledby={titleId}>
      <h4 id={titleId} className="twin-card-title">Spatial mapping state</h4>
      <p>
        {canonical === null ? "Placement counts appear once topology has loaded." : `${canonical} canonical device placement${canonical === 1 ? "" : "s"}.`}{" "}
        Remaining hash-based positions and live overlay positions are schematic fallback, not measured locations. Campus imports use their separate coordinate frame.
      </p>
      <div className="twin-badges">
        <Badge text="persisted spatial_ref_id" tone="ok" />
        <Badge text="session sidecar mapping" tone="warn" />
      </div>
    </section>
  );
}
