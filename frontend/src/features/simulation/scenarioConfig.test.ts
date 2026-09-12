import { describe, expect, it } from "vitest";
import { exampleScenario, parseScenarioConfig } from "./scenarioConfig";

describe("strict ADR017 scenario editor", () => {
  it("accepts the explicit example, fractional byte queues and exact action binding", () => {
    expect(parseScenarioConfig(JSON.stringify(exampleScenario))).toEqual(exampleScenario);
    const config = structuredClone(exampleScenario);
    config.links[0].initial_queue_bytes = 0.5;
    config.action_binding = { intent_id: "00000000-0000-0000-0000-000000000001", plan_sha256: "a".repeat(64), network_state_sha256: "b".repeat(64) };
    expect(parseScenarioConfig(JSON.stringify(config))).toEqual(config);
  });
  it.each([
    { version: 2 }, { version: true }, { seed: "42" }, { seed: Number.MAX_SAFE_INTEGER + 1 }, { tick_ms: true }, { duration_ticks: 1001 }, { unknown: 1 },
    { action_binding: {} }, { links: [] }, { limits: { ...exampleScenario.limits, max_loss_pct: 101 } },
  ])("rejects unsupported versions, coerced values and unknown shapes: %j", (change) => {
    expect(() => parseScenarioConfig(JSON.stringify({ ...exampleScenario, ...change }))).toThrow();
  });
  it("rejects malformed JSON, nonfinite values, invalid queues and duplicate IDs", () => {
    expect(() => parseScenarioConfig("{" )).toThrow();
    expect(() => parseScenarioConfig(JSON.stringify(exampleScenario).replace('"seed":42', '"seed":1e999'))).toThrow();
    const config = structuredClone(exampleScenario);
    config.links[0].initial_queue_bytes = config.links[0].buffer_bytes + 1;
    expect(() => parseScenarioConfig(JSON.stringify(config))).toThrow(/initial_queue_bytes/);
    config.links[0].initial_queue_bytes = 0;
    config.links.push(config.links[0]);
    expect(() => parseScenarioConfig(JSON.stringify(config))).toThrow(/Duplicate/);
  });
  it("enforces connected acyclic paths, demand schedules and server work bounds", () => {
    const config = structuredClone(exampleScenario);
    config.flows[0].path.reverse();
    expect(() => parseScenarioConfig(JSON.stringify(config))).toThrow(/connected/);
    config.flows[0].path.reverse();
    config.flows[0].demand_mbps = [1, 2];
    expect(() => parseScenarioConfig(JSON.stringify(config))).toThrow(/duration_ticks/);
    config.flows[0].demand_mbps = [6];
    config.duration_ticks = 1000;
    config.flows = Array.from({ length: 10 }, (_, index) => ({ ...config.flows[0], flow_id: `f${index}` }));
    expect(() => parseScenarioConfig(JSON.stringify(config))).toThrow(/16384/);
  });
});
