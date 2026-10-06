import { Button } from "@/shared/ui/Button";
import type { TwinLayerState } from "./twinViewState";

const LAYER_BUTTONS: ReadonlyArray<{ layer: keyof TwinLayerState; label: string }> = [
  { layer: "showLinks", label: "Links" },
  { layer: "showLabels", label: "Labels" },
  { layer: "showCongestion", label: "Congestion" },
  { layer: "showOverlays", label: "Simulation/Intent" },
  { layer: "showModel", label: "Campus model" },
  { layer: "showImportedBuildings", label: "OSM buildings" },
];

/** Layer toggles (aria-pressed); the campus model layer is unavailable until a model is loaded. */
export function TwinLayerToolbar({ layers, modelAvailable, onToggle }: {
  layers: TwinLayerState;
  modelAvailable: boolean;
  onToggle: (layer: keyof TwinLayerState) => void;
}) {
  return (
    <div role="group" aria-label="Digital twin layer controls" className="twin-layer-toolbar">
      {LAYER_BUTTONS.map(({ layer, label }) => {
        const unavailable = layer === "showModel" && !modelAvailable;
        const pressed = !unavailable && layers[layer];
        return (
          <Button key={layer} type="button" tone={pressed ? "primary" : "ghost"} aria-pressed={pressed} disabled={unavailable}
            title={unavailable ? "Import or restore a campus model first" : undefined} onClick={() => onToggle(layer)}>
            {label}
          </Button>
        );
      })}
    </div>
  );
}
