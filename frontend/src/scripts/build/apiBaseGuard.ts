// Production build guard for API/WebSocket base URLs (ADR-028 C16).
//
// A packaged gateway UI must talk to its own origin. A production bundle that
// bakes in a loopback origin (for example from a developer `.env`) cannot log in
// from any other machine, so such builds fail. Owned local runners that really
// serve a cross-origin loopback API opt in with NANFO_ALLOW_LOOPBACK_API_BASE_URL=1
// (a build-process variable; it is never exposed to client code).

export const ALLOW_LOOPBACK_ENV = "NANFO_ALLOW_LOOPBACK_API_BASE_URL";

const CHECKED = {
  VITE_API_BASE_URL: ["http:", "https:"],
  VITE_WS_BASE_URL: ["ws:", "wss:", "http:", "https:"],
} as const;

export interface BaseUrlGuardInput {
  command: "build" | "serve";
  mode: string;
  env: Record<string, string | undefined>;
  allowLoopback?: boolean | undefined;
}

export function isLoopbackHostname(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  return host === "localhost" || host.endsWith(".localhost") ||
    /^127(?:\.\d{1,3}){3}$/.test(host) || host === "0.0.0.0" ||
    host === "::1" || host === "::" || /^::ffff:(?:7f[0-9a-f]{2}:|127\.)/.test(host) ||
    /^(?:0+:){7}0*1$/.test(host);
}

/** Problems with configured base URLs; an empty list means the build may proceed. */
export function baseUrlProblems({ command, mode, env, allowLoopback = false }: BaseUrlGuardInput): string[] {
  if (command !== "build" || mode === "development") return [];
  const problems: string[] = [];
  for (const [name, schemes] of Object.entries(CHECKED)) {
    const value = env[name]?.trim();
    if (!value || value.startsWith("/")) continue; // unset / same-origin path prefix
    let url: URL;
    try {
      url = new URL(value);
    } catch {
      problems.push(`${name} is not an absolute URL or same-origin path.`);
      continue;
    }
    if (!(schemes as readonly string[]).includes(url.protocol)) {
      problems.push(`${name} uses unsupported scheme ${url.protocol}`);
    } else if (url.username || url.password || url.search || url.hash) {
      problems.push(`${name} must not contain credentials, a query string or a fragment.`);
    } else if (!allowLoopback && isLoopbackHostname(url.hostname)) {
      problems.push(`${name} points at loopback (${url.hostname}); production bundles must use the same origin.`);
    }
  }
  return problems;
}

export function assertProductionBaseUrls(input: BaseUrlGuardInput): void {
  const problems = baseUrlProblems(input);
  if (problems.length) {
    throw new Error([
      `Refusing a ${input.mode} build (ADR-028 C16):`,
      ...problems.map((problem) => `  - ${problem}`),
      "Leave VITE_API_BASE_URL/VITE_WS_BASE_URL unset for same-origin gateway builds, keep local",
      `values in .env.development.local, or set ${ALLOW_LOOPBACK_ENV}=1 for an owned local cross-origin runner.`,
    ].join("\n"));
  }
}
