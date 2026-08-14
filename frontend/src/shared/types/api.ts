export interface ApiMeta {
  request_id: string;
  timestamp: string;
  execution_time_ms?: number;
  next_cursor?: string | null;
}

export interface ApiError {
  code: string;
  message: string;
}

export interface ApiEnvelope<T> {
  success: boolean;
  data: T | null;
  meta: ApiMeta;
  errors: ApiError | null;
}
