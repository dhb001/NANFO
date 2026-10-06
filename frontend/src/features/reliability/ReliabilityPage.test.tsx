import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReliabilityPage } from "@/features/reliability/ReliabilityPage";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";
import { useLiveStore } from "@/features/realtime/store";
import { useUiStore } from "@/shared/state/ui-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";

const mockUseTelemetryHealth = vi.fn();
const mockUseAlertsQuery = vi.fn();
const mockUseAcknowledgeAlert = vi.fn();
const mockUseResolveAlert = vi.fn();

vi.mock("@/features/telemetry/hooks", () => ({
  useTelemetryHealth: (...args: unknown[]) => mockUseTelemetryHealth(...args),
}));

vi.mock("@/features/reliability/hooks", () => ({
  useAlertsQuery: (...args: unknown[]) => mockUseAlertsQuery(...args),
  useAcknowledgeAlert: (...args: unknown[]) => mockUseAcknowledgeAlert(...args),
  useResolveAlert: (...args: unknown[]) => mockUseResolveAlert(...args),
}));

const mockAcknowledgeMutateAsync = vi.fn();
const mockResolveMutateAsync = vi.fn();
const mockAlertsRefetch = vi.fn();

function queryResult<T>(data: T, refetch = vi.fn()) {
  return {
    isLoading: false,
    isError: false,
    data,
    refetch,
  };
}

describe("ReliabilityPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceStore.setState({ organizationId: "org-1", workspaceId: "workspace-1", networkId: "network-1" });

    useAuthStore.setState({
      profile: { ...operatorProfile, roles: ["Admin"] },
      accessToken: "token-1",
      refreshToken: "refresh-1",
      userId: "00000000-0000-0000-0000-000000000123",
    });
    useUiStore.setState({
      commandPaletteOpen: false,
      toasts: [],
    });
    useLiveStore.setState({
      topologyByDeviceId: {},
      telemetryByDeviceMetric: {},
      telemetryKeysNewestFirst: [],
      sceneObjects: {},
      sceneObjectIdsNewestFirst: [],
      alerts: [
        {
          event_id: "evt-ws-ack",
          event_type: "alert.acknowledged",
          source: "alert",
          payload: {
            alert_id: "00000000-0000-0000-0000-000000000101",
            status: "acknowledged",
          },
          correlation_id: "corr-ws-1",
          timestamp: "2026-08-14T12:00:05Z",
        },
      ],
      topologyStatus: "closed",
      telemetryStatus: "closed",
      alertsStatus: "open",
      digitalTwinStatus: "closed",
    });

    mockUseTelemetryHealth.mockReturnValue(
      queryResult({
        status: "degraded",
        ingest_lag_ms: 1400,
        dropped_events: 3,
        latest_observed_at: "2026-08-14T12:00:00Z",
        total_records: 1234,
      }),
    );

    mockUseAlertsQuery.mockReturnValue(
      queryResult(
        {
          items: [
            {
              alert_id: "00000000-0000-0000-0000-000000000101",
              alert_key: "telemetry_runtime_adapter_slo_threshold_breach",
              source: "telemetry",
              status: "active",
              severity: "critical",
              correlation_id: "00000000-0000-0000-0000-000000000401",
              payload: {
                alert_id: "00000000-0000-0000-0000-000000000101",
                alert_key: "telemetry_runtime_adapter_slo_threshold_breach",
                status: "active",
                severity: "critical",
              },
              acknowledged_by_user_id: null,
              resolved_by_user_id: null,
              acknowledged_at: null,
              resolved_at: null,
              created_at: "2026-08-14T11:50:00Z",
              updated_at: "2026-08-14T12:00:00Z",
            },
            {
              alert_id: "00000000-0000-0000-0000-000000000102",
              alert_key: "telemetry_runtime_adapter_recovery_window",
              source: "telemetry",
              status: "acknowledged",
              severity: "high",
              correlation_id: "00000000-0000-0000-0000-000000000402",
              payload: {
                alert_id: "00000000-0000-0000-0000-000000000102",
                alert_key: "telemetry_runtime_adapter_recovery_window",
                status: "acknowledged",
                severity: "high",
              },
              acknowledged_by_user_id: "00000000-0000-0000-0000-000000000777",
              resolved_by_user_id: null,
              acknowledged_at: "2026-08-14T11:59:00Z",
              resolved_at: null,
              created_at: "2026-08-14T11:55:00Z",
              updated_at: "2026-08-14T11:59:00Z",
            },
          ],
          total: 2,
          status_counts: {
            active: 1,
            acknowledged: 1,
            resolved: 0,
          },
        },
        mockAlertsRefetch,
      ),
    );

    mockUseAcknowledgeAlert.mockReturnValue({
      mutateAsync: mockAcknowledgeMutateAsync,
      isPending: false,
      isError: false,
      error: null,
    });

    mockUseResolveAlert.mockReturnValue({
      mutateAsync: mockResolveMutateAsync,
      isPending: false,
      isError: false,
      error: null,
    });

    mockAcknowledgeMutateAsync.mockResolvedValue({
      queue_status: "queued",
      idempotent_replay: false,
    });
    mockResolveMutateAsync.mockResolvedValue({
      queue_status: "queued",
      idempotent_replay: false,
    });
  });

  it("renders list and applies acknowledged filter", async () => {
    const user = userEvent.setup();
    render(<ReliabilityPage />);

    expect(screen.getByText("Alerts Lifecycle")).toBeInTheDocument();
    expect(screen.getByText("Collector Status")).toBeInTheDocument();
    expect(screen.getByText("OPEN")).toBeInTheDocument();
    expect(screen.getByText("telemetry_runtime_adapter_slo_threshold_breach")).toBeInTheDocument();
    expect(screen.getByText("telemetry_runtime_adapter_recovery_window")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Ack" }));
    expect(mockUseAlertsQuery).toHaveBeenLastCalledWith("token-1", expect.objectContaining({ status: "acknowledged", workspaceId: "workspace-1", networkId: "network-1" }), true);
  });

  it("calls acknowledge and resolve actions", async () => {
    const user = userEvent.setup();
    render(<ReliabilityPage />);

    await user.click(screen.getAllByRole("button", { name: "Acknowledge" })[0]);
    expect(mockAcknowledgeMutateAsync).toHaveBeenCalledWith("00000000-0000-0000-0000-000000000101");

    await user.click(screen.getAllByRole("button", { name: "Resolve" })[0]);
    expect(mockResolveMutateAsync).toHaveBeenCalledWith("00000000-0000-0000-0000-000000000101");
  });

  it("submits search/source/severity and resets filters on scope change but not token rotation", async () => {
    const user = userEvent.setup();
    render(<ReliabilityPage />);
    await user.type(screen.getByLabelText("Filter alerts"), " older active ");
    await user.type(screen.getByLabelText("Source", { exact: true }), "telemetry");
    await user.type(screen.getByLabelText("Severity", { exact: true }), "warning");
    expect(mockUseAlertsQuery).toHaveBeenLastCalledWith("token-1", expect.not.objectContaining({ search: "older active" }), true);
    await user.click(screen.getByRole("button", { name: "Apply alert filters" }));
    await user.click(screen.getByRole("button", { name: "Active" }));
    expect(mockUseAlertsQuery).toHaveBeenLastCalledWith("token-1", expect.objectContaining({ search: "older active", source: "telemetry", severity: "warning", status: "active" }), true);
    act(() => useAuthStore.setState({ accessToken: "token-2" }));
    expect(screen.getByLabelText("Filter alerts")).toHaveValue(" older active ");
    act(() => useWorkspaceStore.setState({ networkId: "network-2" }));
    expect(screen.getByLabelText("Filter alerts")).toHaveValue("");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
    expect(mockUseAlertsQuery).toHaveBeenLastCalledWith("token-2", { status: undefined, limit: 200, workspaceId: "workspace-1", networkId: "network-2" }, true);
    expect(screen.getByText(/Counts are not global totals/)).toBeInTheDocument();
    expect(screen.getAllByText(/Origin: source telemetry/)).toHaveLength(2);
  });

  it("requires a workspace instead of silently showing all authorized alerts", () => {
    useWorkspaceStore.setState({ workspaceId: null, networkId: null });
    render(<ReliabilityPage />);
    expect(screen.getByText("Select a workspace")).toBeInTheDocument();
    expect(mockUseAlertsQuery).toHaveBeenLastCalledWith("token-1", expect.anything(), false);
    expect(screen.queryByText("telemetry_runtime_adapter_slo_threshold_breach")).not.toBeInTheDocument();
  });

  it("renders unavailable ingest lag without coercing null to zero", () => {
    mockUseTelemetryHealth.mockReturnValue(queryResult({ status: "unavailable", ingest_lag_ms: null, dropped_events: 0 }));
    render(<ReliabilityPage />);
    expect(screen.getByText("UNAVAILABLE")).toBeInTheDocument();
    expect(screen.getByText("Unavailable (no observations)")).toBeInTheDocument();
    expect(screen.queryByText("null")).not.toBeInTheDocument();
  });

  it("explains restricted diagnostics without hiding tenant alerts", () => {
    useAuthStore.getState().setProfile(operatorProfile);
    render(<ReliabilityPage />);
    expect(screen.getByText("Telemetry health restricted")).toBeInTheDocument();
    expect(screen.getByText("Alerts Lifecycle")).toBeInTheDocument();
    expect(screen.queryByText("Collector Status")).not.toBeInTheDocument();
    // Platform alerts are a global-Admin view only.
    expect(screen.queryByLabelText(/including platform runtime alerts/)).not.toBeInTheDocument();
  });

  it("colours severity and status from explicit backend maps and shows the collector SLO (ADR-028)", () => {
    mockUseTelemetryHealth.mockReturnValue(queryResult({
      status: "ok", ingest_lag_ms: 10, dropped_events: 0, latest_observed_at: null, total_records: 5,
      slo: { status: "critical", stale: false, evaluated_at: "2026-08-14T12:00:00Z", severity_reason: "anomaly_streak_threshold_exceeded",
        alert_active: true, anomaly_streak: 3, evaluation_interval_seconds: 30 },
    }));
    const [first, second] = mockUseAlertsQuery().data.items;
    mockUseAlertsQuery.mockReturnValue(queryResult({ items: [first, { ...second, severity: "catastrophic" }], total: 2, status_counts: {} }, mockAlertsRefetch));
    render(<ReliabilityPage />);
    expect(screen.getByText("critical")).toHaveClass("badge--danger");
    expect(screen.getByText("catastrophic")).toHaveClass("badge--neutral");
    expect(screen.getByText("active")).toHaveClass("badge--warn");
    expect(screen.getByText("acknowledged")).toHaveClass("badge--info");
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
    expect(screen.getByText(/Reason: anomaly_streak_threshold_exceeded/)).toBeInTheDocument();
  });

  it("keeps platform runtime alerts read-only and shows their evaluation window (ADR-028)", () => {
    const [first, second] = mockUseAlertsQuery().data.items;
    const platform = { ...first, severity: "degraded", payload: { alert_scope: "platform", severity: "degraded",
      evaluation_window: { start: "2026-08-14T11:59:00Z", end: "2026-08-14T12:00:00Z", seconds: 60, counter_reset: false } } };
    mockUseAlertsQuery.mockReturnValue(queryResult({ items: [platform, second], total: 2, status_counts: {} }, mockAlertsRefetch));
    render(<ReliabilityPage />);
    const [platformCard, tenantCard] = screen.getAllByRole("article");
    expect(within(platformCard).getByText("platform alert (read-only)")).toBeInTheDocument();
    expect(within(platformCard).getByText(/\(60 s\); counter reset: no\./)).toBeInTheDocument();
    expect(within(platformCard).queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
    expect(within(platformCard).queryByRole("button", { name: "Resolve" })).not.toBeInTheDocument();
    expect(within(platformCard).getByText(/platform runtime \(no tenant\)/)).toBeInTheDocument();
    // Tenant alerts keep their lifecycle actions.
    expect(within(tenantCard).getByRole("button", { name: "Resolve" })).toBeInTheDocument();
  });

  it("lets a global Admin list platform alerts without a tenant selection", async () => {
    const user = userEvent.setup();
    useWorkspaceStore.setState({ workspaceId: null, networkId: null });
    render(<ReliabilityPage />);
    expect(screen.getByText("Select a workspace")).toBeInTheDocument();
    await user.click(screen.getByLabelText(/including platform runtime alerts/));
    expect(mockUseAlertsQuery).toHaveBeenLastCalledWith("token-1", { status: undefined, limit: 200 }, true);
    expect(screen.queryByText("Select a workspace")).not.toBeInTheDocument();
    expect(screen.getByText("telemetry_runtime_adapter_slo_threshold_breach")).toBeInTheDocument();
  });
});
