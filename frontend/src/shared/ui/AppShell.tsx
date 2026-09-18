import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuthStore } from "@/shared/state/auth-store";
import { Button } from "@/shared/ui/Button";
import { BrandMark } from "@/shared/ui/BrandMark";
import { useUiStore } from "@/shared/state/ui-store";
import { RealtimeBridge } from "@/features/realtime/RealtimesBridge";
import { logoutSession } from "@/features/auth/session";
import { canAccessRoute } from "@/features/auth/permissions";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { AsyncState } from "@/shared/ui/AsyncState";
import { ExecutionModeBanner } from "@/shared/ui/ExecutionModeBanner";

const navGroups = [
  { label: "Observe", items: [
    { to: "/ops/overview", label: "Overview", key: "O" },
    { to: "/ops/topology-analysis", label: "Topology", key: "P" },
    { to: "/ops/telemetry", label: "Telemetry", key: "T" },
    { to: "/ops/reliability", label: "Reliability", key: "R" },
  ] },
  { label: "Orchestrate", items: [
    { to: "/ops/digital-twin", label: "Digital Twin", key: "D" },
    { to: "/ops/simulation", label: "Simulation", key: "S" },
    { to: "/ops/intent", label: "Intent", key: "I" },
    { to: "/ops/autonomy", label: "Autonomy", key: "N" },
  ] },
  { label: "Manage", items: [
    { to: "/ops/tenancy", label: "Tenancy", key: "W" },
    { to: "/ops/plugins", label: "Plugins", key: "U" },
    { to: "/ops/reports", label: "Reports", key: "Y" },
    { to: "/ops/audit", label: "Audit", key: "A" },
  ] },
];

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const profile = useAuthStore((state) => state.profile);
  const endingSession = useAuthStore((state) => state.endingSession);
  const generation = useAuthStore((state) => state.generation);
  const organizationId = useWorkspaceStore((state) => state.organizationId);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const contextKey = JSON.stringify([generation, organizationId, workspaceId, networkId]);
  const activeUser = useAuthStore((state) => state.userId);
  const commandPaletteOpen = useUiStore((state) => state.commandPaletteOpen);
  const setCommandPaletteOpen = useUiStore((state) => state.setCommandPaletteOpen);
  const currentPage = navGroups.flatMap((group) => group.items).find((item) => item.to === location.pathname);

  return (
    <div className="app-shell">
      <RealtimeBridge />
      <a className="skip-link" href="#workspace-content">Skip to workspace</a>
      <aside className="app-rail">
        <div className="rail-brand"><BrandMark /></div>
        <nav className="rail-navigation" aria-label="Main navigation">
          {navGroups.map((group) => {
            const items = group.items.filter((item) => canAccessRoute(profile, item.to));
            return items.length ? <div className="nav-group" key={group.label}>
              <div className="nav-group-label">{group.label}</div>
              {items.map((item) => (
                <NavLink key={item.to} to={item.to} className={({ isActive }) => `nav-item${isActive ? " is-active" : ""}`}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" aria-hidden="true"><use href={`/navigation.svg#${item.key}`} /></svg>
                  <span>{item.label}</span>
                  <span className="nav-key" aria-hidden="true">{item.key}</span>
                </NavLink>
              ))}
            </div> : null;
          })}
        </nav>
        <div className="rail-footer"><span className="rail-index">N / 01</span><span>Network operations<br /><strong>A clearer perspective.</strong></span></div>
      </aside>
      <main className="app-main">
        <header className="app-topbar">
          <div className="breadcrumb"><span>Operations</span><span aria-hidden="true">/</span><strong>{currentPage?.label ?? "Workspace"}</strong></div>
          <div className="topbar-actions">
            <button className="command-trigger" aria-label="Toggle command palette" aria-expanded={commandPaletteOpen} onClick={() => setCommandPaletteOpen(!commandPaletteOpen)}>
              <span aria-hidden="true">⌕</span><span>Jump to…</span><kbd>⌘ / Ctrl K</kbd>
            </button>
            <div className="operator-id" title={activeUser ?? "operator"}><span className="operator-avatar" aria-hidden="true">OP</span><span>Operator</span></div>
            <Button tone="ghost" disabled={endingSession} onClick={async () => {
              try {
                await logoutSession();
              } catch {
                useUiStore.getState().pushToast({ title: "Signed out locally", tone: "warn", description: "Backend revocation could not be confirmed. Sign in again to continue." });
              }
              navigate("/login", { replace: true });
            }}>{endingSession ? "Signing Out..." : "Logout"}</Button>
          </div>
        </header>
        <ExecutionModeBanner />
        <div key={contextKey} id="workspace-content" tabIndex={-1} className="workspace-content">
          {canAccessRoute(profile, location.pathname) ? <Outlet /> : <AsyncState title="Permission denied" description="Your current backend profile does not permit this route." />}
        </div>
      </main>
    </div>
  );
}
