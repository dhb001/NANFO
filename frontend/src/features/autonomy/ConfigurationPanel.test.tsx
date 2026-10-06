import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConfigurationPanel } from "./ConfigurationPanel";
import { getConfiguration, putConfiguration } from "./configurationApi";
import { configurationFixture } from "./operatorFixtures";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";
vi.mock("./configurationApi", async (original) => ({ ...await original<object>(), getConfiguration: vi.fn(), putConfiguration: vi.fn() }));
describe("configuration operator panel", () => {
  let client: QueryClient;
  const data = configurationFixture();
  const read = vi.mocked(getConfiguration); const put = vi.mocked(putConfiguration);
  beforeEach(() => {
    vi.clearAllMocks(); client = new QueryClient();
    useAuthStore.setState({ accessToken: "token", generation: 1, endingSession: false, profile: { ...operatorProfile, permissions: ["read:telemetry", "write:config", "execute:rollback"] } });
    useWorkspaceStore.setState({ organizationId: "org", networkId: data.network_id, workspaceId: data.workspace_id });
    read.mockResolvedValue(data); put.mockResolvedValue({ ...data, revision: 2 });
  });
  afterEach(() => { cleanup(); client.clear(); });
  it("does not silently rebase a conflicted draft or change effective training", async () => {
    render(<QueryClientProvider client={client}><ConfigurationPanel now={Date.now()} /></QueryClientProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "Edit current revision" }));
    await userEvent.type(screen.getByLabelText("Configuration change reason"), "Maintenance");
    read.mockResolvedValue({ ...data, revision: 2 }); put.mockRejectedValue(new Error("CONFIGURATION_REVISION_CONFLICT"));
    await userEvent.click(screen.getByRole("button", { name: "Save new configuration revision" }));
    await screen.findByText(/Configuration not confirmed.*CONFIGURATION_REVISION_CONFLICT/);
    await waitFor(() => expect(screen.getByRole("button", { name: "Save new configuration revision" })).toBeDisabled());
    expect(screen.getByText(/Revision conflict: reload this draft/)).toBeInTheDocument();
    expect(screen.getByText(/Effective frozen model reward settings are unavailable/)).toBeInTheDocument();
    expect(put).toHaveBeenCalledTimes(1); expect(put.mock.calls[0][2].expected_revision).toBe(1);
    expect(screen.getByText("Revision 1: Initial requested settings")).toBeInTheDocument();
  });
  it("disables writes on stale configuration read", async () => {
    render(<QueryClientProvider client={client}><ConfigurationPanel now={Date.now()} /></QueryClientProvider>);
    await screen.findByRole("button", { name: "Edit current revision" });
    read.mockRejectedValue(new Error("Offline"));
    await userEvent.click(screen.getByRole("button", { name: "Refresh configuration" }));
    await screen.findByText(/Configuration read unavailable/);
    expect(screen.getByRole("button", { name: "Edit current revision" })).toBeDisabled(); expect(put).not.toHaveBeenCalled();
  });
  it("shows the C17 confidence gate honestly and round-trips it in every saved revision", async () => {
    read.mockResolvedValue({ ...data, operational: { ...data.operational, min_confidence: 0.97, allow_uncalibrated_confidence: true }, allow_uncalibrated_confidence_honoured: false });
    render(<QueryClientProvider client={client}><ConfigurationPanel now={Date.now()} /></QueryClientProvider>);
    const gate = await screen.findByRole("note", { name: "Confidence gate" });
    expect(gate).toHaveTextContent("requires calibrated confidence of at least 0.97");
    expect(gate).toHaveTextContent("allowed by this policy but NOT honoured in this deployment; uncalibrated proposals are still refused.");
    await userEvent.click(screen.getByRole("button", { name: "Edit current revision" }));
    expect(screen.getByLabelText(/Allow uncalibrated confidence \(experimental lab only; ignored in this deployment\)/)).toBeChecked();
    await userEvent.type(screen.getByLabelText("Configuration change reason"), "Tighten");
    await userEvent.click(screen.getByRole("button", { name: "Save new configuration revision" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    // A save never drops (and so silently resets) the confidence gate.
    expect(put.mock.calls[0][2].operational).toMatchObject({ min_confidence: 0.97, allow_uncalibrated_confidence: true });
  });
});
