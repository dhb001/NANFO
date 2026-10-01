import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { BufferGeometry, Color, Float32BufferAttribute, Matrix4, Object3D, Vector3, type InstancedMesh } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { TwinOrbitControls } from "./TwinOrbitControls";
import { SceneLabelHost } from "./SceneLabel";
import { useSceneLabels } from "./sceneLabelContext";
import { contentRadius, resolveCameraClip } from "./twinCamera";
import { CameraClipController } from "./CameraClipController";
import { loadOwnedModel } from "./modelResources";
import { DeviceInstances } from "./DeviceInstances";
import type { SpatialScene } from "@/shared/types/spatial";
import { EMPTY_SPATIAL_SCENE } from "./spatialScene";
import { buildSpatialGeometry, floorClipPlane, geometryCameraFocus } from "./spatialGeometry";
import { CanonicalGeometry } from "./CanonicalGeometry";
import type { ModelRegistration } from "./ModelRegistration";
import type { TwinCongestion, TwinLink, TwinNode, TwinOverlayObject } from "./sceneAdapter";
import type { MeasuredPathSegment } from "./measuredPathMapping";
import type { RFSample } from "./rfArtifact";
import { CampusBuildings } from "@/features/digitalTwin/CampusBuildings";
import {
  type CampusBuilding,
  buildBuildingByNodeIdIndex,
  deriveSpatialBuildingScope,
  isNodeVisibleInBuildingView,
  resolveCampusBuildingCameraFocus,
  type CampusBuildingViewState,
} from "@/features/digitalTwin/campusBuildings";
import { DEFAULT_MAX_DEVICE_LABELS } from "@/features/digitalTwin/deviceVisuals";
import { overlayColor } from "./twinStatusTones";
import { MAX_SCENE_OVERLAYS, linkLabelSpecs, linkSegmentPositions, overlayLabelSpecs, rfLabelSpecs } from "./sceneLayers";

export interface TwinSceneLayers {
  showLinks: boolean;
  showLabels: boolean;
  showCongestion: boolean;
  showOverlays: boolean;
  showModel: boolean;
}

export interface TwinSceneProps {
  spatialScene?: SpatialScene | undefined;
  rfSamples?: readonly RFSample[] | undefined;
  measuredPath?: readonly MeasuredPathSegment[] | undefined;
  /** Topology/placement only; telemetry colours arrive separately in `congestionByDevice`. */
  nodes: TwinNode[];
  links: TwinLink[];
  overlays: TwinOverlayObject[];
  /** Visual heuristic per device (ring colours only), updated in animation-frame batches. */
  congestionByDevice?: Readonly<Record<string, TwinCongestion>> | undefined;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  reducedMotion: boolean;
  layers: TwinSceneLayers;
  /** Devices with an active backend alert (REST snapshot + realtime deltas, derived upstream). */
  alertingDeviceIds?: ReadonlySet<string> | undefined;
  /** Maximum simultaneous labels per layer. */
  maxDeviceLabels?: number | undefined;
  importedModelUrl?: string | null | undefined;
  modelRegistration?: ModelRegistration | null | undefined;
  importedCampusBuildings?: readonly CampusBuilding[] | undefined;
  onImportedModelStatusChange?: ((status: "loading" | "ready" | "error", message?: string) => void) | undefined;
  buildingViewState?: CampusBuildingViewState | undefined;
  onSelectBuilding?: ((buildingId: string) => void) | undefined;
}

const noRaycast = () => {};

function CameraFocusController({ focusPosition, focusTarget, reducedMotion }: {
  focusPosition: [number, number, number] | null;
  focusTarget: [number, number, number] | null;
  reducedMotion: boolean;
}) {
  const camera = useThree((state) => state.camera);
  const invalidate = useThree((state) => state.invalidate);
  const desiredPosition = useMemo(() => new Vector3(), []);
  const desiredTarget = useMemo(() => new Vector3(), []);
  const currentLookAt = useMemo(() => new Vector3(), []);
  const focusing = useRef(false);
  useEffect(() => {
    focusing.current = Boolean(focusPosition && focusTarget);
    if (focusing.current) invalidate();
  }, [focusPosition, focusTarget, invalidate]);

  useFrame(() => {
    if (!focusing.current || !focusPosition || !focusTarget) return;
    desiredPosition.set(focusPosition[0], focusPosition[1], focusPosition[2]);
    desiredTarget.set(focusTarget[0], focusTarget[1], focusTarget[2]);
    const alpha = reducedMotion ? 1 : 0.12;
    camera.position.lerp(desiredPosition, alpha);
    currentLookAt.lerp(desiredTarget, alpha);
    camera.lookAt(currentLookAt);
    if (reducedMotion || camera.position.distanceToSquared(desiredPosition) < 0.001) focusing.current = false;
    else invalidate();
  });
  return null;
}

function LinksLayer({ links, showLabels, maxLabels }: { links: TwinLink[]; showLabels: boolean; maxLabels: number }) {
  const geometry = useMemo(() => {
    const result = new BufferGeometry();
    result.setAttribute("position", new Float32BufferAttribute(linkSegmentPositions(links), 3));
    result.computeBoundingSphere();
    return result;
  }, [links]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  const labels = useMemo(() => (showLabels ? linkLabelSpecs(links, maxLabels) : []), [links, showLabels, maxLabels]);
  useSceneLabels("links", labels);
  return (
    <lineSegments>
      <primitive attach="geometry" object={geometry} />
      <lineBasicMaterial color="#608ea8" transparent opacity={0.72} />
    </lineSegments>
  );
}

/** One instanced draw for up to 160 overlays; colours are explicit backend-state tones. */
function OverlaysLayer({ overlays, showLabels }: { overlays: TwinOverlayObject[]; showLabels: boolean }) {
  const mesh = useRef<InstancedMesh>(null);
  const invalidate = useThree((state) => state.invalidate);
  const shown = useMemo(() => overlays.slice(0, MAX_SCENE_OVERLAYS), [overlays]);
  useLayoutEffect(() => {
    const target = mesh.current;
    if (!target) return;
    const matrix = new Matrix4();
    const color = new Color();
    shown.forEach((overlay, index) => {
      target.setMatrixAt(index, matrix.makeTranslation(overlay.x, overlay.y, overlay.z));
      target.setColorAt(index, color.set(overlayColor(overlay)));
    });
    target.count = shown.length;
    target.instanceMatrix.needsUpdate = true;
    if (target.instanceColor) target.instanceColor.needsUpdate = true;
    target.computeBoundingSphere();
    invalidate();
  }, [shown, invalidate]);
  const labels = useMemo(() => (showLabels ? overlayLabelSpecs(shown) : []), [shown, showLabels]);
  useSceneLabels("overlays", labels);
  if (!shown.length) return null;
  return (
    <instancedMesh key={shown.length} ref={mesh} args={[undefined, undefined, shown.length]} raycast={noRaycast}>
      <octahedronGeometry args={[0.34, 0]} />
      <meshStandardMaterial color="#ffffff" emissive="#12263d" emissiveIntensity={0.2} roughness={0.34} metalness={0.08} />
    </instancedMesh>
  );
}

function RFSamplesLayer({ samples, showLabels }: { samples: readonly RFSample[]; showLabels: boolean }) {
  const mesh = useRef<InstancedMesh>(null);
  const invalidate = useThree((state) => state.invalidate);
  useLayoutEffect(() => {
    const target = mesh.current;
    if (!target) return;
    const matrix = new Matrix4();
    samples.forEach((sample, index) => target.setMatrixAt(index, matrix.makeTranslation(...sample.position)));
    target.count = samples.length;
    target.instanceMatrix.needsUpdate = true;
    target.computeBoundingSphere();
    invalidate();
  }, [samples, invalidate]);
  const labels = useMemo(() => (showLabels ? rfLabelSpecs(samples) : []), [samples, showLabels]);
  useSceneLabels("rf-samples", labels);
  if (!samples.length) return null;
  return (
    <instancedMesh key={samples.length} ref={mesh} args={[undefined, undefined, samples.length]} raycast={noRaycast}>
      <octahedronGeometry args={[0.24, 0]} />
      <meshBasicMaterial color="#9a43cb" />
    </instancedMesh>
  );
}

function disableRaycastForModel(object: Object3D): void {
  object.traverse((child) => {
    const candidate = child as Object3D & { isMesh?: boolean; raycast?: (...args: unknown[]) => void };
    if (candidate.isMesh && typeof candidate.raycast === "function") candidate.raycast = () => {};
  });
}

function SessionModelLayer({ modelUrl, visible, onStatusChange, registration }: {
  modelUrl: string | null | undefined;
  visible: boolean;
  onStatusChange?: ((status: "loading" | "ready" | "error", message?: string) => void) | undefined;
  registration?: ModelRegistration | null | undefined;
}) {
  const [loaded, setLoaded] = useState<{ url: string; root: Object3D } | null>(null);
  useEffect(() => {
    if (!modelUrl) {
      setLoaded(null);
      return;
    }
    setLoaded(null);
    onStatusChange?.("loading");
    // The only full glTF parse of the model (validation is structural, see modelAsset.ts).
    const loader = new GLTFLoader();
    return loadOwnedModel(
      (ready, failed) => loader.load(modelUrl, (gltf) => ready([...new Set([gltf.scene, ...gltf.scenes].filter(Boolean))]), undefined, failed),
      (root) => {
        disableRaycastForModel(root);
        setLoaded({ url: modelUrl, root });
        onStatusChange?.("ready");
      },
      (error) => {
        setLoaded(null);
        onStatusChange?.("error", error instanceof Error ? error.message : "GLB/GLTF load failed.");
      },
    );
  }, [modelUrl, onStatusChange]);
  if (!visible || !loaded || loaded.url !== modelUrl || !registration) return null;
  return (
    <group position={registration.position} rotation={[...registration.rotation, "ZYX"]} scale={registration.scale} dispose={null}>
      <primitive object={loaded.root} dispose={null} />
    </group>
  );
}

const EMPTY_ALERTING: ReadonlySet<string> = new Set<string>();
const EMPTY_CONGESTION: Readonly<Record<string, TwinCongestion>> = Object.freeze({});

function MeasuredPathLayer({ segments }: { segments: readonly MeasuredPathSegment[] }) {
  return <group>{segments.map((segment) => {
    const source = new Vector3(...segment.source);
    const delta = new Vector3(...segment.target).sub(source);
    const length = delta.length();
    return length > 0 ? <arrowHelper key={segment.id} args={[delta.normalize(), source, length, "#a332d1", Math.min(0.9, length / 3), Math.min(0.5, length / 5)]} /> : null;
  })}</group>;
}

export function TwinScene({
  spatialScene,
  rfSamples,
  nodes,
  links,
  overlays,
  congestionByDevice = EMPTY_CONGESTION,
  selectedNodeId,
  onSelectNode,
  reducedMotion,
  layers,
  alertingDeviceIds = EMPTY_ALERTING,
  maxDeviceLabels = DEFAULT_MAX_DEVICE_LABELS,
  importedModelUrl,
  modelRegistration,
  importedCampusBuildings,
  onImportedModelStatusChange,
  buildingViewState,
  onSelectBuilding,
  measuredPath,
}: TwinSceneProps) {
  const [floorId, setFloorId] = useState("");
  const [cutHeight, setCutHeight] = useState("");
  const geometry = useMemo(() => buildSpatialGeometry(spatialScene ?? EMPTY_SPATIAL_SCENE), [spatialScene]);
  const activeFloor = geometry.floors.some((floor) => floor.object_id === floorId) ? floorId : "";
  const shapes = useMemo(() => geometry.shapes.filter((shape) => !activeFloor || geometry.floorByObject.get(shape.object.object_id) === activeFloor), [geometry, activeFloor]);
  const clippingPlanes = useMemo(() => floorClipPlane(geometry.world.get(activeFloor), cutHeight), [geometry, activeFloor, cutHeight]);
  const canonicalFocus = useMemo(() => geometryCameraFocus(shapes), [shapes]);
  const campusBuildings = useMemo(() => (importedCampusBuildings?.length ? [...importedCampusBuildings].sort((left, right) => left.id.localeCompare(right.id)) : []), [importedCampusBuildings]);
  const buildingByNodeId = useMemo(() => buildBuildingByNodeIdIndex(campusBuildings), [campusBuildings]);
  const selectedBuildingIdFromNode = selectedNodeId ? (buildingByNodeId[selectedNodeId] ?? null) : null;
  const selectedFloorKeyFromNode = useMemo(() => {
    if (!selectedNodeId) return null;
    return deriveSpatialBuildingScope(nodes.find((node) => node.id === selectedNodeId)?.spatialRefId).floorKey;
  }, [nodes, selectedNodeId]);
  const mergedBuildingViewState = useMemo<CampusBuildingViewState | undefined>(() => {
    if (!buildingViewState && !selectedBuildingIdFromNode) return undefined;
    return {
      ...(buildingViewState ?? {}),
      selectedBuildingId: buildingViewState?.selectedBuildingId ?? selectedBuildingIdFromNode,
      selectedFloorKey: buildingViewState?.selectedFloorKey ?? selectedFloorKeyFromNode,
    };
  }, [buildingViewState, selectedBuildingIdFromNode, selectedFloorKeyFromNode]);
  const selectedBuilding = useMemo(
    () => (mergedBuildingViewState?.selectedBuildingId ? campusBuildings.find((building) => building.id === mergedBuildingViewState.selectedBuildingId) ?? null : null),
    [campusBuildings, mergedBuildingViewState?.selectedBuildingId],
  );
  const cameraFocus = useMemo(() => {
    if (activeFloor) return canonicalFocus;
    const node = nodes.find((item) => item.id === selectedNodeId && item.placementSource === "canonical");
    if (node) return { position: [node.x + 18, node.y + 15, node.z + 18] as [number, number, number], target: [node.x, node.y, node.z] as [number, number, number] };
    if (!selectedBuilding) return canonicalFocus;
    return resolveCampusBuildingCameraFocus(selectedBuilding, { floorKey: mergedBuildingViewState?.selectedFloorKey });
  }, [selectedBuilding, mergedBuildingViewState?.selectedFloorKey, nodes, selectedNodeId, canonicalFocus, activeFloor]);
  const visibleNodes = useMemo(() => {
    const point = new Vector3();
    return nodes.filter((node) =>
      (!activeFloor || geometry.floorByObject.get(node.spatialObjectId ?? "") === activeFloor)
      && clippingPlanes.every((plane) => plane.distanceToPoint(point.set(node.x, node.y, node.z)) >= 0)
      && isNodeVisibleInBuildingView(node.spatialRefId, mergedBuildingViewState));
  }, [nodes, mergedBuildingViewState, activeFloor, geometry, clippingPlanes]);
  const sceneRadius = useMemo(() => contentRadius({
    points: [
      ...nodes.map((node) => [node.x, node.y, node.z] as const),
      ...overlays.map((overlay) => [overlay.x, overlay.y, overlay.z] as const),
      ...(rfSamples ?? []).map((sample) => sample.position),
      ...(modelRegistration ? [modelRegistration.position] : []),
    ],
    boxes: [
      ...geometry.shapes.map((shape) => ({ min: shape.bounds.min.toArray(), max: shape.bounds.max.toArray() })),
      ...campusBuildings.map((building) => ({
        min: [building.x - building.width / 2, building.baseY, building.z - building.depth / 2] as const,
        max: [building.x + building.width / 2, building.baseY + building.height, building.z + building.depth / 2] as const,
      })),
    ],
  }), [nodes, overlays, rfSamples, modelRegistration, geometry, campusBuildings]);
  const clip = useMemo(() => resolveCameraClip(sceneRadius, Boolean(selectedNodeId) && !activeFloor), [sceneRadius, selectedNodeId, activeFloor]);
  const orbitLimits = useMemo(() => ({ minDistance: clip.minDistance, maxDistance: clip.maxDistance }), [clip.minDistance, clip.maxDistance]);
  const visibleLinks = useMemo(() => {
    const ids = new Set(visibleNodes.map((node) => node.id));
    return links.filter((link) => ids.has(link.sourceId) && ids.has(link.targetId));
  }, [links, visibleNodes]);
  const shownRf = useMemo(() => (activeFloor ? [] : rfSamples ?? []), [activeFloor, rfSamples]);

  return (<>
    {geometry.floors.length ? <div className="twin-floor-controls">
      <label>Canonical floor <select aria-label="Canonical floor" value={activeFloor} onChange={(event) => { setFloorId(event.target.value); setCutHeight(""); }}>
        <option value="">All floors</option>{geometry.floors.map((floor) => <option key={floor.object_id} value={floor.object_id}>{floor.name}</option>)}
      </select></label>
      <label>Clip above floor (m) <input aria-label="Clip above floor (m)" type="number" min="0" max="1000000" step="any" placeholder="No cut" disabled={!activeFloor} value={cutHeight} onChange={(event) => setCutHeight(event.target.value)} /></label>
      <span>View-only cut in floor-local Y. Blank shows full height.</span>
    </div> : null}
    <Canvas
      className="twin-canvas"
      frameloop="demand"
      dpr={[1, 1.8]}
      gl={{ localClippingEnabled: true }}
      camera={{ position: [18, 15, 18], fov: 46, near: clip.near, far: clip.far }}
    >
      <SceneLabelHost>
        <CameraClipController clip={clip} />
        <ambientLight intensity={0.7} />
        <directionalLight position={[18, 18, 12]} intensity={1.1} />
        <CameraFocusController focusPosition={cameraFocus?.position ?? null} focusTarget={cameraFocus?.target ?? null} reducedMotion={reducedMotion} />
        <CanonicalGeometry shapes={shapes} floorByObject={geometry.floorByObject} clippingPlanes={clippingPlanes} showLabels={layers.showLabels} />
        <CampusBuildings buildings={activeFloor ? [] : campusBuildings} showLabels={layers.showLabels} viewState={mergedBuildingViewState} onSelectBuilding={onSelectBuilding} />
        <SessionModelLayer modelUrl={importedModelUrl} visible={layers.showModel && !activeFloor} onStatusChange={onImportedModelStatusChange} registration={modelRegistration} />
        <RFSamplesLayer samples={shownRf} showLabels={layers.showLabels} />
        {layers.showLinks ? <LinksLayer links={visibleLinks} showLabels={layers.showLabels} maxLabels={maxDeviceLabels} /> : null}
        {layers.showLinks && measuredPath && !activeFloor ? <MeasuredPathLayer segments={measuredPath} /> : null}
        <DeviceInstances
          nodes={visibleNodes}
          selectedId={selectedNodeId}
          onSelect={onSelectNode}
          showLabels={layers.showLabels}
          showCongestion={layers.showCongestion}
          congestionByDevice={congestionByDevice}
          alerts={alertingDeviceIds}
          maxLabels={maxDeviceLabels}
        />
        {layers.showOverlays && !activeFloor ? <OverlaysLayer overlays={overlays} showLabels={layers.showLabels} /> : null}
        <TwinOrbitControls target={cameraFocus?.target} reducedMotion={reducedMotion} limits={orbitLimits} />
      </SceneLabelHost>
    </Canvas></>
  );
}
