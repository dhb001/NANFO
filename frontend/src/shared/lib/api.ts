import { apiUrl } from "@/shared/lib/env";
import type { ApiEnvelope, ApiMeta, ApiSuccess } from "@/shared/types/api";
import { ApiClientError, parseErrorDetails } from "@/shared/lib/errors";
import { retryAfterMs } from "@/shared/lib/backoff";
import { useExecutionModeStore } from "@/shared/state/execution-mode-store";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { authorityKey } from "@/features/auth/sessionScope";

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

/** Default bound for one API round trip; long uploads pass `timeoutMs`. */
export const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;

export interface RequestOptions {
  method?: Method;
  body?: unknown;
  token?: string | null;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  timeoutMs?: number;
}

function createHeaders(options: RequestOptions): Record<string, string> {
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

/** Session generation and tenant scope by value: a no-op store update is not a context change. */
function contextOf() {
  const scope = useWorkspaceStore.getState();
  return `${useAuthStore.getState().generation}|${scope.organizationId}|${scope.workspaceId}|${scope.networkId}`;
}

function anySignal(signals: AbortSignal[]): AbortSignal {
  if (typeof AbortSignal.any === "function") return AbortSignal.any(signals);
  const controller = new AbortController();
  for (const signal of signals) {
    if (signal.aborted) {
      controller.abort(signal.reason);
      break;
    }
    signal.addEventListener("abort", () => controller.abort(signal.reason), { once: true });
  }
  return controller.signal;
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const timeout = AbortSignal.timeout(options.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS);
  try {
    return await fetch(apiUrl(path), {
      method: options.method,
      headers: createHeaders(options),
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal ? anySignal([options.signal, timeout]) : timeout,
    });
  } catch (error) {
    if (timeout.aborted && !options.signal?.aborted) {
      throw new ApiClientError(
        options.method && options.method !== "GET"
          ? "The request timed out. Its outcome is unknown; check the current state before retrying."
          : "The request timed out. Retry shortly.",
        "API_TIMEOUT", 0,
      );
    }
    throw error;
  }
}

function errorFrom(response: Response, payload: ApiEnvelope<unknown> | null, fallback: string): ApiClientError {
  const errors = payload?.success === false ? payload.errors : null;
  return new ApiClientError(
    errors?.message ?? fallback,
    errors?.code ?? `HTTP_${response.status}`,
    response.status,
    {
      requestId: payload?.meta?.request_id ?? response.headers.get("X-Request-ID"),
      details: parseErrorDetails((errors as { details?: unknown } | null)?.details),
      retryAfterMs: retryAfterMs(response.headers.get("Retry-After")),
    },
  );
}

export async function apiRequest<T, M extends ApiMeta = ApiMeta>(
  path: string,
  { method = "GET", body, token, headers, signal, timeoutMs }: RequestOptions = {},
  retryAuth = true,
): Promise<ApiSuccess<NonNullable<T>, M>> {
  const session = useAuthStore.getState();
  const context = contextOf();
  const response = await send(path, { method, body, token, headers, signal, timeoutMs });

  let payload: ApiEnvelope<T, M> | null = null;
  if (response.status !== 204) {
    try { payload = (await response.json()) as ApiEnvelope<T, M>; } catch {
      if (response.ok) throw new ApiClientError("API returned an unreadable response. Mutation outcome may be unknown; inspect history before retrying.", "API_INVALID_RESPONSE", response.status);
    }
  }

  if (token && token === session.accessToken &&
      (session.generation !== useAuthStore.getState().generation ||
        (!path.startsWith("/api/v1/auth/") && context !== contextOf()))) {
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
        context === contextOf() && !useAuthStore.getState().endingSession) {
      if (method !== "GET" && authorityKey(session.profile) !== authorityKey()) {
        throw new ApiClientError("Permissions changed. Review and explicitly approve the action again.", "API_AUTHORITY_CHANGED", 403);
      }
      return apiRequest<T, M>(path, { method, body, headers, signal, timeoutMs, token: useAuthStore.getState().accessToken }, false);
    }
  }

  if (!response.ok || payload?.success === false) {
    if (response.status === 401 && !retryAuth && token === useAuthStore.getState().accessToken) {
      useAuthStore.getState().clearSession();
    }
    throw errorFrom(response, payload, `Request failed (${response.status})`);
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
  { method = "DELETE", body, token, headers, signal, timeoutMs }: RequestOptions = {},
  retryAuth = true,
): Promise<void> {
  const session = useAuthStore.getState();
  const context = contextOf();
  const response = await send(path, { method, body, token, headers, signal, timeoutMs });

  if (token === session.accessToken && context !== contextOf()) {
    throw new ApiClientError("Session context changed", "API_STALE_CONTEXT", response.status);
  }
  if (response.status === 401 && retryAuth && token && token === session.accessToken) {
    const { refreshSession } = await import("@/features/auth/session");
    const refreshed = useAuthStore.getState().accessToken !== token || await refreshSession();
    if (refreshed && context === contextOf() && !useAuthStore.getState().endingSession) {
      if (authorityKey(session.profile) !== authorityKey()) {
        throw new ApiClientError("Permissions changed. Review the action again.", "API_AUTHORITY_CHANGED", 403);
      }
      return apiRequestNoContent(path, { method, body, headers, signal, timeoutMs, token: useAuthStore.getState().accessToken }, false);
    }
  }

  if (response.status !== 204) {
    if (response.status === 401 && !retryAuth && token === useAuthStore.getState().accessToken) {
      useAuthStore.getState().clearSession();
    }
    let payload: ApiEnvelope<unknown> | null = null;
    try {
      payload = (await response.json()) as ApiEnvelope<unknown>;
    } catch {
      // Non-JSON proxy errors keep the HTTP status.
    }
    throw errorFrom(response, payload, `Expected no-content response (${response.status})`);
  }
}
