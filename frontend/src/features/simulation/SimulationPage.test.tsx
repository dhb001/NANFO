import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SimulationPage } from "@/features/simulation/SimulationPage";

const cancelledDetail = {
  simulation_id: "demo", scenario_id: "scenario", status: "cancelled", queue_status: "queued", risk_gate: "blocked", validation: {},
};
let detail: Record<string, unknown> = cancelledDetail;

vi.mock("@/features/simulation/hooks", () => ({
  useSimulationHistory: () => ({ data: { items: [], total: 0, page: 1, page_size: 20 } }),
  useStartSimulation: () => ({}),
  usePauseSimulation: () => ({}),
  useBranchSimulation: () => ({}),
  useSimulationDetail: () => ({ isLoading: false, isError: false, data: detail }),
  useSimulationCompare: () => ({ isLoading: false, isError: false, data: {
    deltas: { latency_ms: null, loss_pct: null, throughput_mbps: null },
  } }),
}));

describe("simulation truthfulness", () => {
  beforeEach(() => { detail = cancelledDetail; });

  it("shows cancelled/blocked outcomes and missing measurements without zero or improvement", () => {
    render(<SimulationPage />);
    expect(screen.getByText("cancelled")).toHaveClass("badge--danger");
    expect(screen.getByText("blocked")).toHaveClass("badge--danger");
    expect(screen.getByText("queued")).toHaveClass("badge--ok");
    expect(screen.getAllByText("Unavailable (no compatible modeled evidence)")).toHaveLength(3);
    expect(screen.queryByText(/^0(?:\.00)? (ms|%|Mbps)$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/improved/i)).not.toBeInTheDocument();
  });

  it("shows the backend failed state with its reason and an unknown state neutrally (ADR-028)", () => {
    detail = { ...cancelledDetail, status: "failed", validation: { status: "failed", failure_reason: "attempts_exhausted" } };
    const { unmount } = render(<SimulationPage />);
    expect(screen.getByText("failed")).toHaveClass("badge--danger");
    expect(screen.getByText("Simulation failed")).toBeInTheDocument();
    expect(screen.getByText(/cannot authorize execution\. Reason: attempts_exhausted/)).toBeInTheDocument();
    unmount();
    detail = { ...cancelledDetail, status: "reticulating", queue_status: "mystery" };
    render(<SimulationPage />);
    expect(screen.getByText("reticulating")).toHaveClass("badge--neutral");
    expect(screen.getByText("mystery")).toHaveClass("badge--neutral");
    expect(screen.queryByText("Simulation failed")).not.toBeInTheDocument();
  });

  it("discloses execution policy floors and runs that can never authorize execution (C18)", () => {
    detail = { ...cancelledDetail, status: "completed", risk_gate: "passed", execution_policy: {
      policy_floors: { max_loss_pct: 1, max_latency_ms: 1000, min_throughput_mbps: 0.1 }, limits_respect_policy: false,
    } };
    const { unmount } = render(<SimulationPage />);
    expect(screen.getByText(/loss at most 1 %, latency at most 1000 ms, throughput at least 0.1 Mbps/)).toBeInTheDocument();
    expect(screen.getByText(/can never authorize a high-impact execution \(SIMULATION_POLICY_VIOLATION\)/)).toHaveAttribute("role", "alert");
    unmount();
    detail = { ...cancelledDetail, execution_policy: null };
    render(<SimulationPage />);
    expect(screen.getByText(/Execution policy: not reported/)).toBeInTheDocument();
  });
});
