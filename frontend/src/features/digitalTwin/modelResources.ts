import type { BufferGeometry, Material, Object3D, Skeleton, Texture } from "three";

/** The loaded glTF owns these resources. Deduplicate across meshes and scene roots. */
export function disposeModelResources(roots: readonly Object3D[]): void {
  const geometries = new Set<BufferGeometry>();
  const materials = new Set<Material>();
  const textures = new Set<Texture>();
  const skeletons = new Set<Skeleton>();
  const images = new Set<{ close?: () => void }>();
  function texture(value: unknown) {
    if (!value || typeof value !== "object" || !(value as Texture).isTexture) return;
    const item = value as Texture;
    textures.add(item);
    for (const image of Array.isArray(item.image) ? item.image : [item.image]) if (image) images.add(image);
  }
  for (const root of roots) root.traverse((object) => {
    const mesh = object as Object3D & { geometry?: BufferGeometry; material?: Material | Material[]; skeleton?: Skeleton };
    if (mesh.geometry) geometries.add(mesh.geometry);
    if (mesh.skeleton) skeletons.add(mesh.skeleton);
    for (const material of Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []) materials.add(material);
  });
  for (const material of materials) {
    Object.values(material).forEach(texture);
    const uniforms = (material as Material & { uniforms?: Record<string, { value: unknown }> }).uniforms;
    for (const uniform of Object.values(uniforms ?? {})) {
      for (const value of Array.isArray(uniform.value) ? uniform.value : [uniform.value]) texture(value);
    }
  }
  geometries.forEach((item) => item.dispose());
  materials.forEach((item) => item.dispose());
  textures.forEach((item) => item.dispose());
  skeletons.forEach((item) => item.dispose());
  images.forEach((item) => item.close?.());
}

/** Load cancellation fences callbacks and releases resources even if the loader cannot abort. */
export function loadOwnedModel(
  load: (ready: (roots: Object3D[]) => void, failed: (error: unknown) => void) => void,
  ready: (root: Object3D) => void,
  failed: (error: unknown) => void,
): () => void {
  let cancelled = false;
  let owned: Object3D[] = [];
  load((roots) => {
    if (cancelled) { disposeModelResources(roots); return; }
    owned = roots;
    if (!roots[0]) { failed(new Error("GLB/GLTF contains no scene root.")); return; }
    ready(roots[0]);
  }, (error) => { if (!cancelled) failed(error); });
  return () => {
    cancelled = true;
    disposeModelResources(owned);
    owned = [];
  };
}
