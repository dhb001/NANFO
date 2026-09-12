import type { ChartSeries } from "@/features/telemetry/TimeSeriesChart";
import type { SimulationDetail } from "@/shared/types/simulation";

export const modeledMetrics = {
  latency_ms: { label: "Latency", unit: "ms", higherIsBetter: false },
  loss_pct: { label: "Loss", unit: "%", higherIsBetter: false },
  throughput_mbps: { label: "Goodput", unit: "Mbps", higherIsBetter: true },
} as const;
export type ModeledMetric = keyof typeof modeledMetrics;

export function modeledOutput(detail: SimulationDetail | undefined) {
  const output = detail?.run_output;
  if (!output || output.model_version !== "finite-buffer-fluid.v1" || output.source !== "operator_configured_model" ||
    ![output.input_sha256, output.checkpoint_sha256, output.output_sha256, output.workload_sha256].every((value) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value))) return null;
  return output;
}

export function modelHistorySeries(detail: SimulationDetail | undefined, metric: ModeledMetric, label: string): ChartSeries[] {
  const output = modeledOutput(detail);
  if (!output || !Array.isArray(output.trace)) return [];
  const groups = new Map<string, ChartSeries>();
  const config = detail?.scenario_config;
  for (const row of output.trace.slice(0, 1000)) {
    if (!row || typeof row !== "object" || typeof row.elapsed_ms !== "number" || !Number.isFinite(row.elapsed_ms)) continue;
    const flows = row.flows;
    if (!flows || typeof flows !== "object" || Array.isArray(flows)) continue;
    for (const [flowId, raw] of Object.entries(flows).slice(0, 64)) {
      const id = JSON.stringify([label, detail?.simulation_id, flowId, metric]);
      let series = groups.get(id);
      if (!series) {
        series = { id, label: `${label} / run ${detail?.simulation_id} / flow ${flowId} / ${modeledMetrics[metric].label} / configured model`, unit: modeledMetrics[metric].unit, interval: config?.tick_ms, points: [] };
        groups.set(id, series);
      }
      const value = raw && typeof raw === "object" ? (raw as Record<string, unknown>)[metric] : null;
      series.points.push({ time: row.elapsed_ms, value: typeof value === "number" && Number.isFinite(value) ? value : null });
    }
  }
  return [...groups.values()];
}
