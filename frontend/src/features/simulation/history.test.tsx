import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SimulationPage } from "./SimulationPage";
import { IntentPage } from "@/features/intent/IntentPage";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";

const envelope = (data: unknown) => Response.json({ success: true, data, meta: {}, errors: null });
const fetchMock = vi.fn<typeof fetch>();

describe("durable operator histories", () => {
  beforeEach(() => {
    useAuthStore.setState({ accessToken: "token", userId: operatorProfile.user_id, profile: operatorProfile, endingSession: false });
    useWorkspaceStore.setState({ organizationId: "org", workspaceId: "workspace", networkId: "network" });
    window.history.replaceState(null, "", "/ops/simulation");
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it.each(["simulation", "intent"] as const)("paginates %s beyond 20, preserves selection through rotation and reload, never auto-acts", async (kind) => {
    const resource = kind === "simulation" ? "simulations" : "intents";
    const idField = `${kind}_id`;
    fetchMock.mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === `/api/v1/${resource}`) {
        const page = Number(url.searchParams.get("page"));
        return envelope({ items: [{ [idField]: `persisted-${page}`, workspace_id: "workspace", network_id: "network",
          scenario_name: `Scenario ${page}`, action: `Action ${page}`, status: "draft", created_at: "2026-09-20T10:00:00Z" }], total: 41, page, page_size: 20 });
      }
      return envelope({ [idField]: url.pathname.split("/").at(-1), workspace_id: "workspace", network_id: "network", status: "draft",
        scenario_name: "Persisted", validation: {}, validation_result: {}, run_output: {}, execution_provenance: {}, explainability: {}, intent_payload: { action: "reroute_path" },
        confidence: { score: 0, band: "unavailable", approval_required: true } });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const page = <QueryClientProvider client={client}>{kind === "simulation" ? <SimulationPage /> : <IntentPage />}</QueryClientProvider>;
    const view = render(page);
    await screen.findByText(`Page 1 | 41 ${kind === "simulation" ? "runs" : "intents"}`);
    fireEvent.click(screen.getByRole("button", { name: `Next ${resource}` }));
    await screen.findByText(`Page 2 | 41 ${kind === "simulation" ? "runs" : "intents"}`);
    fireEvent.click(screen.getByRole("button", { name: `Next ${resource}` }));
    fireEvent.click(await screen.findByRole("button", { name: `${kind === "simulation" ? "Scenario" : "Action"} 3 — draft` }));
    expect(screen.getByLabelText(kind === "simulation" ? "Simulation ID" : "Intent ID")).toHaveValue("persisted-3");
    expect(new URLSearchParams(window.location.search).get(idField)).toBe("persisted-3");
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes(`/${resource}/persisted-3`))).toBe(true));
    const historyReads = fetchMock.mock.calls.filter(([url]) => String(url).includes(`/${resource}?`)).length;
    act(() => useAuthStore.getState().replaceTokens({ accessToken: "rotated", refreshToken: "refresh" }));
    expect(screen.getByLabelText(kind === "simulation" ? "Simulation ID" : "Intent ID")).toHaveValue("persisted-3");
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes(`/${resource}?`))).toHaveLength(historyReads);
    view.unmount();
    render(page);
    expect(screen.getByLabelText(kind === "simulation" ? "Simulation ID" : "Intent ID")).toHaveValue("persisted-3");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes(`/${resource}?`)).every(([url]) => String(url).includes("workspace_id=workspace") && String(url).includes("network_id=network"))).toBe(true);
    act(() => useWorkspaceStore.setState({ networkId: "another-network" }));
    expect(screen.getByLabelText(kind === "simulation" ? "Simulation ID" : "Intent ID")).toHaveValue("");
    client.clear();
  });
});
