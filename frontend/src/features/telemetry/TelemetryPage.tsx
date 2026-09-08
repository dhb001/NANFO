import { useMemo, useRef, useState } from "react";
import { useTelemetryHealth, useTelemetryHistory, useDeviceTelemetry } from "@/features/telemetry/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { QueryState } from "@/shared/ui/QueryState";
import { Panel } from "@/shared/ui/Panel";
import { StatTile } from "@/shared/ui/StatTile";
import { Badge } from "@/shared/ui/Badge";
import { formatNumber, formatTimestamp } from "@/shared/lib/format";
import { useLiveStore } from "@/features/realtime/store";
import { useDevices } from "@/features/networks/hooks";
import { useIsNarrowViewport } from "@/shared/lib/viewport";
import { useVirtualizer } from "@tanstack/react-virtual";
import { TelemetryProvenance } from "@/features/telemetry/TelemetryProvenance";
import { canReadTelemetryHealth } from "@/features/auth/permissions";
import { AsyncState } from "@/shared/ui/AsyncState";

export function TelemetryPage() {
  const canReadHealth = useAuthStore((state) => canReadTelemetryHealth(state.profile));
  const token = useAuthStore((state) => state.accessToken);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const [metricFilter, setMetricFilter] = useState("");
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const isNarrowViewport = useIsNarrowViewport();

  const healthQuery = useTelemetryHealth(token);
  const historyQuery = useTelemetryHistory(token, {
    networkId: networkId ?? undefined,
    workspaceId: workspaceId ?? undefined,
    metric: metricFilter || undefined,
    page: 1,
    pageSize: 120,
  });
  const devicesQuery = useDevices(token, networkId);
  const deviceHistoryQuery = useDeviceTelemetry(token, selectedDeviceId);

  const liveMetrics = useLiveStore((state) => state.telemetryByDeviceMetric);
  const telemetryKeysNewestFirst = useLiveStore((state) => state.telemetryKeysNewestFirst);

  const liveMetricEntries = useMemo(
    () =>
      telemetryKeysNewestFirst
        .slice(0, 20)
        .map((key) => liveMetrics[key])
        .filter((metric): metric is (typeof liveMetrics)[string] => Boolean(metric)),
    [liveMetrics, telemetryKeysNewestFirst],
  );
  const historyRows = historyQuery.data?.items ?? [];
  const historyParentRef = useRef<HTMLDivElement | null>(null);

  const historyVirtualizer = useVirtualizer({
    count: historyRows.length,
    getScrollElement: () => historyParentRef.current,
    estimateSize: () => 80,
    overscan: 10,
  });

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Panel title="Telemetry Health" subtitle="VS2 /telemetry/health and realtime status snapshot">
        {!canReadHealth ? <AsyncState title="Telemetry health restricted" description="Global diagnostics require Admin and read:telemetry permission. Tenant telemetry history remains available below." /> : <QueryState query={healthQuery}>
          {(health) => (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: isNarrowViewport ? "repeat(2, minmax(0, 1fr))" : "repeat(4, minmax(0, 1fr))",
                gap: "0.6rem",
              }}
            >
              <StatTile label="Status" value={health.status.toUpperCase()} tone={health.status === "ok" ? "ok" : "warn"} />
              <StatTile label="Ingest Lag" value={health.ingest_lag_ms === null ? "Unavailable (no observations)" : `${formatNumber(health.ingest_lag_ms, 0)} ms`} />
              <StatTile label="Dropped Events" value={String(health.dropped_events)} tone={health.dropped_events > 0 ? "warn" : "ok"} />
              <StatTile label="Total Records" value={String(health.total_records)} />
            </div>
          )}
        </QueryState>}
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: isNarrowViewport ? "1fr" : "1.2fr 1fr", gap: "1rem", alignItems: "start" }}>
        <Panel
          title="Telemetry History"
          subtitle="Dense engineer timeline with filter + quick scan"
          action={
            <label className="mono" style={{ fontSize: "0.75rem", color: "var(--ink-3)", display: "flex", gap: "0.4rem", alignItems: "center" }}>
              metric
              <input
                value={metricFilter}
                onChange={(event) => setMetricFilter(event.target.value)}
                aria-label="Filter telemetry metric"
                placeholder="cpu_usage"
                style={{
                  border: "1px solid var(--line-soft)",
                  borderRadius: "8px",
                  padding: "0.25rem 0.4rem",
                  minWidth: 130,
                  background: "white",
                }}
              />
            </label>
          }
        >
          <QueryState query={historyQuery} hasData={(data) => data.items.length > 0} emptyTitle="No telemetry history">
            {() => (
              <div
                ref={historyParentRef}
                style={{
                  maxHeight: 430,
                  overflow: "auto",
                  border: "1px solid var(--line-soft)",
                  borderRadius: "10px",
                  position: "relative",
                }}
              >
                <div
                  style={{
                    height: historyVirtualizer.getTotalSize(),
                    width: "100%",
                    position: "relative",
                  }}
                >
                  {historyVirtualizer.getVirtualItems().map((virtualRow) => {
                    const row = historyRows[virtualRow.index];
                    if (!row) {
                      return null;
                    }

                    return (
                      <button
                        key={row.record_id}
                        onClick={() => setSelectedDeviceId(row.device_id)}
                        style={{
                          position: "absolute",
                          top: 0,
                          left: 0,
                          width: "100%",
                          transform: `translateY(${virtualRow.start}px)`,
                          textAlign: "left",
                          borderBottom: "1px solid var(--line-soft)",
                          padding: "0.48rem 0.52rem",
                          display: "grid",
                          gap: "0.2rem",
                          background: "transparent",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.4rem" }}>
                          <strong>{row.metric}</strong>
                          <TelemetryProvenance tags={row.tags} />
                          <Badge text={`${formatNumber(row.value)} ${row.unit ?? ""}`.trim()} tone="info" />
                        </div>
                        <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                          {row.device_id}
                        </div>
                        <div style={{ color: "var(--ink-3)", fontSize: "0.78rem" }}>{formatTimestamp(row.observed_at)}</div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </QueryState>
        </Panel>

        <Panel title="Device Drilldown" subtitle="Per-device telemetry history + realtime joins">
          <QueryState
            query={devicesQuery}
            hasData={(data) => data.items.length > 0}
            emptyTitle="No devices in network"
            emptyDescription="Select a network and seed devices in Overview first."
          >
            {(devices) => (
              <div style={{ display: "grid", gap: "0.5rem" }}>
                <select
                  value={selectedDeviceId ?? ""}
                  onChange={(event) => setSelectedDeviceId(event.target.value)}
                  style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.48rem 0.5rem" }}
                >
                  <option value="">Select device</option>
                  {devices.items.map((device) => (
                    <option key={device.device_id} value={device.device_id}>
                      {device.hostname} ({device.device_type})
                    </option>
                  ))}
                </select>

                <QueryState
                  query={deviceHistoryQuery}
                  hasData={(data) => data.items.length > 0}
                  emptyTitle="No device telemetry"
                  emptyDescription="No records available for the selected device."
                >
                  {(deviceHistory) => (
                    <div style={{ display: "grid", gap: "0.35rem", maxHeight: 280, overflow: "auto" }}>
                      {deviceHistory.items.slice(0, 20).map((row) => (
                        <div
                          key={row.record_id}
                          style={{ border: "1px solid var(--line-soft)", borderRadius: "8px", padding: "0.42rem 0.48rem" }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between" }}>
                            <strong>{row.metric}</strong>
                            <TelemetryProvenance tags={row.tags} />
                            <span className="mono" style={{ fontSize: "0.8rem" }}>
                              {formatNumber(row.value)}
                            </span>
                          </div>
                          <div style={{ color: "var(--ink-3)", fontSize: "0.76rem" }}>{formatTimestamp(row.observed_at)}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </QueryState>
              </div>
            )}
          </QueryState>
        </Panel>
      </div>

      <Panel title="Realtime Metrics" subtitle="WebSocket /ws/telemetry live delta preview">
        <div
          style={{
            display: "grid",
            gridTemplateColumns: isNarrowViewport ? "repeat(2, minmax(0, 1fr))" : "repeat(4, minmax(0, 1fr))",
            gap: "0.45rem",
          }}
        >
          {liveMetricEntries.length === 0 ? (
            <div style={{ color: "var(--ink-3)", fontSize: "0.85rem" }}>Awaiting live telemetry deltas...</div>
          ) : (
            liveMetricEntries.map((metric) => (
              <div
                key={`${metric.device_id}:${metric.metric}`}
                style={{
                  border: "1px solid var(--line-soft)",
                  borderRadius: "10px",
                  padding: "0.45rem 0.5rem",
                }}
              >
                <div style={{ fontWeight: 600 }}>{metric.metric}</div>
                <TelemetryProvenance tags={metric.tags} />
                <div className="mono" style={{ fontSize: "1.1rem", color: "var(--ink-2)" }}>
                  {formatNumber(metric.value)} {metric.unit ?? ""}
                </div>
                <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.72rem" }}>
                  {metric.device_id.slice(0, 8)}
                </div>
              </div>
            ))
          )}
        </div>
      </Panel>
    </div>
  );
}
