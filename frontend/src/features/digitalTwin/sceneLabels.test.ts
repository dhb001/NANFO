import { afterEach, describe, expect, it } from "vitest";
import { PerspectiveCamera } from "three";
import { SceneLabelEngine, type SceneLabelSpec } from "./sceneLabels";

const label = (id: string, position: [number, number, number], text = id): SceneLabelSpec => ({ id, position, text, variant: "device", distanceFactor: 18 });

function camera() {
  const value = new PerspectiveCamera(46, 800 / 560, 0.1, 2000);
  value.position.set(0, 0, 30);
  value.lookAt(0, 0, 0);
  value.updateMatrixWorld();
  return value;
}

describe("single-container scene labels", () => {
  let container: HTMLDivElement;
  afterEach(() => container?.remove());

  function engine() {
    container = document.createElement("div");
    document.body.appendChild(container);
    return new SceneLabelEngine(container);
  }

  it("renders every layer into one container and reconciles by layer + id", () => {
    const labels = engine();
    labels.setLayer("devices", [label("a", [0, 0, 0]), label("b", [1, 0, 0])]);
    labels.setLayer("links", [label("a", [2, 0, 0], "connected_to")]);
    expect(container.children).toHaveLength(3);
    expect(container.getAttribute("aria-hidden")).toBe("true");
    const first = container.children[0];
    labels.setLayer("devices", [label("a", [0, 0, 0], "renamed")]);
    expect(container.children).toHaveLength(2);
    expect(container.children[0]).toBe(first);
    expect(first.textContent).toBe("renamed");
    labels.removeLayer("links");
    expect(labels.size).toBe(1);
    labels.dispose();
    expect(container.children).toHaveLength(0);
  });

  it("writes text, never markup", () => {
    const labels = engine();
    labels.setLayer("devices", [label("x", [0, 0, 0], "<img src=x onerror=alert(1)>")]);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toBe("<img src=x onerror=alert(1)>");
  });

  it("skips all DOM writes while camera, viewport and labels are unchanged", () => {
    const labels = engine();
    const view = camera();
    labels.setLayer("devices", [label("a", [0, 0, 0]), label("b", [5, 2, 0])]);
    expect(labels.frame(view, 800, 560)).toBe(true);
    const element = container.children[0] as HTMLElement;
    expect(element.style.display).toBe("block");
    expect(element.style.transform).toBe("translate(400px,280px) translate(-50%,-50%) scale(0.6)");
    const writes = labels.writes;
    for (let i = 0; i < 10; i += 1) expect(labels.frame(view, 800, 560)).toBe(false);
    expect(labels.writes).toBe(writes);
    view.position.x += 3;
    view.updateMatrixWorld();
    expect(labels.frame(view, 800, 560)).toBe(true);
    expect(labels.writes).toBeGreaterThan(writes);
    const afterMove = labels.writes;
    expect(labels.frame(view, 1024, 560)).toBe(true);
    expect(labels.writes).toBeGreaterThan(afterMove);
  });

  it("hides labels outside the view and behind the camera", () => {
    const labels = engine();
    labels.setLayer("devices", [label("front", [0, 0, 0]), label("behind", [0, 0, 60]), label("aside", [500, 0, 0])]);
    labels.frame(camera(), 800, 560);
    const [front, behind, aside] = [...container.children] as HTMLElement[];
    expect(front.style.display).toBe("block");
    expect(behind.style.display).toBe("none");
    expect(aside.style.display).toBe("none");
  });
});
