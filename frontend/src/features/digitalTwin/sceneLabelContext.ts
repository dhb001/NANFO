import { createContext, useContext, useEffect } from "react";
import { useThree } from "@react-three/fiber";
import type { SceneLabelEngine, SceneLabelSpec } from "./sceneLabels";

export const SceneLabelContext = createContext<SceneLabelEngine | null>(null);

/**
 * Publish a layer's labels to the single label container. `specs` must be memoized:
 * the layer is re-reconciled only when its array identity changes.
 */
export function useSceneLabels(layer: string, specs: readonly SceneLabelSpec[]): void {
  const engine = useContext(SceneLabelContext);
  const invalidate = useThree((state) => state.invalidate);
  useEffect(() => {
    if (!engine) return;
    engine.setLayer(layer, specs);
    invalidate();
  }, [engine, layer, specs, invalidate]);
  useEffect(() => () => {
    engine?.removeLayer(layer);
  }, [engine, layer]);
}
