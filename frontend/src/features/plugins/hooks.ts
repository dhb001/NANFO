import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { disablePlugin, enablePlugin, installPlugin, listPlugins, uninstallPlugin } from "./api";
import { useAuthStore } from "@/shared/state/auth-store";
import { canAccessRoute } from "@/features/auth/permissions";

interface UsePluginsQueryOptions {
  status?: "installed" | "enabled" | "disabled" | "failed";
  enabled?: boolean;
  search?: string;
  limit?: number;
  pollMs?: number;
}

export function usePluginsQuery(token: string | null, options: UsePluginsQueryOptions = {}) {
  const allowed = useAuthStore((state) => canAccessRoute(state.profile, "/ops/plugins"));
  return useQuery({
    queryKey: ["plugins", token, options],
    queryFn: async () => (await listPlugins(token as string, options)).data,
    enabled: Boolean(token && allowed),
    refetchInterval: options.pollMs ?? 4000,
  });
}

function useRegistryAction<T, R>(token: string | null, action: (token: string, input: T) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: T) => {
      if (!token) throw new Error("Authentication token is required.");
      return action(token, input);
    },
    onSuccess: () => { client.invalidateQueries({ queryKey: ["plugins", token] }); },
  });
}

export const useInstallPlugin = (token: string | null) => useRegistryAction(token, async (auth, input: Parameters<typeof installPlugin>[1]) => (await installPlugin(auth, input)).data);
export const useEnablePlugin = (token: string | null) => useRegistryAction(token, async (auth, id: string) => (await enablePlugin(auth, id)).data);
export const useDisablePlugin = (token: string | null) => useRegistryAction(token, async (auth, id: string) => (await disablePlugin(auth, id)).data);
export const useUninstallPlugin = (token: string | null) => useRegistryAction(token, uninstallPlugin);
