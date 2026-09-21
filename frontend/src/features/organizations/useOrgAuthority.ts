import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "@/shared/state/auth-store";
import { ApiClientError } from "@/shared/lib/errors";
import type { OrgMemberList } from "@/shared/types/organization";
import { listOrgMembers } from "./api";

const PAGE_SIZE = 20;

export function useOrgAuthority(token: string | null, orgId: string | null, members?: OrgMemberList) {
  const userId = useAuthStore((state) => state.userId);
  const generation = useAuthStore((state) => state.generation);
  const profile = useAuthStore((state) => state.profile);
  // A location hint, never an authorization grant. Rotation revalidates this page.
  const foundPage = useRef<{ scope: string; page: number } | null>(null);
  const scope = JSON.stringify([generation, orgId, userId]);
  const current = members?.items.find((member) => member.user_id === userId && member.org_id === orgId);
  const hintedPage = current && (members?.page_size ?? PAGE_SIZE) === PAGE_SIZE ? members?.page ?? 1 : undefined;
  const query = useQuery({
    queryKey: ["org-members", "authority", generation, orgId, userId, token],
    enabled: Boolean(token && orgId && userId),
    initialData: current ? { role: current.org_role as string | null, page: hintedPage ?? 1 } : undefined,
    staleTime: 30_000,
    retry: false,
    queryFn: async ({ signal }) => {
      const firstPage = hintedPage ?? (foundPage.current?.scope === scope ? foundPage.current.page : 1);
      const read = async (page: number) => {
        signal.throwIfAborted();
        const result = (await listOrgMembers(token!, orgId!, page, PAGE_SIZE, signal)).data;
        signal.throwIfAborted();
        return result;
      };
      const first = await read(firstPage);
      let actor = first.items.find((member) => member.user_id === userId && member.org_id === orgId);
      if (actor) return { role: actor.org_role, page: firstPage };
      // Snapshot the count: concurrent inserts cannot extend this lookup forever.
      // Only one page is held at a time; retain only the actor's role/page result.
      const pages = Math.max(1, Math.ceil(first.total / PAGE_SIZE));
      for (let page = 1; page <= pages; page++) {
        if (page === firstPage) continue;
        const batch = await read(page);
        actor = batch.items.find((member) => member.user_id === userId && member.org_id === orgId);
        if (actor) return { role: actor.org_role, page };
      }
      return { role: null, page: 1 };
    },
  });
  useEffect(() => {
    if (query.data?.role) foundPage.current = { scope, page: query.data.page };
  }, [query.data, scope]);
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
