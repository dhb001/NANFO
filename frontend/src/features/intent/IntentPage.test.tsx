import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactElement, ReactNode } from "react";
import { act, render as rtlRender, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { IntentPage } from "@/features/intent/IntentPage";
import { intentHandoffState } from "@/features/intent/handoff";
import { ApiClientError } from "@/shared/lib/errors";
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
  useIntentHistory: () => ({ data: { items: [], total: 0, page: 1, page_size: 20 } }),
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

// The page reads router state (Digital Twin handoff), so it renders inside a router.
const render = (ui: ReactElement) => rtlRender(ui, { wrapper: ({ children }: { children: ReactNode }) => <MemoryRouter>{children}</MemoryRouter> });

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

  it("shows the exact backend status with an explicit tone and never an invented alias (ADR-028)", () => {
    mockUseIntentDetail.mockReturnValue(detailQuery({ ...validatedDetail, status: "execution_compensated", queue_status: "outbox_pending",
      confidence: { score: 0.97, band: "95-100", approval_required: false } }));
    const { unmount } = render(<IntentPage />);
    expect(screen.getByText("execution_compensated")).toHaveClass("badge--warn");
    expect(screen.getByText("confidence 95-100")).toHaveClass("badge--ok");
    expect(screen.getByText("outbox_pending")).toHaveClass("badge--info");
    unmount();
    // "completed" is not a backend intent status: shown verbatim and neutral, not as execution_completed.
    mockUseIntentDetail.mockReturnValue(detailQuery({ ...validatedDetail, status: "completed", queue_status: "queued" }));
    render(<IntentPage />);
    expect(screen.getByText("completed")).toHaveClass("badge--neutral");
    expect(screen.queryByText("execution_completed")).not.toBeInTheDocument();
    expect(screen.getByText("confidence unavailable")).toHaveClass("badge--neutral");
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
    expect(screen.getByLabelText("Execution idempotency key")).toHaveAttribute("readonly");
    const first = mockExecuteAsync.mock.calls[0][0];
    expect(first.request).toMatchObject({ manual_approval: true, cancel: false, intent_id: "lab-intent", idempotency_key: "persisted-key" });
    expect(first.request).not.toHaveProperty("simulation_id");
    expect(first.idempotencyKey).toBe(first.request.idempotency_key);
    act(() => useAuthStore.getState().replaceTokens({ accessToken: "rotated", refreshToken: "rotated-refresh" }));
    expect(screen.getByLabelText("Intent ID")).toHaveValue("lab-intent");
    expect(screen.getByLabelText("Execution idempotency key")).toHaveValue(first.idempotencyKey);
    expect(screen.getByRole("checkbox", { name: /explicitly approve/ })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Execute" }));
    expect(mockExecuteAsync.mock.calls[1][0]).toEqual(first);
    expect(screen.getByText(/Execution accepted, not completed/)).toBeInTheDocument();
    expect(screen.queryByText("Execution Completed")).not.toBeInTheDocument();
  });
  it("retains drafts and immutable pending execution through rotation, revoking approval on authority change", async () => {
    authorizeLab();
    let finish!: (value: unknown) => void;
    mockExecuteAsync.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    render(<IntentPage />);
    await userEvent.type(screen.getByLabelText("Intent ID"), "lab-intent");
    await userEvent.clear(screen.getByLabelText("Scope JSON"));
    await userEvent.type(screen.getByLabelText("Scope JSON"), "draft in progress");
    await userEvent.click(screen.getByRole("checkbox", { name: /explicitly approve/ }));
    await userEvent.click(screen.getByRole("button", { name: "Execute" }));
    const request = mockExecuteAsync.mock.calls[0][0];
    act(() => useAuthStore.getState().replaceTokens({ accessToken: "rotated", refreshToken: "new-refresh" }));
    expect(screen.getByLabelText("Scope JSON")).toHaveValue("draft in progress");
    expect(screen.getByLabelText("Execution idempotency key")).toHaveValue(request.idempotencyKey);
    await act(async () => finish({ status: "execution_started", queue_status: "queued" }));
    expect(screen.getByText(/Execution accepted, not completed/)).toBeInTheDocument();
    act(() => useAuthStore.getState().setProfile({ ...useAuthStore.getState().profile!, roles: ["Admin"] }));
    expect(screen.getByRole("checkbox", { name: /explicitly approve/ })).not.toBeChecked();
    expect(screen.getByLabelText("Scope JSON")).toHaveValue("draft in progress");
    expect(screen.getByLabelText("Execution idempotency key")).toHaveValue(request.idempotencyKey);
    expect(mockExecuteAsync).toHaveBeenCalledTimes(1);
  });
  it("sends only an explicit valid simulation UUID, preserves it on retry, and omits it for cancel", async () => {
    authorizeLab();
    mockExecuteAsync.mockRejectedValueOnce(new Error("lost response")).mockResolvedValue({ status: "execution_started", queue_status: "pending" });
    render(<IntentPage />);
    await userEvent.type(screen.getByLabelText("Intent ID"), "lab-intent");
    const input = screen.getByLabelText("Referenced simulation UUID");
    await userEvent.type(input, "invalid");
    await userEvent.click(screen.getByRole("checkbox", { name: /explicitly approve/ }));
    expect(screen.getByRole("button", { name: "Execute" })).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "00000000-0000-0000-0000-000000000701");
    expect(screen.getByRole("checkbox", { name: /explicitly approve/ })).not.toBeChecked();
    await userEvent.click(screen.getByRole("checkbox", { name: /explicitly approve/ }));
    await userEvent.click(screen.getByRole("button", { name: "Execute" }));
    expect(input).toBeDisabled();
    expect(mockExecuteAsync.mock.calls[0][0].request.simulation_id).toBe("00000000-0000-0000-0000-000000000701");
    expect(mockExecuteAsync.mock.calls[0][0].request).not.toHaveProperty("action_binding");
    await userEvent.click(screen.getByRole("button", { name: "Execute" }));
    expect(mockExecuteAsync.mock.calls[1][0]).toEqual(mockExecuteAsync.mock.calls[0][0]);
    await userEvent.click(screen.getByRole("button", { name: "Cancel execution" }));
    expect(mockExecuteAsync.mock.calls[2][0].request.cancel).toBe(true);
    expect(mockExecuteAsync.mock.calls[2][0].request).not.toHaveProperty("simulation_id");
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

  it("marks a URL-prefilled intent form as untrusted and strips the link parameters", () => {
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
    // URL content can be crafted by anyone: it is marked untrusted, never presented as the Twin's own handoff.
    expect(screen.getByRole("alert")).toHaveTextContent("Prefilled from a link (untrusted)");
    expect(screen.getByRole("alert")).toHaveTextContent("Link summary (unverified): device=edge-1");
    expect(screen.queryByText(/^Prefilled from Digital Twin:/)).not.toBeInTheDocument();
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

  describe("ADR-028 C3 identities, bindings and conflicts", () => {
    const binding = { plan_hash: "a".repeat(64), binding_digest: "b".repeat(64), run_id: "00000000-0000-0000-0000-00000000c0de" };
    const validated = (overrides: Record<string, unknown> = {}) => ({
      intent_id: "lab-intent", workspace_id: "00000000-0000-0000-0000-000000000222", network_id: "00000000-0000-0000-0000-000000000333",
      status: "validated", confidence: { score: 0, band: "below_60", approval_required: true }, idempotency_key: "k", idempotent_replay: false,
      validation: { validation_kind: "baseline_schema_only" }, ...overrides,
    });

    it("uses a fresh validation key per submission and reuses it only to retry an unconfirmed submission of the same draft", async () => {
      authorizeLab();
      mockValidateAsync
        .mockRejectedValueOnce(new ApiClientError("The request timed out.", "API_TIMEOUT", 0))
        .mockResolvedValueOnce(validated({ idempotent_replay: true }))
        .mockResolvedValueOnce(validated());
      render(<IntentPage />);
      await userEvent.click(screen.getByRole("button", { name: "Validate" }));
      expect(screen.getByLabelText("Validation request key")).toHaveTextContent(/retries with key intent-/);
      await userEvent.click(screen.getByRole("button", { name: "Validate" }));
      const [first, retry] = mockValidateAsync.mock.calls.map(([input]) => input.idempotencyKey as string);
      expect(first).toMatch(/^intent-/);
      expect(retry).toBe(first);
      expect(useUiStore.getState().toasts.at(-1)).toMatchObject({ title: "Existing intent returned" });
      expect(useUiStore.getState().toasts.at(-1)?.description).toContain("schema-only validation");
      await userEvent.click(screen.getByRole("button", { name: "Validate" }));
      expect(mockValidateAsync.mock.calls[2][0].idempotencyKey).not.toBe(first);
      expect(screen.getByLabelText("Validation request key")).toHaveTextContent("Each Validate submission uses a new request key.");
    });

    it("mints a new key after the draft changes, another intent is selected, or the key was reused elsewhere", async () => {
      authorizeLab();
      mockValidateAsync
        .mockRejectedValueOnce(new Error("Connection lost"))
        .mockRejectedValueOnce(new Error("Connection lost"))
        .mockRejectedValueOnce(new ApiClientError("Idempotency-Key already identifies a different intent submission", "IDEMPOTENCY_KEY_REUSED", 409))
        .mockResolvedValueOnce(validated());
      render(<IntentPage />);
      await userEvent.click(screen.getByRole("button", { name: "Validate" }));
      await userEvent.type(screen.getByLabelText("Constraints JSON"), " ");
      await userEvent.click(screen.getByRole("button", { name: "Validate" }));
      await userEvent.type(screen.getByLabelText("Intent ID"), "x");
      await userEvent.click(screen.getByRole("button", { name: "Validate" }));
      expect(screen.getByRole("alert")).toHaveTextContent("Request key already used (IDEMPOTENCY_KEY_REUSED)");
      await userEvent.click(screen.getByRole("button", { name: "Validate" }));
      const keys = mockValidateAsync.mock.calls.map(([input]) => input.idempotencyKey);
      expect(new Set(keys).size).toBe(4);
    });

    it("executes with the selected intent's stored key and the detail's current approval binding", async () => {
      authorizeLab();
      mockUseIntentDetail.mockReturnValue(detailQuery({ ...validatedDetail, approval_binding: binding,
        validation_result: { validation_kind: "manual_lab_plan", simulation_required: false } }));
      mockExecuteAsync.mockResolvedValue({ status: "execution_started", queue_status: "queued" });
      render(<IntentPage />);
      await userEvent.type(screen.getByLabelText("Intent ID"), "lab-intent");
      expect(screen.getByLabelText("Execution idempotency key")).toHaveValue("persisted-key");
      expect(screen.getByText(`plan_hash: ${binding.plan_hash}`)).toBeInTheDocument();
      expect(screen.getByText(/Validated against the trusted manual lab plan/)).toBeInTheDocument();
      await userEvent.click(screen.getByRole("checkbox", { name: /explicitly approve/ }));
      await userEvent.click(screen.getByRole("button", { name: "Execute" }));
      expect(mockExecuteAsync).toHaveBeenCalledWith({
        request: { workspace_id: validatedDetail.workspace_id, intent_id: "lab-intent", idempotency_key: "persisted-key",
          manual_approval: true, cancel: false, approval_binding: binding },
        idempotencyKey: "persisted-key",
      });
    });

    it("gives a legacy intent without a stored key one stable execution identity", async () => {
      authorizeLab();
      mockUseIntentDetail.mockReturnValue(detailQuery({ ...validatedDetail, idempotency_key: null }));
      mockExecuteAsync.mockRejectedValueOnce(new Error("lost")).mockResolvedValue({ status: "execution_started", queue_status: "queued" });
      render(<IntentPage />);
      await userEvent.type(screen.getByLabelText("Intent ID"), "lab-intent");
      expect(screen.getByText(/No stored key yet/)).toBeInTheDocument();
      await userEvent.click(screen.getByRole("checkbox", { name: /explicitly approve/ }));
      await userEvent.click(screen.getByRole("button", { name: "Execute" }));
      await userEvent.click(screen.getByRole("button", { name: "Execute" }));
      const [first, retry] = mockExecuteAsync.mock.calls.map(([input]) => input.request.idempotency_key);
      expect(first).toMatch(/^intent-exec-/);
      expect(retry).toBe(first);
    });

    it("re-reads the detail and revokes approval on APPROVAL_BINDING_MISMATCH", async () => {
      authorizeLab();
      mockUseIntentDetail.mockReturnValue(detailQuery({ ...validatedDetail, approval_binding: binding }));
      mockExecuteAsync.mockRejectedValueOnce(new ApiClientError("approval_binding must equal the current plan_hash", "APPROVAL_BINDING_MISMATCH", 409));
      render(<IntentPage />);
      await userEvent.type(screen.getByLabelText("Intent ID"), "lab-intent");
      await userEvent.click(screen.getByRole("checkbox", { name: /explicitly approve/ }));
      await userEvent.click(screen.getByRole("button", { name: "Execute" }));
      expect(mockDetailRefetch).toHaveBeenCalled();
      expect(screen.getByRole("alert")).toHaveTextContent("Lab identity changed since approval (APPROVAL_BINDING_MISMATCH)");
      expect(screen.getByRole("checkbox", { name: /explicitly approve/ })).not.toBeChecked();
      expect(screen.queryByText(/Request outcome unknown/)).not.toBeInTheDocument();
      // Refused, so nothing is pinned: the operator can change inputs and approve again.
      expect(screen.getByLabelText("Referenced simulation UUID")).toBeEnabled();
    });

    it.each([
      ["DISTINCT_APPROVER_REQUIRED", "A different approver is required", false],
      ["SIMULATION_REQUIRED", "Simulation required first", false],
      ["SIMULATION_POLICY_VIOLATION", "Simulation limits weaker than policy", false],
      ["SIMULATION_EVIDENCE_REJECTED", "Simulation evidence rejected", false],
      ["INTENT_ALREADY_EXECUTING", "Execution already started", true],
      ["INTENT_IDEMPOTENCY_CONFLICT", "Execution identity conflict", true],
    ] as const)("explains 409 %s without claiming an unknown outcome", async (code, title, refetches) => {
      authorizeLab();
      mockExecuteAsync.mockRejectedValueOnce(new ApiClientError("refused", code, 409));
      render(<IntentPage />);
      await userEvent.type(screen.getByLabelText("Intent ID"), "lab-intent");
      await userEvent.type(screen.getByLabelText("Referenced simulation UUID"), "00000000-0000-0000-0000-000000000701");
      await userEvent.click(screen.getByRole("checkbox", { name: /explicitly approve/ }));
      await userEvent.click(screen.getByRole("button", { name: "Execute" }));
      expect(screen.getByRole("alert")).toHaveTextContent(`${title} (${code})`);
      expect(useUiStore.getState().toasts.at(-1)).toMatchObject({ title, tone: "danger" });
      expect(mockDetailRefetch).toHaveBeenCalledTimes(refetches ? 1 : 0);
      expect(screen.getByRole("checkbox", { name: /explicitly approve/ })).not.toBeChecked();
      expect(screen.getByLabelText("Referenced simulation UUID")).toBeEnabled();
      expect(screen.queryByText(/Request outcome unknown/)).not.toBeInTheDocument();
    });

    it("discloses schema-only validation and the simulation requirement", () => {
      mockUseIntentDetail.mockReturnValue(detailQuery({ ...validatedDetail,
        validation_result: { validation_kind: "baseline_schema_only", model_evidence: "unavailable", simulation_required: true } }));
      render(<IntentPage />);
      expect(screen.getByRole("note", { name: "Validation coverage" })).toHaveTextContent("Schema-only validation.");
      expect(screen.getByRole("note", { name: "Validation coverage" })).toHaveTextContent("model evidence: unavailable");
      expect(screen.getByRole("note", { name: "Validation coverage" })).toHaveTextContent("Simulation required before execution");
      // Lab plan without a binding: the refusal is predicted, not hidden.
      expect(screen.getByText(/No approval binding recorded/)).toBeInTheDocument();
    });

    it("applies a Digital Twin handoff from router state as in-app content, once", async () => {
      const prefill = { source: "digital-twin" as const, action: null, scopeJson: '{"device_id":"d-1"}', constraintsJson: '{"max_downtime":0}', contextSummary: "device=edge-1" };
      const { unmount } = rtlRender(<MemoryRouter initialEntries={[{ pathname: "/ops/intent", state: intentHandoffState(prefill) }]}><IntentPage /></MemoryRouter>);
      expect(screen.getByDisplayValue('{"device_id":"d-1"}')).toBeInTheDocument();
      expect(screen.getByText(/Prefilled from Digital Twin: device=edge-1\. Review every field before validating\./)).toBeInTheDocument();
      expect(screen.queryByText(/untrusted/)).not.toBeInTheDocument();
      expect(screen.getByDisplayValue("reroute_path")).toBeInTheDocument();
      // A workspace switch remounts the form; the handoff belongs to the previous context and is not re-applied.
      act(() => useWorkspaceStore.setState({ workspaceId: "00000000-0000-0000-0000-000000000999" }));
      expect(screen.queryByDisplayValue('{"device_id":"d-1"}')).not.toBeInTheDocument();
      expect(screen.queryByText(/Prefilled from Digital Twin/)).not.toBeInTheDocument();
      unmount();
    });
  });
});
