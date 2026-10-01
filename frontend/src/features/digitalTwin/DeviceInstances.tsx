import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import type { InstancedMesh } from "three";
import type { TwinCongestion, TwinNode } from "./sceneAdapter";
import type { DeviceGeometryKind } from "./deviceVisuals";
import { useSceneLabels } from "./sceneLabelContext";
import { alertOnlyLabelIds, buildDeviceBatches, deviceLabelSpecs, distanceLabelIds, pickedDeviceId, writeDeviceInstances, writeRingColors, type DeviceBatch } from "./deviceInstances";

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
const EMPTY_CONGESTION: Readonly<Record<string, TwinCongestion>> = Object.freeze({});

function Instances({ batch, onSelect, showCongestion, congestionByDevice }: {
  batch: DeviceBatch; onSelect: (id: string) => void; showCongestion: boolean; congestionByDevice: Readonly<Record<string, TwinCongestion>>;
}) {
  const body = useRef<InstancedMesh>(null);
  const ring = useRef<InstancedMesh>(null);
  const outline = useRef<InstancedMesh>(null);
  const invalidate = useThree((state) => state.invalidate);
  const { visual, nodes } = batch;
  useLayoutEffect(() => {
    if (body.current) writeDeviceInstances(body.current, batch);
    if (ring.current) writeDeviceInstances(ring.current, batch, true);
    if (outline.current) writeDeviceInstances(outline.current, batch);
    invalidate();
  }, [batch, showCongestion, invalidate]);
  // Telemetry-driven colours only: no geometry rebuild, no remount.
  useLayoutEffect(() => {
    if (!ring.current) return;
    writeRingColors(ring.current, batch, congestionByDevice);
    invalidate();
  }, [batch, congestionByDevice, showCongestion, invalidate]);
  // Capacity changes reconstruct the mesh; in-place updates refresh bounds and IDs.
  return <group>
    <instancedMesh ref={body} args={[undefined, undefined, nodes.length]} onClick={(event) => {
      const id = pickedDeviceId(batch, event.instanceId);
      if (id) { event.stopPropagation(); onSelect(id); }
    }}>
      <DeviceGeometry kind={visual.definition.geometry} radius={visual.radius} />
      <meshStandardMaterial color={visual.color} emissive={visual.emissive} emissiveIntensity={visual.emissiveIntensity} roughness={0.32} metalness={0.24} />
    </instancedMesh>
    {showCongestion ? <instancedMesh ref={ring} args={[undefined, undefined, nodes.length]} raycast={noRaycast}>
      <ringGeometry args={[visual.radius * 1.2, visual.radius * 1.2 + 0.14, 24]} />
      <meshBasicMaterial color="#ffffff" transparent opacity={0.78} />
    </instancedMesh> : null}
    {visual.outlineColor ? <instancedMesh ref={outline} args={[undefined, undefined, nodes.length]} raycast={noRaycast}>
      <sphereGeometry args={[visual.radius * 1.45, 16, 12]} />
      <meshBasicMaterial color={visual.outlineColor} transparent opacity={0.22} />
    </instancedMesh> : null}
  </group>;
}

const LABEL_SAMPLE_MS = 250;

/** Nearest labels follow the camera; sampling is throttled and allocation-free per frame. */
function useDeviceLabels(nodes: readonly TwinNode[], selectedId: string | null, alerts: ReadonlySet<string>, maxLabels: number, enabled: boolean) {
  const camera = useThree((state) => state.camera);
  const invalidate = useThree((state) => state.invalidate);
  const sampled = useMemo(() => camera.position.clone(), [camera]);
  const [revision, setRevision] = useState(0);
  const last = useRef(0);
  const pending = useRef<number | null>(null);
  useEffect(() => () => { if (pending.current !== null) window.clearTimeout(pending.current); }, []);
  useFrame(() => {
    if (!enabled || sampled.distanceToSquared(camera.position) < 4) return;
    const now = performance.now();
    if (now - last.current < LABEL_SAMPLE_MS) {
      // With on-demand frames, make sure a final sample happens after the camera settles.
      if (pending.current === null) pending.current = window.setTimeout(() => { pending.current = null; invalidate(); }, LABEL_SAMPLE_MS);
      return;
    }
    last.current = now;
    sampled.copy(camera.position);
    setRevision((value) => value + 1);
  });
  const specs = useMemo(() => {
    if (!enabled) return deviceLabelSpecs(nodes, alertOnlyLabelIds(nodes, alerts, maxLabels), alerts);
    const ids = distanceLabelIds(nodes, sampled, selectedId, alerts, maxLabels);
    return deviceLabelSpecs(nodes, ids, alerts);
    // `revision` re-evaluates the nearest set after the sampled position changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, nodes, selectedId, alerts, maxLabels, revision, sampled]);
  useSceneLabels("devices", specs);
}

export function DeviceInstances({ nodes, selectedId, onSelect, alerts, congestionByDevice = EMPTY_CONGESTION, showCongestion, showLabels, maxLabels }: {
  nodes: TwinNode[]; selectedId: string | null; onSelect: (id: string) => void; alerts: ReadonlySet<string>;
  congestionByDevice?: Readonly<Record<string, TwinCongestion>>;
  showCongestion: boolean; showLabels: boolean; maxLabels: number;
}) {
  const batches = useMemo(() => buildDeviceBatches(nodes, selectedId, alerts), [nodes, selectedId, alerts]);
  useDeviceLabels(nodes, selectedId, alerts, maxLabels, showLabels);
  return <group>
    {batches.map((batch) => <Instances key={`${batch.key}:${batch.nodes.length}`} batch={batch} onSelect={onSelect} showCongestion={showCongestion} congestionByDevice={congestionByDevice} />)}
  </group>;
}
