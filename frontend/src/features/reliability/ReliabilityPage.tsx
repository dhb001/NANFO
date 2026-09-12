import { useState } from "react";
import { useTelemetryHealth } from "@/features/telemetry/hooks";
import { canReadTelemetryHealth, hasPermission } from "@/features/auth/permissions";
import { useAcknowledgeAlert, useAlertsQuery, useResolveAlert } from "./hooks";
import { AlertHistory } from "./AlertHistory";
import { useAuthStore } from "@/shared/state/auth-store";
import { useLiveStore } from "@/features/realtime/store";
import { useUiStore } from "@/shared/state/ui-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { toErrorMessage } from "@/shared/lib/errors";
import { formatTimestamp } from "@/shared/lib/format";
import { QueryState } from "@/shared/ui/QueryState";
import { AsyncState } from "@/shared/ui/AsyncState";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { Panel } from "@/shared/ui/Panel";
import { StatTile } from "@/shared/ui/StatTile";

export function ReliabilityPage() {
  const token = useAuthStore((state) => state.accessToken);
  const generation = useAuthStore((state) => state.generation);
  const scope = useWorkspaceStore((state) => `${state.workspaceId}:${state.networkId}`);
  const canReadHealth = useAuthStore((state) => canReadTelemetryHealth(state.profile));
  const canWrite = useAuthStore((state) => hasPermission(state.profile, "write:config"));
  const pushToast = useUiStore((state) => state.pushToast);
  const health = useTelemetryHealth(token);
  const alerts = useAlertsQuery(token, { limit: 200 });
  const acknowledge = useAcknowledgeAlert(token), resolve = useResolveAlert(token);
  const connection = useLiveStore((state) => state.alertsStatus);
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState("");
  const [error, setError] = useState<string | null>(null);
  const items = alerts.data?.items ?? [];
  const needle = search.trim().toLowerCase();
  const filtered = items.filter((alert) => (status === "all" || alert.status === status)
    && `${alert.alert_key} ${alert.source} ${alert.correlation_id}`.toLowerCase().includes(needle));
  const counts: Record<string, number> = {};
  for (const alert of items) counts[alert.source] = (counts[alert.source] ?? 0) + 1;

  async function action(id: string, kind: "ack" | "resolve") {
    if (!canWrite || acknowledge.isPending || resolve.isPending) return;
    setError(null);
    try {
      const result = await (kind === "ack" ? acknowledge : resolve).mutateAsync(id);
      pushToast({ title: kind === "ack" ? "Alert acknowledged" : "Alert resolved", description: `Queue status: ${result.queue_status}`, tone: "info" });
      await alerts.refetch();
    } catch (cause) { setError(toErrorMessage(cause)); }
  }

  return <div style={{ display: "grid", gap: "1rem", minWidth: 0 }}>
    <Panel title="Runtime Reliability">
      {!canReadHealth ? <AsyncState title="Telemetry health restricted" description="Global diagnostics require Admin and read:telemetry permission. Tenant alerts remain available below." /> : <QueryState query={health}>
        {(data) => <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 160px), 1fr))", gap: "0.6rem" }}>
          <StatTile label="Collector Status" value={data.status.toUpperCase()} tone={data.status === "ok" ? "ok" : "warn"} />
          <StatTile label="Ingest Lag ms" value={data.ingest_lag_ms === null ? "Unavailable (no observations)" : String(data.ingest_lag_ms)} />
          <StatTile label="Dropped Events" value={String(data.dropped_events)} tone={data.dropped_events > 0 ? "danger" : "ok"} />
        </div>}
      </QueryState>}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <Badge text={connection.toUpperCase()} tone={connection === "open" ? "info" : "warn"} />
        <span>Loaded unresolved: {items.filter((alert) => alert.status !== "resolved").length}; acknowledged: {items.filter((alert) => alert.status === "acknowledged").length}</span>
      </div>
    </Panel>
    <Panel title="Source Breakdown" subtitle="Loaded authorized alerts, up to 200.">
      {Object.entries(counts).map(([source, count]) => <Badge key={source} text={`${source} ${count}`} tone="info" />)}
      {!items.length ? <p>No source counts yet.</p> : null}
    </Panel>
    <Panel title="Alerts Lifecycle" subtitle="Operator resolution is not measured recovery."
      action={<div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
        <input aria-label="Filter alerts" placeholder="Search key/source/correlation" value={search} onChange={(event) => setSearch(event.target.value)} />
        {[["all", "All"], ["active", "Active"], ["acknowledged", "Ack"], ["resolved", "Resolved"]].map(([value, label]) => <Button key={value} tone={status === value ? "primary" : "ghost"} onClick={() => setStatus(value)}>{label}</Button>)}
        <Button tone="ghost" onClick={() => alerts.refetch()}>Refresh Alerts</Button>
      </div>}>
      <QueryState query={alerts} hasData={(data) => data.items.length > 0} emptyTitle="No reliability alerts observed yet">
        {() => <div style={{ display: "grid", gap: "0.5rem", maxHeight: 640, overflow: "auto" }}>
          {!filtered.length ? <p>No alerts match these filters.</p> : null}
          {filtered.map((alert) => {
            const key = `${generation}:${scope}:${alert.alert_id}`;
            return <article key={alert.alert_id} style={{ display: "grid", gap: "0.4rem", padding: "0.6rem", border: "1px solid var(--line-soft)", borderRadius: 10, overflowWrap: "anywhere" }}>
              <strong>{alert.alert_key}</strong>
              <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
                <Badge text={alert.severity ?? "severity unavailable"} tone={["critical", "high"].includes(alert.severity ?? "") ? "danger" : "warn"} />
                <Badge text={alert.status} tone={alert.status === "resolved" ? "ok" : "info"} />
              </div>
              {typeof alert.payload.severity_reason === "string" ? <p>{alert.payload.severity_reason}</p> : null}
              {typeof alert.payload.runbook_reference === "string" ? <span>{alert.payload.runbook_reference}</span> : null}
              <span>{formatTimestamp(alert.updated_at)} | corr {alert.correlation_id}</span>
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                <Button permission="write:config" tone="ghost" disabled={!canWrite || alert.status !== "active" || acknowledge.isPending || resolve.isPending} onClick={() => action(alert.alert_id, "ack")}>Acknowledge</Button>
                <Button permission="write:config" disabled={!canWrite || alert.status === "resolved" || acknowledge.isPending || resolve.isPending} onClick={() => action(alert.alert_id, "resolve")}>Resolve</Button>
                <Button tone="ghost" aria-expanded={expanded === key} onClick={() => setExpanded(expanded === key ? "" : key)}>Details and History</Button>
              </div>
              {expanded === key ? <AlertHistory key={key} id={alert.alert_id} /> : null}
            </article>;
          })}
        </div>}
      </QueryState>
      {error ? <AsyncState title="Alert action failed" description={error} /> : null}
    </Panel>
  </div>;
}
