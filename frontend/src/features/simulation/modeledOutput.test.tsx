import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SimulationDetail } from "@/shared/types/simulation";
import { modeledOutput, modelHistorySeries, modeledMetrics } from "./modeledOutput";
import { ModeledEvidence } from "./ModeledEvidence";

const detail = { simulation_id: "run", scenario_config: { tick_ms: 100 }, run_output: { model_version: "finite-buffer-fluid.v1", source: "operator_configured_model", input_sha256: "a".repeat(64), checkpoint_sha256: "b".repeat(64), output_sha256: "c".repeat(64), workload_sha256: "d".repeat(64), elapsed_ms: 300,
  latency_ms: null, loss_pct: 10, throughput_mbps: 3,
  trace: [{ elapsed_ms: 100, flows: { f1: { latency_ms: null }, f2: { latency_ms: 5 } } }, { elapsed_ms: 200, flows: { f1: { latency_ms: 8 }, f2: { latency_ms: 6 } } }],
} } as unknown as SimulationDetail;

describe("modeled output presentation", () => {
  it("requires positive version, source and hashes, without treating legacy metrics as evidence", () => {
    expect(modeledOutput(detail)).toBe(detail.run_output);
    expect(modeledOutput({ ...detail, run_output: { latency_ms: 0, loss_pct: 0, throughput_mbps: 1000 } })).toBeNull();
    expect(modeledOutput({ ...detail, run_output: { ...detail.run_output, source: "measured" } })).toBeNull();
  });
  it("isolates runs/flows and preserves unavailable histories and metric direction", () => {
    const series = modelHistorySeries(detail, "latency_ms", "Candidate");
    expect(series).toHaveLength(2);
    expect(series[0].points).toEqual([{ time: 100, value: null }, { time: 200, value: 8 }]);
    expect(series[0].id).not.toBe(modelHistorySeries(detail, "latency_ms", "Baseline")[0].id);
    expect(modeledMetrics.latency_ms.higherIsBetter).toBe(false);
    expect(modeledMetrics.loss_pct.higherIsBetter).toBe(false);
    expect(modeledMetrics.throughput_mbps.higherIsBetter).toBe(true);
  });
  it("labels modeled metrics, expired evidence and absent measured/model proof honestly", () => {
    render(<ModeledEvidence detail={{ ...detail, evidence_expires_at: "2020-01-01T00:00:00Z" }} />);
    expect(screen.getByText("Modeled latency").nextElementSibling).toHaveTextContent("Unavailable");
    expect(screen.getByText("Modeled goodput").nextElementSibling).toHaveTextContent("3 Mbps");
    expect(screen.getByText(/Modeled evidence expiry:/)).toHaveTextContent("Expired 2020-01-01T00:00:00.000Z");
    expect(screen.getByText(/Neither grants physical production authorization/)).toBeInTheDocument();
  });
});
