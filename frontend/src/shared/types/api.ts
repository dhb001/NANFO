export interface ApiMeta {
  request_id: string;
  timestamp: string;
  execution_time_ms?: number;
  execution_mode?: "demo" | "emulation" | "production";
  /** Idempotent writes (intents, plugins, reports): the stored result was returned (ADR-028 C3). */
  idempotent_replay?: boolean;
  /** Autonomy mode switch recorded as the first of two approvals (ADR-028 C25). */
  pending_approval?: boolean;
}

/** Only cursor-paginated endpoints (topology graph) provide `next_cursor`. */
export interface CursorMeta extends ApiMeta {
  next_cursor?: string | null;
}

export interface ApiError {
  code: string;
  message: string;
  /** 422 only: `[{loc, type}]` without input values (ADR-028 C2). */
  details?: Array<{ loc: Array<string | number>; type: string }>;
}

export interface ApiSuccess<T, M extends ApiMeta = ApiMeta> {
  success: true;
  data: T;
  meta: M;
  errors: null;
}

export type ApiEnvelope<T, M extends ApiMeta = ApiMeta> = ApiSuccess<T, M> | {
  success: false;
  data: null;
  meta: M;
  errors: ApiError;
};
