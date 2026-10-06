import { Badge } from "@/shared/ui/Badge";
import { Panel } from "@/shared/ui/Panel";
import { MAX_MODEL_SIZE_TEXT } from "./modelAsset";
import type { ModelAssetWorkflow } from "./useModelAssetWorkflow";

export function CampusImportPanel({ model }: { model: ModelAssetWorkflow }) {
  const summary = model.importSummary;
  return (
    <Panel title="Easy Campus Import (Session Only)" subtitle="Upload GLB/GLTF with optional sidecar mapping JSON.">
      <div className="twin-stack">
        <div className="twin-two-columns">
          <label className="twin-field">
            <span className="mono twin-field-label">Model file (.glb or .gltf)</span>
            <input aria-label="Campus model file" type="file" accept=".glb,.gltf,model/gltf-binary,model/gltf+json"
              onChange={(event) => void model.importModelFile(event.target.files?.[0] ?? null)} />
          </label>
          <label className="twin-field">
            <span className="mono twin-field-label">Sidecar mapping (.json, optional)</span>
            <input aria-label="Campus mapping file" type="file" accept=".json,application/json"
              onChange={(event) => void model.importSidecarFile(event.target.files?.[0] ?? null)} />
          </label>
        </div>
        <p className="twin-muted">Models must be self-contained (embedded data: URIs only) and at most {MAX_MODEL_SIZE_TEXT}; they are validated before anything is rendered.</p>
        {model.isImporting ? <p role="status" className="twin-muted">Validating campus import files...</p> : null}
        {model.importError ? <p role="status" className="twin-error">{model.importError}</p> : null}
        {summary ? (
          <div className="twin-card">
            <div className="twin-badges">
              <Badge text={`model ${summary.modelType.toUpperCase()}`} tone="info" />
              <Badge text={`rows ${summary.totalRows}`} tone="neutral" />
              <Badge text={`matched ${summary.matched}`} tone="ok" />
              <Badge text={`unmatched ${summary.unmatched}`} tone={summary.unmatched > 0 ? "warn" : "ok"} />
              <Badge text={`duplicates ${summary.duplicateKeys.length}`} tone={summary.duplicateKeys.length > 0 ? "danger" : "ok"} />
            </div>
            <div className="mono twin-meta">model: {summary.modelFileName}</div>
            <div className="mono twin-meta">mapping: {summary.mappingFileName ?? "none"}</div>
            {summary.duplicateKeys.length > 0 ? <div className="mono twin-error">duplicate object_name entries: {summary.duplicateKeys.slice(0, 6).join(", ")}</div> : null}
            <p className="twin-muted">Imported mapping is session-only and clears on reload.</p>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
