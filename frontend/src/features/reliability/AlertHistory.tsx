import { useAlertDetail, useAlertHistory } from "./hooks";
import { formatTimestamp } from "@/shared/lib/format";
import { useAuthStore } from "@/shared/state/auth-store";
import { QueryState } from "@/shared/ui/QueryState";
import { Button } from "@/shared/ui/Button";
import { EvaluationWindowSummary } from "./EvaluationWindowSummary";

function Evidence({ payload }: { payload: Record<string, unknown> }) {
  const text = (value: unknown) => typeof value === "string" || typeof value === "number" || typeof value === "boolean" ? String(value) : "Unavailable";
  const rule = payload.rule && typeof payload.rule === "object" && !Array.isArray(payload.rule) ? payload.rule as Record<string, unknown> : null;
  return <div style={{ overflowWrap: "anywhere" }}>
    {rule ? <>
      <p>Rule {text(rule.version)}: breach &gt;= {text(rule.breach)} {text(payload.unit)}; recovery &lt; {text(rule.recover)} {text(payload.unit)}.</p>
      <p>Window {text(rule.duration_seconds)} s; minimum {text(rule.min_samples)} samples; max gap {text(rule.max_gap_seconds)} s; max age {text(rule.max_age_seconds)} s.</p>
      <p>Measurement {text(payload.metric)}: {text(payload.value)} {text(payload.unit)}; observed {text(payload.observed_at)}; window started {text(payload.window_started_at)}; {text(payload.sample_count)} samples.</p>
      <p>Provenance: {text(payload.source)} / {text(payload.execution_mode)} / {text(payload.quality)}; synthetic {text(payload.synthetic)}; method {text(payload.measurement_method)}; observation {text(payload.observation_event_id)}.</p>
      <p>Recovery scope: {(["org_id", "workspace_id", "network_id", "device_id", "port_no", "peer_host", "run_id", "rule_version"] as const).map((key) => `${key}: ${text(payload[key])}`).join("; ")}</p>
      <p>Missing, stale, duplicate, out-of-order, unknown-unit or synthetic data cannot establish recovery.</p>
    </> : <p>No measured detector evidence.</p>}
    {payload.evaluation_window ? <EvaluationWindowSummary payload={payload} /> : null}
    {payload.resolution_reason ? <p>Resolution reason: {text(payload.resolution_reason)}</p> : null}
    {payload.acknowledged_by_user_id ? <p>Acknowledged by {text(payload.acknowledged_by_user_id)}</p> : null}
    {payload.resolved_by_user_id ? <p>Resolved by {text(payload.resolved_by_user_id)} (operator action, not measured recovery)</p> : null}
  </div>;
}

export function AlertHistory({ id }: { id: string }) {
  const token = useAuthStore((state) => state.accessToken);
  const detail = useAlertDetail(token, id);
  const history = useAlertHistory(token, id);
  return <section aria-label="Alert details and history">
    <Button tone="ghost" onClick={() => { void detail.refetch(); void history.refetch(); }}>Refresh Alert History</Button>
    <QueryState query={detail}>{(alert) => <><p>Current lifecycle: {alert.status}; alert {alert.alert_id}; correlation {alert.correlation_id}</p><Evidence payload={alert.payload} /></>}</QueryState>
    <h3>Immutable Lifecycle History</h3>
    <QueryState query={history} hasData={(data) => data.items.length > 0} emptyTitle="No lifecycle history recorded">
      {(data) => <><p>{data.items.length} of {data.total} entries</p><ol>{data.items.map((entry) => <li key={entry.event_id}>
        <strong>{entry.event_type}</strong> {formatTimestamp(entry.occurred_at)}
        <p>Event {entry.event_id}; alert {entry.alert_id}; correlation {entry.correlation_id}</p><Evidence payload={entry.payload} />
      </li>)}</ol></>}
    </QueryState>
  </section>;
}
