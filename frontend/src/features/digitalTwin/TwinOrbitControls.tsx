import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { Spherical, Vector3 } from "three";
import { clampOrbitDistance, type CameraClip } from "./twinCamera";

const DEFAULT_LIMITS: Pick<CameraClip, "minDistance" | "maxDistance"> = { minDistance: 1, maxDistance: 400 };

/**
 * Twin only needs orbit/pan/zoom, not the general controls' cursor/dolly modes.
 * Works with `frameloop="demand"`: every interaction invalidates, and orbit damping keeps
 * requesting frames only while it is still moving. Zoom-out is clamped inside the far plane.
 */
export function TwinOrbitControls({ target, reducedMotion, limits = DEFAULT_LIMITS }: {
  target?: [number, number, number] | undefined;
  reducedMotion: boolean;
  limits?: Pick<CameraClip, "minDistance" | "maxDistance">;
}) {
  const { camera, gl, invalidate } = useThree();
  const center = useMemo(() => new Vector3(), []);
  const delta = useMemo(() => ({ theta: 0, phi: 0 }), []);
  const offset = useMemo(() => new Vector3(), []);
  const spherical = useMemo(() => new Spherical(), []);
  const axisX = useMemo(() => new Vector3(), []);
  const axisY = useMemo(() => new Vector3(), []);
  const bounds = useRef(limits);
  bounds.current = limits;

  useEffect(() => { if (target) { center.set(...target); delta.theta = delta.phi = 0; invalidate(); } }, [center, delta, target, invalidate]);
  useEffect(() => {
    // Limits can shrink (e.g. a smaller scene): pull an out-of-range camera back in.
    offset.copy(camera.position).sub(center);
    const length = offset.length();
    const clamped = clampOrbitDistance(length, limits);
    if (length > 0 && clamped !== length) {
      camera.position.copy(center).add(offset.setLength(clamped));
      camera.lookAt(center);
      invalidate();
    }
  }, [camera, center, offset, limits, invalidate]);

  useFrame(() => {
    if (!delta.theta && !delta.phi) return;
    spherical.setFromVector3(offset.copy(camera.position).sub(center));
    const factor = reducedMotion ? 1 : 0.3;
    spherical.theta += delta.theta * factor;
    spherical.phi = Math.max(0.01, Math.min(Math.PI - 0.01, spherical.phi + delta.phi * factor));
    camera.position.copy(offset.setFromSpherical(spherical).add(center)); camera.lookAt(center);
    delta.theta *= 1 - factor; delta.phi *= 1 - factor;
    if (Math.abs(delta.theta) + Math.abs(delta.phi) < 0.00001) delta.theta = delta.phi = 0;
    else invalidate();
  });

  useEffect(() => {
    const canvas = gl.domElement;
    const points = new Map<number, { x: number; y: number }>();
    const oldTouch = canvas.style.touchAction;
    canvas.style.touchAction = "none";
    canvas.tabIndex = 0; canvas.setAttribute("aria-label", "Twin scene: drag to orbit, right-drag to pan, wheel to zoom; arrow keys pan, + and - zoom");
    const pan = (x: number, y: number) => {
      const scale = camera.position.distanceTo(center) / Math.max(1, canvas.clientHeight);
      axisX.setFromMatrixColumn(camera.matrix, 0).multiplyScalar(-x * scale);
      axisX.addScaledVector(axisY.setFromMatrixColumn(camera.matrix, 1), y * scale);
      center.add(axisX); camera.position.add(axisX);
      // Keep the orbit centre inside the zoom envelope so content cannot be lost off-plane.
      const limit = bounds.current.maxDistance;
      if (center.length() > limit) {
        axisX.copy(center).setLength(limit).sub(center);
        center.add(axisX); camera.position.add(axisX);
      }
      invalidate();
    };
    const zoom = (amount: number) => {
      offset.copy(camera.position).sub(center);
      offset.setLength(clampOrbitDistance(offset.length() * Math.exp(Math.max(-1, Math.min(1, amount))), bounds.current));
      camera.position.copy(center).add(offset); camera.lookAt(center);
      invalidate();
    };
    const down = (event: PointerEvent) => { points.set(event.pointerId, { x: event.clientX, y: event.clientY }); canvas.setPointerCapture(event.pointerId); };
    const move = (event: PointerEvent) => {
      const previous = points.get(event.pointerId); if (!previous) return;
      const x = event.clientX - previous.x, y = event.clientY - previous.y;
      let other: { x: number; y: number } | undefined;
      for (const [id, point] of points) if (id !== event.pointerId) { other = point; break; }
      if (other) {
        const before = Math.hypot(previous.x - other.x, previous.y - other.y);
        const after = Math.hypot(event.clientX - other.x, event.clientY - other.y);
        if (before && after) zoom(Math.log(before / after));
        pan(x / 2, y / 2);
      } else if (event.button === 2 || event.buttons === 2 || event.shiftKey) pan(x, y);
      else { delta.theta -= x * 0.005; delta.phi -= y * 0.005; invalidate(); }
      previous.x = event.clientX; previous.y = event.clientY;
    };
    const up = (event: PointerEvent) => { points.delete(event.pointerId); if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId); };
    const wheel = (event: WheelEvent) => { event.preventDefault(); zoom(event.deltaY * (event.deltaMode === 1 ? 0.02 : 0.001)); };
    const menu = (event: Event) => event.preventDefault();
    const key = (event: KeyboardEvent) => {
      const step: readonly [number, number] | null = event.key === "ArrowLeft" ? [-20, 0] : event.key === "ArrowRight" ? [20, 0] : event.key === "ArrowUp" ? [0, -20] : event.key === "ArrowDown" ? [0, 20] : null;
      if (step) { event.preventDefault(); pan(step[0], step[1]); }
      if (event.key === "+" || event.key === "-") { event.preventDefault(); zoom(event.key === "+" ? -0.1 : 0.1); }
    };
    canvas.addEventListener("pointerdown", down); canvas.addEventListener("pointermove", move);
    canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", up);
    canvas.addEventListener("wheel", wheel, { passive: false }); canvas.addEventListener("contextmenu", menu); canvas.addEventListener("keydown", key);
    camera.lookAt(center);
    invalidate();
    return () => {
      canvas.style.touchAction = oldTouch;
      canvas.removeEventListener("pointerdown", down); canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerup", up); canvas.removeEventListener("pointercancel", up);
      canvas.removeEventListener("wheel", wheel); canvas.removeEventListener("contextmenu", menu); canvas.removeEventListener("keydown", key);
    };
  }, [axisX, axisY, camera, center, delta, gl, offset, invalidate]);
  return null;
}
