import { SceneLabel } from "./SceneLabel";
import type { ThreeEvent } from "@react-three/fiber";
import { useMemo } from "react";
import { DoubleSide, Shape } from "three";
import {
  type CampusBuilding,
  type CampusBuildingHighlightState,
  type CampusBuildingViewState,
  isCampusBuildingVisible,
  resolveCampusBuildingHighlight,
} from "@/features/digitalTwin/campusBuildings";

interface CampusBuildingsProps {
  buildings: readonly CampusBuilding[];
  showLabels?: boolean;
  viewState?: CampusBuildingViewState;
  onSelectBuilding?: (buildingId: string) => void;
}

interface BuildingMaterialConfig {
  color: string;
  emissive: string;
  emissiveIntensity: number;
  opacity: number;
}

function materialForHighlight(state: CampusBuildingHighlightState): BuildingMaterialConfig {
  if (state === "selected") {
    return {
      color: "#79a28a",
      emissive: "#2f5c43",
      emissiveIntensity: 0.24,
      opacity: 0.48,
    };
  }

  if (state === "muted") {
    return {
      color: "#cfdacb",
      emissive: "#1d3628",
      emissiveIntensity: 0.03,
      opacity: 0.14,
    };
  }

  return {
    color: "#d5e3d4",
    emissive: "#3c5949",
    emissiveIntensity: 0.08,
    opacity: 0.28,
  };
}

function toFootprintShape(points: Array<[number, number]>): Shape {
  if (points.length === 0) {
    const fallback = new Shape();
    fallback.moveTo(-1, -1);
    fallback.lineTo(1, -1);
    fallback.lineTo(1, 1);
    fallback.lineTo(-1, 1);
    fallback.closePath();
    return fallback;
  }

  const shape = new Shape();
  const [first, ...rest] = points;
  shape.moveTo(first[0], first[1]);
  for (const point of rest) {
    shape.lineTo(point[0], point[1]);
  }
  shape.closePath();
  return shape;
}

function BuildingMesh({
  building,
  showLabel,
  highlightState,
  onSelectBuilding,
}: {
  building: CampusBuilding;
  showLabel: boolean;
  highlightState: CampusBuildingHighlightState;
  onSelectBuilding?: (buildingId: string) => void;
}) {
  const material = materialForHighlight(highlightState);
  const footprintShape = useMemo(() => {
    if (building.geometry !== "extrude") {
      return null;
    }
    return toFootprintShape(building.footprint);
  }, [building.geometry, building.footprint]);

  const labelY = building.height + 0.5;

  function handleSelect(event: ThreeEvent<MouseEvent>) {
    if (!onSelectBuilding) {
      return;
    }
    event.stopPropagation();
    onSelectBuilding(building.id);
  }

  return (
    <group position={[building.x, building.baseY, building.z]}>
      {building.geometry === "box" ? (
        <mesh position={[0, building.height / 2, 0]} onClick={handleSelect}>
          <boxGeometry args={[building.width, building.height, building.depth]} />
          <meshStandardMaterial
            color={material.color}
            emissive={material.emissive}
            emissiveIntensity={material.emissiveIntensity}
            roughness={0.86}
            metalness={0.05}
            transparent
            opacity={material.opacity}
          />
        </mesh>
      ) : footprintShape ? (
        <mesh rotation={[-Math.PI / 2, 0, 0]} onClick={handleSelect}>
          <extrudeGeometry args={[footprintShape, { depth: building.height, bevelEnabled: false, steps: 1 }]} />
          <meshStandardMaterial
            color={material.color}
            emissive={material.emissive}
            emissiveIntensity={material.emissiveIntensity}
            roughness={0.84}
            metalness={0.06}
            side={DoubleSide}
            transparent
            opacity={material.opacity}
          />
        </mesh>
      ) : null}

      {showLabel ? (
        <SceneLabel distanceFactor={28} position={[0, labelY, 0]}>
          <div
            style={{
              padding: "0.14rem 0.38rem",
              borderRadius: "999px",
              border: "1px solid rgba(18, 54, 36, 0.26)",
              background: "rgba(246, 250, 244, 0.9)",
              color: "#20352b",
              fontSize: "10px",
              fontFamily: "var(--font-mono)",
              whiteSpace: "nowrap",
            }}
          >
            {building.label} f{building.floors} n{building.nodeCount}
          </div>
        </SceneLabel>
      ) : null}
    </group>
  );
}

export function CampusBuildings({
  buildings,
  showLabels = true,
  viewState,
  onSelectBuilding,
}: CampusBuildingsProps) {
  const visibleBuildings = useMemo(() => {
    return [...buildings]
      .filter((building) => isCampusBuildingVisible(building, viewState))
      .sort((left, right) => left.id.localeCompare(right.id));
  }, [buildings, viewState]);

  return (
    <group>
      {visibleBuildings.map((building) => (
        <BuildingMesh
          key={building.id}
          building={building}
          showLabel={showLabels}
          highlightState={resolveCampusBuildingHighlight(building, viewState)}
          onSelectBuilding={onSelectBuilding}
        />
      ))}
    </group>
  );
}
