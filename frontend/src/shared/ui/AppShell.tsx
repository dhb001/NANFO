import { useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuthStore } from "@/shared/state/auth-store";
import { Button } from "@/shared/ui/Button";
import { BrandMark } from "@/shared/ui/BrandMark";
import { useUiStore } from "@/shared/state/ui-store";
import { RealtimeBridge } from "@/features/realtime/RealtimesBridge";
import { RealtimeRetryControl } from "@/features/realtime/RealtimeRetryControl";
import { SessionRecoveryBanner } from "@/features/auth/SessionRecoveryBanner";
import { logoutSession } from "@/features/auth/session";
import { canAccessRoute } from "@/features/auth/permissions";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { AsyncState } from "@/shared/ui/AsyncState";
import { ExecutionModeBanner } from "@/shared/ui/ExecutionModeBanner";
import { useFocusRestoration } from "@/shared/lib/focusRestore";

const navGroups = [
  { label: "Observe", items: [
    { to: "/ops/overview", label: "Overview", key: "O", description: "" },
    { to: "/ops/topology-analysis", label: "Topology", key: "P", description: "Trace connections. Understand dependencies. See the impact of change." },
    { to: "/ops/telemetry", label: "Telemetry", key: "T", description: "Read the signals behind your network. Explore measurements over time." },
    { to: "/ops/reliability", label: "Reliability", key: "R", description: "Investigate alerts, review their evidence and track resolution." },
  ] },
  { label: "Orchestrate", items: [
    { to: "/ops/digital-twin", label: "Digital Twin", key: "D", description: "Infrastructure in context. Explore the scene, layers and spatial evidence." },
    { to: "/ops/simulation", label: "Simulation", key: "S", description: "Explore what happens next, before making a change." },
    { to: "/ops/intent", label: "Intent", key: "I", description: "From a desired outcome to an explainable, validated action." },
    { to: "/ops/autonomy", label: "Autonomy", key: "N", description: "" },
  ] },
  { label: "Manage", items: [
    { to: "/ops/tenancy", label: "Tenancy", key: "W", description: "Organize workspaces, manage membership and choose your operating scope." },
    { to: "/ops/plugins", label: "Plugins", key: "U", description: "Manage the metadata registry for your network integrations." },
    { to: "/ops/reports", label: "Reports", key: "Y", description: "Turn operational evidence into a record you can share." },
    { to: "/ops/audit", label: "Audit", key: "A", description: "Follow the record. Inspect actions, actors and outcomes." },
  ] },
];

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const [menuPath, setMenuPath] = useState<string | null>(null);
  const menuOpen = menuPath === location.pathname;
  const menuButton = useRef<HTMLButtonElement>(null);
  const profile = useAuthStore((state) => state.profile);
  const endingSession = useAuthStore((state) => state.endingSession);
  const generation = useAuthStore((state) => state.generation);
  const organizationId = useWorkspaceStore((state) => state.organizationId);
  const workspaceId = useWorkspaceStore((state) => state.workspaceId);
  const networkId = useWorkspaceStore((state) => state.networkId);
  const contextKey = JSON.stringify([generation, organizationId, workspaceId, networkId]);
  // Scope changes remount the content; the control that changed scope gets its focus back.
  const content = useRef<HTMLDivElement>(null);
  useFocusRestoration(content, contextKey);
  const activeUser = useAuthStore((state) => state.userId);
  const commandPaletteOpen = useUiStore((state) => state.commandPaletteOpen);
  const setCommandPaletteOpen = useUiStore((state) => state.setCommandPaletteOpen);
  const currentPage = navGroups.flatMap((group) => group.items).find((item) => item.to === location.pathname);
  const currentGroup = navGroups.find((group) => group.items.some((item) => item.to === location.pathname));
  const operatorName = profile?.display_name || profile?.email?.split("@")[0] || "Operator";

  return (
    <div className="app-shell">
      <RealtimeBridge />
      <a className="skip-link" href="#workspace-content">Skip to workspace</a>
      <aside className="app-rail" data-menu-open={menuOpen} onKeyDown={(event) => {
        if (event.key === "Escape" && menuOpen) { setMenuPath(null); menuButton.current?.focus(); }
      }}>
        <div className="rail-brand"><BrandMark /><button ref={menuButton} className="mobile-menu" aria-label="Toggle navigation" aria-expanded={menuOpen} aria-controls="main-navigation" onClick={() => setMenuPath(menuOpen ? null : location.pathname)}><span aria-hidden="true">{menuOpen ? "×" : "☰"}</span> Menu</button></div>
        <nav id="main-navigation" className="rail-navigation" aria-label="Main navigation">
          {navGroups.map((group) => {
            const items = group.items.filter((item) => canAccessRoute(profile, item.to));
            return items.length ? <div className="nav-group" key={group.label}>
              <div className="nav-group-label">{group.label}</div>
              {items.map((item) => (
                <NavLink key={item.to} to={item.to} title={`${item.label} · G ${item.key}`} onClick={() => {
                  if (menuOpen) { setMenuPath(null); requestAnimationFrame(() => document.getElementById("workspace-content")?.focus()); }
                }} className={({ isActive }) => `nav-item${isActive ? " is-active" : ""}`}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" aria-hidden="true"><use href={`/navigation.svg#${item.key}`} /></svg>
                  <span>{item.label}</span>
                  <span className="nav-key" aria-hidden="true">{item.key}</span>
                </NavLink>
              ))}
            </div> : null;
          })}
        </nav>
        <div className="rail-footer"><span className="rail-index">N /</span><span>THE NETWORK ATLAS<br /><strong>Every connection, considered.</strong></span></div>
      </aside>
      <main className="app-main">
        <header className="app-topbar">
          <div className="breadcrumb"><span className="breadcrumb-mark" aria-hidden="true">⌘</span><span>{currentGroup?.label ?? "Operations"}</span><span aria-hidden="true">/</span><strong>{currentPage?.label ?? "Workspace"}</strong></div>
          <div className="topbar-actions">
            <button className="command-trigger" aria-label="Toggle command palette" aria-expanded={commandPaletteOpen} onClick={() => setCommandPaletteOpen(!commandPaletteOpen)}>
              <span aria-hidden="true">⌕</span><span>Find a workspace tool</span><kbd>⌘ / Ctrl K</kbd>
            </button>
            <div className="operator-id" title={activeUser ?? "operator"}><span className="operator-avatar" aria-hidden="true">{operatorName.slice(0, 2).toUpperCase()}</span><span>{operatorName}</span></div>
            <Button tone="ghost" disabled={endingSession} onClick={async () => {
              try {
                await logoutSession();
              } catch {
                useUiStore.getState().pushToast({ title: "Signed out locally", tone: "warn", description: "Backend revocation could not be confirmed. Sign in again to continue." });
              }
              void navigate("/login", { replace: true });
            }}>{endingSession ? "Signing Out..." : "Logout"}</Button>
          </div>
        </header>
        <ExecutionModeBanner />
        <SessionRecoveryBanner />
        <RealtimeRetryControl />
        <div key={contextKey} ref={content} id="workspace-content" tabIndex={-1} className="workspace-content">
          {currentPage?.description && canAccessRoute(profile, location.pathname) ? <header className="page-heading" key={location.pathname}><div><div className="eyebrow">{currentGroup?.label} / Network atlas</div><h1>{currentPage.label}</h1><p>{currentPage.description}</p></div><span className="page-index" aria-hidden="true">N / {currentPage.key}</span></header> : null}
          {canAccessRoute(profile, location.pathname) ? <Outlet /> : <AsyncState title="Permission denied" description="Your current backend profile does not permit this route." />}
        </div>
      </main>
    </div>
  );
}
