import type { SpatialSceneSnapshot } from "@/shared/types/spatial";

// Offline operator contract: scripts/evaluate_twin_physics.py spatial-rf output.
// No REST/event envelope, no frontend RF solver and no synthetic receiver positions.
export const MAX_RF_BYTES = 1024 * 1024;
export const MAX_RF_SAMPLES = 64;
type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type Rule = (value: unknown) => void;
const fail = (): never => { throw new Error("Invalid or unsupported spatial-rf artifact schema/bounds."); };
const literal = (...values: unknown[]): Rule => (value) => { if (!values.includes(value)) fail(); };
const number = (min: number, max: number): Rule => (value) => { if (typeof value !== "number" || !Number.isFinite(value) || value < min || value > max) fail(); };
const nullable = (rule: Rule): Rule => (value) => { if (value !== null) rule(value); };
const id: Rule = (value) => { if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/.test(value)) fail(); };
const spatialId: Rule = (value) => { if (typeof value !== "string" || !value.trim() || value.length > 128 || value.includes("\0")) fail(); };
const hash: Rule = (value) => { if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) fail(); };
function record(value: unknown): Record<string, Json> {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail();
  return value as Record<string, Json>;
}
const object = (fields: Record<string, Rule>): Rule => (value) => {
  const item = record(value);
  if (Object.keys(item).length !== Object.keys(fields).length || Object.keys(item).some((key) => !Object.hasOwn(fields, key))) fail();
  for (const [key, rule] of Object.entries(fields)) rule(item[key]);
};
const list = (rule: Rule): Rule => (value) => { if (!Array.isArray(value) || value.length > 256) return fail(); value.forEach(rule); };
const map = (keyRule: Rule, rule: Rule): Rule => (value) => {
  const item = record(value); if (Object.keys(item).length > 1806) fail();
  for (const [key, entry] of Object.entries(item)) { keyRule(key); rule(entry); }
};
const point = object({ x: number(-100000, 100000), y: number(-100000, 100000), z: number(-100000, 100000) });
const scope = object({ workspace_id: id, network_id: id });
const source = object({ kind: literal("configured", "measured"), source_id: id, record_id: id, artifact_sha256: hash });
const material = literal("glass", "drywall", "concrete", "metal", "custom");
const uncertainty = nullable((value) => { number(Number.MIN_VALUE, 100)(value); });
const RF_VERSION = "log-distance-segment-walls.v1";
const rfScene = object({ model_version: literal(RF_VERSION), scope, scene_id: id, coordinate_frame_id: id, geometry_source_id: id,
  transmitter_id: id, transmitter: point, frequency_mhz: number(100, 100000), tx_power_dbm: number(-100, 60), tx_gain_dbi: number(-30, 60), rx_gain_dbi: number(-30, 60),
  path_loss_exponent: number(1, 6), reference_distance_m: number(1, 100), uncertainty_db: uncertainty,
  walls: list(object({ wall_id: id, start: point, end: point, height_m: number(Number.MIN_VALUE, 1000), material, loss_db: nullable(number(0, 100)) })) });
const provenance = object({ version: literal("canonical-spatial-rf.v1"), scope, scene_revision: (value) => { number(1, Number.MAX_SAFE_INTEGER)(value); if (!Number.isSafeInteger(value)) fail(); },
  spatial_document_sha256: hash, adapter_input_sha256: hash, rf_config_sha256: hash, axis_conversion: literal("network(X,Y,Z)->rf(X,-Z,Y)"),
  radio_object_id: spatialId, radio_device_id: spatialId, receiver_frame_object_id: spatialId, wall_frame_object_ids: map(id, spatialId),
  scene_source: source, radio_source: source, receiver_source: source, wall_inventory_source: source, wall_sources: map(id, source),
  placement_accuracy_m: map(spatialId, number(0, 1000000)), physical_safety_authorized: literal(false) });
const evaluation = object({ model_version: literal(RF_VERSION), source: literal("operator_configured_model"), physical_safety_authorized: literal(false), scope,
  config_sha256: hash, input_sha256: hash, receiver_id: id, distance_m: number(0, 350000), effective_distance_m: number(1, 350000), distance_clamped: literal(true, false),
  reference_loss_db: number(-1000, 1000), distance_loss_db: number(0, 1000), wall_loss_db: number(0, 25600), signal_dbm: number(-30000, 1000),
  crossings: list(object({ wall_id: id, material, loss_db: number(0, 100), loss_source: literal("configured", "nominal_default") })),
  uncertainty_db: uncertainty, interference_dbm: literal(null), sinr_db: literal(null), congestion: literal(null) });

/** Python json.dumps(sort_keys=True, ensure_ascii=True) after Pydantic float coercion.
 * Scene version/revision are ints; all RF numeric fields and spatial vectors are floats.
 */
export function pythonCanonical(value: Json, key = ""): string {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) fail();
    if (key === "version" || key === "revision") return String(value);
    if (Object.is(value, -0)) return "-0.0";
    const raw = value !== 0 && (Math.abs(value) < 0.0001 || Math.abs(value) >= 1e16) ? value.toExponential() : String(value);
    return raw.includes("e") ? raw.replace(/e([+-]?)(\d+)$/, (_, sign: string, digits: string) => `e${sign || "+"}${digits.padStart(2, "0")}`) : raw.includes(".") ? raw : `${raw}.0`;
  }
  if (Array.isArray(value)) return `[${value.map((entry) => pythonCanonical(entry)).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.keys(value).sort(codepointOrder).map((name) => `${pythonCanonical(name)}:${pythonCanonical(value[name], name)}`).join(",")}}`;
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g, (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
}
function codepointOrder(a: string, b: string) {
  const left = Array.from(a, (char) => char.codePointAt(0)!); const right = Array.from(b, (char) => char.codePointAt(0)!);
  for (let i = 0; i < Math.min(left.length, right.length); i++) if (left[i] !== right[i]) return left[i] - right[i];
  return left.length - right.length;
}
async function digest(value: Json) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(pythonCanonical(value)));
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
export async function rfSpatialHash(scene: SpatialSceneSnapshot) {
  return digest({ ...scene, objects: [...scene.objects].sort((a, b) => codepointOrder(a.object_id, b.object_id)) } as unknown as Json);
}

export interface RFSample {
  receiverId: string; position: [number, number, number]; signalDbm: number; uncertaintyDb: number | null;
  frameId: string; configHash: string; sceneHash: string; inputHash: string; provenance: string;
}
export async function parseRFArtifact(text: string, scene: SpatialSceneSnapshot, workspaceId: string, networkId: string, frameId: string): Promise<RFSample> {
  if (new Blob([text]).size > MAX_RF_BYTES) throw new Error("RF artifact exceeds 1 MiB.");
  const artifact = record(JSON.parse(text));
  object({ rf_request: object({ scene: rfScene, receiver_id: id, receiver: point }), provenance, evaluation })(artifact);
  const request = record(artifact.rf_request); const config = record(request.scene); const p = record(artifact.provenance); const result = record(artifact.evaluation);
  const aligned = (condition: boolean) => { if (!condition) throw new Error("RF artifact scene/revision/scope/frame or evidence mismatch."); };
  for (const item of [config, p, result]) {
    const scoped = record(item.scope); aligned(scoped.workspace_id === workspaceId && scoped.network_id === networkId);
  }
  const sceneHash = await rfSpatialHash(scene);
  aligned(scene.revision > 0 && p.scene_revision === scene.revision && p.spatial_document_sha256 === sceneHash && record(p.scene_source).artifact_sha256 === sceneHash);
  aligned(frameId.trim() !== "" && config.coordinate_frame_id === frameId);
  const objects = new Map(scene.objects.map((item) => [item.object_id, item]));
  const radio = objects.get(p.radio_object_id as string);
  aligned(radio?.object_type === "device" && radio.device_id === p.radio_device_id);
  const frames = record(p.wall_frame_object_ids); const sources = record(p.wall_sources); const accuracies = record(p.placement_accuracy_m);
  const walls = config.walls as Record<string, Json>[];
  aligned(new Set(walls.map((wall) => wall.wall_id)).size === walls.length && Object.keys(frames).length === walls.length && Object.keys(sources).length === walls.length);
  const needed = new Set<string>();
  for (const start of [p.radio_object_id, p.receiver_frame_object_id, ...Object.values(frames)]) {
    let current = start as string | null;
    while (current !== null) {
      const item = objects.get(current); aligned(Boolean(item));
      aligned(item!.provenance.source !== "schematic-fallback" && item!.provenance.accuracy_m !== null && accuracies[current] === item!.provenance.accuracy_m);
      needed.add(current); current = item!.parent_id;
    }
  }
  aligned(needed.size === Object.keys(accuracies).length);
  for (const evidence of [p.scene_source, p.radio_source, p.receiver_source, p.wall_inventory_source, ...Object.values(sources)]) aligned(record(evidence).source_id !== "schematic-fallback");
  for (const wall of walls) {
    aligned(Object.hasOwn(frames, wall.wall_id as string) && Object.hasOwn(sources, wall.wall_id as string));
    const start = record(wall.start); const end = record(wall.end);
    aligned(start.z === end.z && Math.hypot((end.x as number) - (start.x as number), (end.y as number) - (start.y as number)) >= 1e-6 && (wall.material !== "custom" || wall.loss_db !== null));
  }
  aligned(config.geometry_source_id === record(p.wall_inventory_source).source_id && result.receiver_id === request.receiver_id && result.uncertainty_db === config.uncertainty_db);
  const canonical = { ...config, walls: [...walls].sort((a, b) => codepointOrder(a.wall_id as string, b.wall_id as string)) };
  const configHash = await digest(canonical);
  aligned(configHash === p.rf_config_sha256 && configHash === result.config_sha256 && await digest({ ...request, scene: canonical }) === result.input_sha256);
  const crossings = result.crossings as Record<string, Json>[];
  aligned(new Set(crossings.map((crossing) => crossing.wall_id)).size === crossings.length && crossings.every((crossing) => walls.some((wall) => wall.wall_id === crossing.wall_id && wall.material === crossing.material)));
  const receiver = record(request.receiver);
  return { receiverId: request.receiver_id as string, position: [receiver.x as number, receiver.z as number, -(receiver.y as number)],
    signalDbm: result.signal_dbm as number, uncertaintyDb: result.uncertainty_db as number | null, frameId,
    configHash, sceneHash, inputHash: result.input_sha256 as string, provenance: JSON.stringify(p, null, 2) };
}
