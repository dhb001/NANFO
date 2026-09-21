import { API_BASE_URL } from "@/shared/lib/env";
import { ApiEnvelope, ApiSuccess } from "@/shared/types/api";
import { ApiClientError } from "@/shared/lib/errors";
import { useExecutionModeStore } from "@/shared/state/execution-mode-store";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { authorityKey } from "@/features/auth/sessionScope";

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RequestOptions {
  method?: Method;
  body?: unknown;
  token?: string | null;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

function createHeaders(options: RequestOptions): HeadersInit {
  const headers: Record<string, string> = {
    ...options.headers,
  };

  if (options.body !== undefined && headers["Content-Type"] === undefined) {
    headers["Content-Type"] = "application/json";
  }

  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }

  return headers;
}

export async function apiRequest<T>(
  path: string,
  { method = "GET", body, token, headers, signal }: RequestOptions = {},
  retryAuth = true,
): Promise<ApiSuccess<NonNullable<T>>> {
  const session = useAuthStore.getState();
  const context = useWorkspaceStore.getState();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: createHeaders({ token, headers, body }),
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  let payload: ApiEnvelope<T> | null = null;
  if (response.status !== 204) {
    try { payload = (await response.json()) as ApiEnvelope<T>; } catch {
      if (response.ok) throw new ApiClientError("API returned an unreadable response. Mutation outcome may be unknown; inspect history before retrying.", "API_INVALID_RESPONSE", response.status);
    }
  }

  if (token && token === session.accessToken &&
      (session.generation !== useAuthStore.getState().generation ||
        (!path.startsWith("/api/v1/auth/") && context !== useWorkspaceStore.getState()))) {
    throw new ApiClientError("Session context changed", "API_STALE_CONTEXT", response.status);
  }
  if (session.generation === useAuthStore.getState().generation) {
    useExecutionModeStore.getState().observe(payload?.meta?.execution_mode);
  }

  if (response.status === 401 && retryAuth && token && token === session.accessToken && !path.startsWith("/api/v1/auth/")) {
    const { refreshSession } = await import("@/features/auth/session");
    const current = useAuthStore.getState();
    const refreshed = current.accessToken !== token || await refreshSession();
    if (refreshed && session.generation === useAuthStore.getState().generation &&
        context === useWorkspaceStore.getState() && !useAuthStore.getState().endingSession) {
      if (method !== "GET" && authorityKey(session.profile) !== authorityKey()) {
        throw new ApiClientError("Permissions changed. Review and explicitly approve the action again.", "API_AUTHORITY_CHANGED", 403);
      }
      return apiRequest<T>(path, { method, body, headers, signal, token: useAuthStore.getState().accessToken }, false);
    }
  }

  if (!response.ok || payload?.success === false) {
    if (response.status === 401 && !retryAuth && token === useAuthStore.getState().accessToken) {
      useAuthStore.getState().clearSession();
    }
    const code = payload?.errors?.code ?? `HTTP_${response.status}`;
    const message = payload?.errors?.message ?? `Request failed (${response.status})`;
    throw new ApiClientError(message, code, response.status);
  }

  if (payload === null) {
    throw new ApiClientError("API returned no content for envelope-based request", "API_EMPTY_RESPONSE", response.status);
  }

  if (payload.success !== true || payload.data == null) {
    throw new ApiClientError("API returned empty data payload", "API_EMPTY_DATA", response.status);
  }

  return { ...payload, data: payload.data };
}

export async function apiRequestNoContent(
  path: string,
  { method = "DELETE", body, token, headers, signal }: RequestOptions = {},
  retryAuth = true,
): Promise<void> {
  const session = useAuthStore.getState();
  const context = useWorkspaceStore.getState();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: createHeaders({ token, headers, body }),
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  if (token === session.accessToken && (session.generation !== useAuthStore.getState().generation ||
      context !== useWorkspaceStore.getState())) {
    throw new ApiClientError("Session context changed", "API_STALE_CONTEXT", response.status);
  }
  if (response.status === 401 && retryAuth && token && token === session.accessToken) {
    const { refreshSession } = await import("@/features/auth/session");
    const refreshed = useAuthStore.getState().accessToken !== token || await refreshSession();
    if (refreshed && session.generation === useAuthStore.getState().generation &&
        context === useWorkspaceStore.getState() && !useAuthStore.getState().endingSession) {
      if (authorityKey(session.profile) !== authorityKey()) {
        throw new ApiClientError("Permissions changed. Review the action again.", "API_AUTHORITY_CHANGED", 403);
      }
      return apiRequestNoContent(path, { method, body, headers, signal, token: useAuthStore.getState().accessToken }, false);
    }
  }

  if (response.status !== 204) {
    if (response.status === 401 && !retryAuth && token === useAuthStore.getState().accessToken) {
      useAuthStore.getState().clearSession();
    }
    let code = `HTTP_${response.status}`;
    let message = `Expected no-content response (${response.status})`;
    try {
      const payload = (await response.json()) as ApiEnvelope<unknown>;
      code = payload.errors?.code ?? code;
      message = payload.errors?.message ?? message;
    } catch {
      // no-op
    }
    throw new ApiClientError(message, code, response.status);
  }
}
