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
import { AlertListParams } from "@/shared/types/alerts";
import { alertOrigin, isPlatformAlert } from "./origin";
import { EvaluationWindowSummary } from "./EvaluationWindowSummary";
import { alertSeverityTone, alertStatusTone, statusLabel, telemetryHealthTone } from "@/shared/lib/statusTones";
import { SloStatusTile } from "@/features/telemetry/SloStatusTile";

export function ReliabilityPage() {
  const userId = useAuthStore((state) => state.userId);
  const scope = useWorkspaceStore((state) => `${state.organizationId}:${state.workspaceId}:${state.networkId}`);
  return <ReliabilityScope key={`${userId}:${scope}`} />;
}

function ReliabilityScope() {
  const token = useAuthStore((state) => state.accessToken);
  const generation = useAuthStore((state) => state.generation);
  const scope = useWorkspaceStore((state) => `${state.workspaceId}:${state.networkId}`);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const canReadHealth = useAuthStore((state) => canReadTelemetryHealth(state.profile));
  const canWrite = useAuthStore((state) => hasPermission(state.profile, "write:config"));
  const pushToast = useUiStore((state) => state.pushToast);
  const health = useTelemetryHealth(token);
  const acknowledge = useAcknowledgeAlert(token), resolve = useResolveAlert(token);
  const connection = useLiveStore((state) => state.alertsStatus);
  const [status, setStatus] = useState<AlertListParams["status"]>();
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("");
  const [severity, setSeverity] = useState("");
  const [filters, setFilters] = useState<AlertListParams>({});
  // Platform (runtime SLO) alerts are listed only without a workspace/network selection, for global Admins.
  const [alertScope, setAlertScope] = useState<"workspace" | "platform">("workspace");
  const platformView = canReadHealth && alertScope === "platform";
  const alerts = useAlertsQuery(token, { ...filters, status, limit: 200,
    ...(platformView ? {} : { workspaceId: workspaceId ?? undefined, networkId: networkId ?? undefined }) }, platformView || Boolean(workspaceId));
  const [expanded, setExpanded] = useState("");
  const [error, setError] = useState<string | null>(null);
  const items = alerts.isError || (!workspaceId && !platformView) ? [] : alerts.data?.items ?? [];
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
          <StatTile label="Collector Status" value={data.status.toUpperCase()} tone={telemetryHealthTone(data.status)} />
          <StatTile label="Ingest Lag ms" value={data.ingest_lag_ms === null ? "Unavailable (no observations)" : String(data.ingest_lag_ms)} />
          <StatTile label="Dropped Events" value={String(data.dropped_events)} tone={data.dropped_events > 0 ? "danger" : "ok"} />
          <SloStatusTile slo={data.slo} />
        </div>}
      </QueryState>}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <Badge text={connection.toUpperCase()} tone={connection === "open" ? "info" : "warn"} />
        <span>Loaded matching unresolved: {items.filter((alert) => alert.status !== "resolved").length}; acknowledged: {items.filter((alert) => alert.status === "acknowledged").length}</span>
      </div>
    </Panel>
    <Panel title="Source Breakdown" subtitle="Loaded matching alerts only, up to 200. Counts are not global totals.">
      {Object.entries(counts).map(([source, count]) => <Badge key={source} text={`${source} ${count}`} tone="info" />)}
      {!items.length ? <p>No source counts yet.</p> : null}
    </Panel>
    <Panel title="Alerts Lifecycle" subtitle="Operator resolution is not measured recovery.">
      {canReadHealth ? <fieldset>
        <legend>Alert scope</legend>
        <label><input type="radio" name="alert-scope" checked={alertScope === "workspace"} onChange={() => { setAlertScope("workspace"); setExpanded(""); }} /> Selected workspace and network</label>
        <label><input type="radio" name="alert-scope" checked={alertScope === "platform"} onChange={() => { setAlertScope("platform"); setExpanded(""); }} /> All authorized scopes, including platform runtime alerts</label>
      </fieldset> : null}
      <p style={{ overflowWrap: "anywhere" }}>{platformView
        ? "Scope: every scope you can read plus platform runtime (SLO) alerts. Platform alerts require global Admin with an unscoped session and are read-only."
        : `Scope: workspace ${workspaceId ?? "not selected"}; ${networkId ? `network ${networkId}` : "all networks in this workspace"}.`}</p>
      <form style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", minWidth: 0 }} onSubmit={(event) => {
        event.preventDefault(); setFilters({ search: search.trim() || undefined, source: source.trim() || undefined, severity: severity.trim() || undefined }); setExpanded("");
      }}>
        <label style={{ display: "grid", minWidth: 0 }}>Filter alerts<input placeholder="Search key/source/correlation/payload" value={search} maxLength={200} onChange={(event) => setSearch(event.target.value)} /></label>
        <label style={{ display: "grid", minWidth: 0 }}>Source<input placeholder="Any source (exact match)" value={source} maxLength={100} onChange={(event) => setSource(event.target.value)} /></label>
        <label style={{ display: "grid", minWidth: 0 }}>Severity<input placeholder="Any severity (exact match)" value={severity} maxLength={50} onChange={(event) => setSeverity(event.target.value)} /></label>
        <Button type="submit" disabled={!workspaceId && !platformView}>Apply alert filters</Button>
      </form>
      <div role="group" aria-label="Alert status" style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
        {([ [undefined, "All"], ["active", "Active"], ["acknowledged", "Ack"], ["resolved", "Resolved"] ] as const).map(([value, label]) => <Button key={label} aria-pressed={status === value} tone={status === value ? "primary" : "ghost"} onClick={() => { setStatus(value); setExpanded(""); }}>{label}</Button>)}
        <Button tone="ghost" disabled={(!workspaceId && !platformView) || alerts.isFetching} onClick={() => alerts.refetch()}>Refresh Alerts</Button>
      </div>
      <p role="status">{items.length} matching alerts loaded (maximum 200). Newest updates first; refine filters to find older incidents.</p>
      {!workspaceId && !platformView ? <AsyncState title="Select a workspace" description="Alerts use the same selected workspace and network as realtime updates." /> :
      <QueryState query={alerts} hasData={(data) => data.items.length > 0} emptyTitle="No alerts match these filters">
        {() => <div style={{ display: "grid", gap: "0.5rem", maxHeight: 640, overflow: "auto" }}>
          {items.map((alert) => {
            const key = `${generation}:${scope}:${alertScope}:${alert.alert_id}`;
            const platform = isPlatformAlert(alert);
            return <article key={alert.alert_id} style={{ display: "grid", gap: "0.4rem", padding: "0.6rem", border: "1px solid var(--line-soft)", borderRadius: 10, overflowWrap: "anywhere" }}>
              <strong>{alert.alert_key}</strong>
              <span>{platform ? `Origin: source ${alert.source}; platform runtime (no tenant)` : alertOrigin(alert)}</span>
              <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
                <Badge text={statusLabel(alert.severity, "severity unavailable")} tone={alertSeverityTone(alert.severity)} />
                <Badge text={statusLabel(alert.status)} tone={alertStatusTone(alert.status)} />
                {platform ? <Badge text="platform alert (read-only)" tone="neutral" /> : null}
              </div>
              {typeof alert.payload.severity_reason === "string" ? <p>{alert.payload.severity_reason}</p> : null}
              {typeof alert.payload.runbook_reference === "string" ? <span>{alert.payload.runbook_reference}</span> : null}
              {platform ? <EvaluationWindowSummary payload={alert.payload} /> : null}
              <span>{formatTimestamp(alert.updated_at)} | corr {alert.correlation_id}</span>
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                {platform ? <p>The SLO evaluator owns this alert's lifecycle; it cannot be acknowledged or resolved here.</p> : <>
                  <Button permission="write:config" tone="ghost" disabled={!canWrite || alert.status !== "active" || acknowledge.isPending || resolve.isPending} onClick={() => action(alert.alert_id, "ack")}>Acknowledge</Button>
                  <Button permission="write:config" disabled={!canWrite || alert.status === "resolved" || acknowledge.isPending || resolve.isPending} onClick={() => action(alert.alert_id, "resolve")}>Resolve</Button>
                </>}
                <Button tone="ghost" aria-expanded={expanded === key} onClick={() => setExpanded(expanded === key ? "" : key)}>Details and History</Button>
              </div>
              {expanded === key ? <AlertHistory key={key} id={alert.alert_id} /> : null}
            </article>;
          })}
        </div>}
      </QueryState>}
      {error ? <AsyncState title="Alert action failed" description={error} /> : null}
    </Panel>
  </div>;
}
