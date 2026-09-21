import { ApiClientError } from "@/shared/lib/errors";

export function isAmbiguousMutation(error: unknown) {
  return !(error instanceof ApiClientError && error.status && error.status >= 400 && error.status < 500 && error.status !== 408 && error.code !== "API_STALE_CONTEXT");
}

export function normalizeOrgSlug(name: string, explicitSlug: string): string {
  const basis = explicitSlug.trim() ? explicitSlug : name;
  return basis
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63).replace(/-+$/g, "");
}

export function shouldClearWorkspace(orgId: string | null, workspaceId: string | null): boolean {
  return !orgId && Boolean(workspaceId);
}
