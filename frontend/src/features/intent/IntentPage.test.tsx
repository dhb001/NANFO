import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IntentPage } from "@/features/intent/IntentPage";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useLiveStore } from "@/features/realtime/store";
import { useUiStore } from "@/shared/state/ui-store";

const mockValidateAsync = vi.fn();
const mockExecuteAsync = vi.fn();
const mockDetailRefetch = vi.fn();
const mockUseIntentDetail = vi.fn();

vi.mock("@/features/intent/hooks", () => ({
  useValidateIntent: () => ({
    mutateAsync: mockValidateAsync,
    isPending: false,
    isError: false,
    error: null,
  }),
  useExecuteIntent: () => ({
    mutateAsync: mockExecuteAsync,
    isPending: false,
    isError: false,
    error: null,
  }),
  useIntentDetail: (...args: unknown[]) => mockUseIntentDetail(...args),
}));

function detailQuery(data: unknown) {
  return {
    isLoading: false,
    isError: false,
    data,
    refetch: mockDetailRefetch,
  };
}

describe("IntentPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState(null, "", "/ops/intent");
    mockUseIntentDetail.mockReturnValue(detailQuery(null));

    useAuthStore.setState({
      profile: operatorProfile,
      accessToken: "token-1",
      refreshToken: "refresh-1",
      userId: "00000000-0000-0000-0000-000000000123",
    });
    useWorkspaceStore.setState({
      organizationId: "00000000-0000-0000-0000-000000000111",
      workspaceId: "00000000-0000-0000-0000-000000000222",
      networkId: "00000000-0000-0000-0000-000000000333",
    });
    useLiveStore.setState({
      sceneObjects: {},
      sceneObjectIdsNewestFirst: [],
      topologyByDeviceId: {},
      telemetryByDeviceMetric: {},
      telemetryKeysNewestFirst: [],
      alerts: [],
      topologyStatus: "closed",
      telemetryStatus: "closed",
      alertsStatus: "closed",
      digitalTwinStatus: "closed",
    });
    useUiStore.setState({
      commandPaletteOpen: false,
      toasts: [],
    });
  });

  it("renders detail empty state panel", () => {
    render(<IntentPage />);
    expect(screen.getByText("Intent Validate and Execute")).toBeInTheDocument();
    expect(screen.getByText("No intent selected")).toBeInTheDocument();
  });

  it("reports failed execution responses without an accepted or completed claim", async () => {
    mockUseIntentDetail.mockReturnValue(detailQuery({
      status: "validated", validation_result: {}, execution_provenance: {}, explainability: {},
      confidence: { score: 0.9, band: "high", approval_required: false },
    }));
    mockExecuteAsync.mockResolvedValueOnce({ status: "execution_failed", queue_status: "blocked",
      warning: "Demo control is not executed", idempotent_replay: false });
    render(<IntentPage />);
    await userEvent.type(screen.getByPlaceholderText("Intent ID"), "demo-intent");
    await userEvent.click(screen.getByRole("button", { name: "Execute" }));
    expect(useUiStore.getState().toasts.at(-1)).toMatchObject({ title: "Execution failed", tone: "danger" });
    expect(useUiStore.getState().toasts.at(-1)?.description).toContain("Demo control is not executed");
  });

  it("prefills intent form from digital twin handoff query params", () => {
    const scope = JSON.stringify({
      source: "digital_twin",
      device_id: "device-1",
      congestion: { severity: "high" },
    });
    const constraints = JSON.stringify({ max_downtime: 0, simulation_required: true });
    const params = new URLSearchParams({
      source: "digital-twin",
      action: "throttle_qos",
      scope,
      constraints,
      context_summary: "device=edge-1 | severity=high | policy=cpu_utilization_percent",
    });
    window.history.replaceState(null, "", `/ops/intent?${params.toString()}`);

    render(<IntentPage />);

    expect(screen.getByDisplayValue("throttle_qos")).toBeInTheDocument();
    expect(screen.getByDisplayValue(scope)).toBeInTheDocument();
    expect(screen.getByDisplayValue(constraints)).toBeInTheDocument();
    expect(screen.getByText(/Prefilled from Digital Twin:/)).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it("shows validation error for malformed JSON and does not submit", async () => {
    const user = userEvent.setup();
    render(<IntentPage />);

    const scopeInput = screen.getByLabelText("Scope JSON");
    await user.clear(scopeInput);
    await user.type(scopeInput, "not-json");
    await user.click(screen.getByRole("button", { name: "Validate" }));

    expect(screen.getByText("Invalid request body")).toBeInTheDocument();
    expect(mockValidateAsync).not.toHaveBeenCalled();
  });

  it("disables execute action when detail status is terminal", async () => {
    const user = userEvent.setup();
    mockUseIntentDetail.mockReturnValue(
      detailQuery({
        intent_id: "00000000-0000-0000-0000-000000000444",
        workspace_id: "00000000-0000-0000-0000-000000000222",
        network_id: "00000000-0000-0000-0000-000000000333",
        status: "execution_completed",
        intent_kind: "reroute_path",
        intent_payload: { action: "reroute_path" },
        validation_result: { validated_at: "2026-08-13T10:00:00Z" },
        execution_provenance: { execution_completed_at: "2026-08-13T10:02:00Z" },
        explainability: { summary: "Completed" },
        confidence: { score: 0.9, band: "high", approval_required: false },
        idempotency_key: "idem-1",
        queue_status: "queued",
        stream_entry_id: "111",
        warning: null,
        correlation_id: "corr-1",
        requested_by_user_id: "00000000-0000-0000-0000-000000000123",
        requested_at: "2026-08-13T10:00:00Z",
        created_at: "2026-08-13T10:00:00Z",
        updated_at: "2026-08-13T10:02:00Z",
      }),
    );

    render(<IntentPage />);

    await user.type(screen.getByPlaceholderText("Intent ID"), "00000000-0000-0000-0000-000000000444");
    expect(screen.getByRole("button", { name: "Execute" })).toBeDisabled();
  });

  it("renders rollback diagnostics and failure state when execution failed", () => {
    mockUseIntentDetail.mockReturnValue(
      detailQuery({
        intent_id: "00000000-0000-0000-0000-000000000444",
        workspace_id: "00000000-0000-0000-0000-000000000222",
        network_id: "00000000-0000-0000-0000-000000000333",
        status: "execution_failed",
        intent_kind: "isolate_vlan",
        intent_payload: { action: "isolate_vlan" },
        validation_result: { validated_at: "2026-08-13T10:00:00Z" },
        execution_provenance: {
          execution_started_at: "2026-08-13T10:01:00Z",
          execution_failed_at: "2026-08-13T10:03:00Z",
          failure_reason: "post_change_verification_failed",
          verification: { status: "failed" },
          rollback: {
            attempted: true,
            status: "completed",
            rollback_reference_id: "rbk-1",
          },
          event_publication: { warning: "event_queue_unavailable" },
        },
        explainability: { summary: "failed" },
        confidence: { score: 0.72, band: "60-79", approval_required: true },
        idempotency_key: "idem-1",
        queue_status: "deferred",
        stream_entry_id: null,
        warning: "event_queue_unavailable",
        correlation_id: "corr-1",
        requested_by_user_id: "00000000-0000-0000-0000-000000000123",
        requested_at: "2026-08-13T10:00:00Z",
        created_at: "2026-08-13T10:00:00Z",
        updated_at: "2026-08-13T10:03:00Z",
      }),
    );

    render(<IntentPage />);

    expect(screen.getByText("rollback_ref: rbk-1")).toBeInTheDocument();
    expect(screen.getByText("failure_reason: post_change_verification_failed")).toBeInTheDocument();
    expect(screen.getByText("Execution failed")).toBeInTheDocument();
  });

  it("refetches intent detail when realtime status changes", async () => {
    const user = userEvent.setup();
    mockUseIntentDetail.mockReturnValue(
      detailQuery({
        intent_id: "00000000-0000-0000-0000-000000000444",
        workspace_id: "00000000-0000-0000-0000-000000000222",
        network_id: "00000000-0000-0000-0000-000000000333",
        status: "execution_started",
        intent_kind: "reroute_path",
        intent_payload: { action: "reroute_path" },
        validation_result: { validated_at: "2026-08-13T10:00:00Z" },
        execution_provenance: { execution_started_at: "2026-08-13T10:01:00Z" },
        explainability: { summary: "Started" },
        confidence: { score: 0.82, band: "high", approval_required: false },
        idempotency_key: "idem-1",
        queue_status: "queued",
        stream_entry_id: "111",
        warning: null,
        correlation_id: "corr-1",
        requested_by_user_id: "00000000-0000-0000-0000-000000000123",
        requested_at: "2026-08-13T10:00:00Z",
        created_at: "2026-08-13T10:00:00Z",
        updated_at: "2026-08-13T10:01:00Z",
      }),
    );

    render(<IntentPage />);
    await user.type(screen.getByPlaceholderText("Intent ID"), "00000000-0000-0000-0000-000000000444");

    await act(async () => {
      useLiveStore.setState({
        sceneObjects: {
          "intent-00000000-0000-0000-0000-000000000444": {
            id: "intent-00000000-0000-0000-0000-000000000444",
            object_type: "intent_state",
            intent_id: "00000000-0000-0000-0000-000000000444",
            status: "execution_completed",
            changed_fields: {},
          },
        },
      });
    });

    await waitFor(() => {
      expect(mockDetailRefetch).toHaveBeenCalled();
    });
  });
});
