import { act, render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";
import { useCampusBuildings, useCampusModelAssets, useDeviceGroups, useDevices, useNetworks } from "@/features/networks/hooks";
import { useTopologyGraph, useTopologyImpact, useTopologyNeighbours, useTopologyNode } from "@/features/topology/hooks";
import { useOrganizations, useOrgMembers, useWorkspaces } from "@/features/organizations/hooks";
import { useOrgAuthority } from "@/features/organizations/useOrgAuthority";
import { useAlertDetail, useAlertHistory, useAlertsQuery } from "@/features/reliability/hooks";
import { usePluginsQuery } from "@/features/plugins/hooks";
import { useReportDetail, useReportHistory } from "@/features/reporting/hooks";
import { useAuditLogs } from "@/features/audit/hooks";
import { useDeviceTelemetry, useTelemetryHistory } from "@/features/telemetry/hooks";
import { useIntentHistory } from "@/features/intent/hooks";
import { useSimulationHistory } from "@/features/simulation/hooks";

const admin = { ...operatorProfile, roles: ["Admin"], permissions: [...operatorProfile.permissions, "read:telemetry", "read:topology"] };
const fetchMock = vi.fn<typeof fetch>();
let mounts = 0;

function answer(url: string) {
  const path = new URL(url, "http://localhost").pathname;
  if (path.endsWith("/topology/graph")) return { nodes: [{ device_id: "d1" }], edges: [] };
  if (path === "/api/v1/organizations/org-1") return { org_id: "org-1", name: "Org", slug: "org", created_at: "2026-09-20T00:00:00Z", caller_role: "Admin" };
  if (/\/reports\/[^/]+$/.test(path)) return { report_id: "r1", status: "generated", artifacts: [] };
  return { items: [], total: 0, page: 1, page_size: 20, status_counts: {} };
}

function EveryScopedRead() {
  const token = useAuthStore((state) => state.accessToken);
  useEffect(() => { mounts += 1; }, []);
  useNetworks(token, "ws-1", 2);
  useDevices(token, "net-1", 3);
  useCampusBuildings(token, "net-1");
  useCampusModelAssets(token, "net-1", 1, 20);
  useDeviceGroups(token, "net-1");
  useTopologyGraph(token, "net-1");
  useTopologyNode(token, "d1");
  useTopologyNeighbours(token, "d1");
  useTopologyImpact(token, "d1");
  useOrganizations(token, 1);
  useWorkspaces(token, "org-1", 1);
  useOrgMembers(token, "org-1", 1);
  useOrgAuthority(token, "org-1");
  useAlertsQuery(token, { workspaceId: "ws-1", networkId: "net-1" });
  useAlertDetail(token, "a1");
  useAlertHistory(token, "a1");
  usePluginsQuery(token, { pollMs: 60_000 });
  useReportHistory(token, "ws-1", 1);
  useReportDetail(token, "r1", "ws-1");
  useAuditLogs(token, "org-1", { page: 1 });
  useTelemetryHistory(token, { workspaceId: "ws-1", networkId: "net-1", page: 1 });
  useDeviceTelemetry(token, "d1");
  useIntentHistory(token, "ws-1", "net-1", 1);
  useSimulationHistory(token, "ws-1", "net-1", 1);
  return null;
}

describe("access-token rotation (ADR-028)", () => {
  beforeEach(() => {
    mounts = 0;
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (url) => Response.json({ success: true, data: answer(String(url)), meta: { request_id: "r", timestamp: "t" }, errors: null }));
    vi.stubGlobal("fetch", fetchMock);
    useAuthStore.getState().setSession({ accessToken: "access-original", refreshToken: "refresh-1", userId: admin.user_id, profile: admin });
    useWorkspaceStore.setState({ organizationId: "org-1", workspaceId: "ws-1", networkId: "net-1" });
  });
  afterEach(() => { useAuthStore.getState().clearSession(); vi.unstubAllGlobals(); });

  it("never puts the credential in a query key, never refetches and never remounts on rotation", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 10_000 } } });
    render(<QueryClientProvider client={client}><EveryScopedRead /></QueryClientProvider>);
    await waitFor(() => expect(client.getQueryCache().getAll().every((query) => query.state.status === "success")).toBe(true));
    const keys = client.getQueryCache().getAll().map((query) => query.queryHash).sort();
    expect(keys.length).toBeGreaterThanOrEqual(24);
    expect(keys.join("\n")).not.toContain("access-original");
    const reads = fetchMock.mock.calls.length;

    for (const rotated of ["access-rotated-1", "access-rotated-2"]) {
      act(() => useAuthStore.getState().replaceTokens({ accessToken: rotated, refreshToken: `${rotated}-refresh` }));
    }

    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 50)); });
    expect(client.getQueryCache().getAll().map((query) => query.queryHash).sort()).toEqual(keys);
    expect(fetchMock.mock.calls.length).toBe(reads);
    expect(mounts).toBe(1);
    expect(client.getQueryCache().getAll().every((query) => !query.state.isInvalidated)).toBe(true);

    // The next read of the same key uses the current credential.
    await act(async () => { await client.refetchQueries({ queryKey: ["networks"] }); });
    const last = fetchMock.mock.calls.at(-1)!;
    expect(String(last[0])).toContain("/api/v1/networks?");
    expect(new Headers(last[1]?.headers).get("Authorization")).toBe("Bearer access-rotated-2");
  });

  it("does change identity (and refetch) for a new session, tenant or authority", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 10_000 } } });
    render(<QueryClientProvider client={client}><EveryScopedRead /></QueryClientProvider>);
    await waitFor(() => expect(client.getQueryCache().getAll().every((query) => query.state.status === "success")).toBe(true));
    const before = new Set(client.getQueryCache().getAll().map((query) => query.queryHash));
    act(() => useAuthStore.getState().setProfile({ ...admin, permissions: admin.permissions.filter((permission) => permission !== "write:config") }));
    await waitFor(() => expect(client.getQueryCache().getAll().some((query) => !before.has(query.queryHash))).toBe(true));
  });
});
