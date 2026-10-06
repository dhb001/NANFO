import { act, cleanup, render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RealtimeBridge } from "./RealtimesBridge";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { useSimulationCompare, useSimulationDetail, useSimulationHistory } from "@/features/simulation/hooks";
import { useIntentDetail, useIntentHistory } from "@/features/intent/hooks";
import { useDeviceTelemetry, useTelemetryHistory } from "@/features/telemetry/hooks";
import { useDevices, useNetworks } from "@/features/networks/hooks";
import { useAlertsQuery } from "@/features/reliability/hooks";
import { useLiveStore } from "./store";
import { operatorProfile } from "@/test/profile";
import type { WebSocketEnvelope } from "@/shared/types/ws";
import { authorityKey } from "@/features/auth/sessionScope";

function sessionKey() {
  const auth = useAuthStore.getState();
  const scope = useWorkspaceStore.getState();
  return JSON.stringify([auth.generation, auth.userId, scope.organizationId, scope.workspaceId, scope.networkId]);
}

type Socket = { path: string; onSubscribed(): void; onError(error: { code: string; message: string }): void; onFrame(frame: WebSocketEnvelope<unknown>): void };
const sockets = new Map<string, Socket>();
vi.mock("@/shared/realtime/useManagedWebSocket", () => ({ useManagedWebSocket: (options: Socket) => sockets.set(options.path, options) }));
const fetchMock = vi.fn<typeof fetch>();
const reply = (data: unknown) => Response.json({ success: true, data, meta: {}, errors: null });
let client: QueryClient;
let result: ReturnType<typeof useSimulationDetail>;

function MountedOwners() {
  const token = useAuthStore((state) => state.accessToken);
  const { workspaceId, networkId } = useWorkspaceStore();
  result = useSimulationDetail(token, "selected");
  useSimulationCompare(token, "selected", "baseline");
  useSimulationHistory(token, workspaceId, networkId, 3);
  useIntentDetail(token, "intent", workspaceId);
  useIntentHistory(token, workspaceId, networkId, 2);
  useTelemetryHistory(token, { workspaceId: workspaceId!, networkId: networkId!, page: 3 });
  useDeviceTelemetry(token, "device-beyond-graph");
  useDevices(token, networkId, 3);
  useNetworks(token, workspaceId, 2);
  useAlertsQuery(token, { workspaceId: workspaceId!, networkId: networkId! });
  return <RealtimeBridge />;
}

const urls = () => fetchMock.mock.calls.map(([url]) => new URL(String(url), "http://localhost"));
const count = (part: string) => urls().filter((url) => `${url.pathname}${url.search}`.includes(part)).length;
async function tick(ms = 501) { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); }
function reconcile(kind: "subscribe" | "backpressure") {
  act(() => { for (const socket of sockets.values()) {
    if (kind === "subscribe") socket.onSubscribed();
    else socket.onError({ code: "WS_BACKPRESSURE", message: "Dropped frames" });
  } });
}

describe("realtime reconciliation with actual mounted owner hooks", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    useAuthStore.setState({ userId: operatorProfile.user_id, accessToken: "old", generation: 10, endingSession: false, profile: operatorProfile });
    useWorkspaceStore.setState({ organizationId: "org", workspaceId: "workspace", networkId: "network" });
    useLiveStore.getState().reset();
    sockets.clear(); fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(async () => reply({ status: "paused", items: [], total: 41, page: 3, page_size: 20 }));
  });
  afterEach(() => { cleanup(); client.clear(); vi.unstubAllGlobals(); vi.useRealTimers(); });

  it("refreshes mounted history/detail/compare, off-graph telemetry and inventory pages on reconnect/backpressure after rotation", async () => {
    render(<QueryClientProvider client={client}><MountedOwners /></QueryClientProvider>);
    await tick(1);
    const stable = client.getQueryCache().getAll().filter((query) => ["simulation", "simulation-compare", "intent", "telemetry"].includes(String(query.queryKey[0])));
    const foreignKeys = stable.map((query) => {
      const key = [...query.queryKey];
      key[key[0] === "telemetry" ? 2 : 1] = "foreign-session-tenant";
      client.setQueryData(key, { private: true });
      return key;
    });
    // Same session, another network; and another session/tenant for the same network (ADR-028 key layout).
    const foreignAlerts = ["alerts", sessionKey(), authorityKey(), { workspaceId: "workspace", networkId: "other" }];
    const foreignDevices = ["devices", sessionKey(), authorityKey(), "other", 3, 20];
    const foreignSessionDevices = ["devices", "foreign-session-tenant", authorityKey(), "network", 3, 20];
    for (const key of [foreignAlerts, foreignDevices, foreignSessionDevices]) client.setQueryData(key, { items: [] });
    // Queue lifecycle reconciliation, then rotate before its debounce expires.
    sockets.get("/ws/digital-twin")!.onSubscribed();
    act(() => useAuthStore.setState({ accessToken: "new" }));
    await tick();
    expect(count("/simulations?" )).toBe(2);
    expect(count("/simulations/selected/compare/baseline")).toBe(2);
    for (const mode of ["subscribe", "backpressure"] as const) {
      const before = urls().length;
      reconcile(mode); await tick();
      const calls = fetchMock.mock.calls.slice(before);
      for (const path of ["/simulations?", "/simulations/selected", "/compare/baseline", "/intents?", "/intents/intent", "/telemetry/history", "/telemetry/device/device-beyond-graph", "/networks/network/devices", "/networks?", "/alerts?"]) {
        expect(calls.some(([url]) => String(url).includes(path)), path).toBe(true);
      }
      expect(calls.every(([, options]) => new Headers(options?.headers).get("Authorization") === "Bearer new")).toBe(true);
    }
    expect(urls().some((url) => url.pathname.endsWith("/devices") && url.searchParams.get("page") === "3")).toBe(true);
    expect(stable.every((query) => client.getQueryCache().find({ queryKey: query.queryKey }) === query)).toBe(true);
    for (const key of [...foreignKeys, foreignAlerts, foreignDevices, foreignSessionDevices]) expect(client.getQueryState(key)?.isInvalidated).toBe(false);
    // A lifecycle event after rotation must invalidate the same stable queries.
    const before = count("/simulations?");
    act(() => sockets.get("/ws/digital-twin")!.onFrame({ event: "simulation.paused", data: { scene_object: { id: "event", object_type: "simulation_state", simulation_id: "selected", status: "paused" } } }));
    await tick();
    expect(count("/simulations?")).toBe(before + 1);
  });

  it("cancels pending owner reads on authority change and never installs late old-authority data", async () => {
    const pending: { signal: AbortSignal; finish(response: Response): void }[] = [];
    fetchMock.mockImplementation((_url, options) => new Promise((finish) => {
      if (options?.signal) pending.push({ signal: options.signal, finish });
      else finish(reply({ items: [], total: 0 }));
    }));
    render(<QueryClientProvider client={client}><MountedOwners /></QueryClientProvider>);
    await tick(1);
    // Every mounted read (history/detail/compare, telemetry, inventory, alerts) passes its abort signal.
    expect(pending).toHaveLength(10);
    const previous = [...pending];
    fetchMock.mockImplementation(async () => reply({ status: "paused", items: [], total: 0, marker: "new-authority" }));
    act(() => useAuthStore.getState().setProfile({ ...operatorProfile, roles: ["Read-Only"], permissions: ["read:topology", "read:telemetry"] }));
    await tick(1);
    expect(previous.every(({ signal }) => signal.aborted)).toBe(true);
    await act(async () => { previous.forEach(({ finish }) => finish(reply({ status: "completed", marker: "old-authority" }))); });
    await tick(1);
    expect(result.data?.status).toBe("paused");
    expect(client.getQueryCache().getAll().some((query) => JSON.stringify(query.state.data)?.includes("old-authority"))).toBe(false);
  });

  it("retains a coalesced lifecycle follow-up while a mounted read spans token rotation", async () => {
    render(<QueryClientProvider client={client}><MountedOwners /></QueryClientProvider>);
    await tick(1);
    let finish!: (value: Response) => void;
    fetchMock.mockImplementation(async (url) => {
      if (new URL(String(url), "http://localhost").pathname === "/api/v1/simulations/selected") {
        return new Promise((resolve) => { finish = resolve; });
      }
      return reply({ status: "paused", items: [], total: 0 });
    });
    act(() => sockets.get("/ws/digital-twin")!.onSubscribed());
    await tick();
    expect(finish).toBeDefined();
    act(() => useAuthStore.setState({ accessToken: "rotated-pending" }));
    const reads = count("/simulations/selected");
    for (let index = 0; index < 20; index++) sockets.get("/ws/digital-twin")!.onError({ code: "WS_BACKPRESSURE", message: "Missed lifecycle" });
    await tick();
    expect(count("/simulations/selected")).toBe(reads);
    fetchMock.mockImplementation(async () => reply({ status: "cancelled", items: [], total: 0 }));
    await act(async () => finish(reply({ status: "paused" })));
    await tick();
    expect(result.data?.status).toBe("cancelled");
    const lastDetail = fetchMock.mock.calls.filter(([url]) => new URL(String(url), "http://localhost").pathname === "/api/v1/simulations/selected").at(-1)!;
    expect(new Headers(lastDetail[1]?.headers).get("Authorization")).toBe("Bearer rotated-pending");
  });
});
