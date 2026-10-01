import { useState } from "react";
import { Button } from "@/shared/ui/Button";
import type { AssetRegistration } from "@/shared/types/network";
import { registrationTransform, validateRegistration } from "./modelRegistration";

export interface ModelRegistration {
  position: [number, number, number];
  rotation: [number, number, number];
  scale: [number, number, number];
}

export function ModelRegistrationControls({ initial, saved = false, disabled = false, onApply }: { initial?: AssetRegistration | null; saved?: boolean; disabled?: boolean; onApply: (value: AssetRegistration) => void }) {
  const [values, setValues] = useState(() => initial ? [...registrationTransform(initial).position, ...registrationTransform(initial).rotation, ...registrationTransform(initial).scale].map(String) : ["0", "0", "0", "0", "0", "0", "1", "1", "1"]);
  const [source, setSource] = useState(initial?.source ?? "");
  const [applied, setApplied] = useState(false);
  const [dirty, setDirty] = useState(false);
  const numbers = values.map(Number);
  let candidate: AssetRegistration | null = null;
  try {
    if (values.every((value) => value.trim() !== "")) candidate = validateRegistration({ version: 1, translation: { x: numbers[0], y: numbers[1], z: numbers[2] }, rotation: { x: numbers[3], y: numbers[4], z: numbers[5] }, scale: { x: numbers[6], y: numbers[7], z: numbers[8] }, target_units: "m", target_up_axis: "y", source });
  } catch { /* Invalid drafts cannot be applied. */ }
  return <fieldset disabled={disabled}>
    <legend>Model registration — {saved && !dirty ? "saved" : "local, unsaved"}</legend>
    <p>Translation meters; rotation radians (Rz × Ry × Rx); positive XYZ scale into meter/Y-up. Apply locally, then Persist Model Asset to save. Legacy assets remain unregistered.</p>
    <div className="twin-registration-grid">
      {["Position X", "Position Y", "Position Z", "Rotation X", "Rotation Y", "Rotation Z", "Scale X", "Scale Y", "Scale Z"].map((label, index) => <label key={label} className="twin-registration-field">{label}
        <input type="number" step="any" value={values[index]} onChange={(event) => { setValues(values.map((value, i) => i === index ? event.target.value : value)); setApplied(false); setDirty(true); }} />
      </label>)}
    </div>
    <label>Registration source <input value={source} onChange={(event) => { setSource(event.target.value); setApplied(false); setDirty(true); }} /></label>
    <Button tone="ghost" disabled={!candidate} onClick={() => {
      onApply(candidate!); setApplied(true);
    }}>Apply local registration</Button>
    <p role="status">{!candidate ? "Finite transforms, positive scale and source required." : applied ? "Registration applied locally — unsaved." : "Review and apply registration."}</p>
  </fieldset>;
}
