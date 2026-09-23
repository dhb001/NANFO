import { useState, type PropsWithChildren } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Outlet } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "@/app/App";

const failures = vi.hoisted(() => ({ page: true, shell: false, gate: false, provider: false }));

vi.mock("@/app/providers", () => ({ AppProviders: ({ children }: PropsWithChildren) => {
  if (failures.provider) throw new Error("provider failed");
  return <><input aria-label="Provider draft" defaultValue="" />{children}</>;
} }));
vi.mock("@/features/auth/SessionGate", () => ({ SessionGate: ({ children }: PropsWithChildren) => {
  if (failures.gate) throw new Error("gate failed");
  return children;
} }));
vi.mock("@/shared/ui/AppShell", () => ({ AppShell: () => {
  const [draft, setDraft] = useState("");
  if (failures.shell) throw new Error("shell failed");
  return <>
    <nav aria-label="Workspace"><Link to="/ops/overview">Overview</Link></nav>
    <input aria-label="Shell draft" value={draft} onChange={(event) => setDraft(event.target.value)} />
    <Outlet />
  </>;
} }));
vi.mock("@/app/routes", () => {
  function Page() {
    if (failures.page) throw new Error("page failed");
    return <p>Healthy route</p>;
  }
  return Object.fromEntries([
    "AuditPage", "AutonomyPage", "IntentPage", "LoginPage", "OverviewPage", "PluginsPage",
    "ReportsPage", "ReliabilityPage", "SimulationPage", "TenancyPage", "TelemetryPage",
    "TopologyAnalysisPage", "TwinPage",
  ].map((name) => [name, Page]));
});

describe("App route boundary placement", () => {
  beforeEach(() => {
    Object.assign(failures, { page: true, shell: false, gate: false, provider: false });
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });
  afterEach(() => vi.restoreAllMocks());

  it.each([
    "overview", "tenancy", "topology-analysis", "telemetry", "reliability", "plugins",
    "reports", "digital-twin", "simulation", "intent", "autonomy", "audit",
  ])("contains /ops/%s failure inside the shell and recovers on navigation", async (route) => {
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={[`/ops/${route}`]}><App /></MemoryRouter>);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Workspace" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Shell draft"), "retained shell");
    await user.type(screen.getByLabelText("Provider draft"), "retained provider");
    failures.page = false;
    await user.click(screen.getByRole("link", { name: "Overview" }));
    expect(screen.getByText("Healthy route")).toBeInTheDocument();
    expect(screen.getByLabelText("Shell draft")).toHaveValue("retained shell");
    expect(screen.getByLabelText("Provider draft")).toHaveValue("retained provider");
  });

  it("recovers the public login route without losing provider state", async () => {
    render(<MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter>);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Provider draft"), "retained");
    failures.page = false;
    await userEvent.click(screen.getByRole("button", { name: "Try page again" }));
    expect(screen.getByText("Healthy route")).toBeInTheDocument();
    expect(screen.getByLabelText("Provider draft")).toHaveValue("retained");
  });

  it.each(["shell", "gate", "provider"] as const)("provides outer recovery for %s failure", async (scope) => {
    failures.page = false;
    failures[scope] = true;
    render(<MemoryRouter initialEntries={["/ops/overview"]}><App /></MemoryRouter>);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    failures[scope] = false;
    await userEvent.click(screen.getByRole("button", { name: "Try page again" }));
    expect(screen.getByText("Healthy route")).toBeInTheDocument();
  });
});
