import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, m, useReducedMotion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { useUiStore } from "@/shared/state/ui-store";
import { useAuthStore } from "@/shared/state/auth-store";
import { canAccessRoute } from "@/features/auth/permissions";

interface CommandEntry {
  id: string;
  label: string;
  hint: string;
  path: string;
  group: string;
}

const commands: CommandEntry[] = [
  { id: "go-overview", label: "Go to Overview", hint: "G O", path: "/ops/overview", group: "Navigation" },
  { id: "go-tenancy", label: "Go to Tenancy", hint: "G W", path: "/ops/tenancy", group: "Navigation" },
  { id: "go-topology-analysis", label: "Go to Topology Analysis", hint: "G P", path: "/ops/topology-analysis", group: "Navigation" },
  { id: "go-telemetry", label: "Go to Telemetry", hint: "G T", path: "/ops/telemetry", group: "Navigation" },
  { id: "go-reliability", label: "Go to Reliability", hint: "G R", path: "/ops/reliability", group: "Navigation" },
  { id: "go-alerts", label: "Go to Alerts Lifecycle", hint: "G L", path: "/ops/reliability", group: "Navigation" },
  { id: "go-plugins", label: "Go to Plugins", hint: "G U", path: "/ops/plugins", group: "Navigation" },
  { id: "go-reports", label: "Go to Reports", hint: "G Y", path: "/ops/reports", group: "Navigation" },
  { id: "go-twin", label: "Go to Digital Twin", hint: "G D", path: "/ops/digital-twin", group: "Navigation" },
  { id: "go-simulation", label: "Go to Simulation", hint: "G S", path: "/ops/simulation", group: "Navigation" },
  { id: "go-intent", label: "Go to Intent", hint: "G I", path: "/ops/intent", group: "Navigation" },
  { id: "go-audit", label: "Go to Audit", hint: "G A", path: "/ops/audit", group: "Navigation" },
];

export function CommandPalette() {
  const profile = useAuthStore((state) => state.profile);
  const navigate = useNavigate();
  const open = useUiStore((state) => state.commandPaletteOpen);
  const setOpen = useUiStore((state) => state.setCommandPaletteOpen);
  const prefersReducedMotion = useReducedMotion();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const allowed = commands.filter((entry) => canAccessRoute(profile, entry.path));
    if (!needle) {
      return allowed;
    }
    return allowed.filter((entry) => {
      return (
        entry.label.toLowerCase().includes(needle) ||
        entry.group.toLowerCase().includes(needle) ||
        entry.hint.toLowerCase().replace(/\s+/g, "").includes(needle.replace(/\s+/g, ""))
      );
    });
  }, [query, profile]);

  useEffect(() => {
    if (!open) {
      setQuery("");
      setActiveIndex(0);
      return;
    }

    setActiveIndex(0);

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveIndex((value) => Math.min(filtered.length - 1, value + 1));
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveIndex((value) => Math.max(0, value - 1));
        return;
      }
      if (event.key === "Enter") {
        const entry = filtered[activeIndex];
        if (!entry) {
          return;
        }
        event.preventDefault();
        setOpen(false);
        navigate(entry.path);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeIndex, filtered, navigate, open, setOpen]);

  return (
    <AnimatePresence>
      {open ? (
        <m.div
          initial={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, backdropFilter: "blur(0px)" }}
          animate={prefersReducedMotion ? { opacity: 1 } : { opacity: 1, backdropFilter: "blur(4px)" }}
          exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, backdropFilter: "blur(0px)" }}
          transition={{ duration: 0.18 }}
          role="dialog"
          aria-modal="true"
          aria-label="Command palette"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setOpen(false);
            }
          }}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(6, 16, 28, 0.3)",
            zIndex: 1300,
            display: "grid",
            placeItems: "start center",
            paddingTop: "14vh",
          }}
        >
          <m.div
            initial={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 18, scale: 0.985 }}
            animate={prefersReducedMotion ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
            exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 10, scale: 0.99 }}
            transition={{ duration: 0.2, ease: [0.21, 1, 0.32, 1] }}
            style={{
              width: "min(720px, calc(100vw - 1.4rem))",
              borderRadius: 16,
              border: "1px solid var(--line-strong)",
              boxShadow: "var(--shadow-mid)",
              background:
                "linear-gradient(170deg, color-mix(in srgb, var(--surface-card) 95%, white), color-mix(in srgb, var(--surface-1) 92%, white))",
              overflow: "hidden",
            }}
          >
            <div style={{ padding: "0.7rem 0.8rem", borderBottom: "1px solid var(--line-soft)" }}>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                autoFocus
                aria-label="Search commands"
                placeholder="Jump to route (example: twin, telemetry, G D)"
                style={{
                  width: "100%",
                  border: "1px solid var(--line-soft)",
                  borderRadius: 10,
                  padding: "0.55rem 0.62rem",
                  background: "rgba(255, 255, 255, 0.9)",
                }}
              />
            </div>

            <div style={{ maxHeight: 380, overflow: "auto", display: "grid" }}>
              {filtered.length === 0 ? (
                <div style={{ padding: "0.8rem", color: "var(--ink-3)" }}>No commands match this filter.</div>
              ) : (
                filtered.map((entry, index) => {
                  const active = index === activeIndex;
                  return (
                    <button
                      key={entry.id}
                      onMouseEnter={() => setActiveIndex(index)}
                      onClick={() => {
                        setOpen(false);
                        navigate(entry.path);
                      }}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        padding: "0.64rem 0.76rem",
                        borderBottom: "1px solid var(--line-soft)",
                        background: active ? "color-mix(in srgb, var(--brand) 16%, white)" : "transparent",
                        textAlign: "left",
                      }}
                    >
                      <span>
                        <strong>{entry.label}</strong>
                        <span style={{ marginLeft: "0.45rem", color: "var(--ink-3)", fontSize: "0.82rem" }}>
                          {entry.group}
                        </span>
                      </span>
                      <span className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                        {entry.hint}
                      </span>
                    </button>
                  );
                })
              )}
            </div>
          </m.div>
        </m.div>
      ) : null}
    </AnimatePresence>
  );
}
