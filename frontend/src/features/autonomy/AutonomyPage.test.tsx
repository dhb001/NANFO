import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AutonomyPage } from "./AutonomyPage";
import { getAutonomy, stopAutonomy, updateAutonomy } from "./api";
import { autonomyFixture, decisionFixture, readyProvidersFixture } from "./fixtures";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";
import { ApiClientError } from "@/shared/lib/errors";
import { getModelDiagnostics, diagnoseModel } from "./modelApi";
import { modelFixture, modelRecordFixture } from "./operatorFixtures";

vi.mock("./api", () => ({ getAutonomy: vi.fn(), stopAutonomy: vi.fn(), updateAutonomy: vi.fn() }));
vi.mock("./modelApi", () => ({ getModelDiagnostics: vi.fn(), diagnoseModel: vi.fn() }));

describe("governed autonomy operator page", () => {
  let client: QueryClient;
  const initial = autonomyFixture();
  const read = vi.mocked(getAutonomy);
  const stop = vi.mocked(stopAutonomy);
  const update = vi.mocked(updateAutonomy);
  const ready = () => autonomyFixture({ ready: true, blocked_reasons: [], providers: readyProvidersFixture() });
  function mount() {
    return render(<QueryClientProvider client={client}><MemoryRouter><AutonomyPage /></MemoryRouter></QueryClientProvider>);
  }
  async function loaded() {
    await waitFor(() => expect(screen.getByRole("button", { name: "Apply configuration" })).toBeEnabled());
  }
  beforeEach(() => {
    vi.clearAllMocks();
    client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    useAuthStore.setState({ accessToken: "token", generation: 1, endingSession: false,
      profile: { ...operatorProfile, permissions: [...operatorProfile.permissions, "execute:rollback"] } });
    useWorkspaceStore.setState({ organizationId: "org", workspaceId: initial.workspace_id, networkId: initial.network_id });
    read.mockResolvedValue(initial);
    stop.mockResolvedValue(autonomyFixture({ emergency_stopped: true, cancellation_status: "requested" }));
    update.mockResolvedValue(initial);
  });
  afterEach(() => { client.clear(); focusManager.setFocused(undefined); vi.useRealTimers(); });

  it("defaults to monitor, shows every gate and empty evidence without claiming readiness", async () => {
    mount();
    await loaded();
    expect(screen.getByLabelText("Requested mode")).toHaveValue("monitor");
    expect(screen.getByLabelText("Checkpoint SHA-256")).toHaveValue("");
    expect(screen.getByTestId("autonomy-mode")).toHaveTextContent("monitor");
    expect(screen.getByRole("option", { name: "Autonomous (unavailable)" })).toBeDisabled();
    for (const reason of initial.blocked_reasons) expect(screen.getByText(reason, { selector: "code" })).toBeInTheDocument();
    expect(screen.getByText("Online learning disabled")).toBeInTheDocument();
    expect(screen.getByText(/No decisions reported/)).toBeInTheDocument();
    expect(screen.getByText(/No observation reported/)).toBeInTheDocument();
    expect(screen.getByText(/not a global or continuous-time stability proof/)).toBeInTheDocument();
    expect(update).not.toHaveBeenCalled();
  });

  it("does not request status with missing scope or denied read permission", () => {
    useWorkspaceStore.setState({ networkId: null });
    mount();
    expect(screen.getByText("Select a network")).toBeInTheDocument();
    expect(read).not.toHaveBeenCalled();
    act(() => useAuthStore.setState({ profile: { ...operatorProfile, permissions: [] } }));
    expect(screen.getByText("Permission denied")).toBeInTheDocument();
    expect(read).not.toHaveBeenCalled();
  });

  it.each(["write:config", "execute:rollback"])("requires %s for changes and stop", async (missing) => {
    useAuthStore.setState({ profile: { ...operatorProfile, permissions: ["read:telemetry", "write:config", "execute:rollback"].filter((value) => value !== missing) } });
    mount();
    await screen.findByTestId("autonomy-mode");
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Emergency stop" })).toBeDisabled();
    expect(screen.getByText(/Read-only: changes and stop require/)).toBeInTheDocument();
    expect(update).not.toHaveBeenCalled();
    expect(stop).not.toHaveBeenCalled();
  });

  it("keeps mode authoritative during recommendation save and after autonomous rejection", async () => {
    read.mockResolvedValue(ready());
    let resolveUpdate!: (value: typeof initial) => void;
    update.mockImplementationOnce(() => new Promise((resolve) => { resolveUpdate = resolve; }));
    mount();
    await loaded();
    await userEvent.selectOptions(screen.getByLabelText("Requested mode"), "recommend");
    await userEvent.click(screen.getByRole("button", { name: "Apply configuration" }));
    expect(screen.getByTestId("autonomy-mode")).toHaveTextContent("monitor");
    expect(update).toHaveBeenCalledWith("token", initial.workspace_id, {
      network_id: initial.network_id, expected_revision: initial.revision, mode: "recommend", checkpoint_sha256: null, approval_expires_at: null,
    });
    await act(async () => resolveUpdate(ready()));
    await loaded();
    await userEvent.selectOptions(screen.getByLabelText("Requested mode"), "autonomous");
    fireEvent.change(screen.getByLabelText("Checkpoint SHA-256"), { target: { value: "a".repeat(64) } });
    const expiry = new Date(Date.now() + 1_800_000);
    const localExpiry = new Date(expiry.getTime() - expiry.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
    fireEvent.change(screen.getByLabelText("Approval expiry (local time)"), { target: { value: localExpiry } });
    update.mockRejectedValueOnce(new ApiClientError("autonomous_executor_unavailable", "AUTONOMY_NOT_READY", 409));
    await userEvent.click(screen.getByRole("button", { name: "Apply configuration" }));
    expect(await screen.findByText(/Mode change not confirmed.*autonomous_executor_unavailable/)).toBeInTheDocument();
    expect(screen.getByTestId("autonomy-mode")).toHaveTextContent("monitor");
  });

  it("stops immediately even during failed status reads and never fakes a latch on mutation failure", async () => {
    read.mockRejectedValue(new Error("Status offline"));
    stop.mockRejectedValueOnce(new Error("Stop response lost"));
    mount();
    await screen.findByText("Autonomy status unavailable");
    await userEvent.click(screen.getByRole("button", { name: "Emergency stop" }));
    expect(await screen.findByText(/Stop failed: latch unconfirmed.*Stop response lost/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(stop).toHaveBeenCalledWith("token", initial.network_id, initial.workspace_id);
    await userEvent.click(screen.getByRole("button", { name: "Emergency stop" }));
    expect(await screen.findByText(/Backend confirmed the emergency latch. Cancellation: requested/)).toBeInTheDocument();
    expect(screen.getByText(/A latch is not proof of verified cancellation/)).toBeInTheDocument();
  });

  it("does not infer a latch from HTTP success when emergency_stopped is false", async () => {
    stop.mockResolvedValueOnce(initial);
    mount();
    await loaded();
    await userEvent.click(screen.getByRole("button", { name: "Emergency stop" }));
    expect(await screen.findByText(/Stop response received, but latch unconfirmed/)).toBeInTheDocument();
  });

  it("waits for the stop response and keeps acknowledged cancellation distinct from verification", async () => {
    let resolveStop!: (value: typeof initial) => void;
    stop.mockImplementationOnce(() => new Promise((resolve) => { resolveStop = resolve; }));
    mount();
    await loaded();
    await userEvent.click(screen.getByRole("button", { name: "Emergency stop" }));
    expect(screen.getByText(/Stop requested. Latch unconfirmed/)).toBeInTheDocument();
    expect(screen.queryByText(/Backend confirmed the emergency latch/)).not.toBeInTheDocument();
    expect(screen.getByText(/Last reported latch/)).toHaveTextContent("not latched");
    const stopped = autonomyFixture({ emergency_stopped: true, cancellation_status: "uncertain", active_execution_id: "owned-execution" });
    read.mockResolvedValue(stopped);
    await act(async () => resolveStop(stopped));
    expect(await screen.findByText(/Backend confirmed the emergency latch. Cancellation: uncertain/)).toBeInTheDocument();
    expect(screen.getByText("owned-execution")).toBeInTheDocument();
  });

  it("renders persisted conditional evidence and unresolved execution as read-only history", async () => {
    const decision = decisionFixture({ status: "uncertain", execution_id: "owned-execution", reasons: ["execution_unresolved"],
      safety: { admissible: true, action_id: "route-1", model_version: "test-bounds", reasons: [], evidence: ["test-only bounds"] },
      verification: { execution_id: "owned-execution", status: "pending", safe_to_release: false, reasons: ["awaiting_verified_cancellation"], evidence: [] },
    });
    read.mockResolvedValue(autonomyFixture({ last_decision: decision, decisions: [decision] }));
    mount();
    await loaded();
    expect(screen.getByText(/Execution: owned-execution. Verification: pending/)).toBeInTheDocument();
    expect(screen.getByText(/conditionally admissible/)).toBeInTheDocument();
    await userEvent.click(screen.getByText("Decision evidence and conditional assessment"));
    expect(screen.getByText(/"safe_to_release": false/)).toBeInTheDocument();
    expect(update).not.toHaveBeenCalled();
    expect(stop).not.toHaveBeenCalled();
  });

  it("allows emergency stop during a pending mode update and suppresses its late success notice", async () => {
    let resolveUpdate!: (value: typeof initial) => void;
    update.mockImplementationOnce(() => new Promise((resolve) => { resolveUpdate = resolve; }));
    mount();
    await loaded();
    await userEvent.click(screen.getByRole("button", { name: "Apply configuration" }));
    expect(screen.getByRole("button", { name: "Emergency stop" })).toBeEnabled();
    const stopped = autonomyFixture({ revision: 1, emergency_stopped: true, status: "stopped" });
    stop.mockResolvedValue(stopped);
    read.mockResolvedValue(stopped);
    await userEvent.click(screen.getByRole("button", { name: "Emergency stop" }));
    await act(async () => resolveUpdate(initial));
    expect(screen.queryByText(/Configuration response received/)).not.toBeInTheDocument();
    expect(screen.getByText(/Backend confirmed the emergency latch/)).toBeInTheDocument();
    expect(screen.getByText(/Last reported latch/)).not.toHaveTextContent("not latched");
  });

  it("retains a newer acknowledged stop after old PUT 409 and uses its revision only on fresh explicit submission", async () => {
    let rejectUpdate!: (error: Error) => void;
    read.mockResolvedValue(autonomyFixture({ revision: 7 }));
    update.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectUpdate = reject; }));
    mount();
    await loaded();
    await userEvent.selectOptions(screen.getByLabelText("Requested mode"), "recommend");
    await userEvent.click(screen.getByRole("button", { name: "Apply configuration" }));
    expect(update.mock.calls[0][2].expected_revision).toBe(7);
    const stopped = autonomyFixture({ revision: 8, emergency_stopped: true, status: "stopped" });
    stop.mockResolvedValue(stopped);
    read.mockResolvedValue(stopped);
    await userEvent.click(screen.getByRole("button", { name: "Emergency stop" }));
    await screen.findByText(/Backend confirmed the emergency latch/);
    const readsBeforeConflict = read.mock.calls.length;
    await act(async () => rejectUpdate(new ApiClientError("Control revision changed", "AUTONOMY_REVISION_CONFLICT", 409)));
    await loaded();
    expect(read.mock.calls.length).toBeGreaterThan(readsBeforeConflict);
    expect(screen.getByText(/Last reported latch/)).toHaveTextContent("latched");
    expect(screen.getByTestId("autonomy-mode")).toHaveTextContent("monitor");
    expect(screen.getByText(/No automatic retry or reapproval/)).toBeInTheDocument();
    expect(update).toHaveBeenCalledTimes(1);
    const changed = autonomyFixture({ revision: 9, mode: "recommend" });
    update.mockResolvedValue(changed);
    read.mockResolvedValue(changed);
    await userEvent.click(screen.getByRole("button", { name: "Apply configuration" }));
    await loaded();
    expect(update).toHaveBeenCalledTimes(2);
    expect(update.mock.calls[1][2]).toMatchObject({ expected_revision: 8, mode: "recommend" });
    expect(screen.getByTestId("autonomy-mode")).toHaveTextContent("recommend");
    expect(screen.getByText(/Last reported latch/)).toHaveTextContent("not latched");
  });

  it("keeps a server-acknowledged stop when subsequent reads return an older revision", async () => {
    mount();
    await loaded();
    stop.mockResolvedValue(autonomyFixture({ revision: 1, emergency_stopped: true, status: "stopped" }));
    await userEvent.click(screen.getByRole("button", { name: "Emergency stop" }));
    await screen.findByText("Autonomy status unavailable");
    expect(screen.getByText(/Last reported latch/)).toHaveTextContent("latched");
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Emergency stop" })).toBeEnabled();
  });

  it("marks cached status stale on refetch failure and keeps stop usable", async () => {
    read.mockResolvedValue(ready());
    mount();
    await loaded();
    read.mockRejectedValueOnce(new Error("Read failed"));
    await userEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    await screen.findByText("Autonomy status unavailable");
    expect(screen.getByText(/Status is stale or refreshing/)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Autonomous (unavailable)" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Emergency stop" })).toBeEnabled();
    expect(screen.getByText("Last-known mode")).toBeInTheDocument();
  });

  it("expires readiness after 30 seconds without a new response", async () => {
    vi.useFakeTimers();
    focusManager.setFocused(false);
    read.mockResolvedValue(ready());
    mount();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeEnabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(31_000); });
    expect(read).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
    expect(screen.getByRole("option", { name: "Autonomous (unavailable)" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Emergency stop" })).toBeEnabled();
  });

  it("cleans draft, status and late mutation notices on network switch", async () => {
    let resolveStop!: (value: typeof initial) => void;
    stop.mockImplementationOnce(() => new Promise((resolve) => { resolveStop = resolve; }));
    mount();
    await loaded();
    await userEvent.type(screen.getByLabelText("Checkpoint SHA-256"), "a".repeat(64));
    await userEvent.click(screen.getByRole("button", { name: "Emergency stop" }));
    read.mockImplementationOnce(() => new Promise(() => {}));
    act(() => useWorkspaceStore.setState({ networkId: "new-network" }));
    expect(screen.getByLabelText("Checkpoint SHA-256")).toHaveValue("");
    expect(screen.queryByTestId("autonomy-mode")).not.toBeInTheDocument();
    await act(async () => resolveStop(autonomyFixture({ emergency_stopped: true })));
    expect(screen.queryByText(/Backend confirmed the emergency latch/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Stop requested/)).not.toBeInTheDocument();
  });
  it("clears operator panel selection and late inference results when the network scope changes", async () => {
    vi.mocked(getModelDiagnostics).mockResolvedValue(modelFixture());
    let resolve!: (value: ReturnType<typeof modelRecordFixture>) => void;
    vi.mocked(diagnoseModel).mockImplementation(() => new Promise((done) => { resolve = done; }));
    mount(); await loaded();
    await userEvent.click(screen.getByRole("button", { name: "Model diagnostics" }));
    await userEvent.selectOptions(await screen.findByLabelText("Operator history reference"), "measured-history-1");
    await userEvent.click(screen.getByRole("button", { name: "Run historical inference" }));
    act(() => useWorkspaceStore.setState({ networkId: "00000000-0000-0000-0000-000000000334" }));
    await act(async () => resolve(modelRecordFixture()));
    expect(screen.queryByLabelText("Operator history reference")).not.toBeInTheDocument();
    expect(screen.queryByText(/Recorded diagnostic 10000000/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Status and decisions" })).toHaveAttribute("aria-pressed", "true");
  });
});
