import { useState } from "react";
import { describeApiError } from "@/shared/lib/errors";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { ConfirmDialog } from "./ConfirmDialog";
import type { CampusBuildingsReview, CampusBuildingsWorkflow } from "./useCampusBuildingsWorkflow";

const MIB = 1024 * 1024;
const formatMiB = (bytes: number) => `${(bytes / MIB).toFixed(2)} MiB`;
const MAX_LISTED_CHANGES = 50;

function ChangeList({ label, items }: { label: string; items: ReadonlyArray<{ id: string; label: string; fields: string[] }> }) {
  if (!items.length) return null;
  return (
    <details>
      <summary>{label} ({items.length})</summary>
      <ul className="twin-diff-list" aria-label={label}>
        {items.slice(0, MAX_LISTED_CHANGES).map((item) => <li key={item.id}>{item.label} (<code>{item.id}</code>){item.fields.length ? `: ${item.fields.join(", ")}` : ""}</li>)}
        {items.length > MAX_LISTED_CHANGES ? <li>… {items.length - MAX_LISTED_CHANGES} more</li> : null}
      </ul>
    </details>
  );
}

function CampusReviewDialog({ review, campus }: { review: CampusBuildingsReview; campus: CampusBuildingsWorkflow }) {
  const [mode, setMode] = useState<"replace" | "merge">(review.incomplete ? "merge" : "replace");
  const { diff } = review;
  const bytes = mode === "replace" ? review.replaceBytes : review.mergeBytes;
  return (
    <ConfirmDialog
      title="Review campus building changes"
      confirmLabel={mode === "replace" ? "Replace persisted buildings" : "Add and update only"}
      danger={mode === "replace" && diff.removed.length > 0}
      busy={campus.persisting}
      onCancel={campus.cancelReview}
      onConfirm={() => campus.confirmPersist(mode)}
    >
      {campus.persistError ? <p role="alert" className="twin-error">{campus.persistError}</p> : null}
      <p>{diff.added.length} added · {diff.changed.length} changed · {diff.unchanged.length} unchanged · {diff.removed.length} persisted buildings not in this import.</p>
      <ChangeList label="Added" items={diff.added} />
      <ChangeList label="Changed" items={diff.changed} />
      <ChangeList label={mode === "replace" ? "Removed by replacement" : "Kept (not in this import)"} items={diff.removed} />
      {review.incomplete ? (
        <p role="alert" className="twin-error">The server listed fewer buildings than it holds, so a full replacement could remove buildings not shown here. Only add-and-update is available.</p>
      ) : null}
      <fieldset>
        <legend>Persistence mode</legend>
        <label>
          <input type="radio" name="campus-persist-mode" checked={mode === "replace"} disabled={review.incomplete} onChange={() => setMode("replace")} />{" "}
          Replace all persisted buildings (removes {diff.removed.length})
        </label>
        <label>
          <input type="radio" name="campus-persist-mode" checked={mode === "merge"} onChange={() => setMode("merge")} />{" "}
          Add and update only (keeps {diff.removed.length})
        </label>
      </fieldset>
      {bytes > campus.bodyLimitBytes ? (
        <p role="alert" className="twin-error">This request is about {formatMiB(bytes)}; the API's default body limit is {formatMiB(campus.bodyLimitBytes)} and may reject it (413). Import a smaller extract.</p>
      ) : null}
    </ConfirmDialog>
  );
}

export function CampusBuildingsPanel({ campus }: { campus: CampusBuildingsWorkflow }) {
  const { query, summary, review } = campus;
  return (
    <section className="twin-card" aria-label="Campus buildings">
      <h4 className="twin-card-title">Campus buildings</h4>
      <div className="twin-badges">
        {summary ? <>
          <Badge text={`features ${summary.featureCount}`} tone="neutral" />
          <Badge text={`buildings ${summary.buildingCount}`} tone="info" />
          {summary.ignoredCount ? <Badge text={`ignored ${summary.ignoredCount}`} tone="warn" /> : null}
        </> : <Badge text="no GeoJSON imported" tone="neutral" />}
        {query.data && !query.isError ? <Badge text={`persisted ${campus.persisted.length}`} tone={campus.persisted.length > 0 ? "ok" : "neutral"} /> : null}
      </div>
      {query.isLoading ? <p role="status" className="twin-muted">Loading persisted campus buildings…</p> : null}
      {!query.data && !query.isLoading && !query.isError ? <p className="twin-muted">Persisted buildings load once a network is selected.</p> : null}
      {query.isError ? (
        <div role="alert" className="twin-error">
          Persisted campus buildings unavailable: {describeApiError(query.error)}{" "}
          <Button type="button" tone="ghost" onClick={() => void query.refetch()}>Retry loading buildings</Button>
        </div>
      ) : null}
      <label className="twin-field">
        <span className="mono twin-field-label">Campus GeoJSON file</span>
        <input aria-label="Campus GeoJSON file" type="file" accept=".geojson,.json,application/geo+json,application/json" onChange={(event) => {
          void campus.importFile(event.target.files?.[0] ?? null);
          event.target.value = "";
        }} />
      </label>
      {summary?.projection ? (
        <p className="twin-muted">
          Local metric projection (equirectangular about the dataset centroid {summary.projection.originLat.toFixed(5)}, {summary.projection.originLon.toFixed(5)}; cos φ corrected;
          ±{Math.round(summary.projection.extentMeters)} m extent). Approximate, not survey-grade. Heights: explicit height tags, else a schematic storey height.
        </p>
      ) : null}
      {summary?.warnings.length ? <ul aria-label="GeoJSON import warnings" className="twin-diff-list">{summary.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
      {campus.importing ? <p role="status" className="twin-muted">Parsing GeoJSON campus buildings...</p> : null}
      {campus.importError ? <p role="alert" className="twin-error">{campus.importError}</p> : null}
      {campus.persistError && !review ? <p role="alert" className="twin-error">{campus.persistError}</p> : null}
      <div className="twin-actions">
        {/* Not disabled while preparing, so focus stays on the opener and returns to it after the dialog. */}
        <Button type="button" tone="ghost" permission="write:config" disabled={!campus.canPersist} aria-busy={campus.preparing}
          onClick={() => void campus.requestPersist()}>
          {campus.persisting ? "Persisting buildings..." : campus.preparing ? "Comparing with persisted buildings…" : "Persist Buildings to Network"}
        </Button>
      </div>
      {review ? <CampusReviewDialog review={review} campus={campus} /> : null}
    </section>
  );
}
