import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ExecutionModeBanner } from "@/shared/ui/ExecutionModeBanner";
import { useExecutionModeStore } from "@/shared/state/execution-mode-store";
import { TelemetryProvenance } from "@/features/telemetry/TelemetryProvenance";
import { MetricSnapshotList } from "@/features/digitalTwin/MetricSnapshotList";

describe("truth labels", () => {
  beforeEach(() => useExecutionModeStore.getState().reset());
  it("remains Unknown until a recognized backend mode is observed", () => {
    render(<ExecutionModeBanner />);
    expect(screen.getByRole("status")).toHaveTextContent("Execution mode: Unknown");
    act(() => useExecutionModeStore.getState().observe("live"));
    expect(screen.getByRole("status")).toHaveTextContent("Execution mode: Unknown");
    act(() => useExecutionModeStore.getState().observe("demo"));
    expect(screen.getByRole("status")).toHaveTextContent("Demo mode: synthetic data");
    expect(screen.getByRole("status")).toHaveTextContent("No real network execution");
    act(() => useExecutionModeStore.getState().observe("emulation"));
    expect(screen.getByRole("status")).toHaveTextContent("Emulation mode: not production");
    act(() => useExecutionModeStore.getState().observe("production"));
    expect(screen.getByRole("status")).toHaveTextContent("Production mode: backend authorization and validation still apply");
  });
  it("uses telemetry tags, never the global mode, to identify synthetic records", () => {
    useExecutionModeStore.getState().observe("production");
    const { rerender } = render(<TelemetryProvenance tags={{ synthetic: true }} />);
    expect(screen.getByText("Synthetic telemetry")).toBeInTheDocument();
    rerender(<TelemetryProvenance tags={{}} />);
    expect(screen.getByText("Telemetry provenance: unverified")).toBeInTheDocument();
    expect(screen.queryByText("Synthetic telemetry")).not.toBeInTheDocument();
  });
  it("retains synthetic provenance in the Digital Twin metric inspector", () => {
    render(<MetricSnapshotList metrics={[{
      metric: "cpu", value: 50, unit: "%", observedAt: "2026-09-08T00:00:00Z", source: "runtime",
      tags: { synthetic: true }, normalizedScore: 0.5, severity: "low", policyId: "cpu", policyPriority: 1,
      lowUpperExclusive: 70, mediumUpperExclusive: 90,
    }]} />);
    expect(screen.getByText("Synthetic telemetry")).toBeInTheDocument();
  });
});
