import { API_BASE_URL } from "@/shared/lib/env";
import { ApiEnvelope } from "@/shared/types/api";
import { ApiClientError } from "@/shared/lib/errors";

type Method = "GET" | "POST" | "PATCH" | "DELETE";

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
): Promise<ApiEnvelope<T>> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: createHeaders({ token, headers, body }),
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  let payload: ApiEnvelope<T> | null = null;
  if (response.status !== 204) {
    payload = (await response.json()) as ApiEnvelope<T>;
  }

  if (!response.ok || payload?.success === false) {
    const code = payload?.errors?.code ?? `HTTP_${response.status}`;
    const message = payload?.errors?.message ?? `Request failed (${response.status})`;
    throw new ApiClientError(message, code, response.status);
  }

  if (payload === null) {
    throw new ApiClientError("API returned no content for envelope-based request", "API_EMPTY_RESPONSE", response.status);
  }

  if (payload.data === null) {
    throw new ApiClientError("API returned empty data payload", "API_EMPTY_DATA", response.status);
  }

  return payload;
}

export async function apiRequestNoContent(
  path: string,
  { method = "DELETE", body, token, headers, signal }: RequestOptions = {},
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: createHeaders({ token, headers, body }),
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    let message = `Request failed (${response.status})`;
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
