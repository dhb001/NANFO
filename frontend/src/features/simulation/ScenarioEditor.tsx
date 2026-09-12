import { useState } from "react";
import { Button } from "@/shared/ui/Button";
import { exampleScenario, parseScenarioConfig } from "./scenarioConfig";

export function ScenarioEditor({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const [advanced, setAdvanced] = useState(false);
  let error = "";
  try { parseScenarioConfig(value); } catch (cause) { error = cause instanceof Error ? cause.message : "Invalid scenario JSON."; }
  const config = (() => { try { return parseScenarioConfig(value); } catch { return null; } })();
  return <fieldset style={{ minWidth: 0, display: "grid", gap: "0.65rem", border: "1px solid var(--line-soft)", borderRadius: 10 }}>
    <legend>Configured scenario v1</legend>
    <p>Explicit operator example, not live topology or measured traffic. Review capacities, queues, paths, demands and limits before starting. These are simulation knobs, not live PPO weights.</p>
    <label><input type="checkbox" checked={advanced} onChange={(event) => setAdvanced(event.target.checked)} /> Advanced scenario JSON (custom links, flows and action binding)</label>
    {advanced || !config ? <label style={{ display: "grid", gap: "0.4rem" }}>Scenario configuration JSON
      <textarea aria-label="Scenario configuration JSON" rows={18} value={value} onChange={(event) => onChange(event.target.value)} spellCheck={false} style={{ width: "100%", minWidth: 0, boxSizing: "border-box", fontFamily: "var(--font-mono)" }} />
    </label> : <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "0.65rem" }}>
        {(["seed", "tick_ms", "duration_ticks"] as const).map((key) => <label key={key} style={{ display: "grid" }}>{key}<input type="number" step={1} value={config[key]} onChange={(event) => onChange(JSON.stringify({ ...config, [key]: event.target.value === "" ? null : Number(event.target.value) }, null, 2))} /></label>)}
        {(["max_loss_pct", "max_latency_ms", "min_throughput_mbps"] as const).map((key) => <label key={key} style={{ display: "grid" }}>{key}<input type="number" step="any" value={config.limits[key]} onChange={(event) => onChange(JSON.stringify({ ...config, limits: { ...config.limits, [key]: event.target.value === "" ? null : Number(event.target.value) } }, null, 2))} /></label>)}
      </div>
      <p>{config.links.length} directed links; {config.flows.length} flows; {config.tick_ms * config.duration_ticks} ms configured duration. Seed recorded; v1 has no hidden random demand.</p>
      {config.links.map((link, index) => <fieldset key={link.link_id} style={{ minWidth: 0 }}><legend>{link.link_id}: {link.source} to {link.target}</legend>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "0.5rem" }}>{(["capacity_mbps", "buffer_bytes", "delay_ms", "initial_queue_bytes"] as const).map((key) => <label key={key} style={{ display: "grid" }}>{key}<input aria-label={`${link.link_id} ${key}`} type="number" step="any" value={link[key]} onChange={(event) => onChange(JSON.stringify({ ...config, links: config.links.map((item, i) => i === index ? { ...item, [key]: Number(event.target.value) } : item) }, null, 2))} /></label>)}</div>
      </fieldset>)}
      {config.flows.map((flow, index) => <label key={flow.flow_id} style={{ display: "grid" }}>{flow.flow_id}: {flow.source} to {flow.target}, path {flow.path.join(" / ")}<span>Demand Mbps (one constant or one value per tick)</span><input aria-label={`${flow.flow_id} demand Mbps`} value={flow.demand_mbps.join(", ")} onChange={(event) => onChange(JSON.stringify({ ...config, flows: config.flows.map((item, i) => i === index ? { ...item, demand_mbps: event.target.value.split(",").map((part) => part.trim() ? Number(part) : null) } : item) }, null, 2))} /></label>)}
      <p>Action binding: {config.action_binding ? `intent ${config.action_binding.intent_id}` : "Unbound example; not execution evidence. Add exact intent, plan and network hashes in advanced JSON if needed."}</p>
    </>}
    {error && <p role="alert">{error}</p>}
    <Button type="button" tone="ghost" onClick={() => onChange(JSON.stringify(exampleScenario, null, 2))}>Load configured example</Button>
    <p>Strict versioned inputs; unknown fields and nonfinite/coerced values are rejected. Server validation and workload bounds remain authoritative.</p>
  </fieldset>;
}
