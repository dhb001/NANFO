import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { disablePlugin, enablePlugin, installPlugin, listPlugins, uninstallPlugin } from "./api";
import { useAuthStore } from "@/shared/state/auth-store";
import { canAccessRoute } from "@/features/auth/permissions";
import { useSessionScope } from "@/features/auth/sessionScope";
import { scopedKey } from "@/shared/lib/queryKeys";
import type { PluginStatus } from "@/shared/types/plugins";

interface UsePluginsQueryOptions {
  status?: PluginStatus | undefined;
  enabled?: boolean | undefined;
  search?: string | undefined;
  limit?: number | undefined;
  pollMs?: number | undefined;
}

export function usePluginsQuery(token: string | null, options: UsePluginsQueryOptions = {}) {
  const allowed = useAuthStore((state) => canAccessRoute(state.profile, "/ops/plugins"));
  const scope = useSessionScope();
  const { pollMs, ...filters } = options;
  return useQuery({
    queryKey: scopedKey(scope, "plugins", filters),
    queryFn: async ({ signal }) => (await scope.read((credential) => listPlugins(credential, filters, signal), signal)).data,
    enabled: Boolean(token && allowed),
    refetchInterval: pollMs ?? 4000,
  });
}

function useRegistryAction<T, R>(token: string | null, action: (token: string, input: T) => Promise<R>) {
  const client = useQueryClient();
  const scope = useSessionScope();
  return useMutation({
    mutationFn: async (input: T) => {
      const credential = useAuthStore.getState().accessToken ?? token;
      if (!credential) throw new Error("Authentication token is required.");
      return action(credential, input);
    },
    onSuccess: () => { void client.invalidateQueries({ queryKey: scopedKey(scope, "plugins") }); },
  });
}

export const useInstallPlugin = (token: string | null) => useRegistryAction(token, async (auth, input: Parameters<typeof installPlugin>[1]) => (await installPlugin(auth, input)).data);
export const useEnablePlugin = (token: string | null) => useRegistryAction(token, async (auth, id: string) => (await enablePlugin(auth, id)).data);
export const useDisablePlugin = (token: string | null) => useRegistryAction(token, async (auth, id: string) => (await disablePlugin(auth, id)).data);
export const useUninstallPlugin = (token: string | null) => useRegistryAction(token, uninstallPlugin);
