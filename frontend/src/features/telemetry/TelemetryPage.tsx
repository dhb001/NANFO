import { useEffect, useMemo, useRef, useState } from "react";
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
import { TelemetryAggregation } from "@/shared/types/telemetry";
import { validateHistoryFilters } from "@/features/telemetry/historyFilters";
import { Button } from "@/shared/ui/Button";
import { TimeSeriesChart } from "./TimeSeriesChart";
import { telemetryChartSeries } from "./chartSeries";
import { FlowCounterIdentity } from "./FlowCounterIdentity";
import { useSessionScope } from "@/features/auth/sessionScope";

export function TelemetryPage() {
  const { key } = useSessionScope();
  return <TelemetryPageContent key={key} />;
}

function TelemetryPageContent() {
  const canReadHealth = useAuthStore((state) => canReadTelemetryHealth(state.profile));
  const token = useAuthStore((state) => state.accessToken);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const [metricFilter, setMetricFilter] = useState("");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [aggregation, setAggregation] = useState<TelemetryAggregation | "">("");
  const [bucketSeconds, setBucketSeconds] = useState(60);
  const filterError = validateHistoryFilters(startTime, endTime, metricFilter, aggregation, bucketSeconds);
  const range = {
    startTime: !filterError && startTime ? new Date(startTime).toISOString() : undefined,
    endTime: !filterError && endTime ? new Date(endTime).toISOString() : undefined,
  };
  const filterKey = JSON.stringify([workspaceId, networkId, metricFilter, startTime, endTime, aggregation, bucketSeconds]);
  const [pagination, setPagination] = useState({ key: filterKey, page: 1 });
  const page = pagination.key === filterKey ? pagination.page : 1;
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [devicePage, setDevicePage] = useState(1);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 10_000);
    return () => window.clearInterval(timer);
  }, []);
  const isNarrowViewport = useIsNarrowViewport();

  const healthQuery = useTelemetryHealth(token);
  const historyQuery = useTelemetryHistory(token, {
    networkId: networkId ?? undefined,
    workspaceId: workspaceId ?? undefined,
    metric: metricFilter || undefined,
    ...range,
    aggregation: aggregation || undefined,
    bucketSeconds: aggregation ? bucketSeconds : undefined,
    page,
    pageSize: 120,
  }, !filterError);
  const devicesQuery = useDevices(token, networkId, devicePage);
  const deviceHistoryQuery = useDeviceTelemetry(token, selectedDeviceId, range, metricFilter || undefined, !filterError);

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
    estimateSize: () => 115,
    overscan: 10,
  });

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Panel title="Telemetry Health" subtitle="Collection health and the latest reported ingest status">
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
          subtitle="Filter measurements, inspect trends and select a device to investigate"
          action={
            <label className="mono" style={{ fontSize: "0.75rem", color: "var(--ink-3)", display: "flex", gap: "0.4rem", alignItems: "center" }}>
              metric
              <input
                value={metricFilter}
                onChange={(event) => setMetricFilter(event.target.value)}
                aria-label="Filter telemetry metric"
                placeholder="cpu_usage"
                list="telemetry-metrics"
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
          <datalist id="telemetry-metrics">
            {["cpu_usage", "queue_backlog_bytes", "queue_backlog_packets", "throughput_mbps", "link_utilization_percent", "latency_ms", "packet_loss_percent", "port_rx_dropped", "port_tx_dropped"].map((metric) => <option key={metric} value={metric} />)}
          </datalist>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem", marginBottom: "0.75rem" }}>
            <label>Start (local, inclusive)<input aria-label="Start time" type="datetime-local" step="1" value={startTime} onChange={(event) => setStartTime(event.target.value)} /></label>
            <label>End (local, exclusive)<input aria-label="End time" type="datetime-local" step="1" value={endTime} onChange={(event) => setEndTime(event.target.value)} /></label>
            <label>Aggregation <select aria-label="Aggregation" value={aggregation} onChange={(event) => setAggregation(event.target.value as TelemetryAggregation | "")}>
              <option value="">Raw records</option><option value="avg">Average</option><option value="min">Minimum</option><option value="max">Maximum</option><option value="sum">Sum</option>
            </select></label>
            {aggregation && <label>Bucket seconds <input aria-label="Bucket seconds" type="number" min={1} max={86400} step={1} value={bucketSeconds} onChange={(event) => setBucketSeconds(Number(event.target.value))} style={{ width: 90 }} /></label>}
          </div>
          <p style={{ color: "var(--ink-3)", fontSize: "0.78rem" }}>Times are sent in UTC. Aggregation: maximum 7 days, grouped by device, metric, unit, source, port, peer and run. Flow counters require raw history: snapshot v1 has no durable flow match identity. Queue backlog is bytes or packets, not occupancy percent. Emulation latency is ping RTT; probe loss is not application delivery ratio. Missing measurements are unavailable, not zero.</p>
          {filterError ? <p role="alert">{filterError}</p> : <QueryState query={historyQuery} hasData={(data) => data.items.length > 0} emptyTitle="No telemetry history" emptyDescription="Measurements are unavailable for this filter. No zero values are inferred.">
            {() => (<>
              <p role="status">Fetched {historyRows.length} {aggregation ? "buckets" : "records"} on this page (limit 120). This is a bounded filtered view, not a full-network total. Invalid timestamps are omitted from the chart.</p>
              <TimeSeriesChart title="Telemetry time series" series={telemetryChartSeries(historyRows, aggregation ? bucketSeconds : undefined)} />
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
                        key={"record_id" in row ? `${row.record_id}:${virtualRow.index}` : JSON.stringify([row.device_id, row.metric, row.unit, row.source, row.port_no, row.peer_host, row.run_id, row.bucket_start])}
                        ref={historyVirtualizer.measureElement}
                        data-index={virtualRow.index}
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
                          {"tags" in row ? <TelemetryProvenance tags={row.tags} /> : <Badge text={`${aggregation.toUpperCase()} / ${row.sample_count} samples`} tone="neutral" />}
                          <Badge text={Number.isFinite(row.value) ? `${formatNumber(row.value)} ${row.unit ?? "(unit unavailable)"}` : "Unavailable"} tone="info" />
                        </div>
                        <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.74rem" }}>
                          {row.device_id}
                        </div>
                        <div style={{ color: "var(--ink-3)", fontSize: "0.78rem" }}>
                          {"bucket_start" in row ? "Bucket start: " : ""}{formatTimestamp("observed_at" in row ? row.observed_at : row.bucket_start)} | {row.source} | Port {String("tags" in row ? row.tags.port_no ?? "unavailable" : row.port_no ?? "unavailable")}
                          {"tags" in row && row.tags.measurement_method ? ` | ${String(row.tags.measurement_method)}` : ""}
                          {` | Peer ${String("tags" in row ? row.tags.peer_host ?? "unavailable" : row.peer_host ?? "unavailable")} | Run ${String("tags" in row ? row.tags.run_id ?? "unavailable" : row.run_id ?? "unavailable")}`}
                          {"tags" in row && <FlowCounterIdentity metric={row.metric} observedAt={row.observed_at} tags={row.tags} />}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
              </>
            )}
          </QueryState>}
          {!filterError && historyQuery.data && <nav aria-label="Telemetry history pagination" style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem", alignItems: "center", marginTop: "0.6rem" }}>
            <Button disabled={page <= 1 || historyQuery.isFetching} onClick={() => setPagination({ key: filterKey, page: page - 1 })}>Previous</Button>
            <span>Page {page} / {Math.max(1, Math.ceil(historyQuery.data.total / historyQuery.data.page_size))} | {historyQuery.data.total} {aggregation ? "buckets" : "records"}</span>
            <Button disabled={page * historyQuery.data.page_size >= historyQuery.data.total || historyQuery.isFetching} onClick={() => setPagination({ key: filterKey, page: page + 1 })}>Next</Button>
          </nav>}
        </Panel>

        <Panel title="Device Drilldown" subtitle="Measurement history and incoming signals for the selected device">
          <QueryState
            query={devicesQuery}
            hasData={(data) => data.items.length > 0}
            emptyTitle="No devices in network"
            emptyDescription="Select a network and seed devices in Overview first."
          >
            {(devices) => (
              <div style={{ display: "grid", gap: "0.5rem" }}>
                <select
                  aria-label="Telemetry device"
                  value={selectedDeviceId ?? ""}
                  onChange={(event) => setSelectedDeviceId(event.target.value)}
                  style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.48rem 0.5rem" }}
                >
                  <option value="">Select device</option>
                  {selectedDeviceId && !devices.items.some((device) => device.device_id === selectedDeviceId) && <option value={selectedDeviceId}>Selected device: {selectedDeviceId} (outside this page)</option>}
                  {devices.items.map((device) => (
                    <option key={device.device_id} value={device.device_id}>
                      {device.hostname} ({device.device_type})
                    </option>
                  ))}
                </select>

                {filterError ? <p>Correct the history filters to view device measurements.</p> : <QueryState
                  query={deviceHistoryQuery}
                  hasData={(data) => data.items.length > 0}
                  emptyTitle="No device telemetry"
                  emptyDescription="No records available for the selected device."
                >
                  {(deviceHistory) => (<>
                    <p>Fetched {deviceHistory.items.length} of {deviceHistory.total} filtered device records (fetch limit 100); preview limited to 20. Not a network total.</p>
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
                              {Number.isFinite(row.value) ? `${formatNumber(row.value)} ${row.unit ?? "(unit unavailable)"}` : "Unavailable"}
                            </span>
                          </div>
                           <div style={{ color: "var(--ink-3)", fontSize: "0.76rem" }}>{formatTimestamp(row.observed_at)} | {row.source} | Port {String(row.tags.port_no ?? "unavailable")}</div>
                           <FlowCounterIdentity metric={row.metric} observedAt={row.observed_at} tags={row.tags} />
                        </div>
                      ))}
                    </div></>
                  )}
                </QueryState>}
              </div>
            )}
          </QueryState>
          <nav aria-label="Telemetry device pagination">
            <Button disabled={devicePage <= 1 || devicesQuery.isFetching} onClick={() => setDevicePage(devicePage - 1)}>Previous devices</Button>
            <span aria-live="polite"> Page {devicePage}{devicesQuery.isPlaceholderData ? " (loading…)" : ""} | {devicesQuery.data?.total ?? "Unknown"} devices </span>
            <Button disabled={!devicesQuery.data || devicePage * devicesQuery.data.page_size >= devicesQuery.data.total || devicesQuery.isFetching} onClick={() => setDevicePage(devicePage + 1)}>Next devices</Button>
          </nav>
        </Panel>
      </div>

      <Panel title="Realtime Metrics" subtitle="Latest incoming measurements from the telemetry stream">
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
                key={JSON.stringify([metric.device_id, metric.metric, metric.unit, metric.source, metric.tags, metric.observed_at, metric.event_id])}
                style={{
                  border: "1px solid var(--line-soft)",
                  borderRadius: "10px",
                  padding: "0.45rem 0.5rem",
                }}
              >
                <div style={{ fontWeight: 600 }}>{metric.metric}</div>
                 <TelemetryProvenance tags={metric.tags} />
                 <FlowCounterIdentity metric={metric.metric} observedAt={metric.observed_at} tags={metric.tags} />
                 <div>Observed: {formatTimestamp(metric.observed_at)} | {Number.isFinite(Date.parse(metric.observed_at))
                   ? `${Math.max(0, Math.floor((now - Date.parse(metric.observed_at)) / 1000))}s old${now - Date.parse(metric.observed_at) > 30_000 ? " — stale (>30s)" : ""}`
                   : "Age unavailable"}</div>
                <div className="mono" style={{ fontSize: "1.1rem", color: "var(--ink-2)" }}>
                  {Number.isFinite(metric.value) ? `${formatNumber(metric.value)} ${metric.unit ?? "(unit unavailable)"}` : "Unavailable"}
                </div>
                <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.72rem" }}>
                  {metric.device_id.slice(0, 8)}
                  {` | ${metric.source} | Port ${String(metric.tags.port_no ?? "unavailable")}`}
                </div>
              </div>
            ))
          )}
        </div>
      </Panel>
    </div>
  );
}
