import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OverridePanel } from "./OverridePanel";
import { actOnOverride, createOverride, getOverrides } from "./overrideApi";
import { getIntentDetail } from "@/features/intent/api";
import { autonomyFixture } from "./fixtures";
import { overrideFixture, overrideIntentFixture } from "./operatorFixtures";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";
vi.mock("./overrideApi", () => ({ actOnOverride: vi.fn(), createOverride: vi.fn(), getOverrides: vi.fn() }));
vi.mock("@/features/intent/api", () => ({ getIntentDetail: vi.fn() }));
describe("timed override operator panel", () => {
  let client: QueryClient;
  const control = autonomyFixture(); const row = overrideFixture();
  const read = vi.mocked(getOverrides); const action = vi.mocked(actOnOverride); const create = vi.mocked(createOverride);
  const view = (stopped = false, now = Date.now()) => <QueryClientProvider client={client}><OverridePanel now={now} control={control} controlFresh stopPending={stopped} refreshControl={vi.fn()} /></QueryClientProvider>;
  beforeEach(() => {
    vi.clearAllMocks(); client = new QueryClient();
    useAuthStore.setState({ accessToken: "token", generation: 1, endingSession: false, profile: { ...operatorProfile, permissions: ["read:telemetry", "write:config", "execute:rollback"] } });
    useWorkspaceStore.setState({ organizationId: "org", networkId: control.network_id, workspaceId: control.workspace_id });
    read.mockResolvedValue({ network_id: row.network_id, control_revision: control.revision, overrides: [row], history_limit: 100 });
    action.mockResolvedValue({ ...row, status: "restoring", verification: { status: "pending", safe_to_release: false } });
  });
  afterEach(() => { cleanup(); client.clear(); });
  it("expiry never triggers client restoration; cancel requests remain pending/uncertain", async () => {
    const rendered = render(view()); await screen.findByText("Override holding");
    expect(action).not.toHaveBeenCalled(); expect(screen.getByText(/Expiry reached by browser clock/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Request restoration" }));
    await screen.findByText(/Server override status: restoring.*Cancellation requests restoration/);
    expect(action.mock.calls[0][4]).toBe("cancel");
    const uncertain = { ...row, status: "restoring" as const, verification: { status: "uncertain", safe_to_release: false }, reasons: ["restoration_unverified"] };
    read.mockResolvedValue({ network_id: row.network_id, control_revision: control.revision, overrides: [uncertain], history_limit: 100 });
    await userEvent.click(screen.getByRole("button", { name: "Refresh override status" }));
    await screen.findByText(/Verification status: uncertain/);
    expect(screen.getByRole("button", { name: "Request gated return" })).toBeDisabled();
    rendered.rerender(view(false, Date.now() + 60_000)); expect(action).toHaveBeenCalledTimes(1);
  });
  it("requires verified restoration, reason and fresh revision; STOP disables return but not restoration", async () => {
    const restored = overrideFixture({ status: "return_blocked", restored_at: "2026-09-10T12:06:00Z", reasons: ["calibrated_safety_unavailable"] });
    read.mockResolvedValue({ network_id: row.network_id, control_revision: control.revision, overrides: [restored], history_limit: 100 });
    const rendered = render(view()); await screen.findByText("Override return_blocked");
    expect(screen.getByRole("button", { name: "Request gated return" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Explicit return reason"), "Reviewed restoration");
    expect(screen.getByRole("button", { name: "Request gated return" })).toBeEnabled();
    rendered.rerender(view(true)); expect(screen.getByRole("button", { name: "Request gated return" })).toBeDisabled();
    rendered.rerender(view()); action.mockRejectedValue(new Error("Control revision changed"));
    await userEvent.click(screen.getByRole("button", { name: "Request gated return" }));
    await screen.findByText(/Override request not confirmed.*Control revision changed/);
    expect(action).toHaveBeenCalledTimes(1); expect(action.mock.calls[0][5]).toEqual({ expected_revision: control.revision, reason: "Reviewed restoration" });
  });
  it("enrolls only an explicitly inspected selected intent/execution pair", async () => {
    read.mockResolvedValue({ network_id: row.network_id, control_revision: control.revision, overrides: [], history_limit: 100 });
    vi.mocked(getIntentDetail).mockResolvedValue({ success: true, meta: { request_id: "fixture", timestamp: row.created_at }, errors: null, data: overrideIntentFixture(operatorProfile.user_id) });
    create.mockResolvedValue(row); render(view()); await screen.findByText(/No timed overrides/);
    await userEvent.type(screen.getByLabelText("Override intent UUID"), row.intent_id);
    await userEvent.type(screen.getByLabelText("Override execution UUID"), row.execution_id);
    await userEvent.type(screen.getByLabelText("Override reason"), "Temporary maintenance");
    expect(screen.getByRole("button", { name: "Enroll timed override" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Inspect selected execution" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Enroll timed override" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Enroll timed override" }));
    await screen.findByText(/Server override status: holding/);
    expect(create.mock.calls[0][2]).toEqual({ network_id: row.network_id, intent_id: row.intent_id, execution_id: row.execution_id, expected_revision: control.revision, reason: "Temporary maintenance", duration_seconds: 300, return_mode: "monitor" });
    act(() => useAuthStore.setState({ profile: { ...operatorProfile, permissions: ["read:telemetry"] } }));
    expect(screen.getByRole("button", { name: "Enroll timed override" })).toBeDisabled();
  });
  it("keeps STOP dominant during a pending return and never changes the confirmed mode", async () => {
    const restored = overrideFixture({ status: "restored", restored_at: "2026-09-10T12:06:00Z" });
    read.mockResolvedValue({ network_id: row.network_id, control_revision: control.revision, overrides: [restored], history_limit: 100 });
    let resolve!: (value: typeof row) => void;
    action.mockImplementation(() => new Promise((done) => { resolve = done; }));
    const rendered = render(view()); await screen.findByText("Override restored");
    await userEvent.type(screen.getByLabelText("Explicit return reason"), "Reviewed restoration");
    await userEvent.click(screen.getByRole("button", { name: "Request gated return" }));
    rendered.rerender(view(true));
    await act(async () => resolve({ ...restored, status: "return_blocked", reasons: ["emergency_stop_latched"] }));
    expect(screen.getByRole("button", { name: "Request gated return" })).toBeDisabled();
    expect(screen.getByText(/STOP dominates enrollment/)).toBeInTheDocument();
    expect(control.mode).toBe("monitor"); expect(action).toHaveBeenCalledTimes(1);
  });
  it.each(["executing approver B", "intent requester A"])("binds enrollment to executing approver, not creator: current %s", async (current) => {
    const requester = "00000000-0000-0000-0000-000000000456";
    const approver = operatorProfile.user_id;
    useAuthStore.setState({ profile: { ...useAuthStore.getState().profile!, user_id: current === "intent requester A" ? requester : approver } });
    const data = { ...overrideIntentFixture(approver), requested_by_user_id: requester };
    read.mockResolvedValue({ network_id: row.network_id, control_revision: control.revision, overrides: [], history_limit: 100 });
    vi.mocked(getIntentDetail).mockResolvedValue({ success: true, meta: { request_id: "fixture", timestamp: row.created_at }, errors: null, data });
    create.mockResolvedValue(row);
    render(view()); await screen.findByText(/No timed overrides/);
    fireEvent.change(screen.getByLabelText("Override intent UUID"), { target: { value: row.intent_id } });
    fireEvent.change(screen.getByLabelText("Override execution UUID"), { target: { value: row.execution_id } });
    fireEvent.change(screen.getByLabelText("Override reason"), { target: { value: "Maintenance" } });
    await userEvent.click(screen.getByRole("button", { name: "Inspect selected execution" }));
    await screen.findByText(/Selected execution status: execution_completed/);
    const enroll = screen.getByRole("button", { name: "Enroll timed override" });
    if (current === "executing approver B") {
      expect(enroll).toBeEnabled(); await userEvent.click(enroll);
      await screen.findByText(/Server override status: holding/);
      expect(create).toHaveBeenCalledTimes(1);
      expect(create.mock.calls[0][2]).toMatchObject({ intent_id: row.intent_id, execution_id: row.execution_id, expected_revision: control.revision });
    } else {
      expect(enroll).toBeDisabled(); await userEvent.click(enroll); expect(create).not.toHaveBeenCalled();
    }
  });
  it.each([undefined, null, "operator", ` ${operatorProfile.user_id}`, { user_id: operatorProfile.user_id }, [operatorProfile.user_id]])(
    "never falls back to intent requester for missing/malformed execution approver %#", async (approver) => {
      const data = overrideIntentFixture(operatorProfile.user_id);
      data.execution_provenance.approved_by_user_id = approver;
      read.mockResolvedValue({ network_id: row.network_id, control_revision: control.revision, overrides: [], history_limit: 100 });
      vi.mocked(getIntentDetail).mockResolvedValue({ success: true, meta: { request_id: "fixture", timestamp: row.created_at }, errors: null, data });
      render(view()); await screen.findByText(/No timed overrides/);
      fireEvent.change(screen.getByLabelText("Override intent UUID"), { target: { value: row.intent_id } });
      fireEvent.change(screen.getByLabelText("Override execution UUID"), { target: { value: row.execution_id } });
      fireEvent.change(screen.getByLabelText("Override reason"), { target: { value: "Maintenance" } });
      await userEvent.click(screen.getByRole("button", { name: "Inspect selected execution" }));
      await screen.findByText(/Not eligible for enrollment/);
      expect(screen.getByRole("button", { name: "Enroll timed override" })).toBeDisabled(); expect(create).not.toHaveBeenCalled();
    });
});
