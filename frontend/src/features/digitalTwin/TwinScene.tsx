import { Suspense, useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { Environment, Html, Line, OrbitControls, Sparkles } from "@react-three/drei";
import { TwinLink, TwinNode } from "@/features/digitalTwin/hooks";

interface TwinSceneProps {
  nodes: TwinNode[];
  links: TwinLink[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  reducedMotion: boolean;
}

interface NodesLayerProps {
  nodes: TwinNode[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
}

interface LinkLabel {
  id: string;
  edgeType: string;
  mid: [number, number, number];
}

function nodeColor(status: string) {
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

function NodesLayer({ nodes, selectedNodeId, onSelectNode }: NodesLayerProps) {
  return (
    <group>
      {nodes.map((node) => (
        <group key={node.id} position={[node.x, node.y, node.z]}>
          <mesh onClick={() => onSelectNode(node.id)}>
            <icosahedronGeometry args={[selectedNodeId === node.id ? 0.72 : 0.52, 1]} />
            <meshStandardMaterial color={nodeColor(node.status)} emissive={selectedNodeId === node.id ? "#a6ffd4" : "#103824"} emissiveIntensity={selectedNodeId === node.id ? 0.38 : 0.12} roughness={0.32} metalness={0.24} />
          </mesh>
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
        </group>
      ))}
    </group>
  );
}

function LinksLayer({ links }: { links: TwinLink[] }) {
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

export function TwinScene({ nodes, links, selectedNodeId, onSelectNode, reducedMotion }: TwinSceneProps) {
  const floorSegments = useMemo(() => Math.max(8, Math.min(42, nodes.length * 2)), [nodes.length]);

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
        <circleGeometry args={[30, floorSegments]} />
        <meshStandardMaterial color="#d8e7da" roughness={0.82} metalness={0.04} />
      </mesh>

      <LinksLayer links={links} />
      <NodesLayer nodes={nodes} selectedNodeId={selectedNodeId} onSelectNode={onSelectNode} />

      {!reducedMotion ? (
        <Sparkles
          count={80}
          size={2.6}
          speed={0.32}
          opacity={0.26}
          color="#80b4d4"
          scale={[40, 12, 40]}
          position={[0, 2, 0]}
        />
      ) : null}

      <OrbitControls enableDamping dampingFactor={0.08} minDistance={8} maxDistance={62} />
    </Canvas>
  );
}
