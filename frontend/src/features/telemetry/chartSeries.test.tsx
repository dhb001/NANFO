import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TelemetryRecord } from "@/shared/types/telemetry";
import { telemetryChartSeries } from "./chartSeries";
import { TimeSeriesChart } from "./TimeSeriesChart";

describe("time-series identity and evidence", () => {
  const row = { device_id: "d", metric: "latency", unit: "ms", source: "emulation", observed_at: "2026-09-10T00:00:00Z", value: 8, tags: { port_no: 1, peer_host: "h2", run_id: "run" } } as unknown as TelemetryRecord;
  it("preserves duplicate raw flow counters as snapshot-local rows, never a durable series", () => {
    const flow = { ...row, metric: "flow_byte_count", tags: { table_id: 0, cookie: "0", priority: 100, flow_index: 1 } };
    const series = telemetryChartSeries([flow, flow, { ...flow, observed_at: "2026-09-10T00:01:00Z" }]);
    expect(series).toHaveLength(3);
    expect(new Set(series.map((item) => item.id)).size).toBe(3);
    expect(series.every((item) => item.points.length === 1 && item.interval === undefined)).toBe(true);
    expect(series[0].label).toContain("snapshot-local flow counter, durable identity unavailable");
    expect(series[0].label).toContain("table 0 / cookie 0 / priority 100 / ordinal 1");
    const { container } = render(<TimeSeriesChart title="Flow counters" series={series} />);
    expect(container.querySelectorAll("line")).toHaveLength(0);
    expect(screen.getAllByRole("option")).toHaveLength(3);
  });
  it("isolates device, metric, units, source, port, peer, run and provenance", () => {
    const rows = [row, ...["device_id", "metric", "unit", "source"].map((field) => ({ ...row, [field]: "different" })),
      ...["port_no", "peer_host", "run_id", "synthetic"].map((field) => ({ ...row, tags: { ...row.tags, [field]: "different" } }))];
    expect(telemetryChartSeries(rows)).toHaveLength(9);
    expect(telemetryChartSeries(Array.from({ length: 130 }, () => row))[0].points).toHaveLength(120);
  });
  it("sorts dates and breaks stale, missing and absent buckets without zero-fill", () => {
    const { container } = render(<TimeSeriesChart title="History" series={[{ id: "a", label: "port 1", unit: "ms", interval: 1000, points: [
      { time: 5000, value: 9 }, { time: 1000, value: 8 }, { time: 2000, value: null }, { time: 3000, value: 2, unavailable: "Stale" }, { time: 6000, value: 10 },
    ] }]} />);
    expect(container.querySelectorAll("circle")).toHaveLength(3);
    expect(container.querySelectorAll("line")).toHaveLength(1);
    fireEvent.click(screen.getByText("History data table"));
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("1970-01-01T00:00:01.000Z");
    expect(screen.getAllByText("Unavailable")).toHaveLength(2);
    expect(screen.getByRole("region", { name: "History table scroll area" })).toHaveAttribute("tabindex", "0");
  });
  it("uses actual bucket sample counts and omits malformed dates", () => {
    const series = telemetryChartSeries([{ device_id: "d", metric: "loss", unit: "%", source: "emulation", port_no: null, peer_host: "h2", run_id: "run", bucket_start: "2026-09-10T00:00:00Z", value: 3, sample_count: 4 }], 60);
    expect(series[0].points[0]).toMatchObject({ value: 3, samples: 4 });
    expect(series[0].interval).toBe(60000);
    const { container } = render(<TimeSeriesChart title="Raw" series={telemetryChartSeries([{ ...row, observed_at: "invalid" }, row, { ...row, tags: { ...row.tags, stale: true } }])} />);
    expect(container.querySelectorAll("circle")).toHaveLength(1);
    expect(container.querySelectorAll("line")).toHaveLength(0);
  });
});
