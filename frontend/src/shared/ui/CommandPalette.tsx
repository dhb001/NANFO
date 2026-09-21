import { useEffect, useMemo, useRef, useState } from "react";
import { useExitPresence } from "@/shared/ui/useExitPresence";
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
  { id: "go-autonomy", label: "Go to Autonomy", hint: "G N", path: "/ops/autonomy", group: "Navigation" },
  { id: "go-audit", label: "Go to Audit", hint: "G A", path: "/ops/audit", group: "Navigation" },
];

export function CommandPalette() {
  const profile = useAuthStore((state) => state.profile);
  const navigate = useNavigate();
  const open = useUiStore((state) => state.commandPaletteOpen);
  const setOpen = useUiStore((state) => state.setCommandPaletteOpen);
  const present = useExitPresence(open);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const surfaceRef = useRef<HTMLDivElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    surfaceRef.current?.querySelector("input")?.focus();
    return () => { if (returnFocus.current?.isConnected) returnFocus.current.focus(); };
  }, [open]);

  useEffect(() => {
    surfaceRef.current?.querySelector('[data-active="true"]')?.scrollIntoView?.({ block: "nearest" });
  }, [activeIndex]);

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

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Tab") {
        const controls = surfaceRef.current?.querySelectorAll<HTMLElement>("input, button");
        if (!controls?.length) return;
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        return;
      }
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
        if (event.target instanceof HTMLButtonElement) return;
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
      present ? (
        <div
          className="command-palette-backdrop"
          data-open={open}
          aria-hidden={!open || undefined}
          {...(!open ? { inert: "" } : {})}
          role="dialog"
          aria-modal="true"
          aria-label="Command palette"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setOpen(false);
            }
          }}
        >
          <div
            ref={surfaceRef}
            className="command-palette-surface"
          >
            <div className="command-search">
              <input
                value={query}
                onChange={(event) => { setQuery(event.target.value); setActiveIndex(0); }}
                aria-label="Search commands"
                placeholder="Where would you like to go?"
              />
            </div>

            <div className="command-results">
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
                      className="command-result"
                      data-active={active}
                    >
                      <span>
                        <strong>{entry.label}</strong>
                        <span className="command-group">
                          {entry.group}
                        </span>
                      </span>
                      <span className="command-hint">
                        {entry.hint}
                      </span>
                    </button>
                  );
                })
              )}
            </div>
            <div className="command-footer"><span>↑ ↓ to explore &nbsp; · &nbsp; Enter to open</span><span>Esc to close</span></div>
          </div>
        </div>
      ) : null
  );
}
