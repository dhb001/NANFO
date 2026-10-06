import type { ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import { DoubleSide, MeshStandardMaterial, Shape } from "three";
import {
  type CampusBuilding,
  type CampusBuildingHighlightState,
  type CampusBuildingViewState,
  buildingLabelSpecs,
  footprintShapePoint,
  isCampusBuildingVisible,
  resolveCampusBuildingHighlight,
} from "@/features/digitalTwin/campusBuildings";
import { useSceneLabels } from "./sceneLabelContext";

interface CampusBuildingsProps {
  buildings: readonly CampusBuilding[];
  showLabels?: boolean;
  viewState?: CampusBuildingViewState | undefined;
  onSelectBuilding?: ((buildingId: string) => void) | undefined;
}

const HIGHLIGHT_MATERIALS: Readonly<Record<CampusBuildingHighlightState, { color: string; emissive: string; emissiveIntensity: number; opacity: number }>> = {
  selected: { color: "#79a28a", emissive: "#2f5c43", emissiveIntensity: 0.24, opacity: 0.48 },
  muted: { color: "#cfdacb", emissive: "#1d3628", emissiveIntensity: 0.03, opacity: 0.14 },
  default: { color: "#d5e3d4", emissive: "#3c5949", emissiveIntensity: 0.08, opacity: 0.28 },
};

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
  const [first = [0, 0], ...rest] = points.map(footprintShapePoint);
  shape.moveTo(first[0], first[1]);
  for (const point of rest) {
    shape.lineTo(point[0], point[1]);
  }
  shape.closePath();
  return shape;
}

function BuildingMesh({ building, material, onSelectBuilding }: {
  building: CampusBuilding;
  material: MeshStandardMaterial;
  onSelectBuilding?: ((buildingId: string) => void) | undefined;
}) {
  const footprintShape = useMemo(() => (building.geometry === "extrude" ? toFootprintShape(building.footprint) : null), [building.geometry, building.footprint]);

  function handleSelect(event: ThreeEvent<MouseEvent>) {
    if (!onSelectBuilding) return;
    event.stopPropagation();
    onSelectBuilding(building.id);
  }

  return (
    <group position={[building.x, building.baseY, building.z]}>
      {building.geometry === "box" ? (
        <mesh position={[0, building.height / 2, 0]} onClick={handleSelect} material={material}>
          <boxGeometry args={[building.width, building.height, building.depth]} />
        </mesh>
      ) : footprintShape ? (
        <mesh rotation={[-Math.PI / 2, 0, 0]} onClick={handleSelect} material={material}>
          <extrudeGeometry args={[footprintShape, { depth: building.height, bevelEnabled: false, steps: 1 }]} />
        </mesh>
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
  // Three shared materials (one per highlight state) instead of one per building.
  const materials = useMemo(() => Object.fromEntries(Object.entries(HIGHLIGHT_MATERIALS).map(([state, config]) => [state,
    new MeshStandardMaterial({ ...config, roughness: 0.85, metalness: 0.05, transparent: true, side: DoubleSide })])) as Record<CampusBuildingHighlightState, MeshStandardMaterial>, []);
  useEffect(() => () => { for (const material of Object.values(materials)) material.dispose(); }, [materials]);
  const labels = useMemo(() => (showLabels ? buildingLabelSpecs(visibleBuildings, viewState) : []), [showLabels, visibleBuildings, viewState]);
  useSceneLabels("campus-buildings", labels);

  return (
    <group>
      {visibleBuildings.map((building) => (
        <BuildingMesh
          key={building.id}
          building={building}
          material={materials[resolveCampusBuildingHighlight(building, viewState)]}
          onSelectBuilding={onSelectBuilding}
        />
      ))}
    </group>
  );
}
