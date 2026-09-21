import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { TwinOrbitControls } from "./TwinOrbitControls";
import { SceneLabel } from "./SceneLabel";
import { BufferGeometry, Float32BufferAttribute, Object3D, Vector3 } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { loadOwnedModel } from "./modelResources";
import { DeviceInstances } from "./DeviceInstances";
import type { SpatialScene } from "@/shared/types/spatial";
import { EMPTY_SPATIAL_SCENE } from "./spatialScene";
import { buildSpatialGeometry, floorClipPlane, geometryCameraFocus } from "./spatialGeometry";
import { CanonicalGeometry } from "./CanonicalGeometry";
import type { ModelRegistration } from "./ModelRegistration";
import { TwinLink, TwinNode, TwinOverlayObject } from "@/features/digitalTwin/hooks";
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
import {
  DEFAULT_MAX_DEVICE_LABELS,
  deriveAlertingDeviceIds,
} from "@/features/digitalTwin/deviceVisuals";

interface AlertLike {
  event_type: string;
  payload: Record<string, unknown>;
}

interface TwinSceneProps {
  spatialScene?: SpatialScene;
  rfSamples?: readonly RFSample[];
  measuredPath?: readonly MeasuredPathSegment[];
  nodes: TwinNode[];
  links: TwinLink[];
  overlays: TwinOverlayObject[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  reducedMotion: boolean;
  layers: {
    showLinks: boolean;
    showLabels: boolean;
    showCongestion: boolean;
    showOverlays: boolean;
    showModel: boolean;
  };
  /** Alert feed consumed as-is; device association is derived in-scene. */
  alerts?: readonly AlertLike[];
  /** Maximum simultaneous DOM labels. Guards against hundreds of `<Html>` overlays. */
  maxDeviceLabels?: number;
  importedModelUrl?: string | null;
  modelRegistration?: ModelRegistration | null;
  importedCampusBuildings?: readonly CampusBuilding[];
  onImportedModelStatusChange?: (status: "loading" | "ready" | "error", message?: string) => void;
  buildingViewState?: CampusBuildingViewState;
  onSelectBuilding?: (buildingId: string) => void;
}

interface LinkLabel {
  id: string;
  edgeType: string;
  mid: [number, number, number];
}

function overlayColor(overlay: TwinOverlayObject) {
  const normalizedStatus = (overlay.status ?? overlay.state ?? "").toLowerCase();
  if (normalizedStatus.includes("failed") || normalizedStatus === "cancelled") {
    return "#c93f2e";
  }
  if (normalizedStatus.includes("completed") || normalizedStatus === "validated") {
    return "#2ca774";
  }
  if (normalizedStatus.includes("paused") || normalizedStatus.includes("queued")) {
    return "#d1780f";
  }
  return overlay.objectType === "intent_state" ? "#2873cb" : "#2f8f99";
}

function CameraFocusController({
  focusPosition,
  focusTarget,
  reducedMotion,
}: {
  focusPosition: [number, number, number] | null;
  focusTarget: [number, number, number] | null;
  reducedMotion: boolean;
}) {
  const { camera } = useThree();

  const desiredPosition = useMemo(() => new Vector3(), []);
  const desiredTarget = useMemo(() => new Vector3(), []);
  const currentLookAt = useMemo(() => new Vector3(), []);
  const focusing = useRef(false);
  useEffect(() => { focusing.current = Boolean(focusPosition && focusTarget); }, [focusPosition, focusTarget]);

  useFrame(() => {
    if (!focusing.current || !focusPosition || !focusTarget) {
      return;
    }

    desiredPosition.set(focusPosition[0], focusPosition[1], focusPosition[2]);
    desiredTarget.set(focusTarget[0], focusTarget[1], focusTarget[2]);

    const alpha = reducedMotion ? 1 : 0.12;
    camera.position.lerp(desiredPosition, alpha);

    currentLookAt.lerp(desiredTarget, alpha);
    camera.lookAt(currentLookAt);
    if (reducedMotion || camera.position.distanceToSquared(desiredPosition) < 0.001) focusing.current = false;
  });

  return null;
}

function LinksLayer({
  links,
  showLabels,
  maxLabels,
}: {
  links: TwinLink[];
  showLabels: boolean;
  maxLabels: number;
}) {
  const geometry = useMemo(() => {
    const result = new BufferGeometry();
    result.setAttribute("position", new Float32BufferAttribute(links.flatMap((link) => [...link.source, ...link.target]), 3));
    result.computeBoundingSphere();
    return result;
  }, [links]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  // Link labels are DOM overlays too. Cap them deterministically by link id.
  const linkLabels = useMemo<LinkLabel[]>(() => {
    if (!showLabels) {
      return [];
    }
    return [...links]
      .sort((left, right) => left.id.localeCompare(right.id))
      .slice(0, Math.max(0, maxLabels))
      .map((link) => ({
        id: link.id,
        edgeType: link.edgeType,
        mid: [
          (link.source[0] + link.target[0]) / 2,
          (link.source[1] + link.target[1]) / 2,
          (link.source[2] + link.target[2]) / 2,
        ],
      }));
  }, [links, showLabels, maxLabels]);

  return (
    <group>
      <lineSegments>
        <primitive attach="geometry" object={geometry} />
        <lineBasicMaterial color="#608ea8" transparent opacity={0.72} />
      </lineSegments>
      {linkLabels.map((label) => (
        <SceneLabel key={`${label.id}:label`} position={label.mid} distanceFactor={30}>
          <div
            style={{
              padding: "0.1rem 0.28rem",
              borderRadius: "999px",
              background: "rgba(10, 30, 44, 0.72)",
              color: "#d6ecf9",
              fontSize: "9px",
              fontFamily: "var(--font-mono)",
              letterSpacing: "0.02em",
            }}
          >
            {label.edgeType}
          </div>
        </SceneLabel>
      ))}
    </group>
  );
}

function OverlaysLayer({ overlays, showLabels }: { overlays: TwinOverlayObject[]; showLabels: boolean }) {
  const labelledOverlays = useMemo(
    () => (showLabels ? overlays.slice(0, 24) : []),
    [overlays, showLabels],
  );
  const labelledIds = useMemo(
    () => new Set(labelledOverlays.map((overlay) => overlay.id)),
    [labelledOverlays],
  );

  return (
    <group>
      {overlays.slice(0, 160).map((overlay) => (
        <group key={overlay.id} position={[overlay.x, overlay.y, overlay.z]}>
          <mesh>
            <octahedronGeometry args={[0.34, 0]} />
            <meshStandardMaterial color={overlayColor(overlay)} emissive="#12263d" emissiveIntensity={0.2} roughness={0.34} metalness={0.08} />
          </mesh>
          {labelledIds.has(overlay.id) ? (
            <SceneLabel distanceFactor={18}>
              <div
                style={{
                  padding: "0.1rem 0.28rem",
                  borderRadius: "999px",
                  background: "rgba(10, 30, 44, 0.75)",
                  color: "#d6ecf9",
                  fontSize: "9px",
                  fontFamily: "var(--font-mono)",
                  whiteSpace: "nowrap",
                }}
              >
                {overlay.objectType} {overlay.status ?? overlay.state ?? ""}
              </div>
            </SceneLabel>
          ) : null}
        </group>
      ))}
    </group>
  );
}

function disableRaycastForModel(object: Object3D): void {
  object.traverse((child) => {
    const candidate = child as Object3D & {
      isMesh?: boolean;
      raycast?: (...args: unknown[]) => void;
    };

    if (candidate.isMesh && typeof candidate.raycast === "function") {
      candidate.raycast = () => {};
    }
  });
}

function SessionModelLayer({
  modelUrl,
  visible,
  onStatusChange,
  registration,
}: {
  modelUrl: string | null | undefined;
  visible: boolean;
  onStatusChange?: (status: "loading" | "ready" | "error", message?: string) => void;
  registration?: ModelRegistration | null;
}) {
  const [loaded, setLoaded] = useState<{ url: string; root: Object3D } | null>(null);

  useEffect(() => {
    if (!modelUrl) {
      setLoaded(null);
      return;
    }

    setLoaded(null);
    onStatusChange?.("loading");

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
        const message = error instanceof Error ? error.message : "GLB/GLTF load failed.";
        onStatusChange?.("error", message);
      },
    );

  }, [modelUrl, onStatusChange]);

  if (!visible || !loaded || loaded.url !== modelUrl || !registration) {
    return null;
  }

  return (
    <group position={registration.position} rotation={[...registration.rotation, "ZYX"]} scale={registration.scale} dispose={null}>
      <primitive object={loaded.root} dispose={null} />
    </group>
  );
}

const EMPTY_ALERTS: readonly AlertLike[] = [];

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
  selectedNodeId,
  onSelectNode,
  reducedMotion,
  layers,
  alerts = EMPTY_ALERTS,
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
  const campusBuildings = useMemo(() => {
    if (importedCampusBuildings && importedCampusBuildings.length > 0) {
      return [...importedCampusBuildings].sort((left, right) => left.id.localeCompare(right.id));
    }
    return [];
  }, [importedCampusBuildings]);

  const buildingByNodeId = useMemo(() => {
    return buildBuildingByNodeIdIndex(campusBuildings);
  }, [campusBuildings]);

  const selectedBuildingIdFromNode = selectedNodeId ? (buildingByNodeId[selectedNodeId] ?? null) : null;

  const selectedFloorKeyFromNode = useMemo(() => {
    if (!selectedNodeId) {
      return null;
    }

    const selectedNode = nodes.find((node) => node.id === selectedNodeId);
    return deriveSpatialBuildingScope(selectedNode?.spatialRefId).floorKey;
  }, [nodes, selectedNodeId]);

  const mergedBuildingViewState = useMemo<CampusBuildingViewState | undefined>(() => {
    if (!buildingViewState && !selectedBuildingIdFromNode) {
      return undefined;
    }

    return {
      ...(buildingViewState ?? {}),
      selectedBuildingId: buildingViewState?.selectedBuildingId ?? selectedBuildingIdFromNode,
      selectedFloorKey: buildingViewState?.selectedFloorKey ?? selectedFloorKeyFromNode,
    };
  }, [buildingViewState, selectedBuildingIdFromNode, selectedFloorKeyFromNode]);

  const selectedBuilding = useMemo(() => {
    if (!mergedBuildingViewState?.selectedBuildingId) {
      return null;
    }

    return (
      campusBuildings.find((building) => building.id === mergedBuildingViewState.selectedBuildingId) ??
      null
    );
  }, [campusBuildings, mergedBuildingViewState?.selectedBuildingId]);

  const cameraFocus = useMemo(() => {
    if (activeFloor) return canonicalFocus;
    const node = nodes.find((item) => item.id === selectedNodeId && item.placementSource === "canonical");
    if (node) return { position: [node.x + 18, node.y + 15, node.z + 18] as [number, number, number], target: [node.x, node.y, node.z] as [number, number, number] };
    if (!selectedBuilding) {
      return canonicalFocus;
    }

    return resolveCampusBuildingCameraFocus(selectedBuilding, {
      floorKey: mergedBuildingViewState?.selectedFloorKey,
    });
  }, [selectedBuilding, mergedBuildingViewState?.selectedFloorKey, nodes, selectedNodeId, canonicalFocus, activeFloor]);

  const alertingDeviceIds = useMemo(() => {
    const knownDeviceIds = new Set(nodes.map((node) => node.id));
    return deriveAlertingDeviceIds(alerts, knownDeviceIds);
  }, [alerts, nodes]);
  const visibleNodes = useMemo(() => nodes.filter((node) =>
    (!activeFloor || geometry.floorByObject.get(node.spatialObjectId ?? "") === activeFloor)
    && clippingPlanes.every((plane) => plane.distanceToPoint(new Vector3(node.x, node.y, node.z)) >= 0)
    && isNodeVisibleInBuildingView(node.spatialRefId, mergedBuildingViewState)), [nodes, mergedBuildingViewState, activeFloor, geometry, clippingPlanes]);
  const visibleLinks = useMemo(() => {
    const ids = new Set(visibleNodes.map((node) => node.id));
    return links.filter((link) => ids.has(link.sourceId) && ids.has(link.targetId));
  }, [links, visibleNodes]);

  return (<>
    {geometry.floors.length ? <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
      <label>Canonical floor <select aria-label="Canonical floor" value={activeFloor} onChange={(event) => { setFloorId(event.target.value); setCutHeight(""); }}>
        <option value="">All floors</option>{geometry.floors.map((floor) => <option key={floor.object_id} value={floor.object_id}>{floor.name}</option>)}
      </select></label>
      <label>Clip above floor (m) <input aria-label="Clip above floor (m)" type="number" min="0" max="1000000" step="any" placeholder="No cut" disabled={!activeFloor} value={cutHeight} onChange={(event) => setCutHeight(event.target.value)} /></label>
      <span>View-only cut in floor-local Y. Blank shows full height.</span>
    </div> : null}
    <Canvas
      dpr={[1, 1.8]}
      gl={{ localClippingEnabled: true }}
      camera={{ position: [18, 15, 18], fov: 46, near: selectedNodeId && !activeFloor ? 0.01 : canonicalFocus?.near ?? 0.1, far: canonicalFocus?.far ?? 2000 }}
      style={{ width: "100%", height: 560, borderRadius: 16, border: "1px solid var(--line-soft)" }}
    >
      <ambientLight intensity={0.7} />
      <directionalLight position={[18, 18, 12]} intensity={1.1} />

      <CameraFocusController
        focusPosition={cameraFocus?.position ?? null}
        focusTarget={cameraFocus?.target ?? null}
        reducedMotion={reducedMotion}
      />

      <CanonicalGeometry shapes={shapes} clippingPlanes={clippingPlanes} showLabels={layers.showLabels} />

      <CampusBuildings
        buildings={activeFloor ? [] : campusBuildings}
        showLabels={layers.showLabels}
        viewState={mergedBuildingViewState}
        onSelectBuilding={onSelectBuilding}
      />

      <SessionModelLayer
        modelUrl={importedModelUrl}
        visible={layers.showModel && !activeFloor}
        onStatusChange={onImportedModelStatusChange}
        registration={modelRegistration}
      />

      {!activeFloor && rfSamples?.map((sample, index) => <group key={sample.receiverId} position={sample.position}>
        <mesh raycast={() => {}}><octahedronGeometry args={[0.24, 0]} /><meshBasicMaterial color="#9a43cb" /></mesh>
        {layers.showLabels && index < 24 ? <SceneLabel distanceFactor={18}><div style={{ background: "#fff", color: "#54216f", fontSize: 11, whiteSpace: "nowrap" }}>
          RF modeled {sample.receiverId}: {sample.signalDbm.toFixed(1)} dBm · {sample.uncertaintyDb === null ? "uncertainty unknown" : `assumed ±${sample.uncertaintyDb} dB`}
        </div></SceneLabel> : null}
      </group>)}

      {layers.showLinks ? (
        <LinksLayer links={visibleLinks} showLabels={layers.showLabels} maxLabels={maxDeviceLabels} />
      ) : null}
      {layers.showLinks && measuredPath && !activeFloor ? <MeasuredPathLayer segments={measuredPath} /> : null}
      <DeviceInstances
        nodes={visibleNodes}
        selectedId={selectedNodeId}
        onSelect={onSelectNode}
        showLabels={layers.showLabels}
        showCongestion={layers.showCongestion}
        alerts={alertingDeviceIds}
        maxLabels={maxDeviceLabels}
      />
      {layers.showOverlays && !activeFloor ? <OverlaysLayer overlays={overlays} showLabels={layers.showLabels} /> : null}

      <TwinOrbitControls target={cameraFocus?.target} reducedMotion={reducedMotion} />
    </Canvas></>
  );
}
