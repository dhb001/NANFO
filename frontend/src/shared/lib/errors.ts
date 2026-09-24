/** 422 location/type pairs from `errors.details` (ADR-028 C2); never contains input values. */
export interface ApiErrorDetail {
  loc: Array<string | number>;
  type: string;
}

export interface ApiClientErrorExtra {
  /** `meta.request_id` / `X-Request-ID`, the correlation id operators quote to support. */
  requestId?: string | null;
  details?: ApiErrorDetail[] | null;
  /** Server-requested wait (`Retry-After`), in milliseconds. */
  retryAfterMs?: number | null;
}

export class ApiClientError extends Error {
  public readonly code: string;
  public readonly status?: number;
  public readonly requestId: string | null;
  public readonly details: ApiErrorDetail[];
  public readonly retryAfterMs: number | null;

  constructor(message: string, code: string, status?: number, extra: ApiClientErrorExtra = {}) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.status = status;
    this.requestId = extra.requestId ?? null;
    this.details = extra.details ?? [];
    this.retryAfterMs = extra.retryAfterMs ?? null;
  }
}

export function toErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Unexpected error";
}

/** Keep only well-formed `{loc, type}` pairs (bounded); anything else is ignored. */
export function parseErrorDetails(value: unknown): ApiErrorDetail[] {
  if (!Array.isArray(value)) return [];
  return value.slice(0, 20).flatMap((item): ApiErrorDetail[] => {
    if (!item || typeof item !== "object") return [];
    const { loc, type } = item as { loc?: unknown; type?: unknown };
    if (!Array.isArray(loc) || typeof type !== "string") return [];
    return [{ loc: loc.filter((part): part is string | number => typeof part === "string" || typeof part === "number"), type }];
  });
}

/** Operator-facing text: backend message plus actionable context for size, outage and validation errors. */
export function describeApiError(error: unknown): string {
  if (!(error instanceof ApiClientError)) return toErrorMessage(error);
  const parts = [error.message];
  if (error.status === 413) parts.push("Reduce the size of the submitted content and try again.");
  if (error.status === 503 || error.status === 429) {
    parts.push(error.retryAfterMs !== null ? `Retry in about ${Math.max(1, Math.ceil(error.retryAfterMs / 1000))} s.` : "Retry shortly.");
  }
  if (error.status === 422 && error.details.length) {
    parts.push(`Check: ${error.details.map((detail) => detail.loc.filter((part) => part !== "body").join(".") || detail.type).join(", ")}.`);
  }
  if (error.requestId) parts.push(`Reference: ${error.requestId}.`);
  return parts.join(" ");
}
