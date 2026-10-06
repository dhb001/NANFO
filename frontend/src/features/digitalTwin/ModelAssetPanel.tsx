import { describeApiError } from "@/shared/lib/errors";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { ModelRegistrationControls } from "./ModelRegistration";
import { MODEL_STATUS_TONES } from "./twinStatusTones";
import { MODEL_ASSET_PAGE_SIZE, type ModelAssetWorkflow } from "./useModelAssetWorkflow";

export function ModelAssetPanel({ model, layerVisible }: { model: ModelAssetWorkflow; layerVisible: boolean }) {
  const { assetsQuery, assetPage, selectedAsset } = model;
  const total = assetsQuery.data?.total;
  const busy = assetsQuery.isFetching || model.isImporting;
  // Never a false zero: the count is shown only when the list was actually read.
  const totalText = total !== undefined ? `${total} assets` : assetsQuery.isError ? "asset count unavailable" : assetsQuery.isLoading ? "loading asset count" : "no asset list loaded";
  return (
    <section className="twin-card" aria-label="Imported model state">
      <h4 className="twin-card-title">Imported model state</h4>
      <div className="twin-badges">
        <Badge text={`model ${model.status}`} tone={MODEL_STATUS_TONES[model.status]} />
        <Badge text={layerVisible ? "layer visible" : "layer hidden"} tone={layerVisible ? "ok" : "neutral"} />
        {total !== undefined && !assetsQuery.isError ? <Badge text={`persisted assets ${total}`} tone={total > 0 ? "ok" : "neutral"} /> : null}
      </div>
      {assetsQuery.isFetching ? <p role="status" className="twin-muted">Loading model assets…</p> : null}
      {assetsQuery.isError ? <p role="alert" className="twin-error">Model asset list unavailable: {describeApiError(assetsQuery.error)} Use Reload model assets to retry.</p> : null}
      {total === 0 ? <p className="twin-muted">No persisted model assets.</p> : null}
      <Button tone="ghost" disabled={busy} onClick={() => void assetsQuery.refetch()}>Reload model assets</Button>
      <nav aria-label="Model asset pages" className="twin-actions">
        <Button tone="ghost" disabled={assetPage === 1 || busy} onClick={() => model.setAssetPage((page) => page - 1)}>Previous asset page</Button>
        <span role="status">Asset page {assetPage} · {totalText}</span>
        <Button tone="ghost" disabled={!assetsQuery.data || assetPage * MODEL_ASSET_PAGE_SIZE >= assetsQuery.data.total || busy} onClick={() => model.setAssetPage((page) => page + 1)}>Next asset page</Button>
      </nav>
      {assetsQuery.data && !model.visibleAssets.length && assetsQuery.data.total > 0 ? <p>No assets on this page. Use Previous asset page.</p> : null}
      <p>Available persisted assets; new saves retain earlier assets. Restore changes only the local view.</p>
      {selectedAsset ? (
        <div className="mono twin-meta">
          selected: {selectedAsset.model_file_name} ({selectedAsset.model_size_bytes} bytes)
          <div>SHA-256: {selectedAsset.model_sha256}</div>
          <div>Source: {selectedAsset.source ?? "unknown"} · updated {selectedAsset.updated_at}</div>
        </div>
      ) : null}
      <div className="twin-actions">
        <Button type="button" tone="ghost" permission="write:config" disabled={!model.canPersist} onClick={() => void model.persist()}>
          {model.isPersisting ? "Persisting model asset..." : "Persist Model Asset"}
        </Button>
        <Button type="button" tone="ghost" disabled={!model.canRestore} onClick={() => void model.restore()}>
          {model.isImporting ? "Validating model..." : "Restore Persisted Model"}
        </Button>
      </div>
      {model.importedModelUrl && model.status !== "ready" && !model.statusMessage ? <p className="twin-muted">Persisting is available once the model has rendered.</p> : null}
      {model.statusMessage ? <p role="status" className="twin-error">{model.statusMessage}</p> : null}
      {model.importedModelUrl ? (
        <ModelRegistrationControls key={`${model.importedModelUrl}:${model.registration?.saved === true}`} initial={model.registration?.value ?? null}
          saved={model.registration?.saved ?? false} disabled={model.isPersisting} onApply={model.applyRegistration} />
      ) : null}
    </section>
  );
}
