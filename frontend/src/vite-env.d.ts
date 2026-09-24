/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Build-time API origin override. Unset (production default) means same-origin. */
  readonly VITE_API_BASE_URL?: string;
  /** Build-time WebSocket origin override. Unset means derived from the API base / page origin. */
  readonly VITE_WS_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
