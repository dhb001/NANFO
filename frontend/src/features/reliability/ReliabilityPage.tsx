import { useMemo, useState } from "react";
import { useTelemetryHealth } from "@/features/telemetry/hooks";
import { canReadTelemetryHealth } from "@/features/auth/permissions";
import {
  useAcknowledgeAlert,
  useAlertsQuery,
  useResolveAlert,
} from "@/features/reliability/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { useLiveStore } from "@/features/realtime/store";
import { useUiStore } from "@/shared/state/ui-store";
import { ApiClientError, toErrorMessage } from "@/shared/lib/errors";
import { formatTimestamp } from "@/shared/lib/format";
import { useIsNarrowViewport } from "@/shared/lib/viewport";
import {
  alertSeverityWeight,
  isAcknowledgedAlert,
  isResolvedAlert,
  normalizeAlertStatus,
  summarizeAlertSource,
} from "@/shared/lib/alerts";
import { QueryState } from "@/shared/ui/QueryState";
import { AsyncState } from "@/shared/ui/AsyncState";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { Panel } from "@/shared/ui/Panel";
import { StatTile } from "@/shared/ui/StatTile";

type AlertStatusFilter = "all" | "active" | "acknowledged" | "resolved";

function inferSeverity(payload: Record<string, unknown>): "ok" | "warn" | "danger" {
  const severity = String(payload.severity ?? "").toLowerCase();
  if (severity === "critical" || severity === "high") {
    return "danger";
  }
  if (severity === "degraded" || severity === "medium") {
    return "warn";
  }
  return "ok";
}

function mapAlertTone(status: string): "ok" | "warn" | "danger" | "info" {
  if (status === "resolved") {
    return "ok";
  }
  if (status === "acknowledged") {
    return "info";
  }
  if (status === "critical" || status === "high") {
    return "danger";
  }
  if (status === "degraded" || status === "medium") {
    return "warn";
  }
  return "info";
}

function asStringOrNull(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim();
  return normalized || null;
}

function extractAlertId(payload: Record<string, unknown>): string | null {
  return asStringOrNull(payload.alert_id);
}

export function ReliabilityPage() {
  const canReadHealth = useAuthStore((state) => canReadTelemetryHealth(state.profile));
  const token = useAuthStore((state) => state.accessToken);
  const pushToast = useUiStore((state) => state.pushToast);
  const healthQuery = useTelemetryHealth(token);
  const alertsQuery = useAlertsQuery(token, { limit: 200 });
  const acknowledgeMutation = useAcknowledgeAlert(token);
  const resolveMutation = useResolveAlert(token);
  const alertsStatus = useLiveStore((state) => state.alertsStatus);
  const isNarrowViewport = useIsNarrowViewport();
  const [statusFilter, setStatusFilter] = useState<AlertStatusFilter>("all");
  const [searchText, setSearchText] = useState("");
  const [pendingActionAlertId, setPendingActionAlertId] = useState<string | null>(null);

  const realtimeAlerts = useLiveStore((state) => state.alerts);
  const latestRealtimeByAlertId = useMemo(() => {
    const map: Record<string, string> = {};
    for (const alert of realtimeAlerts) {
      const alertId = extractAlertId(alert.payload);
      if (!alertId) {
        continue;
      }
      if (!(alertId in map)) {
        map[alertId] = alert.event_type;
      }
    }
    return map;
  }, [realtimeAlerts]);

  const listedAlerts = useMemo(() => alertsQuery.data?.items ?? [], [alertsQuery.data]);

  const reliabilityAlerts = useMemo(
    () =>
      listedAlerts
        .filter((alert) => {
          const source = String(alert.source ?? "");
          return source === "telemetry" || source === "alert";
        })
        .map((alert) => {
          const realtimeEventType = latestRealtimeByAlertId[alert.alert_id];
          return {
            event_id: realtimeEventType ? `${alert.alert_id}:${realtimeEventType}` : alert.alert_id,
            event_type: realtimeEventType ?? `alert.${alert.status}`,
            source: alert.source,
            payload: alert.payload,
            correlation_id: alert.correlation_id,
            timestamp: alert.updated_at,
          };
        }),
    [latestRealtimeByAlertId, listedAlerts],
  );

  const unresolvedAlerts = reliabilityAlerts.filter((alert) => !isResolvedAlert(alert)).length;
  const acknowledgedAlerts = reliabilityAlerts.filter((alert) => isAcknowledgedAlert(alert)).length;
  const highestSeverity = reliabilityAlerts.reduce((maxSeverity, alert) => {
    return Math.max(maxSeverity, alertSeverityWeight(alert));
  }, 0);
  const sourceBreakdown = summarizeAlertSource(reliabilityAlerts);

  const filteredAlerts = useMemo(() => {
    const needle = searchText.trim().toLowerCase();

    return listedAlerts.filter((alert) => {
      const normalizedStatus = normalizeAlertStatus(String(alert.status ?? alert.payload.status ?? "active"));

      if (statusFilter === "active" && normalizedStatus !== "active") {
        return false;
      }
      if (statusFilter === "acknowledged" && normalizedStatus !== "acknowledged") {
        return false;
      }
      if (statusFilter === "resolved" && normalizedStatus !== "resolved") {
        return false;
      }

      if (!needle) {
        return true;
      }

      const title = String(alert.payload.alert_key ?? alert.alert_key ?? alert.source).toLowerCase();
      const source = String(alert.source ?? "").toLowerCase();
      const correlationId = String(alert.correlation_id ?? "").toLowerCase();
      return title.includes(needle) || source.includes(needle) || correlationId.includes(needle);
    });
  }, [listedAlerts, searchText, statusFilter]);

  async function acknowledgeAlertAction(alertId: string) {
    try {
      setPendingActionAlertId(alertId);
      const result = await acknowledgeMutation.mutateAsync(alertId);
      pushToast({
        title: result.idempotent_replay ? "Already acknowledged" : "Alert acknowledged",
        description: `Queue status: ${result.queue_status}`,
        tone: result.queue_status === "queued" || result.queue_status === "replayed" ? "ok" : "warn",
      });
      await alertsQuery.refetch();
    } catch (error) {
      if (error instanceof ApiClientError && error.code === "ALERT_ALREADY_RESOLVED") {
        pushToast({
          title: "Cannot acknowledge resolved alert",
          description: error.message,
          tone: "warn",
        });
      } else {
        pushToast({
          title: "Acknowledge failed",
          description: toErrorMessage(error),
          tone: "danger",
        });
      }
    } finally {
      setPendingActionAlertId(null);
    }
  }

  async function resolveAlertAction(alertId: string) {
    try {
      setPendingActionAlertId(alertId);
      const result = await resolveMutation.mutateAsync(alertId);
      pushToast({
        title: result.idempotent_replay ? "Already resolved" : "Alert resolved",
        description: `Queue status: ${result.queue_status}`,
        tone: result.queue_status === "queued" || result.queue_status === "replayed" ? "ok" : "warn",
      });
      await alertsQuery.refetch();
    } catch (error) {
      pushToast({
        title: "Resolve failed",
        description: toErrorMessage(error),
        tone: "danger",
      });
    } finally {
      setPendingActionAlertId(null);
    }
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Panel title="Runtime Reliability" subtitle="VS11 alerts lifecycle monitoring and operator actions">
        {!canReadHealth ? <AsyncState title="Telemetry health restricted" description="Global diagnostics require Admin and read:telemetry permission. Tenant alerts remain available below." /> : <QueryState query={healthQuery}>
          {(health) => (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: isNarrowViewport ? "repeat(2, minmax(0, 1fr))" : "repeat(4, minmax(0, 1fr))",
                gap: "0.6rem",
              }}
            >
              <StatTile label="Collector Status" value={health.status.toUpperCase()} tone={health.status === "ok" ? "ok" : "warn"} />
              <StatTile label="Ingest Lag ms" value={health.ingest_lag_ms === null ? "Unavailable (no observations)" : String(health.ingest_lag_ms)} tone={health.ingest_lag_ms !== null && health.ingest_lag_ms > 1200 ? "warn" : "normal"} />
              <StatTile label="Dropped Events" value={String(health.dropped_events)} tone={health.dropped_events > 0 ? "danger" : "ok"} />
              <StatTile label="Alerts WS" value={alertsStatus.toUpperCase()} tone={alertsStatus === "open" ? "ok" : "warn"} />
              <StatTile label="Active Alerts" value={String(unresolvedAlerts)} tone={unresolvedAlerts > 0 ? "danger" : "ok"} />
              <StatTile label="Acknowledged" value={String(acknowledgedAlerts)} tone={acknowledgedAlerts > 0 ? "normal" : "ok"} />
              <StatTile
                label="Highest Severity"
                value={highestSeverity > 0 ? String(highestSeverity) : "0"}
                tone={highestSeverity >= 4 ? "danger" : highestSeverity >= 2 ? "warn" : "ok"}
              />
            </div>
          )}
        </QueryState>}
      </Panel>

      <Panel title="Source Breakdown" subtitle="Current alert volume grouped by producer source">
        {Object.keys(sourceBreakdown).length === 0 ? (
          <div style={{ color: "var(--ink-3)" }}>No source counts yet.</div>
        ) : (
          <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
            {Object.entries(sourceBreakdown).map(([source, count]) => (
              <Badge key={source} text={`${source} ${count}`} tone="info" />
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title="Alerts Lifecycle"
        subtitle="/api/v1/alerts with acknowledge and resolve actions plus /ws/alerts reconciliation"
        action={
          <div style={{ display: "flex", gap: "0.4rem", alignItems: "center", flexWrap: "wrap" }}>
            <input
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
              aria-label="Filter alerts"
              placeholder="Search key/source/correlation"
              style={{ border: "1px solid var(--line-soft)", borderRadius: "8px", padding: "0.32rem 0.4rem" }}
            />
            <Button tone={statusFilter === "all" ? "primary" : "ghost"} onClick={() => setStatusFilter("all")}>
              All
            </Button>
            <Button tone={statusFilter === "active" ? "primary" : "ghost"} onClick={() => setStatusFilter("active")}>
              Active
            </Button>
            <Button tone={statusFilter === "acknowledged" ? "primary" : "ghost"} onClick={() => setStatusFilter("acknowledged")}>
              Ack
            </Button>
            <Button tone={statusFilter === "resolved" ? "primary" : "ghost"} onClick={() => setStatusFilter("resolved")}>
              Resolved
            </Button>
          </div>
        }
      >
        <QueryState
          query={alertsQuery}
          hasData={(data) => data.items.length > 0}
          emptyTitle="No reliability alerts observed yet"
          emptyDescription="When telemetry and lifecycle events produce alerts, they appear here with action controls."
        >
          {() => (
            <div style={{ display: "grid", gap: "0.45rem", maxHeight: 540, overflow: "auto" }}>
              {filteredAlerts.map((alert) => {
                const payload = alert.payload;
                const severity = inferSeverity(payload);
                const title = String(payload.alert_key ?? alert.alert_key ?? payload.severity_reason ?? alert.source);
                const reason = String(payload.severity_reason ?? "");
                const runbook = String(payload.runbook_reference ?? "");
                const normalizedStatus = normalizeAlertStatus(String(alert.status ?? payload.status ?? "active"));
                const isResolved = normalizedStatus === "resolved";
                const isAcknowledged = normalizedStatus === "acknowledged";
                const disableAcknowledge =
                  isResolved ||
                  isAcknowledged ||
                  acknowledgeMutation.isPending ||
                  pendingActionAlertId === alert.alert_id;
                const disableResolve =
                  isResolved ||
                  resolveMutation.isPending ||
                  pendingActionAlertId === alert.alert_id;
                const actionLoading = pendingActionAlertId === alert.alert_id;

                return (
                  <article
                    key={alert.alert_id}
                    style={{
                      border: "1px solid var(--line-soft)",
                      borderRadius: "10px",
                      padding: "0.55rem 0.6rem",
                      background: isResolved
                        ? "color-mix(in srgb, var(--ok) 6%, white)"
                        : isAcknowledged
                          ? "color-mix(in srgb, var(--info) 7%, white)"
                          : "white",
                      display: "grid",
                      gap: "0.35rem",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                      <strong>{title}</strong>
                      <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
                        <Badge
                          text={isResolved ? "resolved" : String(alert.severity ?? "active")}
                          tone={isResolved ? "ok" : severity === "danger" ? "danger" : severity === "warn" ? "warn" : "info"}
                        />
                        <Badge text={normalizedStatus} tone={mapAlertTone(normalizedStatus)} />
                      </div>
                    </div>
                    {reason ? <div style={{ color: "var(--ink-2)", fontSize: "0.86rem" }}>{reason}</div> : null}
                    {runbook ? (
                      <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                        {runbook}
                      </div>
                    ) : null}
                    <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.72rem" }}>
                      {formatTimestamp(alert.updated_at)}  {alert.correlation_id ? `| corr ${alert.correlation_id}` : ""}
                    </div>
                    <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                      <Button
                        permission="write:config"
                        tone="ghost"
                        type="button"
                        disabled={disableAcknowledge}
                        onClick={() => acknowledgeAlertAction(alert.alert_id)}
                      >
                        {actionLoading && !isResolved ? "Working..." : "Acknowledge"}
                      </Button>
                      <Button
                        permission="write:config"
                        tone={isResolved ? "ghost" : "primary"}
                        type="button"
                        disabled={disableResolve}
                        onClick={() => resolveAlertAction(alert.alert_id)}
                      >
                        {actionLoading && !isAcknowledged ? "Working..." : "Resolve"}
                      </Button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </QueryState>

        {acknowledgeMutation.isError ? (
          <AsyncState title="Acknowledge action failed" description={toErrorMessage(acknowledgeMutation.error)} />
        ) : null}
        {resolveMutation.isError ? (
          <AsyncState title="Resolve action failed" description={toErrorMessage(resolveMutation.error)} />
        ) : null}
      </Panel>
    </div>
  );
}
