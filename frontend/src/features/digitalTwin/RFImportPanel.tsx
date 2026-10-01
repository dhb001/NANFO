import { useEffect, useRef, useState } from "react";
import type { SpatialSceneSnapshot } from "@/shared/types/spatial";
import { Button } from "@/shared/ui/Button";
import { MAX_RF_BYTES, MAX_RF_SAMPLES, parseRFArtifact, type RFSample } from "./rfArtifact";

export interface RFImportState { scene: SpatialSceneSnapshot; samples: RFSample[] }
export function RFImportPanel({ scene, workspaceId, networkId, value, onChange }: {
  scene?: SpatialSceneSnapshot | undefined; workspaceId: string | null; networkId: string | null;
  value: RFImportState | null; onChange: (value: RFImportState | null) => void;
}) {
  const [frame, setFrame] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const operation = useRef(0);
  useEffect(() => { const counter = operation; counter.current++; return () => { counter.current++; }; }, [scene, workspaceId, networkId]);
  const samples = value && value.scene === scene ? value.samples : [];
  return <section aria-label="Operator RF samples">
    <p>Import <code>evaluate_twin_physics.py spatial-rf</code> output:64 samples max,1MiB/file. Plain rf output is unsupported.</p>
    <p>Modeled RSSI, not congestion. Uncertainty: assumed ±dB, not a confidence interval. No SINR, interpolation or physical-safety authorization. Hashes verify consistency, not authenticity.</p>
    <label>Expected RF coordinate frame ID <input value={frame} disabled={busy || samples.length > 0} onChange={(event) => setFrame(event.target.value)} /></label>
    <label>Backend spatial-rf artifacts <input type="file" accept=".json,application/json" multiple disabled={busy || !scene || !workspaceId || !networkId || !frame.trim()} onChange={async (event) => {
      const files = Array.from(event.target.files ?? []); event.target.value = "";
      if (!files.length || !scene || !workspaceId || !networkId) return;
      const current = ++operation.current; setBusy(true); setMessage("");
      try {
        if (files.length + samples.length > MAX_RF_SAMPLES) throw new Error("At most64 RF samples.");
        const next = [...samples];
        for (const file of files) {
          if (file.size > MAX_RF_BYTES) throw new Error("RF artifact exceeds 1 MiB.");
          const sample = await parseRFArtifact(await file.text(), scene, workspaceId, networkId, frame);
          if (current !== operation.current) return;
          if (next.some((item) => item.receiverId === sample.receiverId || item.configHash !== sample.configHash)) throw new Error("Duplicate receiver or mixed RF configuration.");
          next.push(sample);
        }
        onChange({ scene, samples: next }); setMessage(`Imported ${next.length} RF samples; alignment verified.`);
      } catch (error) { if (current === operation.current) setMessage(error instanceof Error ? error.message : "RF import failed."); }
      finally { setBusy(false); }
    }} /></label>
    <Button tone="ghost" disabled={busy || !value} onClick={() => { onChange(null); setMessage("RF samples cleared."); }}>Clear RF samples</Button>
    {value && value.scene !== scene ? <p role="alert">Scene changed/unavailable: RF hidden. Reimport required.</p> : null}
    {busy ? <p role="status">Validating RF artifacts…</p> : null}
    {message ? <p role="status">{message}</p> : null}
    <div className="twin-scroll-pre">{samples.map((sample) => <details key={sample.receiverId}>
      <summary>{sample.receiverId}: {sample.signalDbm.toFixed(1)} dBm · {sample.uncertaintyDb === null ? "uncertainty unknown" : `assumed ±${sample.uncertaintyDb} dB`}</summary>
      <p>Network XYZ meters: {sample.position.join(", ")} · frame {sample.frameId} · revision {scene?.revision}</p>
      <p>Scene SHA256: {sample.sceneHash}<br />RF config SHA256: {sample.configHash}<br />RF request SHA256: {sample.inputHash}</p>
      <pre className="twin-pre-wrap">{sample.provenance}</pre>
    </details>)}</div>
  </section>;
}
