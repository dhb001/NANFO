import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IntentPage } from "@/features/intent/IntentPage";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useLiveStore } from "@/features/realtime/store";
import { useUiStore } from "@/shared/state/ui-store";
import { useExecutionModeStore } from "@/shared/state/execution-mode-store";

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

const validatedDetail = {
  intent_id: "lab-intent", workspace_id: "00000000-0000-0000-0000-000000000222",
  status: "validated", validation_result: {}, execution_provenance: {}, explainability: {},
  intent_payload: { action: "reroute_path" },
  confidence: { score: 0, band: "unavailable", approval_required: true },
  idempotency_key: "persisted-key",
};

function authorizeLab() {
  useExecutionModeStore.getState().observe("emulation");
  useAuthStore.setState({ profile: { ...operatorProfile, permissions: [...operatorProfile.permissions, "execute:rollback"] } });
  mockUseIntentDetail.mockReturnValue(detailQuery(validatedDetail));
}

describe("IntentPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useExecutionModeStore.getState().reset();
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
    authorizeLab();
    mockExecuteAsync.mockResolvedValueOnce({ status: "execution_failed", queue_status: "blocked",
      warning: "Lab executor unavailable", idempotent_replay: false });
    render(<IntentPage />);
    await userEvent.type(screen.getByPlaceholderText("Intent ID"), "lab-intent");
    await userEvent.click(screen.getByRole("checkbox", { name: /explicitly approve/ }));
    await userEvent.click(screen.getByRole("button", { name: "Execute" }));
    expect(useUiStore.getState().toasts.at(-1)).toMatchObject({ title: "Execution failed", tone: "danger" });
    expect(useUiStore.getState().toasts.at(-1)?.description).toContain("Lab executor unavailable");
  });

  it("requires explicit approval and retries a lost response with the same request identity", async () => {
    authorizeLab();
    mockExecuteAsync.mockRejectedValueOnce(new Error("Connection lost")).mockResolvedValueOnce({ status: "execution_started", queue_status: "queued" });
    render(<IntentPage />);
    await userEvent.type(screen.getByLabelText("Intent ID"), "lab-intent");
    await userEvent.click(screen.getByRole("button", { name: "Execute" }));
    expect(mockExecuteAsync).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("checkbox", { name: /explicitly approve/ }));
    await userEvent.click(screen.getByRole("button", { name: "Execute" }));
    expect(screen.getByText(/Request outcome unknown/)).toBeInTheDocument();
    expect(screen.getByLabelText("Idempotency Key")).toBeDisabled();
    const first = mockExecuteAsync.mock.calls[0][0];
    expect(first.request).toMatchObject({ manual_approval: true, cancel: false, intent_id: "lab-intent" });
    expect(first.idempotencyKey).toBe(first.request.idempotency_key);
    await userEvent.click(screen.getByRole("button", { name: "Execute" }));
    expect(mockExecuteAsync.mock.calls[1][0]).toEqual(first);
    expect(screen.getByText(/Execution accepted, not completed/)).toBeInTheDocument();
    expect(screen.queryByText("Execution Completed")).not.toBeInTheDocument();
  });

  it("cancels an in-flight execution through the same route and identity without auto approval", async () => {
    authorizeLab();
    mockUseIntentDetail.mockReturnValue(detailQuery({ ...validatedDetail, status: "execution_started", execution_provenance: { execution_id: "job-1", phase: "dispatching" } }));
    mockExecuteAsync.mockResolvedValue({ status: "execution_started", queue_status: "queued" });
    render(<IntentPage />);
    await userEvent.type(screen.getByLabelText("Intent ID"), "lab-intent");
    expect(screen.getByRole("checkbox", { name: /explicitly approve/ })).not.toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Cancel execution" }));
    expect(mockExecuteAsync).toHaveBeenCalledWith({
      request: { workspace_id: validatedDetail.workspace_id, intent_id: "lab-intent", idempotency_key: "persisted-key", manual_approval: false, cancel: true },
      idempotencyKey: "persisted-key",
    });
    expect(screen.getByText(/Cancellation requested. Reconciliation/)).toBeInTheDocument();
    expect(screen.getByText("execution_id: job-1")).toBeInTheDocument();
  });

  it("compensates a completed policy with the persisted identity and displays verified rollback", async () => {
    authorizeLab();
    mockUseIntentDetail.mockReturnValue(detailQuery({ ...validatedDetail, status: "execution_completed",
      intent_payload: { action: "throttle_qos", constraints: { operation: "police" } },
      execution_provenance: { execution_id: "job-1", phase: "completed", verification: {
        readback_verified: true, readback_sha256: "a".repeat(64), probe: { sent: 3, received: 3 },
      } },
    }));
    mockExecuteAsync.mockResolvedValue({ status: "execution_started", queue_status: "outbox_pending" });
    const { rerender } = render(<IntentPage />);
    await userEvent.type(screen.getByLabelText("Intent ID"), "lab-intent");
    expect(screen.getByRole("button", { name: "Execute" })).toBeDisabled();
    expect(screen.getByText("verification readback verified")).toBeInTheDocument();
    expect(screen.getByText("completion_scope: config_readback_and_reachability")).toBeInTheDocument();
    expect(screen.getByText("Reachability probe: 3/3 received")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel execution" }));
    expect(mockExecuteAsync).toHaveBeenCalledWith({ request: { workspace_id: validatedDetail.workspace_id,
      intent_id: "lab-intent", idempotency_key: "persisted-key", cancel: true, manual_approval: false }, idempotencyKey: "persisted-key" });
    expect(screen.getByText(/Cancellation requested. Reconciliation/)).toBeInTheDocument();
    expect(screen.queryByText("rollback verified")).not.toBeInTheDocument();
    mockUseIntentDetail.mockReturnValue(detailQuery({ ...validatedDetail, status: "execution_failed", execution_provenance: {
      execution_id: "job-1", phase: "cancelled", rollback: { verified: true, readback_sha256: "b".repeat(64) },
    } }));
    rerender(<IntentPage />);
    expect(screen.getByText("rollback verified")).toBeInTheDocument();
    expect(screen.getByText(`rollback.readback_sha256: ${"b".repeat(64)}`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel execution" })).toBeDisabled();
    expect(screen.queryByText("Execution outcome uncertain")).not.toBeInTheDocument();
  });

  it("renders safe no-mutation failure without claiming execution or rollback", () => {
    mockUseIntentDetail.mockReturnValue(detailQuery({ ...validatedDetail, status: "execution_failed", execution_provenance: {
      phase: "failed", failure_reason: "deadline_before_dispatch", verification: { no_mutation_verified: true }, rollback: null,
    } }));
    render(<IntentPage />);
    expect(screen.getByText(/No mutation verified by the backend/)).toBeInTheDocument();
    expect(screen.getByText("Execution Failed")).toBeInTheDocument();
    expect(screen.getByText("completion_scope: Not reported")).toBeInTheDocument();
    expect(screen.queryByText("rollback verified")).not.toBeInTheDocument();
    expect(screen.queryByText("Execution Completed")).not.toBeInTheDocument();
  });

  it.each(["demo", "production", null] as const)("keeps %s mode non-actuating regardless of confidence", async (mode) => {
    authorizeLab();
    useExecutionModeStore.setState({ mode });
    render(<IntentPage />);
    await userEvent.type(screen.getByLabelText("Intent ID"), "lab-intent");
    expect(screen.getByRole("button", { name: "Execute" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel execution" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Validate" })).toBeEnabled();
    expect(mockExecuteAsync).not.toHaveBeenCalled();
  });

  it.each(["write:config", "execute:rollback"])("requires %s for execute and cancellation", async (missing) => {
    authorizeLab();
    useAuthStore.setState({ profile: { ...operatorProfile, permissions: ["write:config", "execute:rollback"].filter((p) => p !== missing) } });
    mockUseIntentDetail.mockReturnValue(detailQuery({ ...validatedDetail, status: "execution_started" }));
    render(<IntentPage />);
    await userEvent.type(screen.getByLabelText("Intent ID"), "lab-intent");
    expect(screen.getByRole("button", { name: "Execute" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel execution" })).toBeDisabled();
  });

  it("builds guided lab validation without auto approval", async () => {
    authorizeLab();
    mockValidateAsync.mockResolvedValue({ intent_id: "lab-intent", status: "validated", confidence: validatedDetail.confidence });
    render(<IntentPage />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Guided manual lab action" }));
    await userEvent.selectOptions(screen.getByLabelText("Operation"), "police");
    await userEvent.selectOptions(screen.getByLabelText("Destination host"), "h4");
    await userEvent.type(screen.getByLabelText("Rate (Mbps)"), "10");
    await userEvent.type(screen.getByLabelText("DSCP (optional classifier)"), "0");
    await userEvent.click(screen.getByRole("button", { name: "Validate" }));
    expect(mockValidateAsync.mock.calls[0][0].request.intent).toEqual({
      action: "throttle_qos", scope: { source_host: "h1", destination_host: "h4" },
      constraints: { operation: "police", paths: [], rate_mbps: 10, dscp: 0 },
    });
    expect(screen.getByRole("checkbox", { name: /explicitly approve/ })).not.toBeChecked();
    expect(mockExecuteAsync).not.toHaveBeenCalled();
  });

  it("keeps unsupported advanced actions validation-only even in emulation", async () => {
    authorizeLab();
    mockUseIntentDetail.mockReturnValue(detailQuery({ ...validatedDetail, intent_payload: { action: "isolate_vlan" } }));
    render(<IntentPage />);
    await userEvent.type(screen.getByLabelText("Intent ID"), "lab-intent");
    expect(screen.getByRole("checkbox", { name: /explicitly approve/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Execute" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Validate" })).toBeEnabled();
  });

  it("separates verified completion from uncertain failure and exposes provenance", () => {
    mockUseIntentDetail.mockReturnValue(detailQuery({ ...validatedDetail, status: "execution_completed", execution_provenance: { execution_id: "job-1", phase: "completed", verification: { status: "passed" } } }));
    const { rerender } = render(<IntentPage />);
    expect(screen.getByText("Execution Completed")).toBeInTheDocument();
    expect(screen.getByText("verification passed")).toBeInTheDocument();
    mockUseIntentDetail.mockReturnValue(detailQuery({ ...validatedDetail, status: "execution_failed", execution_provenance: { execution_id: "job-1", phase: "uncertain", deadline: "2026-09-09T12:00:00Z", verification: { status: "uncertain" }, rollback: { status: "failed" }, failure_reason: "Lost readback" } }));
    rerender(<IntentPage />);
    expect(screen.getByText("Execution outcome uncertain")).toBeInTheDocument();
    expect(screen.getByText("deadline: 2026-09-09T12:00:00Z")).toBeInTheDocument();
    expect(screen.queryByText("Execution Completed")).not.toBeInTheDocument();
  });

  it("revokes local approval when permissions or workspace context change", async () => {
    authorizeLab();
    render(<IntentPage />);
    await userEvent.type(screen.getByLabelText("Intent ID"), "lab-intent");
    await userEvent.click(screen.getByRole("checkbox", { name: /explicitly approve/ }));
    expect(screen.getByRole("button", { name: "Execute" })).toBeEnabled();
    act(() => useAuthStore.setState({ profile: operatorProfile }));
    expect(screen.getByRole("checkbox", { name: /explicitly approve/ })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Execute" })).toBeDisabled();
    act(() => useWorkspaceStore.setState({ workspaceId: "another-workspace" }));
    expect(screen.getByLabelText("Intent ID")).toHaveValue("");
    expect(mockExecuteAsync).not.toHaveBeenCalled();
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
