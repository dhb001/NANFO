import { useLiveStore } from "./store";

export function SceneReconciliationStatus() {
  const reconciliation = useLiveStore((state) => state.sceneReconciliation);
  return <p role="status">{reconciliation
    ? `Lifecycle reconciliation: ${reconciliation.attempted} of ${reconciliation.known} known overlays requested; ${reconciliation.unavailable} unavailable; ${reconciliation.omitted} omitted.`
    : "Lifecycle reconciliation has not completed."} Partial known-object view only, capped at 20 detail reads per batch; not full history. Missing or pending evidence remains stale.</p>;
}
