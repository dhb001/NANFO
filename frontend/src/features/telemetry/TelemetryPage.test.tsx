import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TelemetryPage } from "@/features/telemetry/TelemetryPage";
import { usePluginsQuery } from "@/features/plugins/hooks";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";
import { TelemetryProvenance } from "./TelemetryProvenance";
import { useLiveStore } from "@/features/realtime/store";

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 115,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, start: index * 115 })),
    measureElement: () => undefined,
  }),
}));

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

  it("reaches device 41 with server totals and retains off-page selection and filters through rotation", async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname.endsWith("/devices")) {
        const page = Number(url.searchParams.get("page"));
        return response({ items: [{ device_id: `device-${page === 3 ? 41 : page}`, hostname: `Device page ${page}`, device_type: "router" }], total: 41, page, page_size: 20 });
      }
      return response({ items: [], total: 0, page: 1, page_size: 120 });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><TelemetryPage /></QueryClientProvider>);
    await screen.findByText("Page 1 | 41 devices");
    fireEvent.click(screen.getByRole("button", { name: "Next devices" }));
    await screen.findByText("Page 2 | 41 devices");
    fireEvent.click(screen.getByRole("button", { name: "Next devices" }));
    await screen.findByText("Device page 3 (router)");
    fireEvent.change(screen.getByLabelText("Telemetry device"), { target: { value: "device-41" } });
    fireEvent.change(screen.getByLabelText("Filter telemetry metric"), { target: { value: "latency_ms" } });
    act(() => useAuthStore.setState({ accessToken: "rotated" }));
    await waitFor(() => expect(screen.getByLabelText("Telemetry device")).toHaveValue("device-41"));
    expect(screen.getByLabelText("Filter telemetry metric")).toHaveValue("latency_ms");
    expect(screen.getByText("Page 3 | 41 devices")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Previous devices" }));
    await screen.findByText(/Selected device: device-41/);
    expect(screen.getByLabelText("Telemetry device")).toHaveValue("device-41");
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("device-41"))).toBe(true);
    client.clear();
  });

  it("labels realtime observation timestamps and stale age", () => {
    const observed = new Date(Date.now() - 60_000).toISOString();
    useLiveStore.setState({ telemetryKeysNewestFirst: ["sample"], telemetryByDeviceMetric: {
      sample: { device_id: "device", network_id: "network", workspace_id: "workspace", metric: "latency_ms", value: 4, unit: "ms", source: "test", tags: {}, observed_at: observed, event_id: "sample" },
    } });
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><TelemetryPage /></QueryClientProvider>);
    expect(screen.getByText(/Observed:.*60s old.*stale/)).toBeInTheDocument();
    act(() => useLiveStore.getState().reset());
    client.clear();
  });

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

  it("labels measured emulation without claiming physical telemetry", () => {
    render(<TelemetryProvenance tags={{ synthetic: false, execution_mode: "emulation" }} />);
    expect(screen.getByText("Measured emulation")).toBeInTheDocument();
    expect(screen.queryByText(/Live physical/i)).not.toBeInTheDocument();
  });

  it("blocks invalid filters, sends UTC bounds, displays ports and paginates groups", async () => {
    fetchMock.mockImplementation(async (url) => {
      const params = new URL(String(url), "http://localhost").searchParams;
      if (params.get("aggregation")) return response({
        items: [1, 2].map((port) => ({ device_id: "switch", metric: "queue_backlog_bytes", unit: "bytes", source: "emulation", port_no: String(port), peer_host: null, run_id: null, bucket_start: "2026-09-08T00:00:00Z", value: port * 100, sample_count: 4 })),
        total: 122, page: Number(params.get("page")), page_size: 120,
      });
      return response({ items: [], total: 0, page: 1, page_size: 120 });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><TelemetryPage /></QueryClientProvider>);
    await screen.findByText("No telemetry history");
    fireEvent.change(screen.getByLabelText("Aggregation"), { target: { value: "avg" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Aggregation requires");
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("aggregation="))).toBe(false);
    fireEvent.change(screen.getByLabelText("Filter telemetry metric"), { target: { value: "queue_backlog_bytes" } });
    fireEvent.change(screen.getByLabelText("Start time"), { target: { value: "2026-09-08T00:00" } });
    fireEvent.change(screen.getByLabelText("End time"), { target: { value: "2026-09-08T01:00" } });
    expect(await screen.findByText("100 bytes")).toBeInTheDocument();
    expect(screen.getByText("200 bytes")).toBeInTheDocument();
    expect(screen.getByText(/Port 1/)).toBeInTheDocument();
    expect(screen.getByText(/Port 2/)).toBeInTheDocument();
    expect(screen.getAllByText("AVG / 4 samples")).toHaveLength(2);
    const aggregateUrl = fetchMock.mock.calls.map(([url]) => new URL(String(url), "http://localhost")).find((url) => url.searchParams.has("aggregation"));
    expect(aggregateUrl?.searchParams.get("start_time")).toBe(new Date("2026-09-08T00:00").toISOString());
    expect(aggregateUrl?.searchParams.get("end_time")).toBe(new Date("2026-09-08T01:00").toISOString());
    expect(aggregateUrl?.searchParams.get("bucket_seconds")).toBe("60");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Page 2 / 2 | 122 buckets");
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(fetchMock.mock.calls.some(([url]) => new URL(String(url), "http://localhost").searchParams.get("page") === "2")).toBe(true);
    fireEvent.change(screen.getByLabelText("Bucket seconds"), { target: { value: "120" } });
    await screen.findByText("Page 1 / 2 | 122 buckets");
    fireEvent.change(screen.getByLabelText("End time"), { target: { value: "2026-09-07T01:00" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Start must be before");
    expect(screen.queryByText("100 bytes")).not.toBeInTheDocument();
  });

  it("displays portless probe peers and runs separately and allows raw flow fallback", async () => {
    fetchMock.mockImplementation(async (url) => {
      const params = new URL(String(url), "http://localhost").searchParams;
      return response({ items: params.has("aggregation") ? [
        { peer_host: "h2", run_id: "run-a", value: 10 },
        { peer_host: "h3", run_id: "run-a", value: 20 },
        { peer_host: "h2", run_id: "run-b", value: 30 },
      ].map((series) => ({ ...series, device_id: "host", metric: "latency_ms", unit: "ms", source: "emulation", port_no: null, bucket_start: "2026-09-08T00:00:00Z", sample_count: 2 })) : [], total: 3, page: 1, page_size: 120 });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><TelemetryPage /></QueryClientProvider>);
    await screen.findByText("No telemetry history");
    fireEvent.change(screen.getByLabelText("Aggregation"), { target: { value: "avg" } });
    fireEvent.change(screen.getByLabelText("Filter telemetry metric"), { target: { value: "latency_ms" } });
    fireEvent.change(screen.getByLabelText("Start time"), { target: { value: "2026-09-08T00:00" } });
    fireEvent.change(screen.getByLabelText("End time"), { target: { value: "2026-09-08T01:00" } });
    await screen.findByText(/Peer h2 \| Run run-a/);
    expect(screen.getByText(/Peer h3 \| Run run-a/)).toBeInTheDocument();
    expect(screen.getByText(/Peer h2 \| Run run-b/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter telemetry metric"), { target: { value: "flow_byte_count" } });
    expect(screen.getByRole("alert")).toHaveTextContent("no durable flow match identity");
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("flow_byte_count"))).toBe(false);
    fireEvent.change(screen.getByLabelText("Aggregation"), { target: { value: "" } });
    await screen.findByText("No telemetry history");
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("flow_byte_count") && !String(url).includes("aggregation="))).toBe(true);
  });
});
