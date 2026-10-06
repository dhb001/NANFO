import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PerspectiveCamera, Vector3 } from "three";
import { TwinOrbitControls } from "./TwinOrbitControls";
import { CameraClipController } from "./CameraClipController";
import { clampOrbitDistance, contentRadius, MIN_FAR_M, resolveCameraClip } from "./twinCamera";

const state = vi.hoisted(() => ({ frame: () => {}, camera: null as unknown as PerspectiveCamera, gl: { domElement: null as unknown as HTMLCanvasElement }, invalidate: vi.fn() }));
vi.mock("@react-three/fiber", () => ({
  useThree: (selector?: (value: typeof state) => unknown) => (selector ? selector(state) : state),
  useFrame: (callback: () => void) => { state.frame = callback; },
}));

describe("bounded Twin controls", () => {
  beforeEach(() => {
    state.camera = new PerspectiveCamera(); state.camera.position.set(18, 15, 18); state.camera.updateMatrixWorld();
    state.gl.domElement = document.createElement("canvas");
    state.gl.domElement.setPointerCapture = vi.fn(); state.gl.domElement.hasPointerCapture = () => false;
    Object.defineProperty(state.gl.domElement, "clientHeight", { value: 560 });
    state.invalidate.mockClear();
  });
  it("supports orbit, zoom and keyboard pan, stops immediately with reduced motion and removes listeners", () => {
    const view = render(<TwinOrbitControls reducedMotion target={[0, 0, 0]} />);
    const canvas = state.gl.domElement;
    const pointer = (type: string, x: number) => { const event = new Event(type); Object.assign(event, { pointerId: 1, clientX: x, clientY: 0, buttons: 1 }); canvas.dispatchEvent(event); };
    const before = state.camera.position.clone();
    act(() => { pointer("pointerdown", 0); pointer("pointermove", 30); state.frame(); });
    expect(state.camera.position.equals(before)).toBe(false);
    const stopped = state.camera.position.clone(); act(() => state.frame());
    expect(state.camera.position.equals(stopped)).toBe(true);
    canvas.dispatchEvent(new WheelEvent("wheel", { deltaY: -100 }));
    expect(state.camera.position.length()).toBeLessThan(stopped.length());
    const zoomed = state.camera.position.clone();
    canvas.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight" }));
    expect(state.camera.position.equals(zoomed)).toBe(false);
    view.unmount(); const final = state.camera.position.clone();
    canvas.dispatchEvent(new WheelEvent("wheel", { deltaY: 100 }));
    expect(state.camera.position.equals(final)).toBe(true);
    expect(canvas.style.touchAction).not.toBe("none");
  });

  it("clamps zoom to the limits (never beyond the far plane) and pulls the camera in when limits shrink", () => {
    const limits = { minDistance: 2, maxDistance: 100 };
    const view = render(<TwinOrbitControls reducedMotion target={[0, 0, 0]} limits={limits} />);
    const canvas = state.gl.domElement;
    for (let i = 0; i < 60; i += 1) canvas.dispatchEvent(new WheelEvent("wheel", { deltaY: 5000 }));
    expect(state.camera.position.length()).toBeCloseTo(100, 6);
    for (let i = 0; i < 60; i += 1) canvas.dispatchEvent(new WheelEvent("wheel", { deltaY: -5000 }));
    expect(state.camera.position.length()).toBeCloseTo(2, 6);
    for (let i = 0; i < 60; i += 1) canvas.dispatchEvent(new WheelEvent("wheel", { deltaY: 5000 }));
    view.rerender(<TwinOrbitControls reducedMotion target={[0, 0, 0]} limits={{ minDistance: 2, maxDistance: 40 }} />);
    expect(state.camera.position.length()).toBeCloseTo(40, 6);
    view.unmount();
  });

  it("requests frames on demand: interactions invalidate and damping stops requesting once settled", () => {
    const view = render(<TwinOrbitControls reducedMotion={false} target={[0, 0, 0]} />);
    const canvas = state.gl.domElement;
    state.invalidate.mockClear();
    canvas.dispatchEvent(new WheelEvent("wheel", { deltaY: 100 }));
    expect(state.invalidate).toHaveBeenCalledTimes(1);
    const pointer = (type: string, x: number) => { const event = new Event(type); Object.assign(event, { pointerId: 1, clientX: x, clientY: 0, buttons: 1 }); canvas.dispatchEvent(event); };
    act(() => { pointer("pointerdown", 0); pointer("pointermove", 40); });
    state.invalidate.mockClear();
    let frames = 0;
    while (frames < 200) { state.frame(); frames += 1; if (!state.invalidate.mock.calls.length) break; state.invalidate.mockClear(); }
    expect(frames).toBeLessThan(200);
    const settled = state.camera.position.clone();
    state.frame();
    expect(state.camera.position.equals(settled)).toBe(true);
    expect(state.invalidate).not.toHaveBeenCalled();
    view.unmount();
  });

  it("keeps the pan centre inside the zoom envelope", () => {
    const view = render(<TwinOrbitControls reducedMotion target={[0, 0, 0]} limits={{ minDistance: 1, maxDistance: 50 }} />);
    const canvas = state.gl.domElement;
    const orbitRadius = state.camera.position.length();
    state.camera.updateMatrixWorld();
    for (let i = 0; i < 400; i += 1) canvas.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight" }));
    // Panning translates camera and centre together, so the view direction is unchanged.
    state.camera.updateMatrixWorld();
    const centre = state.camera.position.clone().addScaledVector(state.camera.getWorldDirection(new Vector3()), orbitRadius);
    expect(centre.length()).toBeLessThanOrEqual(50 + 1e-6);
    expect(centre.length()).toBeGreaterThan(49);
    view.unmount();
  });
});

describe("camera clipping policy", () => {
  it("derives near/far and orbit limits from the content extent", () => {
    expect(resolveCameraClip(10, false)).toEqual({ near: 0.1, far: MIN_FAR_M, minDistance: 1, maxDistance: 160 });
    expect(resolveCameraClip(10, true).near).toBe(0.01);
    const campus = resolveCameraClip(25_000, false);
    expect(campus.far).toBeGreaterThanOrEqual(campus.maxDistance + 25_000);
    expect(campus.maxDistance).toBe(100_000);
    expect(campus.near).toBeCloseTo(campus.far / 20_000);
    expect(resolveCameraClip(Number.NaN, false)).toEqual(resolveCameraClip(0, false));
    expect(clampOrbitDistance(1e9, campus)).toBe(campus.maxDistance);
    expect(clampOrbitDistance(Number.POSITIVE_INFINITY, campus)).toBe(campus.maxDistance);
    expect(clampOrbitDistance(0, campus)).toBe(campus.minDistance);
  });

  it("measures content from points and boxes and ignores non-finite values", () => {
    expect(contentRadius({ points: [[3, 4, 0], [Number.NaN, 0, 0]], boxes: [{ min: [-10, 0, -1], max: [2, 0, 1] }] })).toBeCloseTo(Math.hypot(10, 0, 1));
    expect(contentRadius({})).toBe(0);
  });

  it("pushes near/far to the live camera after mount (R3F applies camera props only at creation)", () => {
    const camera = new PerspectiveCamera(46, 1, 0.1, 2000);
    state.camera = camera;
    const update = vi.spyOn(camera, "updateProjectionMatrix");
    const view = render(<CameraClipController clip={{ near: 0.1, far: 2000 }} />);
    expect(update).not.toHaveBeenCalled();
    view.rerender(<CameraClipController clip={{ near: 5, far: 150_000 }} />);
    expect([camera.near, camera.far]).toEqual([5, 150_000]);
    expect(update).toHaveBeenCalledTimes(1);
    expect(state.invalidate).toHaveBeenCalled();
    expect(camera.projectionMatrix.elements).toEqual(new PerspectiveCamera(46, 1, 5, 150_000).projectionMatrix.elements);
    view.unmount();
  });
});
