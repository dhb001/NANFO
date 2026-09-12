import { useEffect, useRef } from "react";
import { nextBackoffMs } from "@/shared/lib/backoff";
import { WS_BASE_URL } from "@/shared/lib/env";
import { SocketUpgradeRecovery, WebSocketErrorData } from "@/shared/types/ws";

interface ManagedSocketOptions<TFrame> {
  path: string;
  token: string | null;
  channel: string;
  filters?: Record<string, unknown>;
  enabled: boolean;
  contextKey?: string;
  isCurrent?: () => boolean;
  onFrame: (frame: TFrame) => void;
  onUnauthorized?: () => void;
  onUpgradeFailure?: (token: string) => Promise<SocketUpgradeRecovery>;
  onError?: (error: WebSocketErrorData) => void;
  onSubscribed?: () => void;
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
  const onFrameRef = useRef(options.onFrame);
  const onUnauthorizedRef = useRef(options.onUnauthorized);
  const onUpgradeFailureRef = useRef(options.onUpgradeFailure);
  // A conclusive attempt survives rotation; an outage allows only cooldown probes.
  const upgradeRecoveryAttemptedRef = useRef(false);
  const unauthorizedAttemptedRef = useRef(false);
  const upgradeProbeRetryRef = useRef({ failures: 0, after: 0 });
  const onErrorRef = useRef(options.onError);
  const onSubscribedRef = useRef(options.onSubscribed);
  const onStatusChangeRef = useRef(options.onStatusChange);
  const filtersRef = useRef<Record<string, unknown>>(options.filters ?? {});

  const filtersKey = JSON.stringify(options.filters ?? {});

  useEffect(() => {
    onFrameRef.current = options.onFrame;
    onUnauthorizedRef.current = options.onUnauthorized;
    onUpgradeFailureRef.current = options.onUpgradeFailure;
    onErrorRef.current = options.onError;
    onSubscribedRef.current = options.onSubscribed;
    onStatusChangeRef.current = options.onStatusChange;
    filtersRef.current = options.filters ?? {};
  }, [options.filters, options.onError, options.onFrame, options.onUnauthorized, options.onUpgradeFailure, options.onStatusChange, options.onSubscribed]);

  useEffect(() => {
    if (!options.enabled || !options.token) {
      return;
    }

    const token = options.token;
    let closed = false;
    const isCurrent = options.isCurrent;
    let socket: WebSocket | null = null;
    let attempt = 0;
    let acknowledgmentTimeout: number | undefined;

    const clearReconnect = () => {
      if (reconnectRef.current !== null) {
        window.clearTimeout(reconnectRef.current);
        reconnectRef.current = null;
      }
    };

    const connect = () => {
      if (closed || isCurrent?.() === false) {
        return;
      }

      onStatusChangeRef.current?.("connecting");
      const connection = new WebSocket(buildSocketUrl(options.path, token));
      socket = connection;
      let opened = false;
      let subscribed = false;
      const isActive = () => !closed && socket === connection && isCurrent?.() !== false;

      socket.onopen = () => {
        if (!isActive()) return;
        opened = true;
        const frame = {
          action: "subscribe",
          channel: options.channel,
          filters: filtersRef.current,
        };
        socket?.send(JSON.stringify(frame));
        acknowledgmentTimeout = window.setTimeout(() => {
          if (isActive() && !subscribed) connection.close();
        }, 10_000);
      };

      socket.onmessage = (event) => {
        if (!isActive()) return;
        try {
          const parsed = JSON.parse(String(event.data)) as Record<string, unknown>;
          if (!parsed || typeof parsed !== "object" || typeof parsed.event !== "string") return;
          const wsError = toWebSocketError(parsed);
          if (wsError) {
            onErrorRef.current?.(wsError);
          }

          if (wsError?.code === "WS_UNAUTHORIZED") {
            if (!unauthorizedAttemptedRef.current) {
              unauthorizedAttemptedRef.current = true;
              onUnauthorizedRef.current?.();
            }
            closed = true;
            onStatusChangeRef.current?.("closed");
            socket?.close();
            return;
          }

          if (wsError) {
            if (["WS_INVALID_FILTER", "WS_FORBIDDEN", "WS_UNKNOWN_CHANNEL"].includes(wsError.code)) {
              closed = true;
              onStatusChangeRef.current?.("closed");
              socket?.close();
            }
            return;
          }

          if (parsed.event === "subscribed") {
            const filters = parsed.filters;
            if (subscribed || !opened || parsed.channel !== options.channel || !filters || typeof filters !== "object" ||
                Object.keys(filters).length !== Object.keys(filtersRef.current).length ||
                !Object.entries(filtersRef.current).every(([key, value]) => (filters as Record<string, unknown>)[key] === value)) return;
            subscribed = true;
            window.clearTimeout(acknowledgmentTimeout);
            upgradeRecoveryAttemptedRef.current = false;
            unauthorizedAttemptedRef.current = false;
            upgradeProbeRetryRef.current = { failures: 0, after: 0 };
            attempt = 0;
            onStatusChangeRef.current?.("open");
            onSubscribedRef.current?.();
            return;
          }
          if (subscribed) onFrameRef.current(parsed as TFrame);
        } catch {
          return;
        }
      };

      socket.onclose = async (event) => {
        if (!isActive()) return;
        window.clearTimeout(acknowledgmentTimeout);
        onStatusChangeRef.current?.("closed");
        if (event.code === 1008 || event.reason.toUpperCase().includes("WS_UNAUTHORIZED")) {
          if (!unauthorizedAttemptedRef.current) {
            unauthorizedAttemptedRef.current = true;
            onUnauthorizedRef.current?.();
          }
          closed = true;
          return;
        }
        socket = null;
        if (!opened && event.code === 1006 && !upgradeRecoveryAttemptedRef.current &&
            Date.now() >= upgradeProbeRetryRef.current.after && onUpgradeFailureRef.current) {
          upgradeRecoveryAttemptedRef.current = true;
          let result: SocketUpgradeRecovery = "inconclusive";
          try {
            result = await onUpgradeFailureRef.current(token);
          } catch {
            // A failed auth probe is not proof of expiry. Keep transport backoff.
          }
          if (closed || isCurrent?.() === false) return;
          if (result === "inconclusive") {
            const failures = Math.min(upgradeProbeRetryRef.current.failures + 1, 5);
            upgradeProbeRetryRef.current = { failures, after: Date.now() + Math.min(5_000 * 2 ** (failures - 1), 60_000) };
            upgradeRecoveryAttemptedRef.current = false;
          }
        }
        attempt += 1;
        const waitMs = nextBackoffMs(attempt);
        reconnectRef.current = window.setTimeout(connect, waitMs);
      };
    };

    connect();

    return () => {
      closed = true;
      clearReconnect();
      window.clearTimeout(acknowledgmentTimeout);
      onStatusChangeRef.current?.("closed");
      socket?.close();
    };
  }, [
    options.channel,
    options.enabled,
    filtersKey,
    options.path,
    options.token,
    options.contextKey,
    options.isCurrent,
  ]);
}
