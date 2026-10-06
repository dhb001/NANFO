import { randomId } from "@/shared/lib/uid";

// Duplicate-tab detection (ADR-028 session robustness).
//
// "Duplicate tab" copies sessionStorage, including the refresh-token family and
// this tab's id. Two tabs rotating one family trigger backend reuse detection
// and revoke both, so a copy must discard its inherited session. On start a tab
// that inherited an id asks, over a BroadcastChannel, whether a live tab owns
// it; a reply within the probe window proves this document is a copy. A reload
// gets no reply (the previous document is gone) and keeps its session.

export type TabOwnership = "owner" | "duplicate";

export const TAB_ID_KEY = "nanfo.tab.id";
export const TAB_CHANNEL = "nanfo.tab-identity.v1";
export const TAB_PROBE_WINDOW_MS = 300;

interface ChannelLike {
  postMessage: (message: unknown) => void;
  close: () => void;
  onmessage: ((event: MessageEvent) => void) | null;
  unref?: () => void;
}

interface StorageLike {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
}

export interface TabIdentityOptions {
  storage: StorageLike | null;
  openChannel: ((name: string) => ChannelLike | null) | null;
  probeWindowMs?: number;
  newId?: () => string;
}

export interface TabIdentity {
  /** Settles once; "duplicate" means the inherited session must be discarded locally (never revoked). */
  readonly ownership: Promise<TabOwnership>;
  /** Synchronous view: null while the probe is pending. */
  state: () => TabOwnership | null;
  tabId: () => string;
  close: () => void;
}

type Message = { type: "probe" | "present"; tabId: string; nonce: string };

function isMessage(value: unknown): value is Message {
  if (!value || typeof value !== "object") return false;
  const message = value as Record<string, unknown>;
  return (message.type === "probe" || message.type === "present") &&
    typeof message.tabId === "string" && typeof message.nonce === "string";
}

export function createTabIdentity({ storage, openChannel, probeWindowMs = TAB_PROBE_WINDOW_MS, newId = () => randomId("tab") }: TabIdentityOptions): TabIdentity {
  const read = () => {
    try { return storage?.getItem(TAB_ID_KEY) ?? null; } catch { return null; }
  };
  const write = (value: string) => {
    try { storage?.setItem(TAB_ID_KEY, value); } catch { /* Tab-local only; nothing to share. */ }
  };
  const inherited = read();
  let id = inherited ?? newId();
  // Only a verified owner answers probes: an unverified copy never claims the id.
  let verified = false;
  let settled: TabOwnership | null = null;
  let channel: ChannelLike | null = null;
  try {
    channel = openChannel?.(TAB_CHANNEL) ?? null;
    channel?.unref?.();
  } catch {
    channel = null;
  }
  const nonce = newId();
  let resolveOwnership!: (value: TabOwnership) => void;
  const ownership = new Promise<TabOwnership>((resolve) => { resolveOwnership = resolve; });
  const settle = (value: TabOwnership) => {
    if (settled) return;
    if (value === "duplicate") id = newId();
    write(id);
    verified = true;
    settled = value;
    resolveOwnership(value);
  };

  if (channel) {
    channel.onmessage = (event: MessageEvent) => {
      const message: unknown = event.data;
      if (!isMessage(message)) return;
      if (message.type === "probe" && verified && message.tabId === id) {
        channel?.postMessage({ type: "present", tabId: id, nonce: message.nonce } satisfies Message);
      } else if (message.type === "present" && !settled && message.tabId === id && message.nonce === nonce) {
        settle("duplicate");
      }
    };
  }

  if (!inherited || !channel) {
    settle("owner");
  } else {
    try {
      channel.postMessage({ type: "probe", tabId: id, nonce } satisfies Message);
      setTimeout(() => settle("owner"), probeWindowMs);
    } catch {
      settle("owner");
    }
  }

  return {
    ownership,
    state: () => settled,
    tabId: () => id,
    close: () => { channel?.close(); channel = null; },
  };
}

function browserChannel(name: string): ChannelLike | null {
  return typeof BroadcastChannel === "function" ? new BroadcastChannel(name) : null;
}

function browserStorage(): StorageLike | null {
  try { return window.sessionStorage; } catch { return null; }
}

/** This document's identity; started at import so every tab can answer probes from copies. */
export const tabIdentity: TabIdentity = createTabIdentity({ storage: browserStorage(), openChannel: browserChannel });
