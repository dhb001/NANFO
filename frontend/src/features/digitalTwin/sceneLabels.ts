import { Matrix4, Vector3, type Camera } from "three";

/**
 * One DOM container for every in-scene label (replaces one React root per label).
 *
 * Labels are plain text written with `textContent` (no HTML). `frame()` projects every
 * label only when the camera, the viewport or the label set changed since the previous
 * frame; otherwise it returns without touching the DOM or allocating. Individual label
 * styles are written only when their rounded position/scale/visibility changed.
 */

export type SceneLabelVariant = "device" | "alert" | "link" | "overlay" | "geometry" | "building" | "rf";

export interface SceneLabelSpec {
  id: string;
  position: readonly [number, number, number];
  text: string;
  variant: SceneLabelVariant;
  /** World distance at which the label renders at scale 1 (closer is capped at 1.5×). */
  distanceFactor: number;
}

interface Entry {
  spec: SceneLabelSpec;
  element: HTMLDivElement;
  visible: boolean;
  x: number;
  y: number;
  scale: number;
}

const MAX_SCALE = 1.5;

function quantize(value: number, step: number) {
  return Math.round(value / step) * step;
}

export class SceneLabelEngine {
  private readonly layers = new Map<string, readonly SceneLabelSpec[]>();
  private readonly entries = new Map<string, Entry>();
  private readonly view = new Matrix4();
  private readonly projection = new Matrix4();
  private readonly point = new Vector3();
  private width = -1;
  private height = -1;
  private dirty = true;
  /** Count of DOM style writes (diagnostics for tests and profiling). */
  writes = 0;

  constructor(readonly container: HTMLElement, private readonly document: Document = container.ownerDocument) {
    container.classList.add("twin-label-layer");
    container.setAttribute("aria-hidden", "true");
  }

  setLayer(layer: string, specs: readonly SceneLabelSpec[]): void {
    this.layers.set(layer, specs);
    this.reconcile();
  }

  removeLayer(layer: string): void {
    if (this.layers.delete(layer)) this.reconcile();
  }

  private reconcile(): void {
    const next = new Map<string, SceneLabelSpec>();
    for (const [layer, specs] of this.layers) for (const spec of specs) next.set(`${layer}\u0000${spec.id}`, spec);
    for (const [key, entry] of this.entries) {
      if (!next.has(key)) { entry.element.remove(); this.entries.delete(key); }
    }
    for (const [key, spec] of next) {
      let entry = this.entries.get(key);
      if (!entry) {
        const element = this.document.createElement("div");
        element.setAttribute("aria-hidden", "true");
        element.style.display = "none";
        this.container.appendChild(element);
        entry = { spec, element, visible: false, x: Number.NaN, y: Number.NaN, scale: Number.NaN };
        this.entries.set(key, entry);
      }
      if (entry.element.textContent !== spec.text) entry.element.textContent = spec.text;
      const className = `twin-label twin-label--${spec.variant}`;
      if (entry.element.className !== className) entry.element.className = className;
      entry.spec = spec;
    }
    this.dirty = true;
  }

  get size(): number {
    return this.entries.size;
  }

  /** Returns true when any label style was written. */
  frame(camera: Camera, width: number, height: number): boolean {
    camera.updateMatrixWorld();
    if (!this.dirty && width === this.width && height === this.height &&
        this.view.equals(camera.matrixWorld) && this.projection.equals(camera.projectionMatrix)) {
      return false;
    }
    this.dirty = false;
    this.width = width;
    this.height = height;
    this.view.copy(camera.matrixWorld);
    this.projection.copy(camera.projectionMatrix);
    const cameraPosition = camera.position;
    let wrote = false;
    for (const entry of this.entries.values()) {
      const [x, y, z] = entry.spec.position;
      this.point.set(x, y, z);
      const distance = this.point.distanceTo(cameraPosition);
      this.point.project(camera);
      const visible = this.point.z >= -1 && this.point.z <= 1 && Math.abs(this.point.x) <= 1 && Math.abs(this.point.y) <= 1;
      if (visible !== entry.visible) {
        entry.element.style.display = visible ? "block" : "none";
        entry.visible = visible;
        this.writes += 1;
        wrote = true;
      }
      if (!visible) continue;
      const screenX = quantize(((this.point.x + 1) * width) / 2, 0.5);
      const screenY = quantize(((1 - this.point.y) * height) / 2, 0.5);
      const scale = quantize(Math.min(MAX_SCALE, entry.spec.distanceFactor / Math.max(1, distance)), 0.01);
      if (screenX === entry.x && screenY === entry.y && scale === entry.scale) continue;
      entry.x = screenX;
      entry.y = screenY;
      entry.scale = scale;
      entry.element.style.transform = `translate(${screenX}px,${screenY}px) translate(-50%,-50%) scale(${scale})`;
      this.writes += 1;
      wrote = true;
    }
    return wrote;
  }

  dispose(): void {
    for (const entry of this.entries.values()) entry.element.remove();
    this.entries.clear();
    this.layers.clear();
  }
}
