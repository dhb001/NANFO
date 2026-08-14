import { useMemo, useState } from "react";
import { useTelemetryHealth } from "@/features/telemetry/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { useLiveStore } from "@/features/realtime/store";
import { Panel } from "@/shared/ui/Panel";
import { QueryState } from "@/shared/ui/QueryState";
import { Badge } from "@/shared/ui/Badge";
import { StatTile } from "@/shared/ui/StatTile";
import { useIsNarrowViewport } from "@/shared/lib/viewport";
import {
  alertSeverityWeight,
  isResolvedAlert,
  normalizeAlertStatus,
  summarizeAlertSource,
} from "@/shared/lib/alerts";
import { Button } from "@/shared/ui/Button";

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

export function ReliabilityPage() {
  const token = useAuthStore((state) => state.accessToken);
  const healthQuery = useTelemetryHealth(token);
  const alerts = useLiveStore((state) => state.alerts);
  const isNarrowViewport = useIsNarrowViewport();
  const [statusFilter, setStatusFilter] = useState<"all" | "active" | "acknowledged" | "resolved">("all");
  const [searchText, setSearchText] = useState("");

  const reliabilityAlerts = useMemo(
    () =>
      alerts.filter((alert) => {
        const source = String(alert.source ?? "");
        const eventType = String(alert.event_type ?? "");
        return source === "telemetry" || eventType.startsWith("alert.");
      }),
    [alerts],
  );

  const unresolvedAlerts = reliabilityAlerts.filter((alert) => !isResolvedAlert(alert)).length;
  const highestSeverity = reliabilityAlerts.reduce((maxSeverity, alert) => {
    return Math.max(maxSeverity, alertSeverityWeight(alert));
  }, 0);
  const sourceBreakdown = summarizeAlertSource(reliabilityAlerts);

  const filteredAlerts = useMemo(() => {
    const needle = searchText.trim().toLowerCase();

    return reliabilityAlerts.filter((alert) => {
      const normalizedStatus = normalizeAlertStatus(String(alert.payload.status ?? "active"));

      if (statusFilter === "active" && normalizedStatus === "resolved") {
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

      const title = String(alert.payload.alert_key ?? alert.payload.severity_reason ?? alert.event_type).toLowerCase();
      const source = String(alert.source ?? "").toLowerCase();
      const correlationId = String(alert.correlation_id ?? "").toLowerCase();
      return title.includes(needle) || source.includes(needle) || correlationId.includes(needle);
    });
  }, [reliabilityAlerts, searchText, statusFilter]);

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Panel title="Runtime Reliability" subtitle="VS3 alert observability, runtime degradation, and operator feedback loops">
        <QueryState query={healthQuery}>
          {(health) => (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: isNarrowViewport ? "repeat(2, minmax(0, 1fr))" : "repeat(4, minmax(0, 1fr))",
                gap: "0.6rem",
              }}
            >
              <StatTile label="Collector Status" value={health.status.toUpperCase()} tone={health.status === "ok" ? "ok" : "warn"} />
              <StatTile label="Ingest Lag ms" value={String(health.ingest_lag_ms)} tone={health.ingest_lag_ms > 1200 ? "warn" : "normal"} />
              <StatTile label="Dropped Events" value={String(health.dropped_events)} tone={health.dropped_events > 0 ? "danger" : "ok"} />
              <StatTile label="Active Alerts" value={String(unresolvedAlerts)} tone={unresolvedAlerts > 0 ? "danger" : "ok"} />
              <StatTile
                label="Highest Severity"
                value={highestSeverity > 0 ? String(highestSeverity) : "0"}
                tone={highestSeverity >= 4 ? "danger" : highestSeverity >= 2 ? "warn" : "ok"}
              />
            </div>
          )}
        </QueryState>
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
        title="Alert Stream"
        subtitle="/ws/alerts deduplicated live list with timeline semantics"
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
            <Button
              tone={statusFilter === "acknowledged" ? "primary" : "ghost"}
              onClick={() => setStatusFilter("acknowledged")}
            >
              Ack
            </Button>
            <Button tone={statusFilter === "resolved" ? "primary" : "ghost"} onClick={() => setStatusFilter("resolved")}>
              Resolved
            </Button>
          </div>
        }
      >
        {filteredAlerts.length === 0 ? (
          <div style={{ color: "var(--ink-3)" }}>No reliability alerts observed yet.</div>
        ) : (
          <div style={{ display: "grid", gap: "0.45rem", maxHeight: 520, overflow: "auto" }}>
            {filteredAlerts.map((alert) => {
              const payload = alert.payload;
              const severity = inferSeverity(payload);
              const title = String(payload.alert_key ?? payload.severity_reason ?? alert.event_type);
              const reason = String(payload.severity_reason ?? "");
              const runbook = String(payload.runbook_reference ?? "");
              const normalizedStatus = normalizeAlertStatus(String(payload.status ?? alert.event_type.replace("alert.", "")));
              const isResolved = isResolvedAlert(alert) || normalizedStatus === "resolved";

              return (
                <article
                  key={`${alert.event_id}-${alert.timestamp}`}
                  style={{
                    border: "1px solid var(--line-soft)",
                    borderRadius: "10px",
                    padding: "0.55rem 0.6rem",
                    background: isResolved ? "color-mix(in srgb, var(--ok) 6%, white)" : "white",
                    display: "grid",
                    gap: "0.25rem",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <strong>{title}</strong>
                    <div style={{ display: "flex", gap: "0.3rem" }}>
                      <Badge
                        text={isResolved ? "resolved" : String(payload.severity ?? "active")}
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
                    {alert.timestamp ?? ""}  {alert.correlation_id ? `| corr ${alert.correlation_id}` : ""}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </Panel>
    </div>
  );
}
