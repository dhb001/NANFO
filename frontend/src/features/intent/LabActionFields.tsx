import { useState } from "react";
import { buildLabIntent, type LabActionInput } from "@/features/intent/logic";

export function LabActionFields({ onChange }: { onChange: (intent: ReturnType<typeof buildLabIntent>) => void }) {
  const [input, setInput] = useState<LabActionInput>({
    operation: "reroute", sourceHost: "h1", destinationHost: "h2", paths: "", weights: "", rate: "", dscp: "",
  });
  function update(patch: Partial<LabActionInput>) {
    const next = { ...input, ...patch };
    setInput(next);
    onChange(buildLabIntent(next));
  }
  const routing = input.operation === "reroute" || input.operation === "multipath";
  return (
    <fieldset style={{ display: "grid", gap: "0.7rem", minWidth: 0, border: "1px solid var(--line-soft)" }}>
      <legend>Disposable lab action</legend>
      <p>Manual changes only, not simulation validation. The server checks observed paths, trusted capabilities, binding and lab freshness.</p>
      <label>Operation <select value={input.operation} onChange={(event) => update({ operation: event.target.value as LabActionInput["operation"] })}>
        <option value="reroute">Reroute</option><option value="multipath">Multipath</option>
        <option value="shape">Shape</option><option value="police">Police</option><option value="restore">Restore owned policy</option>
      </select></label>
      {(["sourceHost", "destinationHost"] as const).map((field) => (
        <label key={field}>{field === "sourceHost" ? "Source host" : "Destination host"} <select value={input[field]} onChange={(event) => update({ [field]: event.target.value })}>
          {["h1", "h2", "h3", "h4"].map((host) => <option key={host}>{host}</option>)}
        </select></label>
      ))}
      {routing ? <>
        <label style={{ display: "grid", gap: "0.3rem" }}>Switch paths (one complete path per line)
          <textarea required rows={2} value={input.paths} placeholder="Enter observed switch names, separated by spaces" onChange={(event) => update({ paths: event.target.value })} />
        </label>
        <p>Reroute requires one simple source-access to destination-access path; multipath requires two.</p>
        <label>Weights (optional, positive integers; omitted means equal)
          <input value={input.weights} pattern="[1-9][0-9]*([ ,]+[1-9][0-9]*)*" onChange={(event) => update({ weights: event.target.value })} />
        </label>
      </> : null}
      {input.operation === "shape" || input.operation === "police" ? <label>Rate (Mbps)
        <input required type="number" min="0.000001" step="any" value={input.rate} onChange={(event) => update({ rate: event.target.value })} />
      </label> : null}
      <label>DSCP (optional classifier)
        <input type="number" min={0} max={63} step={1} value={input.dscp} onChange={(event) => update({ dscp: event.target.value })} />
      </label>
      {input.operation === "restore" ? <p>Restores only the last matching owned policy, never arbitrary switch rules.</p> : null}
    </fieldset>
  );
}
