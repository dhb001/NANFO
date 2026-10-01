import { lazy, Suspense, useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import { noteServerRequestId, onUiIncident, type UiIncident } from "@/shared/lib/errorReporting";

function BrokenPage({ error = new Error("private internal details") }: { error?: unknown }): never {
  throw error;
}

function NavigationFixture() {
  const location = useLocation();
  const navigate = useNavigate();
  return <>
    <Link to="/healthy">Another page</Link>
    <Link to="?recovered=true">Change query</Link>
    <Link to="#recovered">Change hash</Link>
    <button onClick={() => navigate(-1)}>Back</button>
    <RouteErrorBoundary>
      {location.pathname === "/broken" && !location.search && !location.hash
        ? <BrokenPage />
        : <input aria-label="Page draft" defaultValue="" />}
    </RouteErrorBoundary>
  </>;
}

describe("route error recovery", () => {
  let reload: ReturnType<typeof vi.fn>;
  let request: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // React reports caught render errors to the development console.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    reload = vi.fn();
    request = vi.fn();
    vi.stubGlobal("location", { reload });
    vi.stubGlobal("fetch", request);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("focuses a named error panel, hides internal details and retries only on keyboard activation", async () => {
    const user = userEvent.setup();
    let failed = true;
    function Page() {
      if (failed) return <BrokenPage />;
      return <p>Recovered page</p>;
    }
    render(<MemoryRouter><RouteErrorBoundary><Page /></RouteErrorBoundary></MemoryRouter>);
    expect(screen.getByRole("alert", { name: "This page could not be displayed" })).toHaveFocus();
    expect(screen.queryByText("private internal details")).not.toBeInTheDocument();
    expect(screen.getByText(/check its status before submitting/)).toBeInTheDocument();
    failed = false;
    expect(screen.queryByText("Recovered page")).not.toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
    await user.tab();
    expect(screen.getByRole("button", { name: "Try page again" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByText("Recovered page")).toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
  });

  it.each(["Another page", "Change query", "Change hash", "Back"])("resets on navigation via %s", async (name) => {
    render(<MemoryRouter initialEntries={["/healthy", "/broken"]}><NavigationFixture /></MemoryRouter>);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await userEvent.click(screen.getByRole(name === "Back" ? "button" : "link", { name }));
    expect(screen.getByLabelText("Page draft")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
  });

  it("preserves healthy local drafts through query/hash/history changes", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/healthy"]}><NavigationFixture /></MemoryRouter>);
    const draft = screen.getByLabelText("Page draft");
    await user.type(draft, "unsaved work");
    await user.click(screen.getByRole("link", { name: "Change query" }));
    await user.click(screen.getByRole("link", { name: "Change hash" }));
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Page draft")).toBe(draft);
    expect(draft).toHaveValue("unsaved work");
  });

  it("retains ancestor-owned drafts and does not replay a submitted mutation on recovery", async () => {
    const user = userEvent.setup();
    let fail = false;
    const mutate = vi.fn();
    function Page() {
      const [, update] = useState(0);
      if (fail) return <BrokenPage />;
      return <button onClick={() => { mutate(); fail = true; update(1); }}>Submit action</button>;
    }
    render(<MemoryRouter>
      <input aria-label="Outside draft" defaultValue="" />
      <RouteErrorBoundary><Page /></RouteErrorBoundary>
    </MemoryRouter>);
    const draft = screen.getByLabelText("Outside draft");
    await user.type(draft, "keep me");
    await user.click(screen.getByRole("button", { name: "Submit action" }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    fail = false;
    await user.click(screen.getByRole("button", { name: "Try page again" }));
    expect(screen.getByLabelText("Outside draft")).toBe(draft);
    expect(draft).toHaveValue("keep me");
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(request).not.toHaveBeenCalled();
    expect(reload).not.toHaveBeenCalled();
  });

  it("contains a real lazy rejection and reloads only after explicit keyboard activation", async () => {
    const user = userEvent.setup();
    const load = vi.fn().mockRejectedValue(new TypeError("Failed to fetch dynamically imported module: private-url"));
    const LazyPage = lazy(load);
    render(<MemoryRouter><RouteErrorBoundary>
      <Suspense fallback={<p>Loading page</p>}><LazyPage /></Suspense>
    </RouteErrorBoundary></MemoryRouter>);
    expect(await screen.findByRole("alert", { name: "Page bundle could not load" })).toHaveFocus();
    expect(screen.queryByText(/private-url/)).not.toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Try page again" }));
    // React.lazy caches rejection: a redraw must remain recoverable, not reload-loop.
    expect(screen.getByRole("alert", { name: "Page bundle could not load" })).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(1);
    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Try page again" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Reload application (may lose drafts)" })).toHaveFocus();
    await user.keyboard(" ");
    expect(reload).toHaveBeenCalledTimes(1);
    expect(request).not.toHaveBeenCalled();
  });

  it.each([
    new Error("Loading chunk 42 failed"),
    new TypeError("Importing a module script failed."),
    new TypeError("error loading dynamically imported module"),
  ])("recognizes browser chunk errors without exposing their contents: %s", (error) => {
    render(<MemoryRouter><RouteErrorBoundary><BrokenPage error={error} /></RouteErrorBoundary></MemoryRouter>);
    expect(screen.getByRole("alert", { name: "Page bundle could not load" })).toBeInTheDocument();
  });

  it("contains non-Error thrown values and keeps a persistent failure bounded", async () => {
    render(<MemoryRouter><RouteErrorBoundary><BrokenPage error={null} /></RouteErrorBoundary></MemoryRouter>);
    await userEvent.click(screen.getByRole("button", { name: "Try page again" }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
  });

  it("reports each failure with a quotable reference and the last server request id, never the message (ADR-028)", () => {
    const incidents: UiIncident[] = [];
    const stop = onUiIncident((incident) => incidents.push(incident));
    noteServerRequestId("req-42");
    render(<MemoryRouter><RouteErrorBoundary><BrokenPage error={new RangeError("token=secret private detail")} /></RouteErrorBoundary></MemoryRouter>);
    stop();
    expect(incidents).toHaveLength(1);
    expect(incidents[0]).toMatchObject({ kind: "render", errorName: "RangeError", lastRequestId: "req-42" });
    expect(screen.getByText(`Reference: ${incidents[0].incidentId} · last server request req-42`)).toBeInTheDocument();
    const logged = JSON.stringify(vi.mocked(console.error).mock.calls.filter(([label]) => label === "[nanfo] ui incident"));
    expect(logged).toContain(incidents[0].incidentId);
    expect(logged).not.toContain("secret");
  });
});
