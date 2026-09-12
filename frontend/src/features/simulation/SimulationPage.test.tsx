import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SimulationPage } from "@/features/simulation/SimulationPage";

vi.mock("@/features/simulation/hooks", () => ({
  useStartSimulation: () => ({}),
  usePauseSimulation: () => ({}),
  useBranchSimulation: () => ({}),
  useSimulationDetail: () => ({ isLoading: false, isError: false, data: {
    simulation_id: "demo", scenario_id: "scenario", status: "cancelled", queue_status: "blocked", risk_gate: "blocked", validation: {},
  } }),
  useSimulationCompare: () => ({ isLoading: false, isError: false, data: {
    deltas: { latency_ms: null, loss_pct: null, throughput_mbps: null },
  } }),
}));

describe("simulation truthfulness", () => {
  it("shows cancelled/blocked outcomes and missing measurements without zero or improvement", () => {
    render(<SimulationPage />);
    expect(screen.getByText("cancelled")).toBeInTheDocument();
    expect(screen.getAllByText("blocked")).toHaveLength(2);
    expect(screen.getAllByText("Unavailable (no compatible modeled evidence)")).toHaveLength(3);
    expect(screen.queryByText(/^0(?:\.00)? (ms|%|Mbps)$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/improved/i)).not.toBeInTheDocument();
  });
});
