import { Suspense, lazy } from "react";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";

const TwinPageContent = lazy(async () => {
  const module = await import("@/features/digitalTwin/TwinPageContent");
  return { default: module.TwinPageContent };
});

export function TwinPage() {
  const generation = useAuthStore((state) => state.generation);
  const userId = useAuthStore((state) => state.userId);
  const organizationId = useWorkspaceStore((state) => state.organizationId);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);
  return (
    <Suspense fallback={<div style={{ color: "var(--ink-3)" }}>Loading...</div>}>
      <TwinPageContent key={JSON.stringify([generation, userId, organizationId, workspaceId, networkId])} />
    </Suspense>
  );
}
