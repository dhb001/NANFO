import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useAuthStore } from "@/shared/state/auth-store";
import { useUiStore } from "@/shared/state/ui-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";
import { useModelAssetWorkflow } from "./useModelAssetWorkflow";

const mocks = vi.hoisted(() => ({ graph: vi.fn(), assets: vi.fn(), upsert: vi.fn(), digest: vi.fn() }));

vi.mock("@/features/topology/hooks", () => ({ useTopologyGraph: () => mocks.graph() }));
vi.mock("@/features/networks/hooks", () => ({
  useCampusModelAssets: () => mocks.assets(),
  useUpsertCampusModelAssets: () => ({ mutateAsync: mocks.upsert, isPending: false }),
}));

const NETWORK = "00000000-0000-0000-0000-000000000333";
const ZERO_SHA = "0".repeat(64);

function glbBytes() {
  const json = JSON.stringify({ asset: { version: "2.0" }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ name: "campus" }] });
  const data = new TextEncoder().encode(json.padEnd(Math.ceil(json.length / 4) * 4, " "));
  const buffer = new ArrayBuffer(20 + data.length);
  const view = new DataView(buffer);
  [0x46546c67, 2, buffer.byteLength, data.length, 0x4e4f534a].forEach((value, index) => view.setUint32(index * 4, value, true));
  new Uint8Array(buffer, 20).set(data);
  return new Uint8Array(buffer);
}

function glbFile(name = "campus.glb") {
  return new File([glbBytes()], name, { type: "model/gltf-binary" });
}

function graph(nextCursor: string | null = null) {
  return { data: { data: { nodes: [{ device_id: "d", hostname: "edge", device_type: "switch", status: "active", spatial_ref_id: null }], edges: [] }, nextCursor },
    isFetching: false, isError: false, refetch: vi.fn() };
}

describe("useModelAssetWorkflow", () => {
  const previousCreate = URL.createObjectURL;
  const previousRevoke = URL.revokeObjectURL;
  const previousCrypto = globalThis.crypto;

  beforeEach(() => {
    mocks.graph.mockReset().mockReturnValue(graph());
    mocks.assets.mockReset().mockReturnValue({ data: { items: [], total: 0 }, isFetching: false, isError: false, refetch: vi.fn(), readPage: vi.fn() });
    mocks.upsert.mockReset();
    mocks.digest.mockReset().mockResolvedValue(new Uint8Array(32).buffer);
    Object.defineProperty(globalThis, "crypto", { configurable: true, value: { subtle: { digest: (...args: unknown[]) => mocks.digest(...args) } } });
    URL.createObjectURL = vi.fn().mockReturnValue("blob:model");
    URL.revokeObjectURL = vi.fn();
    useAuthStore.setState({ profile: operatorProfile, accessToken: "token-1", endingSession: false });
    useWorkspaceStore.setState({ networkId: NETWORK });
    useUiStore.setState({ toasts: [] });
  });

  afterEach(() => {
    URL.createObjectURL = previousCreate;
    URL.revokeObjectURL = previousRevoke;
    Object.defineProperty(globalThis, "crypto", { configurable: true, value: previousCrypto });
  });

  it("keeps persistence unavailable until the validated model rendered, then persists the same bytes and checks the receipt", async () => {
    const file = glbFile();
    const { result } = renderHook(() => useModelAssetWorkflow());
    await act(() => result.current.importModelFile(file));
    expect(result.current).toMatchObject({ importedModelUrl: "blob:model", status: "loading", canPersist: false });
    expect(result.current.importSummary?.modelType).toBe("glb");
    act(() => result.current.onModelStatusChange("ready"));
    expect(result.current.canPersist).toBe(true);

    mocks.upsert.mockResolvedValue({ items: [{ network_id: NETWORK, model_sha256: ZERO_SHA, model_size_bytes: file.size, registration: null }], total: 1 });
    await act(() => result.current.persist());
    const bytes = glbBytes();
    expect(mocks.digest).toHaveBeenCalledTimes(1);
    expect(mocks.upsert).toHaveBeenCalledWith({
      model_file_name: "campus.glb", model_mime_type: "model/gltf-binary", model_data_base64: btoa(String.fromCharCode(...bytes)), model_sha256: ZERO_SHA,
      model_size_bytes: file.size, mapping_by_device_id: {}, registration: null, source: "session_import", replace_existing: false,
    });
    expect(useUiStore.getState().toasts.at(-1)).toMatchObject({ tone: "ok", title: "Campus model asset persisted" });
  });

  it("rejects a save whose metadata receipt does not match the uploaded digest", async () => {
    const file = glbFile();
    const { result } = renderHook(() => useModelAssetWorkflow());
    await act(() => result.current.importModelFile(file));
    act(() => result.current.onModelStatusChange("ready"));
    mocks.upsert.mockResolvedValue({ items: [{ network_id: NETWORK, model_sha256: "f".repeat(64), model_size_bytes: file.size, registration: null }], total: 1 });
    await act(() => result.current.persist());
    expect(useUiStore.getState().toasts.at(-1)).toMatchObject({ tone: "danger", title: "Model asset persist failed", description: "Saved asset receipt mismatch. Reload asset metadata." });
  });

  it("reports render failures and never persists an unrendered model", async () => {
    const { result } = renderHook(() => useModelAssetWorkflow());
    await act(() => result.current.importModelFile(glbFile()));
    act(() => result.current.onModelStatusChange("error"));
    expect(result.current).toMatchObject({ status: "error", statusMessage: "Could not render the uploaded model.", canPersist: false });
    await act(() => result.current.persist());
    expect(mocks.upsert).not.toHaveBeenCalled();
    expect(useUiStore.getState().toasts.at(-1)).toMatchObject({ tone: "danger", description: "The model must render successfully before it is persisted." });
  });

  it("requires a model before a sidecar mapping and validates the mapping file type", async () => {
    const { result } = renderHook(() => useModelAssetWorkflow());
    await act(() => result.current.importSidecarFile(new File(["[]"], "mapping.json", { type: "application/json" })));
    expect(result.current.importError).toBe("Upload a GLB/GLTF model first, then upload sidecar mapping JSON.");
    await act(() => result.current.importModelFile(glbFile()));
    await act(() => result.current.importSidecarFile(new File(["x"], "mapping.txt", { type: "text/plain" })));
    expect(result.current.importError).toBe("Sidecar mapping must be a JSON file.");
    expect(result.current.importedModelUrl).toBe("blob:model");
  });

  it("only allows restoring a selected asset against a complete topology", async () => {
    const asset = { campus_model_asset_id: "asset-1", network_id: NETWORK, model_file_name: "saved.glb" };
    mocks.assets.mockReturnValue({ data: { items: [asset], total: 1 }, isFetching: false, isError: false, refetch: vi.fn(), readPage: vi.fn() });
    mocks.graph.mockReturnValue(graph("more"));
    const { result, rerender } = renderHook(() => useModelAssetWorkflow());
    act(() => result.current.selectAsset("asset-1"));
    expect(result.current.selectedAsset).toMatchObject({ campus_model_asset_id: "asset-1" });
    expect(result.current.canRestore).toBe(false);
    mocks.graph.mockReturnValue(graph());
    rerender();
    await waitFor(() => expect(result.current.canRestore).toBe(true));
  });
});
