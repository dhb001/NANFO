import { useEffect, useRef } from "react";
import { nextBackoffMs } from "@/shared/lib/backoff";
import { webSocketBaseUrl } from "@/shared/lib/env";
import type { RealtimeHaltReason, SocketUpgradeRecovery, WebSocketErrorData } from "@/shared/types/ws";

// ADR-028 C1 transport: the credential travels as a subprotocol, never in the URL.
export const WS_PROTOCOL = "nanfo.v1";
export const WS_BEARER_PREFIX = "nanfo.bearer.";

const CLOSE_ABNORMAL = 1006;
const CLOSE_POLICY = 1008;
const CLOSE_TOO_BIG = 1009;
const SUBSCRIBE_ACK_TIMEOUT_MS = 10_000;
export const RECONNECT_BACKOFF = { baseMs: 500, capMs: 30_000 } as const;

// Retrying cannot fix these denials.
const TERMINAL_CODES = new Set(["WS_INVALID_FILTER", "WS_UNKNOWN_CHANNEL", "WS_FORBIDDEN"]);
// Dependency outage / missed subscribe / slow consumer: the server closes (1013) and we retry.
const TRANSIENT_CODES = new Set(["WS_UNAVAILABLE", "WS_SUBSCRIBE_TIMEOUT", "WS_BACKPRESSURE"]);

type SocketStatus = "connecting" | "open" | "closed";

interface ManagedSocketOptions<TFrame> {
  path: string;
  /** Current access token. Rotation never reconnects a healthy socket; it only revives an expired one. */
  token: string | null;
  channel: string;
  filters?: Record<string, unknown>;
  enabled: boolean;
  contextKey?: string;
  /** Changing this value restarts a halted socket (for example the visible "Retry realtime" control). */
  retryKey?: number | string;
  isCurrent?: () => boolean;
  onFrame: (frame: TFrame) => void;
  onUnauthorized?: () => void;
  onUpgradeFailure?: (token: string) => Promise<SocketUpgradeRecovery>;
  onError?: (error: WebSocketErrorData) => void;
  onSubscribed?: () => void;
  onStatusChange?: (status: SocketStatus) => void;
  onHalt?: (reason: RealtimeHaltReason, error: WebSocketErrorData) => void;
}

export function socketUrl(path: string): string {
  return `${webSocketBaseUrl()}${path}`;
}

export function socketProtocols(token: string): string[] {
  return [WS_PROTOCOL, `${WS_BEARER_PREFIX}${token}`];
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

function matchesFilters(received: unknown, expected: Record<string, unknown>): boolean {
  if (!received || typeof received !== "object") return false;
  const filters = received as Record<string, unknown>;
  return Object.keys(filters).length === Object.keys(expected).length &&
    Object.entries(expected).every(([key, value]) => filters[key] === value);
}

export function useManagedWebSocket<TFrame>(options: ManagedSocketOptions<TFrame>) {
  const tokenRef = useRef(options.token);
  const resumeRef = useRef<(() => void) | null>(null);
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
  const onHaltRef = useRef(options.onHalt);
  const filtersRef = useRef<Record<string, unknown>>(options.filters ?? {});

  const filtersKey = JSON.stringify(options.filters ?? {});
  const hasToken = Boolean(options.token);

  useEffect(() => {
    onFrameRef.current = options.onFrame;
    onUnauthorizedRef.current = options.onUnauthorized;
    onUpgradeFailureRef.current = options.onUpgradeFailure;
    onErrorRef.current = options.onError;
    onSubscribedRef.current = options.onSubscribed;
    onStatusChangeRef.current = options.onStatusChange;
    onHaltRef.current = options.onHalt;
    filtersRef.current = options.filters ?? {};
  }, [options.filters, options.onError, options.onFrame, options.onUnauthorized, options.onUpgradeFailure, options.onStatusChange, options.onSubscribed, options.onHalt]);

  // Declared before the connection effect so a fresh credential is visible to it.
  useEffect(() => {
    tokenRef.current = options.token;
    resumeRef.current?.();
  }, [options.token]);

  useEffect(() => {
    if (!options.enabled || !hasToken) {
      return;
    }

    let stopped = false;
    const isCurrent = options.isCurrent;
    let socket: WebSocket | null = null;
    let attempt = 0;
    let acknowledgmentTimeout: number | undefined;
    let reconnectTimer: number | undefined;
    // Credential rejected by the server; the next distinct token resumes the channel.
    let parkedOnToken: string | null = null;

    const setStatus = (status: SocketStatus) => onStatusChangeRef.current?.(status);
    const schedule = (delayMs: number) => {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = window.setTimeout(connect, delayMs);
    };
    const retryLater = () => {
      attempt += 1;
      schedule(nextBackoffMs(attempt, RECONNECT_BACKOFF));
    };
    const halt = (reason: RealtimeHaltReason, error: WebSocketErrorData) => {
      stopped = true;
      window.clearTimeout(reconnectTimer);
      setStatus("closed");
      onHaltRef.current?.(reason, error);
    };
    const unauthorized = (connectionToken: string) => {
      const current = tokenRef.current;
      if (current && current !== connectionToken) {
        // Already rotated (for example by a REST 401): reconnect with the fresh credential.
        schedule(0);
        return;
      }
      parkedOnToken = connectionToken;
      if (!unauthorizedAttemptedRef.current) {
        unauthorizedAttemptedRef.current = true;
        onUnauthorizedRef.current?.();
      }
    };

    function connect() {
      reconnectTimer = undefined;
      const token = tokenRef.current;
      if (stopped || !token || isCurrent?.() === false) {
        return;
      }
      parkedOnToken = null;
      setStatus("connecting");
      let connection: WebSocket;
      try {
        connection = new WebSocket(socketUrl(options.path), socketProtocols(token));
      } catch {
        // For example a credential that is not a valid subprotocol token: retrying cannot help.
        const error = { code: "WS_CLIENT_ERROR", message: "This browser could not open the realtime connection." };
        onErrorRef.current?.(error);
        halt("client_error", error);
        return;
      }
      socket = connection;
      let opened = false;
      let subscribed = false;
      let lastErrorCode: string | null = null;
      const isActive = () => !stopped && socket === connection && isCurrent?.() !== false;
      // Detach first so this connection's own close event is ignored.
      const detach = () => {
        socket = null;
        window.clearTimeout(acknowledgmentTimeout);
        setStatus("closed");
        connection.close();
      };

      connection.onopen = () => {
        if (!isActive()) return;
        opened = true;
        connection.send(JSON.stringify({ action: "subscribe", channel: options.channel, filters: filtersRef.current }));
        acknowledgmentTimeout = window.setTimeout(() => {
          if (isActive() && !subscribed) connection.close();
        }, SUBSCRIBE_ACK_TIMEOUT_MS);
      };

      connection.onmessage = (event: MessageEvent) => {
        if (!isActive()) return;
        let parsed: Record<string, unknown>;
        try {
          parsed = JSON.parse(String(event.data)) as Record<string, unknown>;
        } catch {
          return; // Fail open: a malformed frame never stops valid ones.
        }
        if (!parsed || typeof parsed !== "object" || typeof parsed.event !== "string") return;
        const wsError = toWebSocketError(parsed);
        if (wsError) {
          lastErrorCode = wsError.code;
          onErrorRef.current?.(wsError);
          if (wsError.code === "WS_UNAUTHORIZED") {
            detach();
            unauthorized(token);
          } else if (wsError.code === "WS_CONNECTION_LIMIT") {
            detach();
            halt("connection_limit", wsError);
          } else if (TERMINAL_CODES.has(wsError.code)) {
            detach();
            halt("denied", wsError);
          }
          // Transient codes: the server closes with 1013 and onclose retries.
          return;
        }

        if (parsed.event === "subscribed") {
          if (subscribed || !opened || parsed.channel !== options.channel || !matchesFilters(parsed.filters, filtersRef.current)) return;
          subscribed = true;
          window.clearTimeout(acknowledgmentTimeout);
          upgradeRecoveryAttemptedRef.current = false;
          unauthorizedAttemptedRef.current = false;
          upgradeProbeRetryRef.current = { failures: 0, after: 0 };
          attempt = 0;
          setStatus("open");
          onSubscribedRef.current?.();
          return;
        }
        if (!subscribed) return;
        try {
          onFrameRef.current(parsed as TFrame);
        } catch {
          // A consumer failure on one frame must not stop the channel.
        }
      };

      connection.onclose = async (event: CloseEvent) => {
        if (!isActive()) return;
        socket = null;
        window.clearTimeout(acknowledgmentTimeout);
        setStatus("closed");
        if (lastErrorCode !== null && TRANSIENT_CODES.has(lastErrorCode)) {
          retryLater();
          return;
        }
        if (event.code === CLOSE_TOO_BIG) {
          const error = { code: "WS_MESSAGE_TOO_BIG", message: "The realtime server rejected an oversized client frame." };
          onErrorRef.current?.(error);
          halt("client_error", error);
          return;
        }
        if (event.code === CLOSE_POLICY) {
          // A policy close without a recognised frame is treated as credential expiry.
          unauthorized(token);
          return;
        }
        if (!opened && event.code === CLOSE_ABNORMAL && !upgradeRecoveryAttemptedRef.current &&
            Date.now() >= upgradeProbeRetryRef.current.after && onUpgradeFailureRef.current) {
          // Browsers report a refused upgrade (HTTP 403) and a transport outage identically.
          upgradeRecoveryAttemptedRef.current = true;
          let result: SocketUpgradeRecovery = "inconclusive";
          try {
            result = await onUpgradeFailureRef.current(token);
          } catch {
            // A failed auth probe is not proof of expiry. Keep transport backoff.
          }
          if (stopped || isCurrent?.() === false) return;
          if (result === "inconclusive") {
            const failures = Math.min(upgradeProbeRetryRef.current.failures + 1, 5);
            upgradeProbeRetryRef.current = { failures, after: Date.now() + Math.min(5_000 * 2 ** (failures - 1), 60_000) };
            upgradeRecoveryAttemptedRef.current = false;
          }
        }
        // 1011 / 1013 / network loss: capped, fully jittered reconnect.
        retryLater();
      };
    }

    resumeRef.current = () => {
      if (!stopped && parkedOnToken !== null && tokenRef.current && tokenRef.current !== parkedOnToken) schedule(0);
    };
    connect();

    return () => {
      stopped = true;
      resumeRef.current = null;
      window.clearTimeout(reconnectTimer);
      window.clearTimeout(acknowledgmentTimeout);
      setStatus("closed");
      const open = socket;
      socket = null;
      open?.close();
    };
  }, [
    options.channel,
    options.enabled,
    filtersKey,
    options.path,
    hasToken,
    options.contextKey,
    options.isCurrent,
    options.retryKey,
  ]);
}
