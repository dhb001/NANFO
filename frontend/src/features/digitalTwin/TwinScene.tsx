import { useEffect, useMemo, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Html, Line, OrbitControls } from "@react-three/drei";
import { Box3, Group, Object3D, Vector3 } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { TwinLink, TwinNode, TwinOverlayObject } from "@/features/digitalTwin/hooks";
import { CampusBuildings } from "@/features/digitalTwin/CampusBuildings";
import {
  deriveWirelessCoverageCells,
  type WirelessCoverageCell,
} from "@/features/digitalTwin/wirelessCoverage";
import {
  type CampusBuilding,
  buildBuildingByNodeIdIndex,
  deriveSpatialBuildingScope,
  deriveCampusBuildings,
  isNodeVisibleInBuildingView,
  resolveCampusBuildingCameraFocus,
  type CampusBuildingViewState,
} from "@/features/digitalTwin/campusBuildings";
import {
  DEFAULT_MAX_DEVICE_LABELS,
  type DeviceColorMode,
  type DeviceGeometryKind,
  type ResolvedDeviceVisual,
  deriveAlertingDeviceIds,
  resolveDeviceVisual,
  selectDeviceLabels,
} from "@/features/digitalTwin/deviceVisuals";

interface AlertLike {
  event_type: string;
  payload: Record<string, unknown>;
}

interface TwinSceneProps {
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
    showWirelessCoverage: boolean;
  };
  /** Alert feed consumed as-is; device association is derived in-scene. */
  alerts?: readonly AlertLike[];
  /** Maximum simultaneous DOM labels. Guards against hundreds of `<Html>` overlays. */
  maxDeviceLabels?: number;
  importedModelUrl?: string | null;
  importedCampusBuildings?: readonly CampusBuilding[];
  onImportedModelStatusChange?: (status: "loading" | "ready" | "error", message?: string) => void;
  buildingViewState?: CampusBuildingViewState;
  onSelectBuilding?: (buildingId: string) => void;
}

interface NodesLayerProps {
  nodes: TwinNode[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  showLabels: boolean;
  showCongestion: boolean;
  alertingDeviceIds: ReadonlySet<string>;
  maxDeviceLabels: number;
  buildingViewState?: CampusBuildingViewState;
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

function coverageFillColor(severity: WirelessCoverageCell["severity"]): string {
  if (severity === "low") {
    return "#3bbd7f";
  }
  if (severity === "medium") {
    return "#d98a2c";
  }
  if (severity === "high") {
    return "#d14a3d";
  }
  return "#5f8fba";
}

function coverageRingColor(severity: WirelessCoverageCell["severity"]): string {
  if (severity === "low") {
    return "#2b915f";
  }
  if (severity === "medium") {
    return "#ba6f16";
  }
  if (severity === "high") {
    return "#af2f25";
  }
  return "#4e7aa2";
}

/**
 * Render the primitive for a device class. Kept as a plain switch so geometry choice
 * stays declarative data in `deviceVisuals.ts` rather than logic scattered per node.
 */
function DeviceGeometry({ kind, radius }: { kind: DeviceGeometryKind; radius: number }) {
  if (kind === "box") {
    const side = radius * 1.5;
    return <boxGeometry args={[side, side, side]} />;
  }
  if (kind === "cylinder") {
    return <cylinderGeometry args={[radius * 0.85, radius * 0.85, radius * 1.7, 16]} />;
  }
  if (kind === "cone") {
    return <coneGeometry args={[radius, radius * 1.9, 16]} />;
  }
  if (kind === "octahedron") {
    return <octahedronGeometry args={[radius, 0]} />;
  }
  if (kind === "sphere") {
    return <sphereGeometry args={[radius, 16, 12]} />;
  }
  return <icosahedronGeometry args={[radius, 1]} />;
}

function DeviceNode({
  node,
  visual,
  onSelectNode,
  showLabel,
}: {
  node: TwinNode;
  visual: ResolvedDeviceVisual;
  onSelectNode: (nodeId: string) => void;
  showLabel: boolean;
}) {
  const ringInnerRadius = visual.radius * 1.2;
  const ringOuterRadius = ringInnerRadius + 0.14;

  return (
    <group position={[node.x, node.y, node.z]}>
      <mesh onClick={() => onSelectNode(node.id)}>
        <DeviceGeometry kind={visual.definition.geometry} radius={visual.radius} />
        <meshStandardMaterial
          color={visual.color}
          emissive={visual.emissive}
          emissiveIntensity={visual.emissiveIntensity}
          roughness={0.32}
          metalness={0.24}
        />
      </mesh>

      {visual.ringColor ? (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -(visual.radius + 0.18), 0]}>
          <ringGeometry args={[ringInnerRadius, ringOuterRadius, 24]} />
          <meshBasicMaterial color={visual.ringColor} transparent opacity={0.78} />
        </mesh>
      ) : null}

      {visual.outlineColor ? (
        <mesh>
          <sphereGeometry args={[visual.radius * 1.45, 16, 12]} />
          <meshBasicMaterial color={visual.outlineColor} transparent opacity={0.22} />
        </mesh>
      ) : null}

      {showLabel ? (
        <Html distanceFactor={18} center>
          <div
            style={{
              padding: "0.16rem 0.34rem",
              borderRadius: "8px",
              border: "1px solid rgba(20, 48, 36, 0.25)",
              background: "rgba(248, 252, 246, 0.88)",
              fontSize: "10px",
              fontFamily: "var(--font-mono)",
              whiteSpace: "nowrap",
            }}
          >
            {node.hostname}
          </div>
        </Html>
      ) : null}
    </group>
  );
}

function NodesLayer({
  nodes,
  selectedNodeId,
  onSelectNode,
  showLabels,
  showCongestion,
  alertingDeviceIds,
  maxDeviceLabels,
  buildingViewState,
}: NodesLayerProps) {
  const colorMode: DeviceColorMode = "type";

  // Budget DOM labels by importance instead of one per device.
  const labelledIds = useMemo(() => {
    if (!showLabels) {
      return new Set<string>();
    }
    return selectDeviceLabels(
      nodes.map((node) => ({ id: node.id, hostname: node.hostname, deviceType: node.type })),
      { maxLabels: maxDeviceLabels, selectedNodeId, alertingDeviceIds },
    );
  }, [nodes, showLabels, maxDeviceLabels, selectedNodeId, alertingDeviceIds]);

  return (
    <group>
      {nodes.map((node) => {
        if (!isNodeVisibleInBuildingView(node.spatialRefId, buildingViewState)) {
          return null;
        }

        const visual = resolveDeviceVisual({
          deviceType: node.type,
          status: node.status,
          congestionSeverity: node.congestion.severity,
          selected: selectedNodeId === node.id,
          alerting: alertingDeviceIds.has(node.id),
          colorMode,
          showCongestionRing: showCongestion,
        });

        return (
          <DeviceNode
            key={node.id}
            node={node}
            visual={visual}
            onSelectNode={onSelectNode}
            showLabel={labelledIds.has(node.id)}
          />
        );
      })}
    </group>
  );
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

  useFrame(() => {
    if (!focusPosition || !focusTarget) {
      return;
    }

    desiredPosition.set(focusPosition[0], focusPosition[1], focusPosition[2]);
    desiredTarget.set(focusTarget[0], focusTarget[1], focusTarget[2]);

    const alpha = reducedMotion ? 1 : 0.12;
    camera.position.lerp(desiredPosition, alpha);

    currentLookAt.lerp(desiredTarget, alpha);
    camera.lookAt(currentLookAt);
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
      {links.map((link) => {
        return (
          <group key={link.id}>
            <Line points={[link.source, link.target]} color="#608ea8" lineWidth={1} transparent opacity={0.72} />
          </group>
        );
      })}
      {linkLabels.map((label) => (
        <Html key={`${label.id}:label`} position={label.mid} distanceFactor={30} center>
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
        </Html>
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
            <Html distanceFactor={18} center>
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
            </Html>
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

function normalizeImportedModel(source: Object3D): Group {
  const root = new Group();
  const model = source.clone(true);
  const box = new Box3().setFromObject(model);

  let scale = 1;
  if (!box.isEmpty()) {
    const size = new Vector3();
    const center = new Vector3();
    box.getSize(size);
    box.getCenter(center);

    model.position.sub(center);
    model.position.y += size.y / 2;

    const maxSpan = Math.max(size.x, size.y, size.z);
    if (maxSpan > 0) {
      scale = Math.max(0.05, Math.min(3.4, 40 / maxSpan));
    }
  }

  disableRaycastForModel(model);
  root.scale.setScalar(scale);
  root.add(model);
  return root;
}

function SessionModelLayer({
  modelUrl,
  visible,
  onStatusChange,
}: {
  modelUrl: string | null | undefined;
  visible: boolean;
  onStatusChange?: (status: "loading" | "ready" | "error", message?: string) => void;
}) {
  const [modelRoot, setModelRoot] = useState<Group | null>(null);

  useEffect(() => {
    if (!modelUrl) {
      setModelRoot(null);
      return;
    }

    let cancelled = false;
    setModelRoot(null);
    onStatusChange?.("loading");

    const loader = new GLTFLoader();
    loader.load(
      modelUrl,
      (gltf) => {
        if (cancelled) {
          return;
        }

        const source = gltf.scene ?? gltf.scenes?.[0] ?? null;
        if (!source) {
          setModelRoot(null);
          onStatusChange?.("error", "GLB/GLTF contains no scene root.");
          return;
        }

        setModelRoot(normalizeImportedModel(source));
        onStatusChange?.("ready");
      },
      undefined,
      (error) => {
        if (cancelled) {
          return;
        }

        setModelRoot(null);
        const message = error instanceof Error ? error.message : "GLB/GLTF load failed.";
        onStatusChange?.("error", message);
      },
    );

    return () => {
      cancelled = true;
    };
  }, [modelUrl, onStatusChange]);

  if (!visible || !modelRoot) {
    return null;
  }

  return (
    <group position={[0, -2.3, 0]}>
      <primitive object={modelRoot} />
    </group>
  );
}

function WirelessCoverageLayer({
  cells,
  showLabels,
  buildingViewState,
}: {
  cells: readonly WirelessCoverageCell[];
  showLabels: boolean;
  buildingViewState?: CampusBuildingViewState;
}) {
  const visibleCells = useMemo(() => {
    return cells.filter((cell) => isNodeVisibleInBuildingView(cell.spatialRefId, buildingViewState));
  }, [buildingViewState, cells]);

  const labelledCellIds = useMemo(() => {
    if (!showLabels) {
      return new Set<string>();
    }
    return new Set(visibleCells.slice(0, 18).map((cell) => cell.id));
  }, [showLabels, visibleCells]);

  return (
    <group>
      {visibleCells.map((cell) => (
        <group key={cell.id} position={[cell.x, cell.y, cell.z]}>
          <mesh rotation={[-Math.PI / 2, 0, 0]}>
            <circleGeometry args={[cell.radius, 28]} />
            <meshBasicMaterial
              color={coverageFillColor(cell.severity)}
              transparent
              opacity={0.08 + cell.intensity * 0.18}
              depthWrite={false}
            />
          </mesh>
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, 0]}>
            <ringGeometry args={[Math.max(0.7, cell.radius * 0.84), cell.radius, 28]} />
            <meshBasicMaterial
              color={coverageRingColor(cell.severity)}
              transparent
              opacity={0.12 + cell.intensity * 0.32}
              depthWrite={false}
            />
          </mesh>
          {labelledCellIds.has(cell.id) ? (
            <Html distanceFactor={24} center>
              <div
                style={{
                  padding: "0.1rem 0.28rem",
                  borderRadius: "999px",
                  background: "rgba(14, 44, 34, 0.72)",
                  color: "#d6f2e6",
                  fontSize: "9px",
                  fontFamily: "var(--font-mono)",
                  whiteSpace: "nowrap",
                }}
              >
                AP coverage (synthetic estimate)
              </div>
            </Html>
          ) : null}
        </group>
      ))}
    </group>
  );
}

const EMPTY_ALERTS: readonly AlertLike[] = [];

export function TwinScene({
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
  importedCampusBuildings,
  onImportedModelStatusChange,
  buildingViewState,
  onSelectBuilding,
}: TwinSceneProps) {
  const campusBuildings = useMemo(() => {
    if (importedCampusBuildings && importedCampusBuildings.length > 0) {
      return [...importedCampusBuildings].sort((left, right) => left.id.localeCompare(right.id));
    }
    return deriveCampusBuildings(nodes);
  }, [importedCampusBuildings, nodes]);

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
    if (!selectedBuilding) {
      return null;
    }

    return resolveCampusBuildingCameraFocus(selectedBuilding, {
      floorKey: mergedBuildingViewState?.selectedFloorKey,
    });
  }, [selectedBuilding, mergedBuildingViewState?.selectedFloorKey]);

  const alertingDeviceIds = useMemo(() => {
    const knownDeviceIds = new Set(nodes.map((node) => node.id));
    return deriveAlertingDeviceIds(alerts, knownDeviceIds);
  }, [alerts, nodes]);

  const wirelessCoverageCells = useMemo(() => {
    return deriveWirelessCoverageCells(nodes, { campusBuildings });
  }, [campusBuildings, nodes]);

  const floorSegments = useMemo(() => Math.max(8, Math.min(42, nodes.length * 2)), [nodes.length]);
  const floorRadius = useMemo(() => {
    const farthest = nodes.reduce((maxValue, node) => {
      const distance = Math.sqrt(node.x ** 2 + node.z ** 2);
      return Math.max(maxValue, distance);
    }, 18);
    return Math.max(24, Math.min(90, farthest + 12));
  }, [nodes]);

  return (
    <Canvas
      dpr={[1, 1.8]}
      camera={{ position: [18, 15, 18], fov: 46 }}
      style={{ width: "100%", height: 560, borderRadius: 16, border: "1px solid var(--line-soft)" }}
    >
      <ambientLight intensity={0.7} />
      <directionalLight position={[18, 18, 12]} intensity={1.1} />

      <CameraFocusController
        focusPosition={cameraFocus?.position ?? null}
        focusTarget={cameraFocus?.target ?? null}
        reducedMotion={reducedMotion}
      />

      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -2.3, 0]}>
        <circleGeometry args={[floorRadius, floorSegments]} />
        <meshStandardMaterial color="#d8e7da" roughness={0.82} metalness={0.04} />
      </mesh>

      <CampusBuildings
        buildings={campusBuildings}
        showLabels={layers.showLabels}
        viewState={mergedBuildingViewState}
        onSelectBuilding={onSelectBuilding}
      />

      <SessionModelLayer
        modelUrl={importedModelUrl}
        visible={layers.showModel}
        onStatusChange={onImportedModelStatusChange}
      />

      {layers.showWirelessCoverage ? (
        <WirelessCoverageLayer
          cells={wirelessCoverageCells}
          showLabels={layers.showLabels}
          buildingViewState={mergedBuildingViewState}
        />
      ) : null}

      {layers.showLinks ? (
        <LinksLayer links={links} showLabels={layers.showLabels} maxLabels={maxDeviceLabels} />
      ) : null}
      <NodesLayer
        nodes={nodes}
        selectedNodeId={selectedNodeId}
        onSelectNode={onSelectNode}
        showLabels={layers.showLabels}
        showCongestion={layers.showCongestion}
        alertingDeviceIds={alertingDeviceIds}
        maxDeviceLabels={maxDeviceLabels}
        buildingViewState={mergedBuildingViewState}
      />
      {layers.showOverlays ? <OverlaysLayer overlays={overlays} showLabels={layers.showLabels} /> : null}

      <OrbitControls enableDamping={!reducedMotion} dampingFactor={reducedMotion ? 0 : 0.08} minDistance={8} maxDistance={92} />
    </Canvas>
  );
}
