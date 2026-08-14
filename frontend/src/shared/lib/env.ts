export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
export const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL ?? "ws://127.0.0.1:8000";
export const ENABLE_MOCK_WS = String(import.meta.env.VITE_ENABLE_MOCK_WS ?? "false") === "true";
