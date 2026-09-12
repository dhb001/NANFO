import { act, cleanup, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useOperatorSession } from "./operatorSession";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";

describe("ADR018 operator session", () => {
  let client: QueryClient;
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  beforeEach(() => {
    client = new QueryClient();
    useAuthStore.setState({ accessToken: "token", generation: 1, endingSession: false,
      profile: { ...operatorProfile, permissions: ["read:telemetry", "write:config", "execute:rollback"] } });
    useWorkspaceStore.setState({ organizationId: "org", networkId: "network", workspaceId: "workspace" });
  });
  afterEach(() => { cleanup(); client.clear(); });
  it.each(["read:telemetry", "write:config", "execute:rollback"])("requires current %s for every mutation", (permission) => {
    const { result } = renderHook(useOperatorSession, { wrapper });
    const session = result.current;
    act(() => useAuthStore.setState({ profile: { ...operatorProfile, permissions: ["read:telemetry", "write:config", "execute:rollback"].filter((value) => value !== permission) } }));
    expect(() => session.assertCurrent(true)).toThrow();
    expect(result.current.canWrite).toBe(false);
  });
  it.each(["organizationId", "workspaceId", "networkId"])("discards callbacks from the previous %s", (field) => {
    const { result } = renderHook(useOperatorSession, { wrapper });
    const session = result.current;
    const invalidate = vi.spyOn(client, "invalidateQueries");
    act(() => useWorkspaceStore.setState({ [field]: "new-scope" }));
    expect(() => session.assertCurrent()).toThrow();
    session.reconcile();
    expect(invalidate).not.toHaveBeenCalled();
  });
  it("blocks logout and token rotation, while readers may explicitly fetch", () => {
    const { result } = renderHook(useOperatorSession, { wrapper });
    const session = result.current;
    act(() => useAuthStore.setState({ accessToken: "new-token" }));
    expect(() => session.assertCurrent()).toThrow();
    act(() => useAuthStore.setState({ profile: { ...operatorProfile, permissions: ["read:telemetry"] } }));
    expect(() => result.current.assertCurrent()).not.toThrow();
    expect(() => result.current.assertCurrent(true)).toThrow();
    act(() => useAuthStore.setState({ endingSession: true }));
    expect(result.current.enabled).toBe(false);
    expect(() => result.current.assertCurrent()).toThrow();
  });
});
