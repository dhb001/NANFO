import { useLayoutEffect, useState, type PropsWithChildren } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { SceneLabelEngine } from "./sceneLabels";
import { SceneLabelContext } from "./sceneLabelContext";

/**
 * Hosts every in-scene label in ONE DOM container next to the canvas. Layers publish
 * text labels with `useSceneLabels`; a single frame callback positions them and skips
 * all DOM writes when the camera, viewport and labels are unchanged. Mount it as the
 * outermost scene element so its frame callback runs after camera controllers.
 */
export function SceneLabelHost({ children }: PropsWithChildren) {
  const gl = useThree((state) => state.gl);
  const [engine] = useState(() => new SceneLabelEngine(document.createElement("div")));
  useLayoutEffect(() => {
    gl.domElement.parentElement?.appendChild(engine.container);
    return () => engine.container.remove();
  }, [engine, gl]);
  useLayoutEffect(() => () => engine.dispose(), [engine]);
  useFrame((state) => { engine.frame(state.camera, state.size.width, state.size.height); });
  return <SceneLabelContext.Provider value={engine}>{children}</SceneLabelContext.Provider>;
}
