import type { TelemetryAggregate, TelemetryRecord } from "@/shared/types/telemetry";
import type { ChartSeries } from "./TimeSeriesChart";
import { displayValue } from "@/shared/lib/format";

export function telemetryChartSeries(rows: (TelemetryRecord | TelemetryAggregate)[], bucketSeconds?: number): ChartSeries[] {
  const groups = new Map<string, ChartSeries>();
  for (const [ordinal, row] of rows.slice(0, 120).entries()) {
    const tags: Record<string, unknown> = "tags" in row ? row.tags : { port_no: row.port_no, peer_host: row.peer_host, run_id: row.run_id };
    const snapshotFlow = row.metric.startsWith("flow_") && "observed_at" in row;
    const flowLabel = snapshotFlow ? ` / snapshot-local flow counter, durable identity unavailable / observed ${row.observed_at} / table ${displayValue(tags.table_id)} / cookie ${displayValue(tags.cookie)} / priority ${displayValue(tags.priority)} / ordinal ${displayValue(tags.flow_index)} / fetched row ${ordinal + 1}` : "";
    const identity = [row.device_id, row.metric, row.unit, row.source, tags.port_no ?? null, tags.peer_host ?? null, tags.run_id ?? null,
      "tags" in row ? [tags.synthetic ?? null, tags.execution_mode ?? null, tags.measurement_method ?? null] : "aggregate",
      snapshotFlow ? [row.observed_at, tags.table_id, tags.cookie, tags.priority, tags.flow_index, ordinal] : null];
    const id = JSON.stringify(identity);
    let series = groups.get(id);
    if (!series) {
      series = { id, label: `${row.device_id} / ${row.metric} / source ${row.source} / port ${displayValue(tags.port_no)} / peer ${displayValue(tags.peer_host)} / run ${displayValue(tags.run_id)}${"tags" in row ? tags.synthetic === true || tags.synthetic === "true" ? " / Synthetic telemetry" : tags.synthetic === false && tags.execution_mode === "emulation" ? " / Measured emulation" : " / Unverified provenance" : " / Aggregated source observations"}${flowLabel}`,
        unit: row.unit ?? "unit unavailable", points: [], interval: "bucket_start" in row && bucketSeconds ? bucketSeconds * 1000 : undefined };
      groups.set(id, series);
    }
    series.points.push({ time: Date.parse("observed_at" in row ? row.observed_at : row.bucket_start),
      value: typeof row.value === "number" && Number.isFinite(row.value) ? row.value : null,
      unavailable: tags.stale === true || tags.stale === "true" ? "Stale observation" : undefined,
      samples: "sample_count" in row ? row.sample_count : undefined });
  }
  return [...groups.values()];
}
