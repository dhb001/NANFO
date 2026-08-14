export function normalizeOrgSlug(name: string, explicitSlug: string): string {
  const basis = explicitSlug.trim() ? explicitSlug : name;
  return basis
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
}

export function shouldClearWorkspace(orgId: string | null, workspaceId: string | null): boolean {
  return !orgId && Boolean(workspaceId);
}
