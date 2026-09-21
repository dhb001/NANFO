import { getSimulationDetail } from "@/features/simulation/api";
import { getIntentDetail } from "@/features/intent/api";
import { ApiClientError } from "@/shared/lib/errors";
import { useLiveStore } from "./store";

// These are bounded reads of known objects, not a discovery endpoint or full history.
export async function reconcileKnownScenes(token: string, workspaceId: string, networkId: string, isCurrent: () => boolean, signal: AbortSignal, currentToken = () => token) {
  const initial = useLiveStore.getState();
  const epoch = initial.epoch;
  const current = () => !signal.aborted && isCurrent() && useLiveStore.getState().epoch === epoch;
  if (!current()) return;
  const known = initial.sceneObjectIdsNewestFirst.filter((id) => initial.sceneObjects[id]);
  const scoped = known.filter((id) => initial.sceneObjectScopes[id]?.workspaceId === workspaceId && initial.sceneObjectScopes[id]?.networkId === networkId);
  const selected = scoped.filter((id) => {
    const object = initial.sceneObjects[id];
    const identity = object.object_type === "simulation_state" ? object.simulation_id : object.object_type === "intent_state" ? object.intent_id : undefined;
    return typeof identity === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(identity);
  }).slice(0, 20);
  useLiveStore.setState((state) => ({ sceneReconciliation: { known: known.length, attempted: selected.length, unavailable: 0, omitted: known.length - selected.length },
    sceneObjectAvailability: { ...state.sceneObjectAvailability, ...Object.fromEntries(known.map((id) => [id, selected.includes(id) ? "pending" as const : "stale" as const])) } }));
  let cursor = 0;
  let unavailable = 0;
  await Promise.all(Array.from({ length: Math.min(2, selected.length) }, async () => {
    while (cursor < selected.length && current()) {
      const id = selected[cursor++];
      const expected = initial.sceneObjects[id];
      const request = new AbortController();
      const abort = () => request.abort();
      signal.addEventListener("abort", abort, { once: true });
      const timeout = window.setTimeout(abort, 10000);
      try {
        const simulation = expected.object_type === "simulation_state";
        const detail = simulation
          ? (await getSimulationDetail(currentToken(), expected.simulation_id!, request.signal)).data
          : (await getIntentDetail(currentToken(), expected.intent_id!, workspaceId, request.signal)).data;
        if (!current()) return;
        if (request.signal.aborted) throw new Error("Lifecycle detail timed out");
        const matches = detail.workspace_id === workspaceId && detail.network_id === networkId &&
          (simulation ? "simulation_id" in detail && detail.simulation_id === expected.simulation_id : "intent_id" in detail && detail.intent_id === expected.intent_id);
        if (!matches) {
          useLiveStore.getState().reconcileSceneObject(id, expected, epoch, "remove");
          unavailable++;
          continue;
        }
        if (typeof detail.status !== "string" || !Number.isFinite(Date.parse(detail.updated_at))) throw new Error("Invalid lifecycle detail");
        const object = { id, object_type: expected.object_type, status: detail.status,
          ...("simulation_id" in detail ? { simulation_id: detail.simulation_id, scenario_id: detail.scenario_id, state: detail.state, risk_gate: detail.risk_gate,
            changed_fields: { validation: detail.validation } } : { intent_id: detail.intent_id, changed_fields: { execution_provenance: detail.execution_provenance } }) };
        useLiveStore.getState().reconcileSceneObject(id, expected, epoch, { object, timestamp: detail.updated_at,
          revision: "revision" in detail && typeof detail.revision === "number" ? detail.revision : undefined });
        if (useLiveStore.getState().sceneObjectAvailability[id] === "stale") unavailable++;
      } catch (error) {
        if (!current()) return;
        unavailable++;
        useLiveStore.getState().reconcileSceneObject(id, expected, epoch,
          error instanceof ApiClientError && [401, 403, 404].includes(error.status ?? 0) ? "remove" : "stale");
      } finally {
        window.clearTimeout(timeout);
        signal.removeEventListener("abort", abort);
      }
    }
  }));
  if (current()) useLiveStore.setState({ sceneReconciliation: { known: known.length, attempted: selected.length, unavailable, omitted: known.length - selected.length } });
}
