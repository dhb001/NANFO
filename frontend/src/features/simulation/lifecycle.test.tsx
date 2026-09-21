import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SimulationPage } from "./SimulationPage";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";

const response = (data: unknown) => Response.json({ success: true, data, meta: {}, errors: null });
const fetchMock = vi.fn<typeof fetch>();

describe("scenario lifecycle contracts", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/ops/simulation");
    useAuthStore.setState({ accessToken: "token", profile: operatorProfile });
    useWorkspaceStore.setState({ workspaceId: "workspace", networkId: "network" });
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
  });
  afterEach(() => vi.unstubAllGlobals());
  it("keeps editing and pending start identity over rotation without replaying a lost response", async () => {
    let finish!: (response: Response) => void;
    fetchMock.mockImplementation(async (url, init) => {
      if (init?.method === "POST") return new Promise((resolve) => { finish = resolve; });
      if (String(url).includes("/simulations?")) return response({ items: [], total: 0, page: 1, page_size: 20 });
      if (String(url).includes("/compare/")) return response({ compatible: false, deltas: { latency_ms: null, loss_pct: null, throughput_mbps: null } });
      return response({ simulation_id: "created", network_id: "network", scenario_name: "Draft", status: "queued", validation: {}, run_output: {} });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><SimulationPage /></QueryClientProvider>);
    fireEvent.change(screen.getByLabelText("Scenario Name"), { target: { value: "My unsaved scenario" } });
    act(() => useAuthStore.getState().replaceTokens({ accessToken: "rotated-edit", refreshToken: "r2" }));
    expect(screen.getByLabelText("Scenario Name")).toHaveValue("My unsaved scenario");
    fireEvent.click(screen.getByRole("button", { name: "Start Simulation" }));
    await waitFor(() => expect(finish).toBeDefined());
    act(() => useAuthStore.getState().replaceTokens({ accessToken: "rotated-start", refreshToken: "r3" }));
    expect(screen.getByRole("button", { name: "Starting..." })).toBeDisabled();
    await act(async () => finish(response({ simulation_id: "created", status: "queued" })));
    await waitFor(() => expect(screen.getByLabelText("Simulation ID")).toHaveValue("created"));
    expect(screen.getByLabelText("Scenario Name")).toHaveValue("My unsaved scenario");
    expect(new URLSearchParams(window.location.search).get("simulation_id")).toBe("created");
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    fetchMock.mockImplementation(async (_url, init) => {
      if (init?.method === "POST") throw new Error("Lost response");
      return response({ items: [], total: 0, page: 1, page_size: 20 });
    });
    fireEvent.click(screen.getByRole("button", { name: "Start Simulation" }));
    await screen.findByText("Simulation start failed");
    act(() => useAuthStore.getState().replaceTokens({ accessToken: "rotated-loss", refreshToken: "r4" }));
    expect(screen.getByLabelText("Simulation ID")).toHaveValue("created");
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(2);
    client.clear();
  });
  it("starts configured input, branches without changes, resumes draft with same ID and pauses", async () => {
    let state = "queued";
    const posts: { url: string; body: Record<string, unknown> }[] = [];
    fetchMock.mockImplementation(async (url, init) => {
      if (String(url).includes("/simulations?")) return response({ items: [], total: 0, page: 1, page_size: 20 });
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        posts.push({ url: String(url), body });
        const branch = String(url).endsWith("/branch");
        state = branch ? "draft" : String(url).endsWith("/pause") ? "paused" : "queued";
        return response({ simulation_id: branch || body.simulation_id === "branch" ? "branch" : "original", status: state });
      }
      if (String(url).includes("/compare/")) return response({ compatible: false, deltas: { latency_ms: null, loss_pct: null, throughput_mbps: null } });
      return response({ simulation_id: String(url).endsWith("/branch") ? "branch" : "original", network_id: "network", scenario_name: "Persisted name", status: state, queue_status: "pending", risk_gate: "required", validation: {}, run_output: {} });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><SimulationPage /></QueryClientProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Start Simulation" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Branch" })).toBeEnabled());
    expect(posts[0].body.scenario_config).toMatchObject({ version: 1, seed: 42, action_binding: null });
    fireEvent.click(screen.getByRole("button", { name: "Branch" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Resume / start draft" })).toBeEnabled());
    expect(posts[1].body).toEqual({ parent_simulation_id: "original", scenario_name: "Branch candidate" });
    fireEvent.click(screen.getByRole("button", { name: "Resume / start draft" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Pause" })).toBeEnabled());
    expect(posts[2].body).toMatchObject({ simulation_id: "branch", scenario_name: "Persisted name" });
    expect(posts[2].body).not.toHaveProperty("scenario_config");
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Resume / start draft" })).toBeEnabled());
    expect(posts[3].body).toEqual({ simulation_id: "branch" });
    client.clear();
  });
  it("rejects unsupported JSON locally without starting or claiming success", async () => {
    fetchMock.mockImplementation(async () => response({ items: [], total: 0, page: 1, page_size: 20 }));
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><SimulationPage /></QueryClientProvider>);
    fireEvent.click(screen.getByLabelText(/Advanced scenario JSON/));
    fireEvent.change(screen.getByLabelText("Scenario configuration JSON"), { target: { value: '{"version":2}' } });
    fireEvent.click(screen.getByRole("button", { name: "Start Simulation" }));
    await waitFor(() => expect(screen.getAllByRole("alert").length).toBeGreaterThan(0));
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    client.clear();
  });
});
