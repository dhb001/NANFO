import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "@/shared/state/auth-store";
import { useSessionScope } from "@/features/auth/sessionScope";
import { ApiClientError } from "@/shared/lib/errors";
import { scopedKey } from "@/shared/lib/queryKeys";
import { getOrganization } from "./api";

/**
 * The caller's organization role from `GET /organizations/{id}` `caller_role`
 * (ADR-028 C6) — one bounded read instead of crawling member pages. Absent and
 * non-member organizations answer the same 404, shown as "denied". A missing
 * role (older backend) fails closed. Presentation only: the backend authorizes.
 */
export function useOrgAuthority(token: string | null, orgId: string | null) {
  const scope = useSessionScope();
  const userId = useAuthStore((state) => state.userId);
  const profile = useAuthStore((state) => state.profile);
  const query = useQuery({
    queryKey: scopedKey(scope, "org-authority", orgId),
    enabled: Boolean(token && orgId && userId),
    staleTime: 30_000,
    retry: false,
    queryFn: async ({ signal }) => {
      const organization = (await scope.read((credential) => getOrganization(credential, orgId as string, signal), signal)).data;
      return { role: organization.org_id === orgId ? organization.caller_role ?? null : null };
    },
  });
  const denied = query.error instanceof ApiClientError && [401, 403, 404].includes(query.error.status ?? 0);
  const status = !token || !orgId || !userId ? "unknown"
    : query.isError ? denied ? "denied" : "error"
      : query.isFetching || !query.isSuccess ? "loading"
        : query.data.role ? "resolved" : "denied";
  const role = status === "resolved" ? query.data?.role ?? null : null;
  const globalWrite = Boolean(profile?.permissions.includes("write:config"));
  return { role, status, error: query.error, retry: query.refetch,
    canAdmin: globalWrite && role === "Admin",
    canWrite: globalWrite && (role === "Admin" || role === "Operator") };
}
