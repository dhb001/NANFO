import { render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TelemetryPage } from "@/features/telemetry/TelemetryPage";
import { usePluginsQuery } from "@/features/plugins/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";

const fetchMock = vi.fn<typeof fetch>();
const response = (data: unknown) => Response.json({ success: true, data, meta: {}, errors: null });

describe("telemetry diagnostic boundaries", () => {
  beforeEach(() => {
    useAuthStore.setState({ accessToken: "token", profile: operatorProfile });
    useWorkspaceStore.setState({ workspaceId: "workspace", networkId: "network" });
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(async (url) => String(url).endsWith("/health")
      ? response({ status: "unavailable", ingest_lag_ms: null, dropped_events: 0, total_records: 0 })
      : response({ items: [], total: 0, page: 1, page_size: 120 }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("does not request health for a non-Admin but still requests tenant history", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><TelemetryPage /></QueryClientProvider>);
    expect(screen.getByText("Telemetry health restricted")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("No telemetry history")).toBeInTheDocument());
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/telemetry?") || String(url).includes("/telemetry/history"))).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/health"))).toBe(false);
  });

  it("renders null Admin health measurements unavailable", async () => {
    useAuthStore.getState().setProfile({ ...operatorProfile, roles: ["Admin"] });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><TelemetryPage /></QueryClientProvider>);
    expect(await screen.findByText("Unavailable (no observations)")).toBeInTheDocument();
    expect(screen.getByText("UNAVAILABLE")).toBeInTheDocument();
    expect(screen.queryByText("0 ms")).not.toBeInTheDocument();
  });

  it("disables plugin registry queries for non-Admins", () => {
    const client = new QueryClient();
    renderHook(() => usePluginsQuery("token"), { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
