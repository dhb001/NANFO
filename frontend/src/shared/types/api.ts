export interface ApiMeta {
  request_id: string;
  timestamp: string;
  execution_time_ms?: number;
  next_cursor?: string | null;
  execution_mode?: "demo" | "emulation" | "production";
}

export interface ApiError {
  code: string;
  message: string;
}

export interface ApiSuccess<T> {
  success: true;
  data: T;
  meta: ApiMeta;
  errors: null;
}

export type ApiEnvelope<T> = ApiSuccess<T> | {
  success: false;
  data: null;
  meta: ApiMeta;
  errors: ApiError;
};
