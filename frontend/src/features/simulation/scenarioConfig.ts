import type { ScenarioConfig } from "@/shared/types/simulation";

export const exampleScenario: ScenarioConfig = {
  version: 1, seed: 42, tick_ms: 100, duration_ticks: 100,
  links: [
    { link_id: "access", source: "source", target: "router", capacity_mbps: 10, buffer_bytes: 125000, delay_ms: 10, initial_queue_bytes: 0 },
    { link_id: "egress", source: "router", target: "destination", capacity_mbps: 8, buffer_bytes: 125000, delay_ms: 10, initial_queue_bytes: 0 },
  ],
  flows: [{ flow_id: "offered-traffic", source: "source", target: "destination", path: ["access", "egress"], demand_mbps: [6] }],
  action_binding: null,
  limits: { max_loss_pct: 1, max_latency_ms: 100, min_throughput_mbps: 5 },
};

function object(value: unknown, keys: string[], path: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).some((key) => !keys.includes(key)) || keys.some((key) => !(key in value))) {
    throw new Error(`${path}: expected exactly ${keys.join(", ")}.`);
  }
  return value as Record<string, unknown>;
}

function numeric(value: unknown, min: number, max: number, path: string, integer = false) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < min || value > max || (integer && !Number.isSafeInteger(value))) {
    throw new Error(`${path}: expected a finite ${integer ? "integer" : "number"} from ${min} to ${max}.`);
  }
}

function identifier(value: unknown, path: string): asserts value is string {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/.test(value)) throw new Error(`${path}: use a nonempty identifier of at most 64 letters, digits, dots, colons, underscores or hyphens.`);
}

export function parseScenarioConfig(text: string): ScenarioConfig {
  if (text.length > 250000) throw new Error("Scenario editor limit: 250,000 characters.");
  const config = object(JSON.parse(text), ["version", "seed", "tick_ms", "duration_ticks", "links", "flows", "action_binding", "limits"], "scenario_config");
  if (config.version !== 1) throw new Error("Only scenario_config version 1 is supported.");
  numeric(config.seed, 0, Number.MAX_SAFE_INTEGER, "seed (browser-safe range)", true);
  numeric(config.tick_ms, 1, 1000, "tick_ms", true);
  numeric(config.duration_ticks, 1, 1000, "duration_ticks", true);
  if (!Array.isArray(config.links) || !config.links.length || config.links.length > 128) throw new Error("links: provide 1..128 explicit directed links.");
  if (!Array.isArray(config.flows) || !config.flows.length || config.flows.length > 64) throw new Error("flows: provide 1..64 explicit flows.");
  const links = new Map<string, Record<string, unknown>>();
  for (const item of config.links) {
    const link = object(item, ["link_id", "source", "target", "capacity_mbps", "buffer_bytes", "delay_ms", "initial_queue_bytes"], "link");
    for (const key of ["link_id", "source", "target"]) identifier(link[key], `link.${key}`);
    if (links.has(link.link_id as string)) throw new Error("Duplicate link_id.");
    if (link.source === link.target) throw new Error("Link endpoints must differ.");
    numeric(link.capacity_mbps, Number.MIN_VALUE, 1000000, "capacity_mbps");
    numeric(link.buffer_bytes, 0, 1e12, "buffer_bytes");
    numeric(link.initial_queue_bytes, 0, link.buffer_bytes as number, "initial_queue_bytes");
    numeric(link.delay_ms, 0, 60000, "delay_ms");
    links.set(link.link_id as string, link);
  }
  const flows = new Set<string>();
  let pathWork = 0;
  for (const item of config.flows) {
    const flow = object(item, ["flow_id", "source", "target", "path", "demand_mbps"], "flow");
    for (const key of ["flow_id", "source", "target"]) identifier(flow[key], `flow.${key}`);
    if (flows.has(flow.flow_id as string)) throw new Error("Duplicate flow_id.");
    flows.add(flow.flow_id as string);
    if (!Array.isArray(flow.path) || !flow.path.length || flow.path.length > 128) throw new Error("flow.path: provide 1..128 directed link IDs.");
    pathWork += flow.path.length;
    let node = flow.source;
    const visited = new Set([node]);
    for (const linkId of flow.path) {
      const link = links.get(linkId);
      if (!link || link.source !== node || visited.has(link.target)) throw new Error("flow.path must be connected, directed, acyclic and use configured links.");
      node = link.target;
      visited.add(node);
    }
    if (node !== flow.target) throw new Error("flow.path must end at the flow target.");
    if (!Array.isArray(flow.demand_mbps) || (flow.demand_mbps.length !== 1 && flow.demand_mbps.length !== config.duration_ticks)) throw new Error("demand_mbps: use one constant or exactly duration_ticks values.");
    for (const demand of flow.demand_mbps) numeric(demand, 0, 1000000, "demand_mbps");
  }
  const nodes = new Set([...links.values()].flatMap((link) => [link.source, link.target]));
  if (nodes.size > 128 || (config.duration_ticks as number) * (links.size + flows.size + pathWork) > 16384) throw new Error("Scenario exceeds 128 nodes or 16384 tick/link/flow/path work units.");
  const limits = object(config.limits, ["max_loss_pct", "max_latency_ms", "min_throughput_mbps"], "limits");
  numeric(limits.max_loss_pct, 0, 100, "max_loss_pct");
  numeric(limits.max_latency_ms, 0, 1e9, "max_latency_ms");
  numeric(limits.min_throughput_mbps, 0, 1000000, "min_throughput_mbps");
  if (config.action_binding !== null) {
    const binding = object(config.action_binding, ["intent_id", "plan_sha256", "network_state_sha256"], "action_binding");
    if (typeof binding.intent_id !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(binding.intent_id)) throw new Error("action_binding.intent_id: UUID required.");
    for (const key of ["plan_sha256", "network_state_sha256"]) if (typeof binding[key] !== "string" || !/^[a-f0-9]{64}$/.test(binding[key] as string)) throw new Error(`action_binding.${key}: lowercase SHA-256 required.`);
  }
  return config as unknown as ScenarioConfig;
}
