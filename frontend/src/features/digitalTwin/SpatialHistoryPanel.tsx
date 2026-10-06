import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSessionScope } from "@/features/auth/sessionScope";
import { scopedKey } from "@/shared/lib/queryKeys";
import type { SpatialSceneSnapshot } from "@/shared/types/spatial";
import { Button } from "@/shared/ui/Button";
import { toErrorMessage } from "@/shared/lib/errors";
import { getSpatialHistory, getSpatialRevision } from "./spatialApi";
import { diffSpatialScenes } from "./spatialHistory";

export function SpatialHistoryPanel({ token, networkId, current, disabled, onStage }: {
  token: string; networkId: string; current?: SpatialSceneSnapshot | undefined; disabled: boolean;
  onStage: (scene: SpatialSceneSnapshot) => void;
}) {
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState<number | null>(null);
  const scope = useSessionScope();
  // Session-scoped keys: rotating the access token neither refetches nor drops history.
  const history = useQuery({ queryKey: scopedKey(scope, "spatial-history", networkId, page, current?.revision),
    queryFn: ({ signal }) => scope.read((credential) => getSpatialHistory(credential, networkId, page, signal), signal), enabled: Boolean(token), retry: false });
  const detail = useQuery({ queryKey: scopedKey(scope, "spatial-revision", networkId, revision),
    queryFn: ({ signal }) => scope.read((credential) => getSpatialRevision(credential, networkId, revision!, signal), signal), enabled: Boolean(token) && revision !== null, retry: false });
  const diff = current && detail.data ? diffSpatialScenes(current, detail.data) : null;
  return <section aria-label="Spatial history">
    <p>Immutable history; restore creates a new revision. Live pages may shift after writes.</p>
    {history.isFetching || detail.isFetching ? <p role="status">Loading history…</p> : null}
    {history.error || detail.error ? <p role="alert">{toErrorMessage(history.error ?? detail.error)}</p> : null}
    <Button tone="ghost" onClick={() => { void history.refetch(); if (revision !== null) void detail.refetch(); }}>Reload history</Button>
    {history.data?.items.length === 0 ? <p>No history on this page.</p> : null}
    {history.data?.items.map((item) => <div key={item.revision}>
      <Button tone="ghost" onClick={() => setRevision(item.revision)}>Revision {item.revision}</Button> {item.origin} · {item.recorded_at} · {item.object_count} objects · actor {item.actor_id ?? "unknown"}
    </div>)}
    <Button tone="ghost" disabled={page === 1 || history.isFetching} onClick={() => setPage(page - 1)}>Previous history page</Button>
    <Button tone="ghost" disabled={!history.data || page * 20 >= history.data.total || history.isFetching} onClick={() => setPage(page + 1)}>Next history page</Button>
    {detail.data && diff ? <>
      <p>Restore revision {detail.data.revision} over current {current!.revision}: +{diff.added.length} / −{diff.removed.length} / changed {diff.changed.length}</p>
      <details><summary>Restore diff and historical JSON</summary><pre className="twin-scroll-pre">{JSON.stringify({ diff, scene: detail.data }, null, 2)}</pre></details>
      <Button permission="write:config" disabled={disabled || detail.isFetching || detail.isError} onClick={() => onStage(detail.data)}>Stage revision {detail.data.revision} for restore</Button>
    </> : null}
  </section>;
}
