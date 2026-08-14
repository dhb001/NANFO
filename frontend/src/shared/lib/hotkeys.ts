export interface ChordNavigationResult {
  nextPrefix: string | null;
  path: string | null;
}

const singleKeyNavigation: Record<string, string> = {
  o: "/ops/overview",
  w: "/ops/tenancy",
  p: "/ops/topology-analysis",
  t: "/ops/telemetry",
  r: "/ops/reliability",
  l: "/ops/reliability",
  u: "/ops/plugins",
  y: "/ops/reports",
  d: "/ops/digital-twin",
  s: "/ops/simulation",
  i: "/ops/intent",
  a: "/ops/audit",
};

const prefixedNavigation: Record<string, string> = {
  go: "/ops/overview",
  gw: "/ops/tenancy",
  gp: "/ops/topology-analysis",
  gt: "/ops/telemetry",
  gr: "/ops/reliability",
  gl: "/ops/reliability",
  gu: "/ops/plugins",
  gy: "/ops/reports",
  gd: "/ops/digital-twin",
  gs: "/ops/simulation",
  gi: "/ops/intent",
  ga: "/ops/audit",
};

export function shouldIgnoreHotkeyTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  if (target.isContentEditable || target.getAttribute("contenteditable") === "true") {
    return true;
  }

  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select";
}

export function resolveChordNavigation(previousPrefix: string | null, key: string): ChordNavigationResult {
  const normalizedKey = key.toLowerCase();

  if (normalizedKey === "g") {
    return { nextPrefix: "g", path: null };
  }

  if (previousPrefix === "g") {
    const prefixedPath = prefixedNavigation[`${previousPrefix}${normalizedKey}`] ?? null;
    return {
      nextPrefix: null,
      path: prefixedPath,
    };
  }

  return {
    nextPrefix: null,
    path: singleKeyNavigation[normalizedKey] ?? null,
  };
}
