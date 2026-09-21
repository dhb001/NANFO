import type { useOrgAuthority } from "./useOrgAuthority";
import { Button } from "@/shared/ui/Button";
import { toErrorMessage } from "@/shared/lib/errors";

export function OrgAuthorityStatus({ authority, administration = false }: { authority: ReturnType<typeof useOrgAuthority>; administration?: boolean }) {
  if (authority.status === "loading") return <p role="status">Checking your organization membership…</p>;
  if (authority.status === "unknown") return <p>Select an organization to check membership.</p>;
  if (authority.status === "error") return <div role="alert">Unable to verify organization membership: {toErrorMessage(authority.error)} <Button tone="ghost" onClick={() => void authority.retry()}>Retry membership check</Button></div>;
  if (authority.status === "denied") return <p role="alert">Current organization membership is unavailable or access was denied. <Button tone="ghost" onClick={() => void authority.retry()}>Retry membership check</Button></p>;
  if (administration ? !authority.canAdmin : !authority.canWrite) return <p>{administration ? "Organization administration requires global write permission and current organization Admin membership." : "Inventory changes require global write permission and current organization Admin or Operator membership."}</p>;
  return null;
}
