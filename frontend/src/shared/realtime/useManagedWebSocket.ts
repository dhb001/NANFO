import { useEffect, useRef } from "react";
import { nextBackoffMs } from "@/shared/lib/backoff";
import { WS_BASE_URL } from "@/shared/lib/env";
import { WebSocketErrorData } from "@/shared/types/ws";

interface ManagedSocketOptions<TFrame> {
  path: string;
  token: string | null;
  channel: string;
  filters?: Record<string, unknown>;
  enabled: boolean;
  onFrame: (frame: TFrame) => void;
  onUnauthorized?: () => void;
  onError?: (error: WebSocketErrorData) => void;
  onStatusChange?: (status: "connecting" | "open" | "closed") => void;
}

function buildSocketUrl(path: string, token: string): string {
  const normalizedBase = WS_BASE_URL.endsWith("/") ? WS_BASE_URL.slice(0, -1) : WS_BASE_URL;
  return `${normalizedBase}${path}?token=${encodeURIComponent(token)}`;
}

function toWebSocketError(frame: Record<string, unknown>): WebSocketErrorData | null {
  if (frame.event !== "error") {
    return null;
  }

  if (typeof frame.data !== "object" || frame.data === null) {
    return {
      code: "WS_ERROR",
      message: "WebSocket error frame missing payload.",
    };
  }

  const data = frame.data as { code?: unknown; message?: unknown };
  return {
    code: typeof data.code === "string" ? data.code : "WS_ERROR",
    message: typeof data.message === "string" ? data.message : "Unexpected websocket error.",
  };
}

export function useManagedWebSocket<TFrame>(options: ManagedSocketOptions<TFrame>) {
  const reconnectRef = useRef<number | null>(null);
  const closedByUserRef = useRef(false);
  const onFrameRef = useRef(options.onFrame);
  const onUnauthorizedRef = useRef(options.onUnauthorized);
  const onErrorRef = useRef(options.onError);
  const onStatusChangeRef = useRef(options.onStatusChange);
  const filtersRef = useRef<Record<string, unknown>>(options.filters ?? {});

  const filtersKey = JSON.stringify(options.filters ?? {});

  useEffect(() => {
    onFrameRef.current = options.onFrame;
    onUnauthorizedRef.current = options.onUnauthorized;
    onErrorRef.current = options.onError;
    onStatusChangeRef.current = options.onStatusChange;
    filtersRef.current = options.filters ?? {};
  }, [options.filters, options.onError, options.onFrame, options.onUnauthorized, options.onStatusChange]);

  useEffect(() => {
    if (!options.enabled || !options.token) {
      return;
    }

    closedByUserRef.current = false;
    let socket: WebSocket | null = null;
    let attempt = 0;

    const clearReconnect = () => {
      if (reconnectRef.current !== null) {
        window.clearTimeout(reconnectRef.current);
        reconnectRef.current = null;
      }
    };

    const connect = () => {
      if (closedByUserRef.current) {
        return;
      }

      onStatusChangeRef.current?.("connecting");
      socket = new WebSocket(buildSocketUrl(options.path, options.token));

      socket.onopen = () => {
        attempt = 0;
        onStatusChangeRef.current?.("open");
        const frame = {
          action: "subscribe",
          channel: options.channel,
          filters: filtersRef.current,
        };
        socket?.send(JSON.stringify(frame));
      };

      socket.onmessage = (event) => {
        try {
          const parsed = JSON.parse(String(event.data)) as Record<string, unknown>;
          const wsError = toWebSocketError(parsed);
          if (wsError) {
            onErrorRef.current?.(wsError);
          }

          if (wsError?.code === "WS_UNAUTHORIZED") {
            onUnauthorizedRef.current?.();
            closedByUserRef.current = true;
            socket?.close();
            return;
          }

          if (wsError) {
            return;
          }

          onFrameRef.current(parsed as TFrame);
        } catch {
          return;
        }
      };

      socket.onclose = () => {
        onStatusChangeRef.current?.("closed");
        if (closedByUserRef.current) {
          return;
        }
        attempt += 1;
        const waitMs = nextBackoffMs(attempt);
        reconnectRef.current = window.setTimeout(connect, waitMs);
      };
    };

    connect();

    return () => {
      closedByUserRef.current = true;
      clearReconnect();
      onStatusChangeRef.current?.("closed");
      socket?.close();
    };
  }, [
    options.channel,
    options.enabled,
    filtersKey,
    options.path,
    options.token,
  ]);
}
