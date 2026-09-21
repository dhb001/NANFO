import { describe, expect, it, vi } from "vitest";
import { BoxGeometry, Group, Mesh, MeshStandardMaterial, Texture, type Object3D } from "three";
import { disposeModelResources, loadOwnedModel } from "./modelResources";

function fixture() {
  const image = { close: vi.fn() };
  const texture = new Texture(image);
  const otherTexture = new Texture(image);
  const material = new MeshStandardMaterial({ map: texture, normalMap: otherTexture });
  const geometry = new BoxGeometry();
  const root = new Group();
  root.add(new Mesh(geometry, [material, material]), new Mesh(geometry, material));
  const spies = [geometry, material, texture, otherTexture].map((resource) => vi.spyOn(resource, "dispose"));
  return { root, spies, image };
}

describe("imported GPU ownership", () => {
  it("disposes shared geometry/materials/textures and closes shared image data exactly once", () => {
    const { root, spies, image } = fixture();
    disposeModelResources([root, root]);
    spies.forEach((spy) => expect(spy).toHaveBeenCalledTimes(1));
    expect(image.close).toHaveBeenCalledTimes(1);
  });
  it("disposes loads that complete after cancellation without publishing a stale root", () => {
    const { root, spies } = fixture();
    let deliver!: (roots: Object3D[]) => void;
    let fail!: (error: unknown) => void;
    const ready = vi.fn(); const failed = vi.fn();
    const cancel = loadOwnedModel((success, error) => { deliver = success; fail = error; }, ready, failed);
    cancel(); deliver([root]); fail(new Error("late"));
    expect(ready).not.toHaveBeenCalled(); expect(failed).not.toHaveBeenCalled();
    spies.forEach((spy) => expect(spy).toHaveBeenCalledTimes(1));
  });
  it("releases every glTF scene on replacement/unmount; cleanup is idempotent", () => {
    const first = fixture(); const alternate = fixture();
    const cancel = loadOwnedModel((ready) => ready([first.root, alternate.root]), vi.fn(), vi.fn());
    cancel(); cancel();
    [...first.spies, ...alternate.spies].forEach((spy) => expect(spy).toHaveBeenCalledTimes(1));
  });
});
