import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { useThree } from "@react-three/fiber";
import { BoxGeometry, DoubleSide, MeshStandardMaterial, type InstancedMesh, type Plane } from "three";
import type { GeometryShape } from "./spatialGeometry";
import { useSceneLabels } from "./sceneLabelContext";
import { CANONICAL_MATERIALS, buildCanonicalBatches, canonicalLabels, type CanonicalBatch, type CanonicalClass } from "./canonicalInstances";

const noRaycast = () => {};

function CanonicalBatchMesh({ batch, geometry, material }: { batch: CanonicalBatch; geometry: BoxGeometry; material: MeshStandardMaterial }) {
  const mesh = useRef<InstancedMesh>(null);
  const invalidate = useThree((state) => state.invalidate);
  useLayoutEffect(() => {
    const target = mesh.current;
    if (!target) return;
    target.instanceMatrix.array.set(batch.matrices);
    target.instanceMatrix.needsUpdate = true;
    target.count = batch.objectIds.length;
    // Per-floor/class bounds: three culls the whole batch when it is outside the view.
    target.computeBoundingBox();
    target.computeBoundingSphere();
    invalidate();
  }, [batch, invalidate]);
  return <instancedMesh ref={mesh} name={`canonical:${batch.key}`} args={[geometry, material, batch.objectIds.length]} raycast={noRaycast} dispose={null} />;
}

/** Canonical geometry as one instanced draw per floor and material class (was one mesh per object). */
export function CanonicalGeometry({ shapes, floorByObject, clippingPlanes, showLabels }: {
  shapes: GeometryShape[];
  floorByObject: ReadonlyMap<string, string>;
  clippingPlanes: Plane[];
  showLabels: boolean;
}) {
  const invalidate = useThree((state) => state.invalidate);
  const batches = useMemo(() => buildCanonicalBatches(shapes, floorByObject), [shapes, floorByObject]);
  const geometry = useMemo(() => new BoxGeometry(1, 1, 1), []);
  const materials = useMemo(() => Object.fromEntries((Object.keys(CANONICAL_MATERIALS) as CanonicalClass[]).map((kind) => {
    const config = CANONICAL_MATERIALS[kind];
    return [kind, new MeshStandardMaterial({ color: config.color, side: DoubleSide, transparent: true, opacity: config.opacity, depthWrite: config.depthWrite })];
  })) as Record<CanonicalClass, MeshStandardMaterial>, []);
  useEffect(() => () => { geometry.dispose(); for (const material of Object.values(materials)) material.dispose(); }, [geometry, materials]);
  useEffect(() => {
    for (const material of Object.values(materials)) material.clippingPlanes = clippingPlanes;
    invalidate();
  }, [materials, clippingPlanes, invalidate]);
  const labels = useMemo(() => (showLabels ? canonicalLabels(shapes, clippingPlanes) : []), [showLabels, shapes, clippingPlanes]);
  useSceneLabels("canonical-geometry", labels);
  return <group name="canonical-geometry">
    {batches.map((batch) => <CanonicalBatchMesh key={`${batch.key}:${batch.objectIds.length}`} batch={batch} geometry={geometry} material={materials[batch.kind]} />)}
  </group>;
}
