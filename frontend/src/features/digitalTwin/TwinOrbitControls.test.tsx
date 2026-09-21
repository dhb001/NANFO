import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PerspectiveCamera } from "three";
import { TwinOrbitControls } from "./TwinOrbitControls";

const state = vi.hoisted(() => ({ frame: () => {}, camera: null as unknown as PerspectiveCamera, gl: { domElement: null as unknown as HTMLCanvasElement } }));
vi.mock("@react-three/fiber", () => ({ useThree: () => state, useFrame: (callback: () => void) => { state.frame = callback; } }));
describe("bounded Twin controls", () => {
  beforeEach(() => {
    state.camera = new PerspectiveCamera(); state.camera.position.set(18, 15, 18); state.camera.updateMatrixWorld();
    state.gl.domElement = document.createElement("canvas");
    state.gl.domElement.setPointerCapture = vi.fn(); state.gl.domElement.hasPointerCapture = () => false;
    Object.defineProperty(state.gl.domElement, "clientHeight", { value: 560 });
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
});
