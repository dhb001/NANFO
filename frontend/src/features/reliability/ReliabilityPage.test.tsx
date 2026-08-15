import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReliabilityPage } from "@/features/reliability/ReliabilityPage";
import { useAuthStore } from "@/shared/state/auth-store";
import { useLiveStore } from "@/features/realtime/store";
import { useUiStore } from "@/shared/state/ui-store";

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

    useAuthStore.setState({
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
    expect(screen.queryByText("telemetry_runtime_adapter_slo_threshold_breach")).not.toBeInTheDocument();
    expect(screen.getByText("telemetry_runtime_adapter_recovery_window")).toBeInTheDocument();
  });

  it("calls acknowledge and resolve actions", async () => {
    const user = userEvent.setup();
    render(<ReliabilityPage />);

    await user.click(screen.getAllByRole("button", { name: "Acknowledge" })[0]);
    expect(mockAcknowledgeMutateAsync).toHaveBeenCalledWith("00000000-0000-0000-0000-000000000101");

    await user.click(screen.getAllByRole("button", { name: "Resolve" })[0]);
    expect(mockResolveMutateAsync).toHaveBeenCalledWith("00000000-0000-0000-0000-000000000101");
  });
});
