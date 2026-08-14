import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuthStore } from "@/shared/state/auth-store";
import { Button } from "@/shared/ui/Button";
import { useUiStore } from "@/shared/state/ui-store";
import { RealtimeBridge } from "@/features/realtime/RealtimesBridge";
import { useIsNarrowViewport } from "@/shared/lib/viewport";

const navItems = [
  { to: "/ops/overview", label: "Overview", keyHint: "G O" },
  { to: "/ops/tenancy", label: "Tenancy", keyHint: "G W" },
  { to: "/ops/topology-analysis", label: "Topology", keyHint: "G P" },
  { to: "/ops/telemetry", label: "Telemetry", keyHint: "G T" },
  { to: "/ops/reliability", label: "Reliability", keyHint: "G R / G L" },
  { to: "/ops/plugins", label: "Plugins", keyHint: "G U" },
  { to: "/ops/reports", label: "Reports", keyHint: "G Y" },
  { to: "/ops/digital-twin", label: "Digital Twin", keyHint: "G D" },
  { to: "/ops/simulation", label: "Simulation", keyHint: "G S" },
  { to: "/ops/intent", label: "Intent", keyHint: "G I" },
  { to: "/ops/audit", label: "Audit", keyHint: "G A" },
];

export function AppShell() {
  const navigate = useNavigate();
  const clearSession = useAuthStore((state) => state.clearSession);
  const activeUser = useAuthStore((state) => state.userId);
  const commandPaletteOpen = useUiStore((state) => state.commandPaletteOpen);
  const setCommandPaletteOpen = useUiStore((state) => state.setCommandPaletteOpen);
  const isNarrowViewport = useIsNarrowViewport();

  const appGridColumns = isNarrowViewport ? "minmax(0, 1fr)" : "260px minmax(0, 1fr)";

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        gridTemplateColumns: appGridColumns,
      }}
    >
      <RealtimeBridge />
      <aside
        style={{
          borderRight: isNarrowViewport ? "none" : "1px solid var(--line-soft)",
          borderBottom: isNarrowViewport ? "1px solid var(--line-soft)" : "none",
          background: "color-mix(in srgb, var(--surface-card) 92%, #ffffff)",
          padding: "1.1rem 0.9rem",
          position: isNarrowViewport ? "relative" : "sticky",
          top: 0,
          height: isNarrowViewport ? "auto" : "100vh",
        }}
      >
        <div style={{ marginBottom: "1rem" }}>
          <div className="mono" style={{ color: "var(--ink-3)", fontSize: "0.82rem" }}>
            NANFO
          </div>
          <div style={{ fontWeight: 700, fontSize: "1.35rem" }}>Network Operations</div>
        </div>
        <nav
          style={{
            display: "grid",
            gap: "0.4rem",
            gridTemplateColumns: isNarrowViewport ? "repeat(2, minmax(0, 1fr))" : undefined,
          }}
        >
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              style={({ isActive }) => ({
                padding: "0.6rem 0.65rem",
                borderRadius: "10px",
                border: "1px solid",
                borderColor: isActive ? "var(--brand)" : "transparent",
                background: isActive ? "color-mix(in srgb, var(--brand) 14%, white)" : "transparent",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                color: isActive ? "var(--ink-1)" : "var(--ink-2)",
              })}
            >
              <span>{item.label}</span>
              <span className="mono" style={{ fontSize: "0.72rem", color: "var(--ink-3)" }}>
                {item.keyHint}
              </span>
            </NavLink>
          ))}
        </nav>
      </aside>

      <main style={{ minWidth: 0 }}>
        <header
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "0.9rem 1rem",
            borderBottom: "1px solid var(--line-soft)",
            position: isNarrowViewport ? "relative" : "sticky",
            top: 0,
            backdropFilter: isNarrowViewport ? "none" : "blur(8px)",
            background: "color-mix(in srgb, var(--surface-0) 88%, transparent)",
            zIndex: 20,
            gap: "0.6rem",
            flexWrap: "wrap",
          }}
        >
          <button
            className="mono"
            style={{
              border: "1px solid var(--line-soft)",
              borderRadius: "10px",
              padding: "0.45rem 0.6rem",
              color: "var(--ink-3)",
              minWidth: "240px",
              textAlign: "left",
            }}
            aria-label="Toggle command palette"
            onClick={() => setCommandPaletteOpen(!commandPaletteOpen)}
          >
            {commandPaletteOpen ? "Close Command Palette" : "Open Command Palette"}  Ctrl/Cmd+K
          </button>

          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <div className="mono" style={{ fontSize: "0.8rem", color: "var(--ink-3)" }}>
              {activeUser ?? "operator"}
              </div>
            <Button
              tone="ghost"
              onClick={() => {
                clearSession();
                navigate("/login");
              }}
            >
              Logout
            </Button>
          </div>
        </header>

        <div style={{ padding: "1rem", display: "grid", gap: "1rem" }}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
