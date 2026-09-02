import { Suspense, lazy } from "react";

const TwinPageContent = lazy(async () => {
  const module = await import("@/features/digitalTwin/TwinPageContent");
  return { default: module.TwinPageContent };
});

export function TwinPage() {
  return (
    <Suspense fallback={<div style={{ color: "var(--ink-3)" }}>Loading...</div>}>
      <TwinPageContent />
    </Suspense>
  );
}
