import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { SceneLabel } from "./SceneLabel";
import { Vector3, type InstancedMesh } from "three";
import type { TwinNode } from "./sceneAdapter";
import type { DeviceGeometryKind } from "./deviceVisuals";
import { buildDeviceBatches, distanceLabelIds, pickedDeviceId, writeDeviceInstances, type DeviceBatch } from "./deviceInstances";

function DeviceGeometry({ kind, radius }: { kind: DeviceGeometryKind; radius: number }) {
  switch (kind) {
    case "box": return <boxGeometry args={[radius * 1.5, radius * 1.5, radius * 1.5]} />;
    case "cylinder": return <cylinderGeometry args={[radius * 0.85, radius * 0.85, radius * 1.7, 16]} />;
    case "cone": return <coneGeometry args={[radius, radius * 1.9, 16]} />;
    case "octahedron": return <octahedronGeometry args={[radius, 0]} />;
    case "sphere": return <sphereGeometry args={[radius, 16, 12]} />;
    default: return <icosahedronGeometry args={[radius, 1]} />;
  }
}

const noRaycast = () => {};
function Instances({ batch, onSelect }: { batch: DeviceBatch; onSelect: (id: string) => void }) {
  const body = useRef<InstancedMesh>(null);
  const ring = useRef<InstancedMesh>(null);
  const outline = useRef<InstancedMesh>(null);
  const { visual, nodes } = batch;
  useLayoutEffect(() => {
    if (body.current) writeDeviceInstances(body.current, batch);
    if (ring.current) writeDeviceInstances(ring.current, batch, true);
    if (outline.current) writeDeviceInstances(outline.current, batch);
  }, [batch]);
  // Capacity changes reconstruct the mesh; in-place updates refresh bounds and IDs.
  return <group>
    <instancedMesh ref={body} args={[undefined, undefined, nodes.length]} onClick={(event) => {
      const id = pickedDeviceId(batch, event.instanceId);
      if (id) { event.stopPropagation(); onSelect(id); }
    }}>
      <DeviceGeometry kind={visual.definition.geometry} radius={visual.radius} />
      <meshStandardMaterial color={visual.color} emissive={visual.emissive} emissiveIntensity={visual.emissiveIntensity} roughness={0.32} metalness={0.24} />
    </instancedMesh>
    {visual.ringColor ? <instancedMesh ref={ring} args={[undefined, undefined, nodes.length]} raycast={noRaycast}>
      <ringGeometry args={[visual.radius * 1.2, visual.radius * 1.2 + 0.14, 24]} />
      <meshBasicMaterial color={visual.ringColor} transparent opacity={0.78} />
    </instancedMesh> : null}
    {visual.outlineColor ? <instancedMesh ref={outline} args={[undefined, undefined, nodes.length]} raycast={noRaycast}>
      <sphereGeometry args={[visual.radius * 1.45, 16, 12]} />
      <meshBasicMaterial color={visual.outlineColor} transparent opacity={0.22} />
    </instancedMesh> : null}
  </group>;
}

function DistanceLabels({ nodes, selectedId, alerts, maxLabels }: { nodes: TwinNode[]; selectedId: string | null; alerts: ReadonlySet<string>; maxLabels: number }) {
  const { camera } = useThree();
  const [position, setPosition] = useState(() => camera.position.clone());
  const last = useRef(0);
  const sampled = useRef(new Vector3(Infinity, Infinity, Infinity));
  useFrame(({ clock }) => {
    if (clock.elapsedTime - last.current < 0.25 || sampled.current.distanceToSquared(camera.position) < 4) return;
    last.current = clock.elapsedTime;
    sampled.current.copy(camera.position);
    setPosition(camera.position.clone());
  });
  const ids = useMemo(() => distanceLabelIds(nodes, position, selectedId, alerts, maxLabels), [nodes, position, selectedId, alerts, maxLabels]);
  return <group>{nodes.filter((node) => ids.has(node.id)).map((node) => <SceneLabel key={node.id} position={[node.x, node.y, node.z]} distanceFactor={18}>
    <div data-device-label={node.id} style={{ padding: "0.16rem 0.34rem", borderRadius: 8, border: "1px solid rgba(20,48,36,.25)", background: "rgba(248,252,246,.88)", fontSize: 10, fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>{node.hostname}</div>
  </SceneLabel>)}</group>;
}

export function DeviceInstances({ nodes, selectedId, onSelect, alerts, showCongestion, showLabels, maxLabels }: {
  nodes: TwinNode[]; selectedId: string | null; onSelect: (id: string) => void; alerts: ReadonlySet<string>;
  showCongestion: boolean; showLabels: boolean; maxLabels: number;
}) {
  const batches = useMemo(() => buildDeviceBatches(nodes, selectedId, alerts, showCongestion), [nodes, selectedId, alerts, showCongestion]);
  return <group>
    {batches.map((batch) => <Instances key={`${batch.key}:${batch.nodes.length}`} batch={batch} onSelect={onSelect} />)}
    {showLabels ? <DistanceLabels nodes={nodes} selectedId={selectedId} alerts={alerts} maxLabels={maxLabels} /> : null}
  </group>;
}
