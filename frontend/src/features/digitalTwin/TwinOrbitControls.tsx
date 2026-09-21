import { useEffect, useMemo } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { Spherical, Vector3 } from "three";

/** Twin only needs orbit/pan/zoom, not the general controls' cursor/dolly modes. */
export function TwinOrbitControls({ target, reducedMotion }: { target?: [number, number, number]; reducedMotion: boolean }) {
  const { camera, gl } = useThree();
  const center = useMemo(() => new Vector3(), []);
  const delta = useMemo(() => ({ theta: 0, phi: 0 }), []);
  const offset = useMemo(() => new Vector3(), []);
  const spherical = useMemo(() => new Spherical(), []);
  useEffect(() => { if (target) { center.set(...target); delta.theta = delta.phi = 0; } }, [center, delta, target]);
  useFrame(() => {
    if (!delta.theta && !delta.phi) return;
    spherical.setFromVector3(offset.copy(camera.position).sub(center));
    const factor = reducedMotion ? 1 : 0.3;
    spherical.theta += delta.theta * factor;
    spherical.phi = Math.max(0.01, Math.min(Math.PI - 0.01, spherical.phi + delta.phi * factor));
    camera.position.copy(offset.setFromSpherical(spherical).add(center)); camera.lookAt(center);
    delta.theta *= 1 - factor; delta.phi *= 1 - factor;
    if (Math.abs(delta.theta) + Math.abs(delta.phi) < 0.00001) delta.theta = delta.phi = 0;
  });
  useEffect(() => {
    const canvas = gl.domElement;
    const points = new Map<number, { x: number; y: number }>();
    const oldTouch = canvas.style.touchAction;
    canvas.style.touchAction = "none";
    canvas.tabIndex = 0; canvas.setAttribute("aria-label", "Twin scene: drag to orbit, right-drag to pan, wheel to zoom");
    const pan = (x: number, y: number) => {
      const scale = camera.position.distanceTo(center) / Math.max(1, canvas.clientHeight);
      const move = new Vector3().setFromMatrixColumn(camera.matrix, 0).multiplyScalar(-x * scale);
      move.addScaledVector(new Vector3().setFromMatrixColumn(camera.matrix, 1), y * scale);
      center.add(move); camera.position.add(move);
    };
    const zoom = (amount: number) => {
      offset.copy(camera.position).sub(center);
      offset.setLength(Math.max(1, Math.min(1000000, offset.length() * Math.exp(Math.max(-1, Math.min(1, amount))))));
      camera.position.copy(center).add(offset); camera.lookAt(center);
    };
    const down = (event: PointerEvent) => { points.set(event.pointerId, { x: event.clientX, y: event.clientY }); canvas.setPointerCapture(event.pointerId); };
    const move = (event: PointerEvent) => {
      const previous = points.get(event.pointerId); if (!previous) return;
      const x = event.clientX - previous.x, y = event.clientY - previous.y;
      const other = [...points.entries()].find(([id]) => id !== event.pointerId)?.[1];
      if (other) {
        const before = Math.hypot(previous.x - other.x, previous.y - other.y);
        const after = Math.hypot(event.clientX - other.x, event.clientY - other.y);
        if (before && after) zoom(Math.log(before / after));
        pan(x / 2, y / 2);
      } else if (event.button === 2 || event.buttons === 2 || event.shiftKey) pan(x, y);
      else { delta.theta -= x * 0.005; delta.phi -= y * 0.005; }
      points.set(event.pointerId, { x: event.clientX, y: event.clientY });
    };
    const up = (event: PointerEvent) => { points.delete(event.pointerId); if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId); };
    const wheel = (event: WheelEvent) => { event.preventDefault(); zoom(event.deltaY * (event.deltaMode === 1 ? 0.02 : 0.001)); };
    const menu = (event: Event) => event.preventDefault();
    const key = (event: KeyboardEvent) => {
      const directions: Record<string, [number, number]> = { ArrowLeft: [-20, 0], ArrowRight: [20, 0], ArrowUp: [0, -20], ArrowDown: [0, 20] };
      if (directions[event.key]) { event.preventDefault(); pan(...directions[event.key]); }
      if (event.key === "+" || event.key === "-") { event.preventDefault(); zoom(event.key === "+" ? -0.1 : 0.1); }
    };
    canvas.addEventListener("pointerdown", down); canvas.addEventListener("pointermove", move);
    canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", up);
    canvas.addEventListener("wheel", wheel, { passive: false }); canvas.addEventListener("contextmenu", menu); canvas.addEventListener("keydown", key);
    camera.lookAt(center);
    return () => {
      canvas.style.touchAction = oldTouch;
      canvas.removeEventListener("pointerdown", down); canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerup", up); canvas.removeEventListener("pointercancel", up);
      canvas.removeEventListener("wheel", wheel); canvas.removeEventListener("contextmenu", menu); canvas.removeEventListener("keydown", key);
    };
  }, [camera, center, delta, gl, offset]);
  return null;
}
