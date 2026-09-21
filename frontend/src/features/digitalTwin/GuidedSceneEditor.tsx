import { useState } from "react";
import type { SpatialObject, SpatialScene } from "@/shared/types/spatial";
import { Button } from "@/shared/ui/Button";
import { toErrorMessage } from "@/shared/lib/errors";
import { parseSpatialScene, validateSpatialScene } from "./spatialScene";
import { TwinInventoryPicker } from "./TwinInventoryPicker";

export function GuidedSceneEditor({ text, disabled, token, networkId, onBegin, onStage, onDirty }: {
  text: string; disabled: boolean; token: string | null; networkId: string | null;
  onBegin: () => void; onStage: (scene: SpatialScene) => void;
  onDirty: (dirty: boolean) => void;
}) {
  const [selection, setSelection] = useState("");
  const [open, setOpen] = useState(false);
  const [opened, setOpened] = useState(false);
  const [dirty, setDirty] = useState(false);
  let scene: SpatialScene;
  try { scene = parseSpatialScene(text); }
  catch { return <p role="status">Correct the advanced JSON before guided editing.</p>; }
  const object = scene.objects.find((item) => item.object_id === selection);
  return <div>
    <Button tone="ghost" aria-expanded={open} onClick={() => { setOpened(true); setOpen(!open); }}>Guided object editor</Button>
    {opened ? <div hidden={!open}>
      <label>Scene object <select disabled={disabled} value={selection} onChange={(event) => {
        if (dirty && !window.confirm("Discard unstaged object fields and select another object?")) return;
        setSelection(event.target.value); setDirty(false); onDirty(false);
      }}>
        <option value="">New object</option>
        {scene.objects.map((item) => <option key={item.object_id} value={item.object_id}>{item.name} ({item.object_id})</option>)}
      </select></label>
      <ObjectForm key={`${selection}:${text}`} object={object} scene={scene} disabled={disabled} token={token} networkId={networkId}
        onBegin={() => { setDirty(true); onDirty(true); onBegin(); }} onStage={(next, id) => { onStage(next); setSelection(id); setDirty(false); onDirty(false); }} />
      {dirty ? <p role="status">Unstaged object fields — stage this object before saving the scene.</p> : null}
    </div> : null}
  </div>;
}

function ObjectForm({ object, scene, disabled, token, networkId, onBegin, onStage }: {
  object?: SpatialObject; scene: SpatialScene; disabled: boolean; token: string | null; networkId: string | null;
  onBegin: () => void; onStage: (scene: SpatialScene, id: string) => void;
}) {
  const [kind, setKind] = useState<string>(object?.geometry?.kind ?? (object?.geometry === null ? "null" : "omitted"));
  const [deviceId, setDeviceId] = useState(object?.device_id ?? "");
  const [message, setMessage] = useState("");
  function field(label: string, name: string, value: string | number | null | undefined, numeric = false) {
    return <label style={{ display: "grid" }} key={name}>{label}<input name={name} defaultValue={value ?? ""} type={numeric ? "number" : "text"} step={numeric ? "any" : undefined} /></label>;
  }
  return <form onChange={onBegin} onSubmit={(event) => {
    event.preventDefault();
    if (disabled) return;
    const data = new FormData(event.currentTarget);
    const str = (key: string) => String(data.get(key) ?? "");
    const num = (key: string) => str(key).trim() === "" ? NaN : Number(str(key));
    const vector = (key: string) => ({ x: num(`${key}.x`), y: num(`${key}.y`), z: num(`${key}.z`) });
    const geometry = kind === "omitted" ? {} : { geometry: kind === "null" ? null : {
      kind, ...Object.fromEntries((kind === "box" ? ["width", "depth", "height"] : kind === "slab" ? ["width", "depth", "thickness"] : ["length", "height", "thickness"]).map((key) => [key, num(key)])),
      ...(kind === "wall" ? { material: { name: str("material.name"), source: str("material.source"), attenuation_db: str("attenuation") === "" ? null : num("attenuation") } } : {}),
    } };
    try {
      const candidate = { object_id: str("id"), name: str("name"), object_type: str("type"), parent_id: str("parent") || null,
        position: vector("position"), rotation: vector("rotation"), device_id: deviceId || null,
        provenance: { source: str("source"), accuracy_m: str("accuracy") === "" ? null : num("accuracy") }, ...geometry };
      const objects = object ? scene.objects.map((item) => item.object_id === object.object_id ? candidate : item) : [...scene.objects, candidate];
      onStage(validateSpatialScene({ ...scene, objects }), candidate.object_id);
    } catch (error) { setMessage(toErrorMessage(error)); }
  }}>
    <fieldset disabled={disabled}><legend>{object ? `Edit ${object.object_id}` : "Create object"}</legend>
      <p>Supply measured or explicitly chosen transforms. Blank accuracy and attenuation mean unknown. Dimensions are never inferred. Stage before switching objects; save separately.</p>
      {field("Object ID", "id", object?.object_id)}
      {field("Object name", "name", object?.name)}
      <label>Object type <select name="type" defaultValue={object?.object_type ?? "building"}>
        {["campus", "building", "floor", "room", "rack", "wall", "device", "interface"].map((type) => <option key={type}>{type}</option>)}
      </select></label>
      <label>Parent object <select name="parent" defaultValue={object?.parent_id ?? ""}>
        <option value="">Scene root</option>
        {scene.objects.map((item) => <option key={item.object_id} value={item.object_id}>{item.object_id} ({item.object_type})</option>)}
      </select></label>
      {(["position", "rotation"] as const).map((key) => <fieldset key={key}><legend>{key === "position" ? "Local position (m)" : "Local rotation (radians)"}</legend>
        {(["x", "y", "z"] as const).map((axis) => field(`${key} ${axis}`, `${key}.${axis}`, object?.[key][axis], true))}
      </fieldset>)}
      {field("Provenance source", "source", object?.provenance.source)}
      {field("Accuracy (m, blank unknown)", "accuracy", object?.provenance.accuracy_m, true)}
      <label>Geometry <select value={kind} onChange={(event) => setKind(event.target.value)}>
        {["omitted", "null", "box", "slab", "wall"].map((value) => <option key={value}>{value}</option>)}
      </select></label>
      {["box", "slab", "wall"].includes(kind) ? <fieldset key={kind}><legend>Dimensions (m)</legend>
        {(kind === "box" ? ["width", "depth", "height"] : kind === "slab" ? ["width", "depth", "thickness"] : ["length", "height", "thickness"]).map((key) => field(key, key, (object?.geometry as unknown as Record<string, number> | undefined)?.[key], true))}
        {kind === "wall" ? <>
          {field("Material name", "material.name", object?.geometry?.kind === "wall" ? object.geometry.material.name : "")}
          {field("Material source", "material.source", object?.geometry?.kind === "wall" ? object.geometry.material.source : "")}
          {field("Attenuation (dB, blank unknown)", "attenuation", object?.geometry?.kind === "wall" ? object.geometry.material.attenuation_db : null, true)}
        </> : null}
      </fieldset> : null}
      <p>Associated device: {deviceId || "none"}</p>
      <Button type="button" tone="ghost" onClick={() => { onBegin(); setDeviceId(""); }}>Clear device association</Button>
      <TwinInventoryPicker token={token} networkId={networkId} selected={deviceId ? [deviceId] : []} onToggle={(id) => { onBegin(); setDeviceId(id === deviceId ? "" : id); }} />
      <Button type="submit">Stage object in draft</Button>
      {object ? <Button type="button" tone="ghost" onClick={() => {
        try {
          const next = validateSpatialScene({ ...scene, objects: scene.objects.filter((item) => item.object_id !== object.object_id) });
          if (window.confirm(`Remove ${object.object_id} from the draft?`)) onStage(next, "");
        } catch (error) { setMessage(toErrorMessage(error)); }
      }}>Remove object from draft</Button> : null}
    </fieldset>
    {message ? <p role="status">{message}</p> : null}
  </form>;
}
