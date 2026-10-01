/**
 * Top-down 2D plan used when WebGL is unavailable (pure layout + hit testing).
 *
 * Scene frame: +x east, +z south, so the plan draws x to the right and z downwards (north
 * up) with one uniform scale. The selected and alerting devices are always kept when the
 * plan has to be truncated.
 */

export const MAX_PLAN_NODES = 5_000;
export const MAX_PLAN_LINKS = 10_000;
export const PLAN_PICK_RADIUS_PX = 10;
export const PLAN_PADDING_PX = 24;

export const PLAN_COLORS = Object.freeze({ link: "#9aaac0", device: "#41516a", alert: "#b52e40", selected: "#2855d9" });

export interface PlanNodeInput { id: string; x: number; z: number }
export interface PlanLinkInput { sourceId: string; targetId: string }

export interface PlanPoint {
  id: string;
  x: number;
  y: number;
  alert: boolean;
  selected: boolean;
}

export interface PlanLayout {
  width: number;
  height: number;
  points: PlanPoint[];
  /** x1, y1, x2, y2 per drawn link. */
  segments: Float32Array;
  shownNodes: number;
  totalNodes: number;
  shownLinks: number;
  totalLinks: number;
}

export interface PlanOptions {
  width: number;
  height: number;
  padding?: number;
  alertingIds?: ReadonlySet<string>;
  selectedId?: string | null;
  maxNodes?: number;
  maxLinks?: number;
}

function finite(value: number): number {
  return Number.isFinite(value) ? value : 0;
}

function prioritised<T extends PlanNodeInput>(nodes: readonly T[], limit: number, alerting: ReadonlySet<string>, selectedId: string | null): T[] {
  if (nodes.length <= limit) return [...nodes];
  const first = nodes.filter((node) => node.id === selectedId || alerting.has(node.id)).slice(0, limit);
  const kept = new Set(first.map((node) => node.id));
  for (const node of nodes) {
    if (first.length >= limit) break;
    if (!kept.has(node.id)) first.push(node);
  }
  return first;
}

export function layoutPlan(nodes: readonly PlanNodeInput[], links: readonly PlanLinkInput[], options: PlanOptions): PlanLayout {
  const width = Math.max(1, options.width);
  const height = Math.max(1, options.height);
  const padding = Math.min(options.padding ?? PLAN_PADDING_PX, width / 4, height / 4);
  const alerting = options.alertingIds ?? new Set<string>();
  const selectedId = options.selectedId ?? null;
  const shown = prioritised(nodes, options.maxNodes ?? MAX_PLAN_NODES, alerting, selectedId);
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  for (const node of shown) {
    const x = finite(node.x), z = finite(node.z);
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (z < minZ) minZ = z;
    if (z > maxZ) maxZ = z;
  }
  if (!shown.length) { minX = maxX = minZ = maxZ = 0; }
  const spanX = Math.max(maxX - minX, 1e-6);
  const spanZ = Math.max(maxZ - minZ, 1e-6);
  const single = maxX - minX < 1e-6 && maxZ - minZ < 1e-6;
  const scale = single ? 1 : Math.min((width - 2 * padding) / spanX, (height - 2 * padding) / spanZ);
  const offsetX = single ? width / 2 - minX : (width - spanX * scale) / 2 - minX * scale;
  const offsetY = single ? height / 2 - minZ : (height - spanZ * scale) / 2 - minZ * scale;
  const byId = new Map<string, PlanPoint>();
  const points = shown.map((node) => {
    const point: PlanPoint = {
      id: node.id,
      x: finite(node.x) * scale + offsetX,
      y: finite(node.z) * scale + offsetY,
      alert: alerting.has(node.id),
      selected: node.id === selectedId,
    };
    byId.set(node.id, point);
    return point;
  });
  const maxLinks = options.maxLinks ?? MAX_PLAN_LINKS;
  const drawn: number[] = [];
  let shownLinks = 0;
  for (const link of links) {
    if (shownLinks >= maxLinks) break;
    const source = byId.get(link.sourceId);
    const target = byId.get(link.targetId);
    if (!source || !target) continue;
    drawn.push(source.x, source.y, target.x, target.y);
    shownLinks += 1;
  }
  return { width, height, points, segments: Float32Array.from(drawn), shownNodes: points.length, totalNodes: nodes.length, shownLinks, totalLinks: links.length };
}

/** Nearest device within `radius` CSS pixels of the pointer, or null. */
export function pickPlanPoint(layout: PlanLayout, x: number, y: number, radius = PLAN_PICK_RADIUS_PX): string | null {
  let best: string | null = null;
  let bestDistance = radius * radius;
  for (const point of layout.points) {
    const dx = point.x - x;
    const dy = point.y - y;
    const distance = dx * dx + dy * dy;
    if (distance <= bestDistance) {
      best = point.id;
      bestDistance = distance;
    }
  }
  return best;
}

/** Draws links, devices (circles), alerting devices (larger squares) and the selection ring. */
export function drawPlan(context: CanvasRenderingContext2D, layout: PlanLayout, pixelRatio = 1): void {
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, layout.width, layout.height);
  context.lineWidth = 1;
  context.strokeStyle = PLAN_COLORS.link;
  context.beginPath();
  for (let index = 0; index < layout.segments.length; index += 4) {
    context.moveTo(layout.segments[index] ?? 0, layout.segments[index + 1] ?? 0);
    context.lineTo(layout.segments[index + 2] ?? 0, layout.segments[index + 3] ?? 0);
  }
  context.stroke();
  context.fillStyle = PLAN_COLORS.device;
  context.beginPath();
  for (const point of layout.points) {
    if (point.alert) continue;
    context.moveTo(point.x + 3, point.y);
    context.arc(point.x, point.y, 3, 0, Math.PI * 2);
  }
  context.fill();
  context.fillStyle = PLAN_COLORS.alert;
  for (const point of layout.points) if (point.alert) context.fillRect(point.x - 5, point.y - 5, 10, 10);
  const selected = layout.points.find((point) => point.selected);
  if (selected) {
    context.lineWidth = 2;
    context.strokeStyle = PLAN_COLORS.selected;
    context.beginPath();
    context.arc(selected.x, selected.y, 9, 0, Math.PI * 2);
    context.stroke();
  }
}
