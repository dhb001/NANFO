import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { useCreateDevice, useDevices, useNetworks } from "@/features/networks/hooks";
import { useOrganizations, useOrgMembers, useWorkspaces } from "@/features/organizations/hooks";

afterEach(() => vi.unstubAllGlobals());
function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("bounded inventory and tenancy hooks", () => {
  it("fetches one requested page per list, exposes total and normalized tenancy pagination", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ success: true, data: { items: [], total: 41 }, meta: {}, errors: null }), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const { result, rerender } = renderHook(({ page }: { page: number | undefined }) => ({
      devices: useDevices("fixture-token", "network", page),
      networks: useNetworks("fixture-token", "workspace", page),
      orgs: useOrganizations("fixture-token", page),
      workspaces: useWorkspaces("fixture-token", "org", page),
      members: useOrgMembers("fixture-token", "org", page),
    }), { initialProps: { page: undefined as number | undefined }, wrapper: wrapper() });
    await waitFor(() => expect(result.current.members.isSuccess).toBe(true));
    expect(fetcher).toHaveBeenCalledTimes(5);
    expect(fetcher.mock.calls.every((args) => String((args as unknown[])[0]).includes("page=1&page_size=20"))).toBe(true);
    rerender({ page: 3 });
    await waitFor(() => expect(result.current.orgs.data?.page).toBe(3));
    expect(result.current.workspaces.data).toMatchObject({ total: 41, page: 3, page_size: 20 });
    expect(fetcher).toHaveBeenCalledTimes(10);
  });

  it("submits every documented device field and retains nulls", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ success: true, data: { device_id: "device" }, meta: {}, errors: null }), { status: 201 }));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useCreateDevice("fixture-token", "network"), { wrapper: wrapper() });
    const input = { hostname: "ap", device_type: "access_point", ip_address: "192.0.2.1", vendor: "example", model: "one", location_hint: "office", spatial_ref_id: null };
    await act(async () => { await result.current.mutateAsync(input); });
    const options = (fetcher.mock.calls[0] as unknown[])[1] as RequestInit;
    expect(JSON.parse(options.body as string)).toEqual(input);
  });
});
