import type { UserProfile } from "@/shared/types/auth";

// Presentation gates mirror existing API dependencies, never replace backend authorization.
export function hasPermission(profile: UserProfile | null, permission: string): boolean {
  return profile?.permissions.includes(permission) ?? false;
}

export function canReadTelemetryHealth(profile: UserProfile | null): boolean {
  return Boolean(profile?.roles.includes("Admin") && hasPermission(profile, "read:telemetry"));
}

export function canAccessRoute(profile: UserProfile | null, path: string): boolean {
  if (!profile) return false;
  if (path === "/ops/audit") return profile.roles.includes("Admin");
  if (path === "/ops/plugins") return profile.roles.includes("Admin") && hasPermission(profile, "read:topology");
  if (["/ops/telemetry", "/ops/reliability", "/ops/reports"].includes(path)) {
    return hasPermission(profile, "read:telemetry");
  }
  if (["/ops/topology-analysis", "/ops/digital-twin", "/ops/intent", "/ops/simulation"].includes(path)) {
    return hasPermission(profile, "read:topology");
  }
  return true;
}
