import { useRef, useState } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import type { SpatialSceneSnapshot } from "@/shared/types/spatial";
import { ApiClientError, toErrorMessage } from "@/shared/lib/errors";
import { Button } from "@/shared/ui/Button";
import { Panel } from "@/shared/ui/Panel";
import { EMPTY_SPATIAL_SCENE, MAX_SCENE_BYTES, parseSpatialScene, validateSpatialScene } from "./spatialScene";
import { useSaveSpatialScene } from "./spatialHooks";
import { SpatialHistoryPanel } from "./SpatialHistoryPanel";
import { GuidedSceneEditor } from "./GuidedSceneEditor";

interface Props {
  query: UseQueryResult<SpatialSceneSnapshot, Error>;
  token: string | null;
  networkId: string | null;
  canWrite: boolean;
  onSelectDevice: (id: string) => void;
}

export function SpatialScenePanel({ query, token, networkId, canWrite, onSelectDevice }: Props) {
  const [draft, setDraft] = useState<{ text: string; revision: number } | null>(null);
  const [message, setMessage] = useState("");
  const [conflict, setConflict] = useState(false);
  const [reading, setReading] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [guidedDirty, setGuidedDirty] = useState(false);
  const [editorVersion, setEditorVersion] = useState(0);
  const operation = useRef(0);
  const save = useSaveSpatialScene(token, networkId);
  const sceneText = JSON.stringify(query.data ? validateSpatialScene(query.data) : EMPTY_SPATIAL_SCENE, null, 2);
  const busy = save.isPending || query.isFetching || reading;
  const editable = canWrite && Boolean(query.data) && !busy;

  async function importFile(file: File | undefined) {
    if (!file || !editable || !query.data) return;
    const id = ++operation.current;
    setReading(true);
    try {
      if (file.size > MAX_SCENE_BYTES) throw new Error("Scene JSON exceeds 8 MiB.");
      const scene = parseSpatialScene(await file.text());
      if (id !== operation.current) return;
      setDraft({ text: JSON.stringify(scene, null, 2), revision: draft?.revision ?? query.data.revision });
      setGuidedDirty(false);
      setEditorVersion((value) => value + 1);
      setMessage("Imported and validated locally. Review the full replacement before saving.");
    } catch (error) { setMessage(toErrorMessage(error)); }
    finally { setReading(false); }
  }

  async function persist() {
    if (!draft || !editable || conflict || guidedDirty) return;
    try {
      const scene = parseSpatialScene(draft.text);
      if (!window.confirm(`Replace the complete spatial scene at revision ${draft.revision} with ${scene.objects.length} objects?`)) return;
      const result = await save.mutateAsync({ expected_revision: draft.revision, scene });
      setDraft(null);
      setGuidedDirty(false);
      setEditorVersion((value) => value + 1);
      setMessage(`Saved revision ${result.revision}.`);
    } catch (error) {
      if (error instanceof ApiClientError && error.status === 409 && error.code === "SPATIAL_REVISION_CONFLICT") {
        setConflict(true);
        setMessage("Revision conflict. Your draft is retained. Reload the server scene, compare it below, then explicitly rebase or discard your draft.");
      } else setMessage(toErrorMessage(error));
    }
  }

  return <Panel title="Canonical spatial scene" subtitle="Meters, y up; local-to-parent radians, matrix T × Rz × Ry × Rx.">
    {!networkId ? <p>Select a network.</p> : null}
    {query.isFetching ? <p role="status">Loading spatial scene…</p> : null}
    {query.isError ? <p role="alert">Spatial scene unavailable: {toErrorMessage(query.error)}. {query.data ? "Showing last loaded placements." : "Device positions use schematic fallback."}</p> : null}
    {query.data ? <p>Server revision {query.data.revision} · {query.data.objects.length} objects{draft ? ` · Unsaved draft based on revision ${draft.revision}` : ""}</p> : null}
    {query.data?.objects.length === 0 ? <p>No canonical placements yet. Import or edit a scene to place devices.</p> : null}
    {!canWrite ? <p>Read-only: editing requires write:config permission.</p> : null}
    <Button tone="ghost" disabled={!token || !networkId || busy} onClick={async () => {
      const result = await query.refetch();
      if (!result.isError) setMessage(draft ? "Server reloaded; unsaved draft retained for comparison." : "Server scene reloaded.");
    }}>Reload server scene</Button>
    <Button tone="ghost" aria-expanded={showHistory} onClick={() => setShowHistory(!showHistory)}>Browse spatial history</Button>
    {showHistory && token && networkId ? <SpatialHistoryPanel token={token} networkId={networkId} current={query.data} disabled={!editable} onStage={(scene) => {
      if (!editable || !query.data || !window.confirm(`Stage revision ${scene.revision} as a full replacement of current ${query.data.revision}? Unsaved draft edits will be replaced. Save separately to create a new revision.`)) return;
      setDraft({ text: JSON.stringify(validateSpatialScene(scene), null, 2), revision: query.data.revision });
      setGuidedDirty(false);
      setEditorVersion((value) => value + 1);
      setConflict(false); setMessage(`History revision ${scene.revision} staged locally. Review and save as a new revision.`);
    }} /> : null}
    <details>
      <summary>Spatial hierarchy and server JSON</summary>
      <p>Only explicit geometry is drawn. Device markers are symbols. Dimensions are local meters; omitted geometry stays omitted on restore.</p>
      <div className="twin-scroll-box">
        {query.data?.objects.map((object) => <div key={object.object_id}>
          {object.object_type}: {object.name} ({object.object_id}) ← {object.parent_id ?? "scene"}
          {object.device_id ? <Button tone="ghost" onClick={() => onSelectDevice(object.device_id!)}>Inspect {object.name}</Button> : null}
          <small> · {object.provenance.source} · accuracy {object.provenance.accuracy_m === null ? "unknown" : `${object.provenance.accuracy_m} m`}</small>
          {object.geometry?.kind === "wall" ? <small> · {object.geometry.material.name} · {object.geometry.material.attenuation_db ?? "unknown"} dB · {object.geometry.material.source}</small> : null}
        </div>)}
      </div>
      <pre className="twin-scroll-box">{sceneText}</pre>
    </details>
    <label>Import spatial scene JSON <input type="file" accept=".json,application/json" disabled={!editable} onChange={(event) => {
      void importFile(event.target.files?.[0]); event.target.value = "";
    }} /></label>
    <GuidedSceneEditor key={editorVersion} text={draft?.text ?? sceneText} disabled={!editable} token={token} networkId={networkId}
      onDirty={setGuidedDirty}
      onBegin={() => { if (!draft && query.data) setDraft({ text: sceneText, revision: query.data.revision }); }}
      onStage={(scene) => { setDraft({ text: JSON.stringify(scene, null, 2), revision: draft?.revision ?? query.data!.revision }); setMessage("Guided edits staged locally."); }} />
    <label className="twin-block-grid">Spatial scene JSON (advanced)
      <textarea aria-label="Spatial scene JSON" rows={12} spellCheck={false} value={draft?.text ?? sceneText} disabled={!editable} onChange={(event) => {
        setDraft({ text: event.target.value, revision: draft?.revision ?? query.data!.revision }); setGuidedDirty(false); setEditorVersion((value) => value + 1); setMessage("");
      }} />
    </label>
    <details><summary>Dimension editing guide</summary>
      <p>Add geometry to an object in the JSON, validate, then save the replacement. Box: building/room/rack; slab: floor; wall: direct floor/room child with null device_id. Dimensions: 0.000001–1000000 m.</p>
      <pre className="twin-scroll-x">{'{"kind":"box","width":12,"depth":8,"height":3}\n{"kind":"slab","width":12,"depth":8,"thickness":0.2}\n{"kind":"wall","length":8,"height":3,"thickness":0.15,"material":{"name":"drywall","attenuation_db":null,"source":"operator-survey"}}'}</pre>
      <p>Box/slab X and Z are centered; Y starts at zero. Wall X starts at zero, Y starts at zero, and thickness is centered on Z. Null attenuation means unknown. Material source records supplied provenance.</p>
    </details>
    <div className="twin-actions">
      <Button tone="ghost" disabled={!editable} onClick={() => {
        try { const scene = parseSpatialScene(draft?.text ?? sceneText); setMessage(`Valid scene: ${scene.objects.length} objects. Server checks network membership on save.`); }
        catch (error) { setMessage(toErrorMessage(error)); }
      }}>Validate JSON</Button>
      <Button permission="write:config" disabled={!editable || !draft || conflict || guidedDirty} onClick={persist}>{save.isPending ? "Saving…" : "Save scene replacement"}</Button>
      <Button tone="ghost" disabled={!draft || busy} onClick={() => {
        if (window.confirm("Discard unsaved scene edits?")) { setDraft(null); setGuidedDirty(false); setEditorVersion((value) => value + 1); setConflict(false); setMessage("Draft discarded."); }
      }}>Discard draft</Button>
      {draft && query.data && draft.revision !== query.data.revision ? <Button tone="ghost" disabled={!editable} onClick={() => {
        if (window.confirm("Use the latest server revision for this full replacement? Review the server JSON first; this does not merge concurrent edits.")) {
          setDraft({ ...draft, revision: query.data.revision }); setConflict(false); setMessage("Draft rebased locally. Review and save explicitly.");
        }
      }}>Rebase draft to revision {query.data.revision}</Button> : null}
    </div>
    {message ? <p role={conflict ? "alert" : "status"}>{message}</p> : null}
  </Panel>;
}
