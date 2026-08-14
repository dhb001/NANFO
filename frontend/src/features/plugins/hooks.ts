import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  disablePlugin,
  enablePlugin,
  installPlugin,
  listPlugins,
} from "@/features/plugins/api";
import { InstallPluginRequest } from "@/shared/types/plugins";

interface UsePluginsQueryOptions {
  status?: "installed" | "enabled" | "disabled" | "failed";
  enabled?: boolean;
  search?: string;
  limit?: number;
  pollMs?: number;
}

export function usePluginsQuery(token: string | null, options: UsePluginsQueryOptions = {}) {
  const pollInterval = options.pollMs ?? 4000;
  return useQuery({
    queryKey: ["plugins", token, options],
    queryFn: async () => {
      const response = await listPlugins(token as string, {
        status: options.status,
        enabled: options.enabled,
        search: options.search,
        limit: options.limit,
      });
      return response.data;
    },
    enabled: Boolean(token),
    refetchInterval: pollInterval,
  });
}

export function useInstallPlugin(token: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (request: InstallPluginRequest) => {
      if (!token) {
        throw new Error("Authentication token is required.");
      }
      const response = await installPlugin(token, request);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["plugins", token] });
    },
  });
}

export function useEnablePlugin(token: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (pluginId: string) => {
      if (!token) {
        throw new Error("Authentication token is required.");
      }
      const response = await enablePlugin(token, pluginId);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["plugins", token] });
    },
  });
}

export function useDisablePlugin(token: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (pluginId: string) => {
      if (!token) {
        throw new Error("Authentication token is required.");
      }
      const response = await disablePlugin(token, pluginId);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["plugins", token] });
    },
  });
}
