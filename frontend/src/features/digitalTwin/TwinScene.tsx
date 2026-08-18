import { Suspense, useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { Environment, Html, Line, OrbitControls, Sparkles } from "@react-three/drei";
import { TwinLink, TwinNode, TwinOverlayObject } from "@/features/digitalTwin/hooks";
import type { CongestionSeverity } from "@/features/digitalTwin/sceneAdapter";

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
  };
}

interface NodesLayerProps {
  nodes: TwinNode[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  showLabels: boolean;
  showCongestion: boolean;
}

interface LinkLabel {
  id: string;
  edgeType: string;
  mid: [number, number, number];
}

function statusNodeColor(status: string) {
  if (status === "active") {
    return "#2ca774";
  }
  if (status === "offline") {
    return "#d1780f";
  }
  if (status === "deleted") {
    return "#c93f2e";
  }
  return "#2b70c8";
}

function congestionColor(severity: CongestionSeverity) {
  if (severity === "low") {
    return "#2ca774";
  }
  if (severity === "medium") {
    return "#d1780f";
  }
  if (severity === "high") {
    return "#c93f2e";
  }
  return "#6f8291";
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

function NodesLayer({ nodes, selectedNodeId, onSelectNode, showLabels, showCongestion }: NodesLayerProps) {
  return (
    <group>
      {nodes.map((node) => (
        <group key={node.id} position={[node.x, node.y, node.z]}>
          <mesh onClick={() => onSelectNode(node.id)}>
            <icosahedronGeometry args={[selectedNodeId === node.id ? 0.72 : 0.52, 1]} />
            <meshStandardMaterial
              color={showCongestion ? congestionColor(node.congestion.severity) : statusNodeColor(node.status)}
              emissive={selectedNodeId === node.id ? "#a6ffd4" : "#103824"}
              emissiveIntensity={selectedNodeId === node.id ? 0.38 : 0.12}
              roughness={0.32}
              metalness={0.24}
            />
          </mesh>
          {showCongestion ? (
            <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.72, 0]}>
              <ringGeometry args={[0.62, 0.74, 24]} />
              <meshBasicMaterial color={congestionColor(node.congestion.severity)} transparent opacity={0.78} />
            </mesh>
          ) : null}
          {showLabels ? (
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
      ))}
    </group>
  );
}

function LinksLayer({ links, showLabels }: { links: TwinLink[]; showLabels: boolean }) {
  const linkLabels = useMemo<LinkLabel[]>(() => {
    return links.map((link) => {
      const source = link.source;
      const target = link.target;
      return {
        id: link.id,
        edgeType: link.edgeType,
        mid: [
          (source[0] + target[0]) / 2,
          (source[1] + target[1]) / 2,
          (source[2] + target[2]) / 2,
        ],
      };
    });
  }, [links]);

  return (
    <group>
      {links.map((link) => {
        return (
          <group key={link.id}>
            <Line points={[link.source, link.target]} color="#608ea8" lineWidth={1} transparent opacity={0.72} />
          </group>
        );
      })}
      {showLabels
        ? linkLabels.map((label) => (
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
          ))
        : null}
    </group>
  );
}

function OverlaysLayer({ overlays, showLabels }: { overlays: TwinOverlayObject[]; showLabels: boolean }) {
  return (
    <group>
      {overlays.slice(0, 160).map((overlay) => (
        <group key={overlay.id} position={[overlay.x, overlay.y, overlay.z]}>
          <mesh>
            <octahedronGeometry args={[0.34, 0]} />
            <meshStandardMaterial color={overlayColor(overlay)} emissive="#12263d" emissiveIntensity={0.2} roughness={0.34} metalness={0.08} />
          </mesh>
          {showLabels ? (
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

export function TwinScene({ nodes, links, overlays, selectedNodeId, onSelectNode, reducedMotion, layers }: TwinSceneProps) {
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
      <Suspense fallback={null}>
        <Environment preset="dawn" />
      </Suspense>

      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -2.3, 0]}>
        <circleGeometry args={[floorRadius, floorSegments]} />
        <meshStandardMaterial color="#d8e7da" roughness={0.82} metalness={0.04} />
      </mesh>

      {layers.showLinks ? <LinksLayer links={links} showLabels={layers.showLabels} /> : null}
      <NodesLayer
        nodes={nodes}
        selectedNodeId={selectedNodeId}
        onSelectNode={onSelectNode}
        showLabels={layers.showLabels}
        showCongestion={layers.showCongestion}
      />
      {layers.showOverlays ? <OverlaysLayer overlays={overlays} showLabels={layers.showLabels} /> : null}

      {!reducedMotion ? (
        <Sparkles
          count={80}
          size={2.6}
          speed={0.32}
          opacity={0.26}
          color="#80b4d4"
          scale={[floorRadius * 1.4, 12, floorRadius * 1.4]}
          position={[0, 2, 0]}
        />
      ) : null}

      <OrbitControls enableDamping={!reducedMotion} dampingFactor={reducedMotion ? 0 : 0.08} minDistance={8} maxDistance={92} />
    </Canvas>
  );
}
