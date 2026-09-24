import { afterEach, describe, expect, it, vi } from "vitest";
import { createTabIdentity, TAB_ID_KEY, TAB_PROBE_WINDOW_MS } from "@/shared/state/tab-identity";

// A same-origin BroadcastChannel bus shared by simulated tabs.
function bus() {
  const members = new Set<{ onmessage: ((event: MessageEvent) => void) | null }>();
  return (name: string) => {
    const channel = {
      name,
      onmessage: null as ((event: MessageEvent) => void) | null,
      postMessage(message: unknown) {
        for (const member of members) {
          if (member !== channel) queueMicrotask(() => member.onmessage?.(new MessageEvent("message", { data: structuredClone(message) })));
        }
      },
      close() { members.delete(channel); },
    };
    members.add(channel);
    return channel;
  };
}

function storage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value); } };
}

let ids = 0;
const newId = () => `tab-${++ids}`;

describe("duplicate-tab session copy detection", () => {
  afterEach(() => vi.useRealTimers());

  it("a fresh tab owns a new id immediately without probing", async () => {
    const tab = createTabIdentity({ storage: storage(), openChannel: bus(), newId });
    expect(tab.state()).toBe("owner");
    expect(await tab.ownership).toBe("owner");
  });

  it("a duplicated tab (same inherited id while the original is alive) is detected and re-identified", async () => {
    vi.useFakeTimers();
    const channel = bus();
    const originalStorage = storage();
    const original = createTabIdentity({ storage: originalStorage, openChannel: channel, newId });
    await original.ownership;
    // Browser "Duplicate tab" copies sessionStorage, including the tab id.
    const copyStorage = storage({ [TAB_ID_KEY]: original.tabId() });
    const copy = createTabIdentity({ storage: copyStorage, openChannel: channel, newId });
    expect(copy.state()).toBeNull();
    await vi.advanceTimersByTimeAsync(0);
    expect(await copy.ownership).toBe("duplicate");
    expect(copy.tabId()).not.toBe(original.tabId());
    expect(copyStorage.getItem(TAB_ID_KEY)).toBe(copy.tabId());
    expect(original.state()).toBe("owner");
  });

  it("a reload (no live owner answers) keeps its id and session", async () => {
    vi.useFakeTimers();
    const tab = createTabIdentity({ storage: storage({ [TAB_ID_KEY]: "tab-reloaded" }), openChannel: bus(), newId });
    expect(tab.state()).toBeNull();
    await vi.advanceTimersByTimeAsync(TAB_PROBE_WINDOW_MS - 1);
    expect(tab.state()).toBeNull();
    await vi.advanceTimersByTimeAsync(1);
    expect(await tab.ownership).toBe("owner");
    expect(tab.tabId()).toBe("tab-reloaded");
  });

  it("an unverified copy never answers for the inherited id", async () => {
    vi.useFakeTimers();
    const channel = bus();
    const shared = { [TAB_ID_KEY]: "tab-restored" };
    // Two restored copies probing at once: neither is a verified owner, so neither claims the other.
    const first = createTabIdentity({ storage: storage(shared), openChannel: channel, newId });
    const second = createTabIdentity({ storage: storage(shared), openChannel: channel, newId });
    await vi.advanceTimersByTimeAsync(TAB_PROBE_WINDOW_MS);
    expect(await first.ownership).toBe("owner");
    expect(await second.ownership).toBe("owner");
  });

  it("ignores malformed messages and answers only matching probes", async () => {
    vi.useFakeTimers();
    const channel = bus();
    const owner = createTabIdentity({ storage: storage(), openChannel: channel, newId });
    const spy = channel("observer");
    const received: unknown[] = [];
    spy.onmessage = (event) => received.push(event.data);
    spy.postMessage({ type: "probe", tabId: "someone-else", nonce: "n1" });
    spy.postMessage({ nonsense: true });
    spy.postMessage({ type: "probe", tabId: owner.tabId(), nonce: "n2" });
    await vi.advanceTimersByTimeAsync(0);
    expect(received).toEqual([{ type: "present", tabId: owner.tabId(), nonce: "n2" }]);
  });

  it("falls back to owner when BroadcastChannel is unavailable", async () => {
    const tab = createTabIdentity({ storage: storage({ [TAB_ID_KEY]: "tab-x" }), openChannel: () => null, newId });
    expect(await tab.ownership).toBe("owner");
  });
});
