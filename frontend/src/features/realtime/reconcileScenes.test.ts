import { beforeEach, describe, expect, it, vi } from "vitest";
import { reconcileKnownScenes } from "./reconcileScenes";
import { useLiveStore } from "./store";
import { ApiClientError } from "@/shared/lib/errors";

const simulation = vi.fn();
const intent = vi.fn();
vi.mock("@/features/simulation/api", () => ({ getSimulationDetail: (...args: unknown[]) => simulation(...args) }));
vi.mock("@/features/intent/api", () => ({ getIntentDetail: (...args: unknown[]) => intent(...args) }));
const uuid = (index: number) => `00000000-0000-0000-0000-${String(index).padStart(12, "0")}`;
const scope = { workspaceId: "workspace", networkId: "network" };
function seed(index = 1, kind = "simulation_state", scoped = true) {
  useLiveStore.getState().applyDigitalTwinDelta({ delta_type: "update", scene_object: { id: "legacy", object_type: kind,
    ...(kind === "simulation_state" ? { simulation_id: uuid(index) } : { intent_id: uuid(index) }), status: "running", changed_fields: { outdated: true } } }, "2026-09-10T00:00:00Z", scoped ? scope : undefined);
  return `${kind === "simulation_state" ? "simulation" : "intent"}:${uuid(index)}`;
}
const detail = (index = 1) => ({ simulation_id: uuid(index), network_id: scope.networkId, workspace_id: scope.workspaceId, status: "completed", state: "completed", risk_gate: "blocked", revision: 3, updated_at: "2026-09-10T00:01:00Z", validation: {} });
const run = (current = () => true) => reconcileKnownScenes("token", scope.workspaceId, scope.networkId, current, new AbortController().signal);

describe("known lifecycle overlay reconciliation", () => {
  beforeEach(() => { useLiveStore.getState().reset(); simulation.mockReset(); intent.mockReset(); });
  it("fetches both kinds without active detail queries, replacing stale payloads", async () => {
    const sim = seed(); const int = seed(2, "intent_state");
    simulation.mockResolvedValue({ data: detail() });
    intent.mockResolvedValue({ data: { intent_id: uuid(2), workspace_id: scope.workspaceId, network_id: scope.networkId, status: "execution_failed", updated_at: "2026-09-10T00:01:00Z", execution_provenance: { phase: "failed" } } });
    await run();
    expect(simulation).toHaveBeenCalledWith("token", uuid(1), expect.any(AbortSignal));
    expect(intent).toHaveBeenCalledWith("token", uuid(2), scope.workspaceId, expect.any(AbortSignal));
    expect(useLiveStore.getState().sceneObjects[sim]).toMatchObject({ status: "completed", risk_gate: "blocked" });
    expect(useLiveStore.getState().sceneObjects[sim].changed_fields).not.toHaveProperty("outdated");
    expect(useLiveStore.getState().sceneObjects[int].status).toBe("execution_failed");
  });
  it("caps reads at 20, skips unscoped IDs and reports omitted history explicitly", async () => {
    for (let index = 1; index <= 24; index++) seed(index);
    seed(25, "simulation_state", false);
    simulation.mockImplementation((_token, id) => Promise.resolve({ data: { ...detail(), simulation_id: id } }));
    await run();
    expect(simulation).toHaveBeenCalledTimes(20);
    expect(useLiveStore.getState().sceneReconciliation).toEqual({ known: 25, attempted: 20, unavailable: 0, omitted: 5 });
    expect(useLiveStore.getState().sceneObjectAvailability[`simulation:${uuid(25)}`]).toBe("stale");
  });
  it.each([403, 404])("removes unavailable %s detail and sensitive scene fields", async (status) => {
    const id = seed(); simulation.mockRejectedValue(new ApiClientError("denied", "DENIED", status));
    await run();
    expect(useLiveStore.getState().sceneObjects[id]).toBeUndefined();
    expect(useLiveStore.getState().sceneObjectScopes[id]).toBeUndefined();
  });
  it("removes mismatched network/identity and marks transport failures stale", async () => {
    const id = seed(); simulation.mockResolvedValue({ data: { ...detail(), network_id: "other" } });
    await run(); expect(useLiveStore.getState().sceneObjects[id]).toBeUndefined();
    seed(); simulation.mockRejectedValue(new Error("offline"));
    await run(); expect(useLiveStore.getState().sceneObjectAvailability[id]).toBe("stale");
  });
  it("does not overwrite a delta arriving during the read, even with a later REST timestamp", async () => {
    const id = seed(); let finish!: (value: unknown) => void;
    simulation.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const pending = run();
    useLiveStore.getState().applyDigitalTwinDelta({ delta_type: "update", scene_object: { ...useLiveStore.getState().sceneObjects[id], status: "paused" } }, "2026-09-10T00:00:30Z", scope);
    finish({ data: detail() }); await pending;
    expect(useLiveStore.getState().sceneObjects[id].status).toBe("paused");
  });
  it("rejects older timestamps/revisions and late responses after epoch/auth changes", async () => {
    const id = seed(); simulation.mockResolvedValue({ data: detail() }); await run();
    simulation.mockResolvedValue({ data: { ...detail(), revision: 2, status: "queued", updated_at: "2026-09-10T00:02:00Z" } }); await run();
    expect(useLiveStore.getState().sceneObjects[id].status).toBe("completed");
    simulation.mockResolvedValue({ data: { ...detail(), revision: 4, status: "queued", updated_at: "2026-09-09T00:00:00Z" } }); await run();
    expect(useLiveStore.getState().sceneObjects[id].status).toBe("completed");
    let finish!: (value: unknown) => void;
    simulation.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    let current = true; const pending = run(() => current); current = false; useLiveStore.getState().reset();
    finish({ data: detail() }); await pending;
    expect(useLiveStore.getState().sceneObjects).toEqual({});
  });
});
