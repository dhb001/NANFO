import { beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AlertHistory } from "./AlertHistory";

const mocks = vi.hoisted(() => ({ detail: vi.fn(), history: vi.fn() }));
vi.mock("./hooks", () => ({ useAlertDetail: mocks.detail, useAlertHistory: mocks.history }));
const payload = { rule: { version: "operator-v1", breach: 100, recover: 70, duration_seconds: 10, min_samples: 3, max_gap_seconds: 10, max_age_seconds: 30 },
  metric: "latency_ms", value: 120, unit: "ms", observed_at: "2026-09-11T00:00:10Z", window_started_at: "2026-09-11T00:00:00Z", sample_count: 3,
  source: "emulation", execution_mode: "emulation", quality: "measured", synthetic: false, measurement_method: "ping_rtt", observation_event_id: "o1",
  workspace_id: "w1", network_id: "n1", device_id: "d1", peer_host: "h2", run_id: "run1", rule_version: "operator-v1" };
beforeEach(() => {
  mocks.detail.mockReturnValue({ data: { alert_id: "a1", status: "resolved", correlation_id: "c1", payload }, refetch: vi.fn() });
  mocks.history.mockReturnValue({ data: { alert_id: "a1", total: 2, items: [
    { event_id: "e1", alert_id: "a1", event_type: "alert.generated", occurred_at: "2026-09-11T00:00:10Z", correlation_id: "c1", payload },
    { event_id: "e2", alert_id: "a1", event_type: "alert.resolved", occurred_at: "2026-09-11T00:01:10Z", correlation_id: "c2", payload: { ...payload, value: 60, resolution_reason: "measured_recovery" } },
  ] }, refetch: vi.fn() });
});
it("renders lifecycle identity, thresholds, units, provenance and exact recovery scope", () => {
  render(<AlertHistory id="a1" />);
  expect(screen.getByText("alert.generated")).toBeInTheDocument();
  expect(screen.getByText("alert.resolved")).toBeInTheDocument();
  expect(screen.getAllByText(/breach >= 100 ms; recovery < 70 ms/)).toHaveLength(3);
  expect(screen.getAllByText(/peer_host: h2; run_id: run1/)).toHaveLength(3);
  expect(screen.getAllByText(/synthetic false; method ping_rtt/)).toHaveLength(3);
  expect(screen.getByText("Resolution reason: measured_recovery")).toBeInTheDocument();
});
it("shows empty history and denial without falling back to stale cached evidence", () => {
  mocks.detail.mockReturnValue({ isError: true, error: new Error("Permission revoked"), data: { payload }, refetch: vi.fn() });
  mocks.history.mockReturnValue({ data: { items: [], total: 0 }, refetch: vi.fn() });
  render(<AlertHistory id="a1" />);
  expect(screen.getByText("Permission revoked")).toBeInTheDocument();
  expect(screen.getByText("No lifecycle history recorded")).toBeInTheDocument();
  expect(screen.queryByText(/Rule operator/)).not.toBeInTheDocument();
});
