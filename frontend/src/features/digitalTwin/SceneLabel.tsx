import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { useFrame, useThree } from "@react-three/fiber";
import { Group, Vector3 } from "three";

/** Noninteractive projected labels: one bounded DOM element, no occlusion/transform mode. */
export function SceneLabel({ children, position, distanceFactor = 18, style }: {
  children: ReactNode; position?: [number, number, number]; distanceFactor?: number; style?: CSSProperties;
}) {
  const { gl, camera, size } = useThree();
  const group = useRef<Group>(null);
  const root = useRef<Root>();
  const [element] = useState(() => document.createElement("div"));
  const [world] = useState(() => new Vector3());
  useEffect(() => {
    Object.assign(element.style, { position: "absolute", top: "0", left: "0", pointerEvents: "none", ...style });
    gl.domElement.parentElement?.appendChild(element);
    const mounted = createRoot(element); root.current = mounted;
    return () => { element.remove(); queueMicrotask(() => mounted.unmount()); };
  }, [element, gl, style]);
  useEffect(() => { root.current?.render(children); }, [children]);
  useFrame(() => {
    if (!group.current) return;
    group.current.getWorldPosition(world);
    const distance = world.distanceTo(camera.position);
    world.project(camera);
    element.style.display = world.z < -1 || world.z > 1 || Math.abs(world.x) > 1 || Math.abs(world.y) > 1 ? "none" : "block";
    element.style.transform = `translate(${(world.x + 1) * size.width / 2}px,${(1 - world.y) * size.height / 2}px) translate(-50%,-50%) scale(${Math.min(1.5, distanceFactor / Math.max(1, distance))})`;
  });
  return <group ref={group} position={position} />;
}
