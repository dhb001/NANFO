import { useMemo } from "react";
import {
  deriveCampusBuildings,
  normalizeFloorKey,
} from "@/features/digitalTwin/campusBuildings";
import type { TwinNode } from "@/features/digitalTwin/hooks";
import { Button } from "@/shared/ui/Button";

interface CampusFocusControlsProps {
  nodes: TwinNode[];
  selectedBuildingId: string | null;
  resolvedBuildingId: string | null;
  selectedFloorKey: string | null;
  resolvedFloorKey: string | null;
  focusSelectedBuildingOnly: boolean;
  filterSelectedFloorOnly: boolean;
  onSelectedBuildingChange: (buildingId: string | null) => void;
  onSelectedFloorKeyChange: (floorKey: string | null) => void;
  onFocusSelectedBuildingOnlyChange: (nextValue: boolean) => void;
  onFilterSelectedFloorOnlyChange: (nextValue: boolean) => void;
  onReset: () => void;
}

function toFloorLabel(floorKey: string): string {
  return floorKey.toUpperCase().replace(/-/g, " ");
}

export function CampusFocusControls({
  nodes,
  selectedBuildingId,
  resolvedBuildingId,
  selectedFloorKey,
  resolvedFloorKey,
  focusSelectedBuildingOnly,
  filterSelectedFloorOnly,
  onSelectedBuildingChange,
  onSelectedFloorKeyChange,
  onFocusSelectedBuildingOnlyChange,
  onFilterSelectedFloorOnlyChange,
  onReset,
}: CampusFocusControlsProps) {
  const buildings = useMemo(() => deriveCampusBuildings(nodes), [nodes]);

  const buildingOptions = useMemo(() => {
    return [...buildings]
      .sort((left, right) => left.label.localeCompare(right.label))
      .map((building) => ({
        id: building.id,
        label: `${building.label} (${building.floors} floors, ${building.nodeCount} nodes)`,
      }));
  }, [buildings]);

  const activeBuildingId = selectedBuildingId ?? resolvedBuildingId;

  const selectedBuilding = useMemo(() => {
    if (!activeBuildingId) {
      return null;
    }
    return buildings.find((building) => building.id === activeBuildingId) ?? null;
  }, [activeBuildingId, buildings]);

  const floorOptions = useMemo(() => {
    if (!selectedBuilding) {
      return [];
    }
    return selectedBuilding.metadata.floorKeys.map((floorKey) => ({
      key: floorKey,
      label: toFloorLabel(floorKey),
    }));
  }, [selectedBuilding]);

  const normalizedSelectedFloorKey = normalizeFloorKey(selectedFloorKey ?? resolvedFloorKey);
  const hasAnySelection = Boolean(
    selectedBuildingId || resolvedBuildingId || normalizedSelectedFloorKey || focusSelectedBuildingOnly || filterSelectedFloorOnly,
  );

  return (
    <div
      style={{
        border: "1px solid var(--line-soft)",
        borderRadius: "10px",
        padding: "0.48rem 0.56rem",
        display: "grid",
        gap: "0.45rem",
      }}
    >
      <strong style={{ fontSize: "0.9rem" }}>Campus focus</strong>

      <label style={{ display: "grid", gap: "0.3rem" }}>
        <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
          Building
        </span>
        <select
          aria-label="Twin building focus"
          value={selectedBuildingId ?? ""}
          onChange={(event) => onSelectedBuildingChange(event.target.value || null)}
          style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
        >
          <option value="">Auto (selected device building)</option>
          {buildingOptions.map((building) => (
            <option key={building.id} value={building.id}>
              {building.label}
            </option>
          ))}
        </select>
      </label>

      <label style={{ display: "grid", gap: "0.3rem" }}>
        <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-3)" }}>
          Floor
        </span>
        <select
          aria-label="Twin floor focus"
          value={normalizedSelectedFloorKey ?? ""}
          disabled={!selectedBuilding}
          onChange={(event) => onSelectedFloorKeyChange(event.target.value || null)}
          style={{ border: "1px solid var(--line-soft)", borderRadius: "10px", padding: "0.45rem 0.5rem" }}
        >
          <option value="">All floors</option>
          {floorOptions.map((floor) => (
            <option key={floor.key} value={floor.key}>
              {floor.label}
            </option>
          ))}
        </select>
      </label>

      <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
        <Button
          type="button"
          tone={focusSelectedBuildingOnly ? "primary" : "ghost"}
          aria-pressed={focusSelectedBuildingOnly}
          disabled={!resolvedBuildingId}
          onClick={() => onFocusSelectedBuildingOnlyChange(!focusSelectedBuildingOnly)}
        >
          Focus building only
        </Button>
        <Button
          type="button"
          tone={filterSelectedFloorOnly ? "primary" : "ghost"}
          aria-pressed={filterSelectedFloorOnly}
          disabled={!normalizeFloorKey(resolvedFloorKey)}
          onClick={() => onFilterSelectedFloorOnlyChange(!filterSelectedFloorOnly)}
        >
          Filter selected floor
        </Button>
        {hasAnySelection ? (
          <Button type="button" tone="ghost" onClick={onReset}>
            Reset focus
          </Button>
        ) : null}
      </div>

      <div style={{ color: "var(--ink-3)", fontSize: "0.78rem" }}>
        Building and floor focus derive from `spatial_ref_id` path segments and preserve existing topology contracts.
      </div>
    </div>
  );
}
